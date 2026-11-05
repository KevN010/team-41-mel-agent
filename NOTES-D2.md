# NOTES-D2: outcome fixture tests

## Delivered
- `tests/outcome_events.py`: builds the event, attempt, survey and clock for each fixture from the fixture and its scenario survey. Imports nothing from `mel`.
- `tests/test_outcomes_fixtures.py`: 183 parametrized cases. Each calls `mel.outcomes.apply_event(survey, attempt, event, clock, codes)` and asserts the ten fields in the D2 prompt.
- Without `mel/outcomes.py`: `183 tests collected, 183 skipped`. Skip reason comes from `pytest.importorskip("mel.outcomes")`.

## Checks run on the pack (not committed as tests)
- All 183 fixtures validate against `pack/json/schemas/response.schema.json`, with `survey.schema.json` refs resolved.
- For all 183, `status`, `failure_code`, `retry_decision`, `retry_after_minutes`, `counts_toward_cap` and the allowed channels match `pack/json/rules/outcome_codes.json`.
- Every fixture's answers are valid options, or in-range scale values. Every survey_closed fixture has `recorded_at` after `send_window.not_after`.
- Derived inputs: 99 `answer`, 60 `failure`, 15 `opt_out`, 9 `decline` events.

## Gaps and disagreements
- `CONTRACTS.md` is not in the repo, though CLAUDE.md says to read it. Event shape comes from the D-outcomes prompt.
- `apply_event(survey, attempt, event, clock, codes)` has no argument for a prior accepted record. `duplicate_answer` needs one. `survey_replaced` needs a supersession fact. I pass them on `attempt` as `already_answered` and `superseded`. Agent D must agree on this or add an argument.
- Answer-arrival codes (`duplicate_answer`, `identity_mismatch`, `survey_closed`, `survey_replaced`) arrive as `kind: "answer"` with a `failure_code`. The D-outcomes kind list does not say this. Agent D must confirm.
- For answer-arrival fixtures, `answers` is `{}` by design. The event instead carries the values that arrived (items with result `answered` or `discarded`), so apply_event must reject them. D-outcomes does not state this.
- `farmer_opted_out` on app has `sheet_outcome: "dismissed"`. The pack defines `dismissed` as "closed or swiped down before answering anything". The opt-out is a button tap, so the label fits poorly. Ask the pack owner.
- `make lint` fails with `ruff: mel: No such file or directory` because `mel/` does not exist yet. `ruff check tests` passes.
- Python: the venv is 3.12.3, matching CLAUDE.md.
