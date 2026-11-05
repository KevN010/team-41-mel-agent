Model: Haiku. Branch: w1-D2. Runs in parallel with Wave 0.
Goal: a parametrized test over all 183 outcome fixtures.
Read first: pack/json/outcomes/** (list them), pack/json/schemas/response.schema.json, pack/json/rules/outcome_codes.json.
You own: tests/test_outcomes_fixtures.py, tests/outcome_events.py, NOTES-D2.md.
Deliver: tests/outcome_events.py: for each fixture, derive the input event dict the state machine would
receive (kind, channel, failure_code, answers, input_kind, farmer_id, timestamps) from the fixture itself.
tests/test_outcomes_fixtures.py: parametrized over all 183 paths; calls mel.outcomes.apply_event with
signature apply_event(survey, attempt, event, clock, codes); asserts equality on status, failure_code,
sheet_outcome, answers, complete, retry_decision, retry_after_minutes, counts_toward_cap, needs_follow_up,
follow_up_reasons. Until mel/outcomes.py exists, mark the test module with pytest.importorskip.
Build the survey and attempt objects from the matching scenario survey (survey_id prefix) or a minimal stub.
Done when: the file collects 183 cases and skips cleanly without mel/outcomes.py. Report: case count.
