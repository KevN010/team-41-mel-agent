Model: Sonnet. Branch: w1-D.
Goal: the outcome state machine that turns a delivery or answer event into a ResponseRecord.
Read first: CLAUDE.md, CONTRACTS.md, mel/models.py, pack/json/rules/outcome_codes.json, 10 files under pack/json/outcomes/ (one per status), tests/test_outcomes_fixtures.py if present (agent D2 writes it against your function signature below).
You own: mel/outcomes.py, tests/test_outcomes_unit.py, NOTES-D.md.
Deliver: apply_event(survey: Survey, attempt: Attempt, event: dict, clock, codes) -> ResponseRecord where
event = {kind: delivered|opened|answer|failure|opt_out|decline, channel, failure_code?, answers?, raw?,
input_kind?, farmer_id, at}. Rules: accept only option values or integer scale values in range;
identity_mismatch when event.farmer_id != survey.farmer_id and never produce accepted answers for it;
duplicate_answer when a response_key already has accepted answers (caller passes existing record);
partial when some answered and sheet closed; negative_outcome when any accepted answer carries a
follow_up reason -> needs_follow_up true with reasons; retry_decision, retry_after_minutes and
counts_toward_cap copied from outcome_codes.json; transport retry (same delivery_attempt) is not a new
attempt; never fabricate delivered/opened timestamps for channels that do not report them.
Done when: tests/test_outcomes_unit.py passes and tests/test_outcomes_fixtures.py passes or lists
contradictions in NOTES-D.md with the fixture path and the field. Report: pass count, contradictions.
