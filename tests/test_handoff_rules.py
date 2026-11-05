"""Rules behind mel.handoff: priority, channel order, cap, expiry, flow ids, no-survey mapping."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta

import pytest

from mel.handoff import (
    RULE_REASON,
    HandoffError,
    build_handoff,
    build_no_survey,
    channel_order_for,
    priority_for,
)
from mel.models import IST, DecisionRecord, Insight, Survey
from mel.protocols import FakeClock
from mel.validate import validate_against_pack

NOW = datetime(2026, 11, 5, 23, 0, tzinfo=IST)


def _mustard(scenarios):
    return next(s for s in scenarios if s["name"] == "1-mustard-aphid-spray")


def _insight(scenarios, **over) -> Insight:
    raw = copy.deepcopy(_mustard(scenarios)["insight"])  # mustard aphid: app, push, direct_action, medium
    for key, value in over.items():
        if key == "verification_method":
            raw["verification"]["method"] = value
        else:
            raw[key] = value
    return Insight.model_validate(raw)


def _survey(scenarios, insight: Insight, **over) -> Survey:
    raw = copy.deepcopy(_mustard(scenarios)["survey_by_lang"]["en-IN"])
    raw["farmer_id"] = insight.farmer_id
    raw["source_insight_ids"] = [insight.insight_id]
    raw.update(over)
    return Survey.model_validate(raw)


def _decision(insight: Insight, sv: Survey, **over) -> DecisionRecord:
    base = {
        "insight_id": insight.insight_id,
        "farmer_id": insight.farmer_id,
        "survey": True,
        "rule_id": "R8",
        "reason_code": None,
        "timing_profile": "golden_v1",
        "send_window": sv.send_window,
        "created_at": insight.created_at,
    }
    base.update(over)
    return DecisionRecord(**base)


def _build(scenarios, rules, **insight_over):
    insight = _insight(scenarios, **insight_over)
    survey = _survey(scenarios, insight)
    return build_handoff(survey, insight, _decision(insight, survey), FakeClock(NOW), rules)


# --------------------------------------------------------------------------- priority


@pytest.mark.parametrize(
    ("over", "expected"),
    [
        ({}, "normal"),
        ({"resolution_type": "escalate_to_expert"}, "high"),
        ({"severity": "high"}, "high"),
        ({"severity": "critical"}, "high"),
        ({"behavioral_intent": "emergency"}, "high"),
        ({"resolution_type": "plan_created"}, "low"),
        ({"resolution_type": "do_not_act"}, "low"),
        ({"resolution_type": "wait_and_monitor"}, "normal"),
        ({"resolution_type": "direct_action"}, "normal"),
        ({"severity": None}, "normal"),
        # high wins over low
        ({"resolution_type": "plan_created", "severity": "high"}, "high"),
        ({"resolution_type": "do_not_act", "behavioral_intent": "emergency"}, "high"),
        ({"resolution_type": "plan_created", "severity": "critical"}, "high"),
    ],
)
def test_priority(scenarios, rules, over, expected):
    assert priority_for(_insight(scenarios, **over), rules) == expected


# --------------------------------------------------------------------------- channels


@pytest.mark.parametrize(
    ("preferred", "method", "priority", "expected"),
    [
        ("app", "push", "normal", ["app", "whatsapp"]),
        ("web", "repeat_photo", "normal", ["web", "app", "whatsapp"]),
        ("telegram", "push", "low", ["telegram", "app", "whatsapp"]),
        ("whatsapp", "whatsapp", "normal", ["whatsapp"]),
        ("voice", "ivr_callback", "high", ["voice", "whatsapp"]),
        ("voice", "agent_followup", "normal", ["voice", "whatsapp"]),
        ("app", "ivr_callback", "normal", ["app", "voice", "whatsapp"]),
        # voice is appended only for high priority
        ("app", "push", "high", ["app", "whatsapp", "voice"]),
        ("web", "ivr_callback", "high", ["web", "voice", "whatsapp"]),
        ("whatsapp", "whatsapp", "high", ["whatsapp", "voice"]),
        ("whatsapp", "push", "low", ["whatsapp", "app"]),
        ("telegram", "none", "normal", ["telegram", "whatsapp"]),
        ("voice", "none", "low", ["voice", "whatsapp"]),
    ],
)
def test_channel_order(scenarios, rules, preferred, method, priority, expected):
    insight = _insight(scenarios, preferred_channel=preferred, verification_method=method)
    steps = channel_order_for(insight, priority, rules)
    assert [s.channel for s in steps] == expected
    assert len({s.channel for s in steps}) == len(steps)


@pytest.mark.parametrize(("priority", "hours"), [("high", 6), ("normal", 24), ("low", 48)])
def test_wait_hours_by_priority_and_last_is_null(scenarios, rules, priority, hours):
    insight = _insight(scenarios, preferred_channel="web", verification_method="push")
    steps = channel_order_for(insight, priority, rules)
    assert len(steps) >= 3 if priority == "high" else len(steps) >= 2
    assert all(s.wait_hours == hours for s in steps[:-1])
    assert steps[-1].wait_hours is None


def test_single_channel_has_only_a_null_wait(scenarios, rules):
    insight = _insight(scenarios, preferred_channel="whatsapp", verification_method="whatsapp")
    steps = channel_order_for(insight, "normal", rules)
    assert [(s.channel, s.wait_hours) for s in steps] == [("whatsapp", None)]


def test_channel_order_never_exceeds_five(scenarios, rules):
    for preferred in ("app", "web", "whatsapp", "telegram", "voice"):
        for method in ("push", "whatsapp", "ivr_callback", "repeat_photo", "agent_followup", "none"):
            insight = _insight(scenarios, preferred_channel=preferred, verification_method=method)
            for priority in ("high", "normal", "low"):
                assert 1 <= len(channel_order_for(insight, priority, rules)) <= 5


# --------------------------------------------------------------------------- cap, expiry, ids


def test_cap_key_is_per_farmer_and_exempt_only_for_high(scenarios, rules):
    normal = _build(scenarios, rules)
    assert normal.frequency_cap.to_pack() == {
        "key": f"mel:farmer:{normal.survey.farmer_id}",
        "max_surveys": 1,
        "window_days": 7,
        "exempt": False,
    }
    assert _build(scenarios, rules, severity="critical").frequency_cap.exempt is True
    assert _build(scenarios, rules, resolution_type="plan_created").frequency_cap.exempt is False


def test_expires_two_days_after_window_end(scenarios, rules):
    h = _build(scenarios, rules)
    assert h.expires_at == h.send_window.not_after + timedelta(days=2)
    assert h.expires_at.utcoffset() == timedelta(hours=5, minutes=30)


def test_created_at_is_the_clock_and_send_window_is_the_surveys(scenarios, rules):
    h = _build(scenarios, rules)
    assert h.created_at == NOW
    assert h.send_window == h.survey.send_window
    assert h.send_hours.to_pack() == {"from": "07:00", "to": "19:00"}


def test_flow_fields(scenarios, rules):
    h = _build(scenarios, rules)
    sid = h.survey.survey_id
    assert h.handoff_id == "H-" + sid[2:]
    assert h.farmerchat_flow.org_id == "org.farmerchat"
    assert h.farmerchat_flow.flow_key == "mel_" + sid.lower().replace("-", "_")
    assert h.farmerchat_flow.version == 1


def test_flow_ids_are_deterministic_and_distinct_per_survey(scenarios, rules):
    insight = _insight(scenarios)
    a = build_handoff(_survey(scenarios, insight), insight, _decision(insight, _survey(scenarios, insight)), FakeClock(NOW), rules)
    again = build_handoff(_survey(scenarios, insight), insight, _decision(insight, _survey(scenarios, insight)), FakeClock(NOW), rules)
    other_survey = _survey(scenarios, insight, survey_id="S-99999")
    b = build_handoff(other_survey, insight, _decision(insight, other_survey), FakeClock(NOW), rules)
    assert a == again
    assert a.farmerchat_flow.campaign_id == b.farmerchat_flow.campaign_id
    assert a.farmerchat_flow.flow_id != b.farmerchat_flow.flow_id
    assert b.farmerchat_flow.flow_key == "mel_s_99999"


def test_built_handoffs_validate_for_every_channel_and_priority(scenarios, rules):
    for preferred in ("app", "web", "whatsapp", "telegram", "voice"):
        for over in ({}, {"severity": "high"}, {"resolution_type": "do_not_act"}):
            h = _build(scenarios, rules, preferred_channel=preferred, **over)
            ok, errors = validate_against_pack(h, "schedule_handoff")
            assert ok, f"{preferred} {over}: {len(errors)} schema errors"


def test_golden_survey_rows_build_valid_handoffs(golden, scenarios, rules):
    rows = [g for g in golden if g["expected"]["survey"]]
    assert len(rows) == 95
    for g in rows:
        insight = Insight.model_validate(g["insight"])
        survey = _survey(scenarios, insight)
        h = build_handoff(survey, insight, _decision(insight, survey), FakeClock(NOW), rules)
        ok, errors = validate_against_pack(h, "schedule_handoff")
        assert ok, f"{g['golden_id']}: {len(errors)} schema errors"
        assert h.priority == priority_for(insight, rules)
        assert h.channel_order[0].channel == insight.preferred_channel
        assert h.channel_order[-1].wait_hours is None


# --------------------------------------------------------------------------- bad input


def test_rules_default_to_the_pack_rules(scenarios, rules):
    insight = _insight(scenarios)
    survey = _survey(scenarios, insight)
    d = _decision(insight, survey)
    assert build_handoff(survey, insight, d, FakeClock(NOW)) == build_handoff(survey, insight, d, FakeClock(NOW), rules)


def test_rejects_a_no_survey_decision(scenarios, rules):
    insight = _insight(scenarios)
    survey = _survey(scenarios, insight)
    d = _decision(insight, survey, survey=False, rule_id="R5", reason_code="no_check_needed", send_window=None)
    with pytest.raises(HandoffError):
        build_handoff(survey, insight, d, FakeClock(NOW), rules)


def test_rejects_mismatched_insight_or_farmer(scenarios, rules):
    insight = _insight(scenarios)
    survey = _survey(scenarios, insight)
    with pytest.raises(HandoffError):
        build_handoff(survey, insight, _decision(insight, survey, insight_id="I-other"), FakeClock(NOW), rules)
    with pytest.raises(HandoffError):
        build_handoff(survey, insight, _decision(insight, survey, farmer_id="F-other"), FakeClock(NOW), rules)
    other = _survey(scenarios, insight, farmer_id="F-other")
    with pytest.raises(HandoffError):
        build_handoff(other, insight, _decision(insight, survey), FakeClock(NOW), rules)
    stray = _survey(scenarios, insight, source_insight_ids=["I-other"])
    with pytest.raises(HandoffError):
        build_handoff(stray, insight, _decision(insight, survey), FakeClock(NOW), rules)


def test_rejects_a_decision_window_that_differs_from_the_survey(scenarios, rules):
    insight = _insight(scenarios)
    survey = _survey(scenarios, insight)
    shifted = survey.send_window.model_copy(update={"not_after": survey.send_window.not_after + timedelta(days=1)})
    with pytest.raises(HandoffError):
        build_handoff(survey, insight, _decision(insight, survey, send_window=shifted), FakeClock(NOW), rules)


def test_error_messages_do_not_echo_ids(scenarios, rules):
    insight = _insight(scenarios)
    survey = _survey(scenarios, insight)
    with pytest.raises(HandoffError) as exc:
        build_handoff(survey, insight, _decision(insight, survey, farmer_id="F-secret-77"), FakeClock(NOW), rules)
    assert "F-secret-77" not in str(exc.value)


# --------------------------------------------------------------------------- no survey


NO_SURVEY_RULES = [
    ("R1", "junk_insight", None),
    ("R2", "critical_needs_human_call", None),
    ("R3", "nothing_to_verify", "generic_information"),
    ("R4", "waiting_for_details", "needs_more_context"),
    ("R5", "no_check_needed", None),
    ("R6", "window_after_season", None),
    ("R7", "crop_already_harvested", None),
]


def _no_survey_decision(insight: Insight, rule_id, reason_code) -> DecisionRecord:
    return DecisionRecord(
        insight_id=insight.insight_id,
        farmer_id=insight.farmer_id,
        survey=False,
        rule_id=rule_id,
        reason_code=reason_code,
        timing_profile="golden_v1",
        send_window=None,
        created_at=insight.created_at,
    )


@pytest.mark.parametrize(("rule_id", "reason", "schema_code"), NO_SURVEY_RULES)
def test_no_survey_only_for_r3_and_r4(scenarios, rule_id, reason, schema_code):
    insight = _insight(scenarios)
    decision = _no_survey_decision(insight, rule_id, reason)
    notice, record = build_no_survey(decision)
    assert record == decision
    assert record.reason_code == reason
    if schema_code is None:
        assert notice is None
    else:
        assert notice is not None
        assert notice.reason_code == schema_code
        assert (notice.insight_id, notice.farmer_id, notice.decision) == (
            insight.insight_id,
            insight.farmer_id,
            "no_survey",
        )
        ok, errors = validate_against_pack(notice, "no_survey")
        assert ok, f"{len(errors)} schema errors"


def test_rule_reason_table_is_the_seven_golden_codes():
    assert set(RULE_REASON) == {"R1", "R2", "R3", "R4", "R5", "R6", "R7"}
    assert len(set(RULE_REASON.values())) == 7


@pytest.mark.parametrize("rule_id", sorted(RULE_REASON))
def test_record_gets_the_golden_reason_code(scenarios, rule_id):
    insight = _insight(scenarios)
    wrong = "junk_insight" if rule_id != "R1" else "no_check_needed"
    _, record = build_no_survey(_no_survey_decision(insight, rule_id, wrong))
    assert record.reason_code == RULE_REASON[rule_id]
    assert record.rule_id == rule_id
    assert record.survey is False


def test_no_survey_text_never_quotes_the_insight(scenarios):
    insight = _insight(scenarios)
    for rule_id in ("R3", "R4"):
        notice, _ = build_no_survey(_no_survey_decision(insight, rule_id, RULE_REASON[rule_id]))
        assert insight.query_summary not in notice.reason
        assert insight.advice_summary not in notice.reason


def test_golden_no_survey_rows(golden):
    for g in golden:
        exp = g["expected"]
        if exp["survey"]:
            continue
        ins = g["insight"]
        decision = DecisionRecord(
            insight_id=g["insight_id"],
            farmer_id=ins["farmer_id"],
            survey=False,
            rule_id=exp["rule"],
            reason_code=exp["reason_code"],
            timing_profile="golden_v1",
            send_window=None,
            created_at=ins["created_at"],
        )
        notice, record = build_no_survey(decision)
        assert record.reason_code == exp["reason_code"]
        assert (notice is not None) == (exp["rule"] in ("R3", "R4"))


def test_survey_decision_is_refused(scenarios):
    insight = _insight(scenarios)
    survey = _survey(scenarios, insight)
    with pytest.raises(HandoffError):
        build_no_survey(_decision(insight, survey))
