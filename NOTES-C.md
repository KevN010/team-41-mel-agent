# NOTES-C: handoff

## Delivered
- `mel/handoff.py`: `build_handoff`, `build_no_survey`, plus helpers `priority_for`, `channel_order_for`, `RULE_REASON`, `HandoffError`.
- `tests/test_handoff_scenarios.py`, `tests/test_handoff_rules.py`: 77 tests.
- All five scenario hand-offs are reproduced exactly (`got == expected`), `handoff_id`, `created_at` and `flow_id` included.

## Disagreements with the pack
- `rules.json` has `campaign_name` only. The prompt says campaign and flow ids come from `rules.json`; they do not. The pack's ids are uuid5: `ns = uuid5(NAMESPACE_URL, "https://farmerchat.digitalgreen.org/mel")`, `campaign_id = uuid5(ns, campaign_name)`, `flow_id = uuid5(ns, survey_id)`. I found this by search; it reproduces all five scenarios. The pack documents none of it. If FarmerChat issues the real ids, replace `campaign_id()` and `flow_id()`.
- `handoff_id` is not specified. All five scenarios use `H-` + the survey number (S-21310 -> H-21310). I do the same, so it is idempotent per survey.
- `created_at` is not specified. The five scenarios use 23:00 on the insight's day. I use `clock.now()`; the scenario tests set the clock to the pack value.
- `no_survey.json` scenario 6 `reason` is a sentence written for that insight. `build_no_survey(decision)` has no insight text, and insight text is untrusted. I emit a fixed sentence per code, so `reason` differs from the pack. All other fields are equal.
- The prompt says the no-survey rules "put the golden reason_code in the record". `rules.py` already sets it. I overwrite it with the golden code for the rule id if it differs.
- `build_handoff` raises `HandoffError` if the decision is not R8, if insight, decision and survey disagree on insight or farmer id, or if `decision.send_window` differs from `survey.send_window`. The prompt is silent. Messages name fields, never values.
- `build_handoff` does not check that the survey language equals `insight.conversation_language`. The pack embeds the hi-IN survey; the caller picks the language.
- `rules` defaults to `load_rules()` when omitted.
- `make lint` needs `.venv/bin/ruff`; `requirements.txt` has it, the cloud venv did not. A bare `ruff` with no project config flags DTZ001 in `tests/test_models_roundtrip.py` (wave 0 file, not mine). `.venv/bin/ruff` passes.
