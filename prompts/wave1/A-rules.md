Model: Sonnet. Branch: w1-A.
Goal: the decision engine. Pure code, data-driven, reproduces the golden set.
Read first: CLAUDE.md, CONTRACTS.md (rule table), mel/models.py, mel/fixtures.py, pack/data/golden_set.jsonl, pack/data/crop_calendar_bihar_rabi.csv, pack/json/rules/rules.json.
You own: mel/rules.py, mel/rules.yaml, tests/test_rules_golden.py, tests/test_rules_edges.py, NOTES-A.md.
Deliver: decide(insight: Insight | dict, clock, calendar, rules) -> DecisionRecord. Rules R1..R8 live in
mel/rules.yaml (ordered list with id, condition name, reason_code) and are applied in order. R1 also
fires when the raw dict fails insight schema validation (use mel.validate). Keep reason_code for all 8
golden codes in DecisionRecord; mapping to the 2-code no_survey schema is done in mel/handoff.py, not here.
tests/test_rules_golden.py prints a per-rule confusion table and asserts matches >= 149; list every miss
with golden_id in the assertion message. tests/test_rules_edges.py: junk row that fails schema, severity
None, asset null, created exactly on season end, crop not in calendar.
Done when: both tests pass under make test. Report: match count, the misses, nothing else.
