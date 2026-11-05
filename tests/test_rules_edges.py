"""Edge cases for mel.rules.decide."""

from __future__ import annotations

import copy
from datetime import date, timedelta

import pytest

from mel.models import SendWindow
from mel.rules import decide, load_rule_table, window_start_date

BASE = {
    "insight_id": "I-900001",
    "farmer_id": "F-900001",
    "conversation_id": "C-900001",
    "created_at": "2026-11-05T10:00:00+05:30",
    "conversation_language": "en-IN",
    "location": {"country": "IN", "state": "Bihar", "district": "Patna"},
    "asset": {"name": "wheat", "category": "crop", "growth_stage": "tillering"},
    "concern": "pest_disease",
    "behavioral_intent": "symptom_reporting",
    "decision_episode_type": "problem_resolution",
    "severity": "medium",
    "query_summary": "Farmer reports aphids on wheat.",
    "advice_summary": "Spray as advised.",
    "resolution_type": "direct_action",
    "action_window_days": 2,
    "verification": {"needed": True, "timing": "two_to_five_days", "method": "push"},
    "preferred_channel": "app",
    "quality_flag": "clean",
}


def make(**over):
    d = copy.deepcopy(BASE)
    for k, v in over.items():
        d[k] = v
    return d


def test_base_row_is_a_survey(clock, crop_calendar, rules):
    d = decide(make(), clock, crop_calendar, rules)
    assert (d.survey, d.rule_id, d.reason_code) == (True, "R8", None)


def test_rule_table_is_ordered_r1_to_r8():
    assert [r.id for r in load_rule_table()] == [f"R{i}" for i in range(1, 9)]


def test_junk_row_that_fails_schema(clock, crop_calendar, rules):
    bad = make(behavioral_intent=None, advice_summary=None, quality_flag="junk")
    d = decide(bad, clock, crop_calendar, rules)
    assert (d.rule_id, d.reason_code, d.survey) == ("R1", "junk_insight", False)
    assert d.insight_id == "I-900001"


def test_clean_row_that_fails_schema_is_r1(clock, crop_calendar, rules):
    d = decide(make(severity="catastrophic"), clock, crop_calendar, rules)
    assert d.rule_id == "R1"


def test_missing_ids_do_not_crash(clock, crop_calendar, rules):
    d = decide({"quality_flag": "junk"}, clock, crop_calendar, rules)
    assert (d.rule_id, d.insight_id, d.farmer_id) == ("R1", "unknown", "unknown")


def test_junk_flag_wins_over_critical(clock, crop_calendar, rules):
    d = decide(make(quality_flag="junk", severity="critical"), clock, crop_calendar, rules)
    assert d.rule_id == "R1"


def test_critical_wins_over_generic(clock, crop_calendar, rules):
    d = decide(make(severity="critical", resolution_type="generic_information"), clock, crop_calendar, rules)
    assert (d.rule_id, d.reason_code) == ("R2", "critical_needs_human_call")


def test_severity_none_is_not_critical(clock, crop_calendar, rules):
    d = decide(make(severity=None), clock, crop_calendar, rules)
    assert d.rule_id == "R8"


def test_resolution_rules(clock, crop_calendar, rules):
    g = decide(make(resolution_type="generic_information"), clock, crop_calendar, rules)
    n = decide(make(resolution_type="needs_more_context"), clock, crop_calendar, rules)
    assert (g.rule_id, g.reason_code) == ("R3", "nothing_to_verify")
    assert (n.rule_id, n.reason_code) == ("R4", "waiting_for_details")


def test_verification_not_needed(clock, crop_calendar, rules):
    v = {"needed": False, "timing": "none", "method": "none"}
    d = decide(make(verification=v), clock, crop_calendar, rules)
    assert (d.rule_id, d.reason_code) == ("R5", "no_check_needed")


def test_asset_null_fields(clock, crop_calendar, rules):
    asset = {"name": None, "category": None, "growth_stage": None}
    d = decide(make(asset=asset), clock, crop_calendar, rules)
    assert d.rule_id == "R8"


def test_asset_object_null_fails_schema(clock, crop_calendar, rules):
    d = decide(make(asset=None), clock, crop_calendar, rules)
    assert d.rule_id == "R1"


def test_crop_not_in_calendar_is_not_r7(clock, crop_calendar, rules):
    asset = {"name": "dragonfruit", "category": "crop", "growth_stage": None}
    d = decide(make(asset=asset, created_at="2027-01-10T10:00:00+05:30"), clock, crop_calendar, rules)
    assert d.rule_id == "R8"


def test_non_crop_asset_never_hits_r7(clock, crop_calendar, rules):
    asset = {"name": "wheat", "category": "livestock", "growth_stage": None}
    d = decide(make(asset=asset, created_at="2027-03-01T10:00:00+05:30"), clock, crop_calendar, rules)
    assert d.rule_id == "R8"


def test_r7_boundary_uses_greater_or_equal(clock, crop_calendar, rules):
    end = crop_calendar["cauliflower"]  # 2027-03-20
    on = decide(make(asset={"name": "cauliflower", "category": "crop", "growth_stage": None},
                     created_at=f"{end.isoformat()}T10:00:00+05:30",
                     verification={"needed": True, "timing": "same_day", "method": "push"}),
                clock, crop_calendar, rules)
    before = decide(make(asset={"name": "cauliflower", "category": "crop", "growth_stage": None},
                         created_at=f"{(end - timedelta(days=1)).isoformat()}T10:00:00+05:30",
                         verification={"needed": True, "timing": "same_day", "method": "push"}),
                    clock, crop_calendar, rules)
    assert (on.rule_id, on.reason_code) == ("R7", "crop_already_harvested")
    assert before.rule_id == "R8"


@pytest.mark.parametrize(
    ("timing", "created", "rule"),
    [
        # created exactly on season end: same_day lo = 0 -> start 2027-03-31, not after season
        ("same_day", "2027-03-31T10:00:00+05:30", "R8"),
        ("next_day", "2027-03-31T10:00:00+05:30", "R6"),
        ("next_day", "2027-03-30T10:00:00+05:30", "R8"),
        ("three_to_ten_days", "2027-03-28T10:00:00+05:30", "R8"),
        ("three_to_ten_days", "2027-03-29T10:00:00+05:30", "R6"),
    ],
)
def test_season_end_boundary(clock, crop_calendar, rules, timing, created, rule):
    # lentil/mustard calendars end on the season end date, so use a non-crop asset to isolate R6
    asset = {"name": None, "category": None, "growth_stage": None}
    ver = {"needed": True, "timing": timing, "method": "push"}
    d = decide(make(asset=asset, created_at=created, verification=ver), clock, crop_calendar, rules)
    assert d.rule_id == rule


def test_timing_none_uses_action_window(rules):
    from mel.models import Insight

    ins = Insight.model_validate(
        make(
            created_at="2027-03-25T10:00:00+05:30",
            action_window_days=5,
            verification={"needed": True, "timing": "none", "method": "none"},
        )
    )
    assert window_start_date(ins, rules) == date(2027, 3, 31)  # 25 + 5 + 1
    ins2 = ins.model_copy(update={"action_window_days": None})
    assert window_start_date(ins2, rules) == date(2027, 3, 28)  # default action window 2, +1


def test_r6_beats_r7(clock, crop_calendar, rules):
    d = decide(
        make(created_at="2027-03-31T11:00:00+05:30",
             verification={"needed": True, "timing": "three_to_ten_days", "method": "push"}),
        clock, crop_calendar, rules)
    assert d.rule_id == "R6"


def test_accepts_typed_insight(clock, crop_calendar, rules):
    from mel.models import Insight

    d = decide(Insight.model_validate(make()), clock, crop_calendar, rules)
    assert d.rule_id == "R8"


def test_r8_send_window_comes_from_window_fn(clock, crop_calendar, rules):
    seen = {}
    win = SendWindow(not_before="2026-11-07T09:00:00+05:30", not_after="2026-11-10T19:00:00+05:30")

    def fn(insight, profile, clk, rls):
        seen["profile"] = profile
        return win

    d = decide(make(), clock, crop_calendar, rules, profile="rules_v1", window_fn=fn)
    assert d.send_window == win
    assert d.timing_profile == "rules_v1"
    assert seen["profile"] == "rules_v1"


def test_no_survey_rules_never_call_window_fn(clock, crop_calendar, rules):
    def fn(*a):
        raise AssertionError("window_fn must not run for no-survey decisions")

    d = decide(make(severity="critical"), clock, crop_calendar, rules, window_fn=fn)
    assert d.send_window is None


def test_decision_time_is_clock_time(clock, crop_calendar, rules):
    d = decide(make(), clock, crop_calendar, rules, window_fn=lambda *a: None)
    assert d.created_at == clock.now()
