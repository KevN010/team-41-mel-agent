# NOTES-J (intake and decide)

## Rejection codes and HTTP statuses (mel/api/intake.py `REJECTIONS`)
- `invalid_request` 400: extra or wrong-typed body key (identity keys included), bad survey id, `sheet_outcome` on a non app/web channel, language not the survey's, nothing to record
- `unauthorized` 401: `mel.api.auth.Unauthorized` (missing or malformed claim)
- `identity_mismatch` 403: survey exists in this org, belongs to another farmer; also `run_decision` when the insight's farmer_id is not the JWT farmer
- `unknown_survey` 404: no such survey for this org and farmer (a survey in another org looks the same)
- `unknown_flow` 404: body `flow_key` is not `mel_<survey_id>` (e.g. `mel_s_21310`)
- `invalid_answer` 422: unknown item id, option value not offered, scale value not an int in `scale_min..scale_max` (bool and float refused)
- `internal_error` 500: the record failed the pack schema or carried another farmer's id; nothing stored
- Success: 201 for completed, partial, negative_outcome; 200 for `duplicate` (`success_status(record)`)

## Disagreements and integration points
- Wrong farmer raises `IntakeError(identity_mismatch)`; it does not return or store an `identity_mismatch` ResponseRecord. A valid record needs the other farmer's `source_insight_ids`, and reading that survey breaks the org+farmer scoping rule.
- Invalid answers are a 422 and are not stored. The pack's `invalid_input` records (typed text, bad keypad) come from channel adapters as `failure` events, not from this route. A stored invalid attempt would also use up the `response_key`.
- Duplicates (decision 4): `ledger.put_response` returning DUPLICATE is the only detector. Intake then calls `apply_event` with `attempt` as a dict plus `already_answered: True` and `existing=<first record>` so D only shapes the record. No pre-check, no record built in intake. A same-instant replay returns the first record unchanged (D's transport-retry rule). Checked end to end against D's branch (`mel/outcomes.py` from PR #14): completed, negative, duplicate, replay, partial, interrupted, stale and invalid all behave.
- Late taps: D returns status `stale` (`survey_closed`) and intake stores it. HTTP is 410 for `stale` (`success_status`). Added after wave 1, not in the first rejection list.
- `mel.outcomes.InvalidAnswer` from `apply_event` maps to `invalid_answer` 422 (matched by class name).
- Event passed to `apply_event` has one key beyond D's contract: `sheet_outcome` (app/web only), which D reads (decision 3). `raw` is always None.
- Partial then complete are two responses with two `response_key`s (`delivery_attempt` 2). The ledger has no list-by-survey call, so intake does not merge answers across keys.
- Follow-up: `put_follow_up` first (source of truth), then SQS. An SQS failure is logged (class name only) and does not fail the request; a retry would only get `duplicate` and never re-enqueue. Integration should replay from `list_follow_ups`.
- `decide.py` calls `generate_survey(insight, decision, window, language, generator, judge, clock, survey_seq=<ledger.next_survey_seq>)`, matching G's final signature (PR #15). `models` is left to its default.
- `TimingException` may be returned or raised; both are handled (matched by class name).
- `run_decision` additions beyond the prompt: opt-out check before any model call (status `opted_out`); the cap is not checked here. Not persisted: the DecisionRecord (no ledger method), and surveys with status failed_review or pending_review (nothing is sent).
- `survey_closed`/`survey_replaced` (stale taps) are not enforced in intake; the Survey record has no expiry, the hand-off does.
- Metrics use a local `MetricsSink` protocol (default no-op, `LogMetrics` writes log lines). Wire E's CloudWatch sink in `DecideDeps.metrics`.
- Ownership: the prompt lists no `tests/test_decide.py`, so the `run_decision` tests live in `tests/test_intake.py`.
- Tests use local doubles for the Ledger and `apply_event`. Two tests run the real `mel.outcomes` and skip until PR #14 merges; they pass against D's branch.
