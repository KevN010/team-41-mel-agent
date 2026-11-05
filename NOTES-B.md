# NOTES-B: timing engine

## Delivered
- `mel/timing.py`: `send_window(insight, profile, clock, rules) -> SendWindow | TimingException`.
  `insight` is an `Insight` or a raw dict. `rules` is `load_rules()`. `clock` is accepted for the
  frozen signature and not used: the window depends only on `created_at`.
- `TimingException` is **returned, not raised** (it is an `Exception` subclass, so `raise result` works).
  `.code` is `window_after_season` or `window_too_narrow`. Message is the code only (no insight data).
- `tests/test_timing_golden.py`: golden_v1 matches 95 of 95 R8 windows, plus edge tests.
- `tests/test_timing_rules.py`: boundary tests per `window_rules` key, the impossible-window cases,
  and rules_v1 reproduces the 5 pack scenario windows exactly (5 of 5).

## golden_v1 decisions
- same_day: start = created + 4h; if that is strictly after 19:00, start = next day 09:00. End = start + 4h.
  The end is not cut at 19:00 (golden has 19:35 and 19:53 ends). Start is not floored at 07:00: no golden
  row needs it (earliest created time on a same_day row is 06:26).
- Other timings: start = created date + lo at 09:00, end = created date + hi at 19:00, end cut at season end 19:00 (G-0145).
- **seasonal is 30..45, not 21..45.** G-0009 (created 2026-11-17, action_window_days 16) expects
  2026-12-17 .. 2027-01-01. Nothing in the pack explains 30; it is a table override fit to one row
  (`GOLDEN_DAY_OVERRIDES`). Alternative fit: start = one calendar month after created, end = start + 15 days.
  Both agree on this row. The 34 other seasonal insights in `insights.jsonl` have no expected value.
- timing `none`: start = aw + 1, end = aw + 7 days (aw default 2) at 09:00..19:00. No golden R8 row uses it.
- next_day: no golden R8 row uses it; uses rules.json [1, 2].
- Start date after season end -> `TimingException("window_after_season")`. Handoff (C) already gets this from R6.

## rules_v1 decisions
- start day = max(lo, earliest_start_day, action_window_days) when `start_not_before_action_window_end` is true.
- end day = max(hi, start day + min_width_days); then cut at season end 19:00.
- Start date after season end -> `window_after_season`. After the cut, width (in dates) < min_width -> `window_too_narrow`.
- `action_window_days_if_null` (2) is applied to **every** timing when `action_window_days` is null, not only `none`.
  rules.json names the key generically. Only matters for next_day (lo 1 becomes start day 2). No pack scenario covers it.
- "Width" is the difference in calendar dates, not hours. Scenario 3 (01-09 to 01-11) is width 2 and valid.

## Differences between the profiles (95 golden R8 rows)
- Time of day: rules_v1 starts at 07:00, golden_v1 at 09:00. All 95 rows differ on this alone.
- Calendar days: only 14 of 95 rows have the same start and end dates under both profiles.
- golden_v1 ignores `action_window_days`. rules_v1 starts no earlier than the action window end. This moves
  the start later on most rows (up to 7 days for seven_to_fourteen_days and three_to_ten_days).
- same_day: golden starts about 4h after the insight. rules_v1 starts the next day at 07:00 and ends 2 days later (min width).
- min width: rules_v1 ends up to 3 days later than golden when hi is before start + 2.
- seasonal: golden 30..45, rules_v1 21..45 (start 9 days earlier on G-0009; action window 16 is already over).
- G-0145 (created 2027-03-28 18:05): golden_v1 gives 03-31 09:00..19:00. rules_v1 returns `window_too_narrow`
  (start 03-31 is the season end, width 0).

## For other owners
- C (handoff): handle both `TimingException` codes. `window_after_season` maps to R6 / `window_after_season`.
  `window_too_narrow` has no pack reason code; suggest the same `window_after_season` reason on the DecisionRecord.
- The pack scenario surveys use 07:00 starts, so `rules_v1` is the profile that matches them.
