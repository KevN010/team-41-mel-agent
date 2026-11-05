"""Send-window engine. Pure code, no I/O, no model calls.

``send_window(insight, profile, clock, rules)`` returns a ``SendWindow`` or a ``TimingException``.
The exception is returned, not raised, so callers can branch on it; it is an ``Exception``
subclass, so ``raise result`` works when a caller prefers that.

Two profiles (see CONTRACTS.md, "Timing profiles"):

* ``golden_v1`` reproduces the pack's 95 golden R8 windows.
* ``rules_v1`` applies ``rules.json`` ``window_rules`` exactly.

All datetimes are India time with the +05:30 offset. Nothing here logs insight text.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Literal

from mel.models import IST, Insight, SendWindow, TimingProfile, to_ist
from mel.protocols import Clock

TimingCode = Literal["window_after_season", "window_too_narrow"]

# Golden-only constants. These are measured from golden_set.jsonl, not taken from rules.json.
GOLDEN_START_TIME = time(9, 0)
GOLDEN_END_TIME = time(19, 0)
GOLDEN_SAME_DAY_HOURS = 4
# G-0009 (the only golden `seasonal` R8 row) expects day 30..45; rules.json says 21..45.
# No rule in the pack explains 30. Fit to one row; see NOTES-B.md.
GOLDEN_DAY_OVERRIDES: dict[str, tuple[int, int]] = {"seasonal": (30, 45)}


class TimingException(Exception):
    """No valid send window exists for this insight.

    ``window_after_season``: the window would start after the season end.
    ``window_too_narrow``: the window fits before the season end but is narrower than the
    minimum width once cut at the season end (``rules_v1`` only).
    """

    def __init__(self, code: TimingCode) -> None:
        super().__init__(code)
        self.code: TimingCode = code

    def __eq__(self, other: object) -> bool:
        return isinstance(other, TimingException) and other.code == self.code

    def __hash__(self) -> int:
        return hash(self.code)

    def __str__(self) -> str:  # no insight data in the message
        return self.code


# --------------------------------------------------------------------------- helpers


def _fields(insight: Insight | dict[str, Any]) -> tuple[datetime, str, int | None]:
    """Pull created_at (IST), verification.timing and action_window_days from a model or dict."""
    if isinstance(insight, Insight):
        return insight.created_at, insight.verification.timing, insight.action_window_days
    created = insight["created_at"]
    if isinstance(created, str):
        created = datetime.fromisoformat(created)
    if created.tzinfo is None:
        raise ValueError("created_at must carry a timezone offset")
    return to_ist(created), insight["verification"]["timing"], insight.get("action_window_days")


def _at(day: date, t: time) -> datetime:
    return datetime.combine(day, t, tzinfo=IST)


def _hhmm(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


def _season_end(rules: dict[str, Any]) -> date:
    return date.fromisoformat(rules["window_rules"]["season_end"])


def _make(start: datetime, end: datetime) -> SendWindow:
    return SendWindow(not_before=start, not_after=end)


def _none_days(rules: dict[str, Any], action_window_days: int | None) -> tuple[int, int]:
    wr = rules["window_rules"]
    aw = wr["action_window_days_if_null"] if action_window_days is None else action_window_days
    return aw + wr["none_start_after_action_window_days"], aw + wr["none_end_after_action_window_days"]


# --------------------------------------------------------------------------- golden_v1


def _golden_v1(created: datetime, timing: str, aw: int | None, rules: dict[str, Any]) -> SendWindow | TimingException:
    season_end = _season_end(rules)
    day0 = created.date()

    if timing == "same_day":
        start = created + timedelta(hours=GOLDEN_SAME_DAY_HOURS)
        if start.time() > GOLDEN_END_TIME:  # strictly after 19:00 -> next morning
            start = _at(start.date() + timedelta(days=1), GOLDEN_START_TIME)
        end = start + timedelta(hours=GOLDEN_SAME_DAY_HOURS)
    else:
        if timing == "none":
            lo, hi = _none_days(rules, aw)
        elif timing in GOLDEN_DAY_OVERRIDES:
            lo, hi = GOLDEN_DAY_OVERRIDES[timing]
        else:
            lo, hi = rules["send_window_days"][timing]
        start = _at(day0 + timedelta(days=lo), GOLDEN_START_TIME)
        end = _at(day0 + timedelta(days=hi), GOLDEN_END_TIME)

    if start.date() > season_end:
        return TimingException("window_after_season")
    end = min(end, _at(season_end, GOLDEN_END_TIME))  # G-0145
    if end <= start:  # same-day start at or after 19:00 on the last season day
        return TimingException("window_after_season")
    return _make(start, end)


# --------------------------------------------------------------------------- rules_v1


def _rules_v1(created: datetime, timing: str, aw: int | None, rules: dict[str, Any]) -> SendWindow | TimingException:
    wr = rules["window_rules"]
    t_from, t_to = _hhmm(wr["not_before_time"]), _hhmm(wr["not_after_time"])
    season_end = _season_end(rules)
    day0 = created.date()

    aw_days = wr["action_window_days_if_null"] if aw is None else aw
    if timing == "none":
        lo, hi = _none_days(rules, aw)
    else:
        lo, hi = rules["send_window_days"][timing]

    start_day = max(lo, wr["earliest_start_day"])
    if wr["start_not_before_action_window_end"]:
        start_day = max(start_day, aw_days)
    end_day = max(hi, start_day + wr["min_width_days"])

    start_date = day0 + timedelta(days=start_day)
    if start_date > season_end:
        return TimingException("window_after_season")
    end_date = min(day0 + timedelta(days=end_day), season_end)
    if (end_date - start_date).days < wr["min_width_days"]:
        return TimingException("window_too_narrow")
    return _make(_at(start_date, t_from), _at(end_date, t_to))


# --------------------------------------------------------------------------- public


def send_window(
    insight: Insight | dict[str, Any],
    profile: TimingProfile,
    clock: Clock,
    rules: dict[str, Any],
) -> SendWindow | TimingException:
    """Compute the send window for ``insight`` under ``profile``.

    ``rules`` is the parsed ``rules.json`` (``mel.fixtures.load_rules()``). ``clock`` is accepted
    for the frozen signature; the window depends only on ``insight.created_at``, so replaying an
    old insight gives the same window.
    """
    created, timing, aw = _fields(insight)
    if profile == "golden_v1":
        return _golden_v1(created, timing, aw, rules)
    if profile == "rules_v1":
        return _rules_v1(created, timing, aw, rules)
    raise ValueError(f"unknown timing profile: {profile}")
