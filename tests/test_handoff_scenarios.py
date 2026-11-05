"""The pack's six worked scenarios, reproduced by mel.handoff (offline)."""

from __future__ import annotations

import copy
from datetime import datetime

import pytest

from mel.handoff import build_handoff, build_no_survey
from mel.models import DecisionRecord, Insight, NoSurvey, Survey
from mel.protocols import FakeClock
from mel.validate import validate_against_pack

SURVEY_SCENARIOS = [
    "1-mustard-aphid-spray",
    "2-wheat-irrigation-timing",
    "3-potato-blight-wait",
    "4-cow-vet-escalation",
    "5-wheat-variety-plan",
]


def _scenario(scenarios, name):
    return next(s for s in scenarios if s["name"] == name)


def _r8(insight: Insight, survey: Survey) -> DecisionRecord:
    return DecisionRecord(
        insight_id=insight.insight_id,
        farmer_id=insight.farmer_id,
        survey=True,
        rule_id="R8",
        reason_code=None,
        timing_profile="golden_v1",
        send_window=survey.send_window,
        created_at=insight.created_at,
    )


@pytest.mark.parametrize("name", SURVEY_SCENARIOS)
def test_handoff_matches_scenario_field_by_field(scenarios, rules, name):
    sc = _scenario(scenarios, name)
    expected = copy.deepcopy(sc["handoff"])
    insight = Insight.model_validate(sc["insight"])
    survey = Survey.model_validate(expected["survey"])
    # The pack builds each hand-off at 23:00 India time on the day of the insight.
    clock = FakeClock(datetime.fromisoformat(expected["created_at"]))

    got = build_handoff(survey, insight, _r8(insight, survey), clock, rules).to_pack()

    assert got == expected
    # Spell the groups out so a failure names the group, not just "dicts differ".
    for key in expected:
        assert got[key] == expected[key], key


@pytest.mark.parametrize("name", SURVEY_SCENARIOS)
def test_handoff_validates_against_pack_schema(scenarios, rules, name):
    sc = _scenario(scenarios, name)
    insight = Insight.model_validate(sc["insight"])
    survey = Survey.model_validate(sc["handoff"]["survey"])
    clock = FakeClock(datetime.fromisoformat(sc["handoff"]["created_at"]))
    handoff = build_handoff(survey, insight, _r8(insight, survey), clock, rules)
    ok, errors = validate_against_pack(handoff, "schedule_handoff")
    assert ok, f"{len(errors)} schema errors"


@pytest.mark.parametrize("name", SURVEY_SCENARIOS)
def test_handoff_embeds_the_survey_for_either_language(scenarios, rules, name):
    sc = _scenario(scenarios, name)
    insight = Insight.model_validate(sc["insight"])
    clock = FakeClock(datetime.fromisoformat(sc["handoff"]["created_at"]))
    for lang, raw in sc["survey_by_lang"].items():
        survey = Survey.model_validate(raw)
        handoff = build_handoff(survey, insight, _r8(insight, survey), clock, rules)
        assert handoff.survey.language == lang
        assert handoff.to_pack()["survey"] == raw
        # Language does not change timing, channels, ids or the cap.
        assert handoff.farmerchat_flow.flow_key == sc["handoff"]["farmerchat_flow"]["flow_key"]
        assert handoff.send_window.to_pack() == sc["handoff"]["send_window"]


def test_scenario_6_generic_information_gives_no_survey(scenarios):
    sc = _scenario(scenarios, "6-zero-tillage-info-no-survey")
    insight = Insight.model_validate(sc["insight"])
    decision = DecisionRecord(
        insight_id=insight.insight_id,
        farmer_id=insight.farmer_id,
        survey=False,
        rule_id="R3",
        reason_code="nothing_to_verify",
        timing_profile="golden_v1",
        send_window=None,
        created_at=insight.created_at,
    )
    notice, record = build_no_survey(decision)

    assert isinstance(notice, NoSurvey)
    got, expected = notice.to_pack(), sc["no_survey"]
    # The pack's reason sentence is written for that one insight. We emit a fixed,
    # insight-free sentence, so `reason` differs by design; every other field is equal.
    assert {k: v for k, v in got.items() if k != "reason"} == {k: v for k, v in expected.items() if k != "reason"}
    assert 1 <= len(got["reason"]) <= 300
    ok, errors = validate_against_pack(notice, "no_survey")
    assert ok, f"{len(errors)} schema errors"
    ok, errors = validate_against_pack(expected, "no_survey")
    assert ok
    assert record == decision
    assert record.reason_code == "nothing_to_verify"
