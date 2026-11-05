Model: Sonnet. Branch: w1-B.
Goal: the timing engine with two named profiles.
Read first: CLAUDE.md, CONTRACTS.md (timing section), mel/models.py, pack/json/rules/rules.json, pack/data/golden_set.jsonl (expected.send_window on R8 rows).
You own: mel/timing.py, tests/test_timing_golden.py, tests/test_timing_rules.py, NOTES-B.md.
Deliver: send_window(insight, profile: "golden_v1"|"rules_v1", clock, rules) -> SendWindow | TimingException.
golden_v1: start = created + lo days at 09:00, end = created + hi days at 19:00; same_day: start = created,
end = created + 4h; timing none -> from_action_window (1..7 days after action_window_days, default 2).
rules_v1: apply rules.json window_rules exactly: earliest start day 1, start not before action window end,
min width 2 days, 07:00..19:00, nothing after 2027-03-31; impossible window -> TimingException(code).
All datetimes +05:30. tests/test_timing_golden.py asserts golden_v1 matches all 95 R8 windows exactly.
tests/test_timing_rules.py: boundary tests for each window_rules key plus the impossible-window case.
Done when: both pass. Report: golden match count and every profile difference as a bullet list.
