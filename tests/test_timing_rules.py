"""rules_v1: one boundary test per rules.json window_rules key, plus the impossible-window cases."""

from __future__ import annotations

import copy

import pytest

from mel import fixtures as pack
from mel.models import Insight, SendWindow
from mel.timing import TimingException, send_window


@pytest.fixture
def base(golden):
    return next(r["insight"] for r in golden if r["expected"].get("survey"))


def make(base: dict, created_at: str, timing: str, aw: int | None) -> dict:
    out = {**base, "created_at": created_at, "action_window_days": aw}
    out["verification"] = {**base["verification"], "timing": timing}
    return out


def win(base, clock, rules, created_at, timing, aw):
    got = send_window(make(base, created_at, timing, aw), "rules_v1", clock, rules)
    return got


def pair(w: SendWindow) -> tuple[str, str]:
    return w.not_before.isoformat(), w.not_after.isoformat()


# --------------------------------------------------------------------------- pack scenarios


def test_rules_v1_reproduces_the_scenario_windows(clock, rules):
    checked = 0
    for sc in pack.load_scenarios():
        if sc["handoff"] is None:
            continue
        got = send_window(sc["insight"], "rules_v1", clock, rules)
        want = next(iter(sc["survey_by_lang"].values()))["send_window"]
        assert isinstance(got, SendWindow), sc["name"]
        assert pair(got) == (want["not_before"], want["not_after"]), sc["name"]
        checked += 1
    assert checked == 5


# --------------------------------------------------------------------------- earliest_start_day


def test_earliest_start_day_pushes_same_day_to_tomorrow(base, clock, rules):
    # same_day lo = 0, aw = 0: the rule still forbids a start before day 1.
    got = win(base, clock, rules, "2026-12-01T10:00:00+05:30", "same_day", 0)
    assert pair(got)[0] == "2026-12-02T07:00:00+05:30"


def test_earliest_start_day_is_a_floor_not_a_shift(base, clock, rules):
    # next_day lo = 1 equals the floor; start stays on day 1.
    got = win(base, clock, rules, "2026-12-01T10:00:00+05:30", "next_day", 1)
    assert pair(got)[0] == "2026-12-02T07:00:00+05:30"


# --------------------------------------------------------------------------- start_not_before_action_window_end


def test_start_equal_to_action_window_end_is_allowed(base, clock, rules):
    # two_to_five lo = 2, aw = 2: start on day 2, the action window end day.
    got = win(base, clock, rules, "2026-12-01T10:00:00+05:30", "two_to_five_days", 2)
    assert pair(got) == ("2026-12-03T07:00:00+05:30", "2026-12-06T19:00:00+05:30")


def test_start_waits_for_a_longer_action_window(base, clock, rules):
    # aw = 3 > lo = 2: start moves to day 3. End stays at hi (day 5): width 2 days.
    got = win(base, clock, rules, "2026-12-01T10:00:00+05:30", "two_to_five_days", 3)
    assert pair(got) == ("2026-12-04T07:00:00+05:30", "2026-12-06T19:00:00+05:30")


def test_rule_can_be_switched_off(base, clock, rules):
    r = copy.deepcopy(rules)
    r["window_rules"]["start_not_before_action_window_end"] = False
    got = send_window(make(base, "2026-12-01T10:00:00+05:30", "two_to_five_days", 9), "rules_v1", clock, r)
    assert pair(got)[0] == "2026-12-03T07:00:00+05:30"


# --------------------------------------------------------------------------- min_width_days


def test_min_width_extends_a_short_window(base, clock, rules):
    # next_day [1,2] with aw 1: start day 1, hi day 2 gives width 1 -> end day 3.
    got = win(base, clock, rules, "2026-12-15T07:30:00+05:30", "next_day", 1)
    assert pair(got) == ("2026-12-16T07:00:00+05:30", "2026-12-18T19:00:00+05:30")


def test_min_width_exactly_met_is_left_alone(base, clock, rules):
    # two_to_five with aw 3: start day 3, end day 5, width exactly 2.
    got = win(base, clock, rules, "2026-12-01T10:00:00+05:30", "two_to_five_days", 3)
    start, end = got.not_before, got.not_after
    assert (end.date() - start.date()).days == 2


def test_min_width_when_action_window_passes_the_hi_day(base, clock, rules):
    # seven_to_fourteen with aw 23: hi (day 14) is before start (day 23); end = start + 2.
    got = win(base, clock, rules, "2026-12-02T16:20:00+05:30", "seven_to_fourteen_days", 23)
    assert pair(got) == ("2026-12-25T07:00:00+05:30", "2026-12-27T19:00:00+05:30")


def test_min_width_reads_the_rules_value(base, clock, rules):
    r = copy.deepcopy(rules)
    r["window_rules"]["min_width_days"] = 5
    got = send_window(make(base, "2026-12-15T07:30:00+05:30", "next_day", 1), "rules_v1", clock, r)
    assert pair(got)[1] == "2026-12-21T19:00:00+05:30"


# --------------------------------------------------------------------------- not_before_time / not_after_time


def test_times_are_0700_and_1900(base, clock, rules):
    got = win(base, clock, rules, "2026-12-01T23:59:00+05:30", "three_to_ten_days", 0)
    assert got.not_before.time().isoformat() == "07:00:00"
    assert got.not_after.time().isoformat() == "19:00:00"
    assert str(got.not_before.utcoffset()) == "5:30:00"
    assert got.not_before.isoformat().endswith("+05:30")


def test_times_read_the_rules_values(base, clock, rules):
    r = copy.deepcopy(rules)
    r["window_rules"]["not_before_time"] = "08:30"
    r["window_rules"]["not_after_time"] = "18:00"
    got = send_window(make(base, "2026-12-01T10:00:00+05:30", "three_to_ten_days", 0), "rules_v1", clock, r)
    assert (got.not_before.time().isoformat(), got.not_after.time().isoformat()) == ("08:30:00", "18:00:00")


# --------------------------------------------------------------------------- none timing keys


def test_none_start_and_end_offsets(base, clock, rules):
    # none_start_after_action_window_days = 1, none_end_after_action_window_days = 7.
    got = win(base, clock, rules, "2026-12-01T10:00:00+05:30", "none", 4)
    assert pair(got) == ("2026-12-06T07:00:00+05:30", "2026-12-12T19:00:00+05:30")


def test_action_window_days_if_null_applies_to_none(base, clock, rules):
    got = win(base, clock, rules, "2026-12-01T10:00:00+05:30", "none", None)
    assert pair(got) == ("2026-12-04T07:00:00+05:30", "2026-12-10T19:00:00+05:30")


def test_action_window_days_if_null_applies_to_other_timings(base, clock, rules):
    # next_day lo = 1, null aw -> default 2 -> start day 2 (not day 1).
    got = win(base, clock, rules, "2026-12-01T10:00:00+05:30", "next_day", None)
    assert pair(got)[0] == "2026-12-03T07:00:00+05:30"


def test_zero_action_window_is_not_treated_as_null(base, clock, rules):
    got = win(base, clock, rules, "2026-12-01T10:00:00+05:30", "none", 0)
    assert pair(got) == ("2026-12-02T07:00:00+05:30", "2026-12-08T19:00:00+05:30")


# --------------------------------------------------------------------------- season_end and impossible windows


def test_end_is_cut_at_season_end(base, clock, rules):
    # created 03-24 + 10 = 04-03, cut to 03-31. Start 03-27.
    got = win(base, clock, rules, "2027-03-24T10:00:00+05:30", "three_to_ten_days", 3)
    assert pair(got) == ("2027-03-27T07:00:00+05:30", "2027-03-31T19:00:00+05:30")


def test_start_two_days_before_season_end_fits(base, clock, rules):
    # start 03-29, end cut to 03-31: width exactly 2.
    got = win(base, clock, rules, "2027-03-26T10:00:00+05:30", "three_to_ten_days", 3)
    assert pair(got) == ("2027-03-29T07:00:00+05:30", "2027-03-31T19:00:00+05:30")


def test_start_one_day_before_season_end_is_too_narrow(base, clock, rules):
    # start 03-30, season ends 03-31: width 1 < 2.
    got = win(base, clock, rules, "2027-03-27T10:00:00+05:30", "three_to_ten_days", 3)
    assert isinstance(got, TimingException)
    assert got.code == "window_too_narrow"


def test_start_on_season_end_day_is_too_narrow(base, clock, rules):
    got = win(base, clock, rules, "2027-03-28T10:00:00+05:30", "three_to_ten_days", 3)
    assert isinstance(got, TimingException)
    assert got.code == "window_too_narrow"


def test_start_after_season_end_is_impossible(base, clock, rules):
    got = win(base, clock, rules, "2027-03-29T10:00:00+05:30", "three_to_ten_days", 3)
    assert isinstance(got, TimingException)
    assert got.code == "window_after_season"


def test_long_action_window_can_push_start_past_season_end(base, clock, rules):
    # lo = 2 would fit, but aw = 30 puts the start after the season.
    got = win(base, clock, rules, "2027-03-10T10:00:00+05:30", "two_to_five_days", 30)
    assert isinstance(got, TimingException)
    assert got.code == "window_after_season"


def test_season_end_reads_the_rules_value(base, clock, rules):
    r = copy.deepcopy(rules)
    r["window_rules"]["season_end"] = "2026-12-31"
    got = send_window(make(base, "2026-12-30T10:00:00+05:30", "next_day", 1), "rules_v1", clock, r)
    assert isinstance(got, TimingException)


def test_exception_is_an_exception_with_a_code_and_no_data(base, clock, rules):
    got = win(base, clock, rules, "2027-03-29T10:00:00+05:30", "three_to_ten_days", 3)
    assert isinstance(got, Exception)
    assert str(got) == "window_after_season"
    with pytest.raises(TimingException):
        raise got


# --------------------------------------------------------------------------- misc


def test_accepts_a_model(base, clock, rules):
    d = make(base, "2026-12-01T10:00:00+05:30", "two_to_five_days", 2)
    assert send_window(Insight.model_validate(d), "rules_v1", clock, rules) == send_window(d, "rules_v1", clock, rules)


def test_naive_created_at_is_rejected(base, clock, rules):
    with pytest.raises(ValueError):
        send_window(make(base, "2026-12-01T10:00:00", "two_to_five_days", 2), "rules_v1", clock, rules)


def test_unknown_profile_is_rejected(base, clock, rules):
    with pytest.raises(ValueError):
        send_window(base, "nope", clock, rules)  # type: ignore[arg-type]


def test_output_serialises_to_pack_shape(base, clock, rules):
    got = win(base, clock, rules, "2026-12-01T10:00:00+05:30", "two_to_five_days", 2)
    assert got.to_pack() == {
        "not_before": "2026-12-03T07:00:00+05:30",
        "not_after": "2026-12-06T19:00:00+05:30",
    }
