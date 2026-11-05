# REVIEW: adversarial security and correctness review of main

Scope: main at `816b4a7`. Read: CLAUDE.md security section, `mel/api/**`, `mel/ledger_ddb.py` (and
`mel/ledger_mem.py`, which holds the shared key helpers), `mel/judge.py`, `mel/generate.py`,
`mel/providers/**`, `infra/**`, `sim/index.html`. No code was changed.

Each open item has a test under `tests/review/`. The tests are marked `xfail(strict=True)`, so
`make test` stays green while the bug exists. When a fix lands, the test passes, strict xfail
turns that into a failure, and the fixer removes the marker. Run `pytest tests/review --runxfail`
to see each failure.

Result on main at `816b4a7`: 6 open, 9 closed. With integration PRs #23 and #24: 2 open (items 10
and 13, both in infra/ or the Jev client), 13 closed. PR #23 also covers note B (follow-ups filtered
to the caller's farmer) and note C (`set_opt_out` is now called).

**Merge order: #23, then #24, then this PR.** Items 3 and 5 are fixed in #23, and items 4 and 5 in
#24. Their tests in `tests/review/` have no xfail marker any more, so they fail on main until both
PRs are merged.

| # | Item | Status | file:line | Test |
|---|---|---|---|---|
| 1 | Identity from body overrides JWT | closed, because identity comes only from `requestContext.authorizer` claims, the payload model forbids every extra key, and the event and attempt use the JWT farmer. Cognito `farmer_id`/`org_id` are immutable and not client-writable. | mel/api/auth.py:71, mel/api/intake.py:99, mel/api/intake.py:282, mel/api/decide.py:212, infra/app.py:133 | none (covered by tests/test_intake.py::test_no_body_field_can_override_identity) |
| 2 | Cross-org read of a survey or follow-up | closed, because every key starts with `ORG#<org_id>`, ids with `#` are refused, and the JWT claim regexes refuse `#`. See note B for a cross-farmer risk inside one org. | mel/ledger_mem.py:49, mel/ledger_mem.py:60, mel/api/auth.py:24 | none (covered by tests/test_ledger.py::test_cross_org_read_returns_nothing) |
| 3 | Cap bypass by retrying a failed delivery | **fixed in PR #23**. On main no code called `record_cap` or `cap_count`. PR #23 records the cap in intake when `counts_toward_cap` is true. `record_cap` is idempotent per survey_id, so a retried delivery counts once. PR #23 also checks the cap in `run_decision` before the model call (status `frequency_capped`, high priority exempt). | mel/ledger_ddb.py:220, mel/api/intake.py:304, mel/api/decide.py:246 (main) | tests/review/test_review_cap.py (regression, needs PR #23) |
| 4 | Duplicate answer overwrites the first | **fixed in PR #24**. On main a duplicate was found only when the client re-sent the same `response_key`, and a key reused on another survey was a false duplicate. PR #24 writes an `ANSWERED#<survey_id>` marker in the same transaction as a final answer, and puts survey_id in the response sort key. A second answer to an answered survey is now `duplicate` whatever its key. The first record still stands. | mel/ledger_ddb.py:184, mel/api/intake.py:295 (main) | tests/review/test_review_duplicates.py (regression, needs PR #24) |
| 5 | Opt-out raced by a concurrent attempt | **fixed in PRs #23 and #24**. On main, an opt-out sent during generation, which takes seconds, was lost. #23 checks the opt-out again before the writes. #24 writes the hand-off in a transaction with a ConditionCheck on OPTOUT, as `put_attempt` does, so an opt-out after the re-check also stops it. The survey item can still be stored without a hand-off. It is never sent. | mel/api/decide.py:247, mel/api/decide.py:273 (main), mel/ledger_ddb.py:148 | tests/review/test_review_optout_race.py (2 regression tests, need PRs #23 and #24) |
| 6 | Jev timeout leads to an accepted survey | closed, because a timeout, transport error, bad status or bad body gives `pending_review=True, ok=False`. The model forbids `ok` with `pending_review`. `generate_survey` accepts only `verdict.ok`. `run_decision` stores nothing unless the status is `accepted`. | mel/judge.py:234, mel/models.py:545, mel/generate.py:185, mel/api/decide.py:259 | none (covered by tests/test_judge.py::test_timeout_retries_then_pending) |
| 7 | Model-supplied schema_valid trusted | closed, because `merge_draft` keeps only `items` and `rationale` from the draft. `schema_valid` is set after our validator passes, and the other self_eval fields come from Jev scores. | mel/generate.py:215, mel/generate.py:245, mel/generate.py:283 | none (covered by tests/test_generate.py::test_model_schema_valid_true_on_invalid_draft_is_ignored) |
| 8 | Insight text reaching the system prompt | closed, because the system prompt is a static file read once. Insight and repair errors are JSON in the user turn. Bedrock sends `system` and `user` in separate fields. Jev gets insight text only in `state`, never in the question text. | mel/generate.py:366, mel/generate.py:447, mel/providers/bedrock.py:174, mel/judge.py:257 | none (covered by tests/test_generate.py::test_llm_generator_puts_insight_in_user_turn_only) |
| 9 | Secret or insight text in any log call | closed, because all 20 log calls in `mel/` log codes, ids, counts, latency, scores or exception class names only. The Jev key is a SecretStr and is masked in `repr`. See note F for the handler. | mel/api/intake.py:193, mel/judge.py:235, mel/generate.py:313, mel/providers/bedrock.py:276 | none |
| 10 | IAM role with wildcard action or resource | **open**. No wildcard actions. The `*` resources for ECR auth and PutMetricData are required. But (a) the Lambda and the AgentCore runtime share one role, and CLAUDE.md asks for one role per component. (b) The role has DynamoDB `Scan`, `DeleteItem`, `BatchGetItem`, `BatchWriteItem`, which no code uses. `Scan` reads every org. (c) Bedrock is granted on `inference-profile/*` and `anthropic.*`, but models.yaml uses only `global.openai.gpt-6-luna`. | infra/app.py:155, infra/app.py:166, infra/app.py:162 | tests/review/test_review_iam.py |
| 11 | S3 or DynamoDB without encryption | closed, because DynamoDB uses AWS_MANAGED SSE with PITR. All three buckets use S3_MANAGED with BLOCK_ALL and enforce_ssl. Both queues use SQS_MANAGED. | infra/app.py:73, infra/app.py:81, infra/app.py:87, infra/app.py:91, infra/app.py:106 | none |
| 12 | API route without authorizer or throttle | closed, because all 5 routes have `authorization_type="JWT"` with the Cognito authorizer. The `$default` stage throttles every route at rate 1, burst 10. Access logs are on. See note G for request validation. | infra/app.py:208, infra/app.py:213 | none |
| 13 | Rate limiter bypass by concurrency | **open**. The bucket is thread safe inside one process. But (a) Jev is one of the two model calls and never takes a token. (b) The bucket is per process and the `mel-api` Lambda has no reserved concurrency, so concurrent requests run in new processes, each with its own 60 rpm. | mel/judge.py:255, mel/providers/ratelimit.py:92, infra/app.py:193 | tests/review/test_review_ratelimit.py |
| 14 | Simulator storing a password or token | closed, because the ID token is kept only in a JS variable. The password field is cleared before the Cognito call. The page uses no localStorage, sessionStorage, IndexedDB or cookies, and puts nothing in the URL. | sim/index.html:483, sim/index.html:604, sim/index.html:616 | none |
| 15 | Converse request without max_tokens | closed, because every request sets `inferenceConfig.maxTokens` from the caller or models.yaml (600). The settings value must be at least 1. A cut-off reply raises ProviderError. | mel/providers/bedrock.py:176, mel/providers/bedrock.py:225, mel/generate.py:463 | none |

## Notes outside the 15 items (for the integration thread)

- A. `mel/api/handler.py` is not on main. infra points the Lambda at `mel.api.handler.lambda_handler`, so every route fails until the integration thread adds it.
- B. `GET /follow-ups` is open to every farmer JWT. `list_follow_ups(org)` returns every farmer's follow-up in the org, with their answers. The handler must check a staff group claim, or filter by farmer.
- C. Nothing calls `ledger.set_opt_out`. Intake handles only `kind=answer`. `POST /farmers/me/opt-out` has no handler. Today an opt-out is never recorded.
- D. Settings reads `LEDGER_TABLE`, `FOLLOW_UP_QUEUE_URL`, `JEV_API_KEY` and `MODELS_FILE`. infra sets `MEL_TABLE`, `MEL_FOLLOWUP_QUEUE_URL`, `MEL_JEV_SECRET_ARN` and `MEL_MODELS_FILE`. The ledger reads `MEL_TABLE` itself, but the queue URL stays unset and no code loads the Jev key from Secrets Manager. Result: no follow-up reaches SQS, and every survey is `pending_review` (fails closed, but nothing ships).
- E. `identity_mismatch` (403) and `unknown_survey` (404) differ, and survey ids are sequential. A farmer can find out which survey ids exist in the org. Low risk.
- F. `run_decision` calls `Insight.model_validate`. A pydantic ValidationError message has the input value in it. The handler must not log `str(exc)` or tracebacks of these errors.
- G. CLAUDE.md asks for API Gateway request validation. HTTP APIs have no request validators. The only validation is pydantic in the app. Say so in the evidence, or move to a REST API.

## Disagreements with the pack

- outcome_codes.json `duplicate_answer` says a second answer to an answered survey is a duplicate. On main the code finds a duplicate only on the same `response_key` (item 4; fixed in #24).
- rules.json `frequency_cap` (1 survey per 7 days, high priority exempt) is copied into the hand-off, but our code never counts or checks it (item 3).
- outcome_codes.json `farmer_opted_out` says to stop all future surveys. No code records the opt-out (note C).
