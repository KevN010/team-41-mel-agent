"""golden_v1 must reproduce every golden R8 send window exactly (95 of 95)."""

from __future__ import annotations

from datetime import datetime

import pytest

from mel import fixtures as pack
from mel.models import IST, Insight, SendWindow
from mel.timing import TimingException, send_window

R8_ROWS = [row for row in pack.load_golden() if row["expected"].get("survey")]


def test_there_are_95_r8_rows():
    assert len(R8_ROWS) == 95


@pytest.mark.parametrize("row", R8_ROWS, ids=[r["golden_id"] for r in R8_ROWS])
def test_golden_v1_matches_expected_window(row, clock, rules):
    got = send_window(row["insight"], "golden_v1", clock, rules)
    assert isinstance(got, SendWindow), got
    expected = row["expected"]["send_window"]
    assert got.not_before.isoformat() == expected["start"]
    assert got.not_after.isoformat() == expected["end"]


def test_golden_v1_match_count_is_95(clock, rules):
    matched = 0
    for row in R8_ROWS:
        got = send_window(row["insight"], "golden_v1", clock, rules)
        exp = row["expected"]["send_window"]
        if isinstance(got, SendWindow) and (got.not_before.isoformat(), got.not_after.isoformat()) == (
            exp["start"],
            exp["end"],
        ):
            matched += 1
    assert matched == 95


def test_golden_v1_accepts_a_model(clock, rules):
    row = R8_ROWS[0]
    from_dict = send_window(row["insight"], "golden_v1", clock, rules)
    from_model = send_window(Insight.model_validate(row["insight"]), "golden_v1", clock, rules)
    assert from_dict == from_model


def test_golden_v1_does_not_depend_on_the_clock(rules):
    from mel.protocols import FakeClock

    row = R8_ROWS[0]
    a = send_window(row["insight"], "golden_v1", FakeClock(datetime(2026, 1, 1, tzinfo=IST)), rules)
    b = send_window(row["insight"], "golden_v1", FakeClock(datetime(2030, 1, 1, tzinfo=IST)), rules)
    assert a == b


def _insight(base: dict, created_at: str, timing: str, aw: int | None = 2) -> dict:
    out = {**base, "created_at": created_at, "action_window_days": aw}
    out["verification"] = {**base["verification"], "timing": timing}
    return out


@pytest.fixture
def base(golden):
    return next(r["insight"] for r in golden if r["expected"].get("survey"))


def test_same_day_after_1500_moves_to_next_morning(base, clock, rules):
    # 15:00 + 4h = 19:00, still today (only strictly after 19:00 moves).
    w = send_window(_insight(base, "2026-12-01T15:00:00+05:30", "same_day"), "golden_v1", clock, rules)
    assert (w.not_before.isoformat(), w.not_after.isoformat()) == (
        "2026-12-01T19:00:00+05:30",
        "2026-12-01T23:00:00+05:30",
    )
    w = send_window(_insight(base, "2026-12-01T15:01:00+05:30", "same_day"), "golden_v1", clock, rules)
    assert (w.not_before.isoformat(), w.not_after.isoformat()) == (
        "2026-12-02T09:00:00+05:30",
        "2026-12-02T13:00:00+05:30",
    )


def test_timing_none_uses_action_window(base, clock, rules):
    w = send_window(_insight(base, "2026-12-01T10:00:00+05:30", "none", aw=4), "golden_v1", clock, rules)
    assert (w.not_before.isoformat(), w.not_after.isoformat()) == (
        "2026-12-06T09:00:00+05:30",
        "2026-12-12T19:00:00+05:30",
    )


def test_timing_none_null_action_window_defaults_to_two(base, clock, rules):
    w = send_window(_insight(base, "2026-12-01T10:00:00+05:30", "none", aw=None), "golden_v1", clock, rules)
    assert (w.not_before.isoformat(), w.not_after.isoformat()) == (
        "2026-12-04T09:00:00+05:30",
        "2026-12-10T19:00:00+05:30",
    )


def test_end_is_cut_at_season_end(base, clock, rules):
    w = send_window(_insight(base, "2027-03-28T18:05:00+05:30", "three_to_ten_days"), "golden_v1", clock, rules)
    assert w.not_after.isoformat() == "2027-03-31T19:00:00+05:30"


def test_start_after_season_end_is_an_exception(base, clock, rules):
    got = send_window(_insight(base, "2027-03-29T10:00:00+05:30", "three_to_ten_days"), "golden_v1", clock, rules)
    assert isinstance(got, TimingException)
    assert got.code == "window_after_season"
