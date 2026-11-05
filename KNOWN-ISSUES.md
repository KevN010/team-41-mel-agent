# KNOWN-ISSUES (integration, wave 2)

Every NOTES-*.md item is either fixed in this branch (marked FIXED) or listed as open here.

## Deployed state (2026-11-05, us-west-2)
- Lambda `mel-api`: real handler (`mel.api.handler.lambda_handler`). Deployed with
  `aws lambda update-function-code` from `build/lambda.zip` (built by `scripts/package_lambda.sh`),
  because the `cdk` CLI is not installed on the deploy Mac. The code equals what
  `cdk deploy MelAgent-Api` would upload from `build/lambda`; the next CDK deploy re-uploads it.
- AgentCore Runtime `mel_agent-vUpOFqHRb4`: real `mel.agent` image, deployed with `python infra/runtime.py`
  (versions 2, 3 and 4 today; 4 is the restart check).
- Simulator `sim/index.html` uploaded to the simulator bucket; served at https://d3eb8n1ufruyva.cloudfront.net.
- No infrastructure was created or changed. No route was added.

## Open
- pin the Jev model version before production; thresholds were validated on jev-latest as of 2026-11-05
- **Lambda path not traced end to end with a JWT.** The trace in `evidence/e2e-run-1.md` goes through
  the AgentCore Runtime (IAM). On the API, unauthenticated calls return 401 and CORS allows the
  simulator origin. A signed-in run needs the seed password, which is the operator's to type
  (simulator sign-in, or `SEED_PASSWORD` in their own shell).
- **No trace id from AgentCore.** `InvokeAgentRuntime` returns no `traceId`; infra launches the runtime
  with `--disable-otel` and the HTTP API has no X-Ray. The evidence records the runtime session id and the
  X-Ray-format trace id we sent with each call.
- **Simulator clock vs server clock.** In LIVE mode the page's virtual clock is not sent to the server
  (no time field, by design). The server has a demo clock per org (`mel/democlock.py`), moved only through
  the AgentCore admin action `clock`: `.venv/bin/python scripts/e2e_run.py --set-clock <ISO>` (org.farmerchat).
- **Review item 13, documented, not fixed:** the token bucket is per process. Jev now takes a token from
  it, but Lambda scales out and each instance has its own bucket, and Lambda concurrency is not pinned.
  So the 60/min limit holds per instance, not per account. A real global limit needs reserved
  concurrency 1 on mel-api (infra) or a shared counter (for example DynamoDB).
- **Review item 10, Bedrock IAM:** the narrower InvokeModel resources (only the models.yaml profiles) are
  written up but not applied. Editing infra/app.py was blocked by this session's permission guard.
- **Follow-ups read is org-wide, filtered in code.** `list_follow_ups(org)` queries GSI1 for the whole org;
  the service keeps only the caller's farmer. Output is scoped; the read is not. Needs a ledger method.
- **AgentCore callers assert identity.** Any IAM principal allowed `InvokeAgentRuntime` can act for any
  farmer and move any org's demo clock. Restrict that permission to FarmerChat and the operator (infra).
- **Response items written before this change** keep the old `RESPONSE#<key>` sort key (only the e2e orgs).
- **Frequency cap uses a fresh org per e2e run.** The cap is now counted and enforced, so a second potato
  run for the same farmer inside 7 days is `frequency_capped`. `scripts/e2e_run.py` uses `org.e2e-<stamp>`.
- **Jev margin.** `matches_advice` was 0.52 on the pack's own potato survey (threshold 0.5) and 0.97 on the
  generated one. Generated surveys near the threshold go to pending_review (fail closed).
- **Retry tier = generation model** (NOTES-MODEL, NOTES-G). gpt-6.1-terra: AccessDenied (Marketplace).
- **Prices unverified** (NOTES-MODEL). luna $0.10/$0.50 from the CLAUDE.md table. Cached prompt tokens are
  now counted at the full rate, so cost is an upper bound.
- **DecisionRecord not persisted** (NOTES-J). No ledger method; it is logged (rule id, reason code) and returned.
- **Partial then complete not merged** (NOTES-J): two records, two response keys.
- **SQS replay not built** (NOTES-J): a failed enqueue is logged; the item stays in the ledger.
- **hi-IN renderers** not implemented (NOTES-I, stretch).
- **IAM: one shared role for Lambda and AgentCore; Lambda concurrency not pinned** (review items 10, 13). Infra.
- Branch is `claude/project-thread-3vuj3e` (the session's assigned branch), not `wave2-integration`.

## Fixed in this branch
- NOTES-L 1-3: failures, declines, opt-outs and sheet dismissals go to `POST /surveys/{id}/responses` with
  `kind` (`mel/api/events.py`); `POST /surveys/decide`, `GET /follow-ups`, `GET /surveys/{id}` and
  `POST /farmers/me/opt-out` are wired (`mel/api/handler.py`). The simulator defaults to these routes.
- NOTES-L clock: server demo clock per org, IAM-only (above).
- Cognito sign-in for the simulator: page prefilled with the deployed API URL, user pool and app client;
  the client allows USER_PASSWORD_AUTH; API CORS allows the CloudFront origin (checked live).
- NOTES-G, NOTES-H, NOTES-E: `MEL_*` env names read by `mel/settings.py` (MEL_TABLE, MEL_FOLLOWUP_QUEUE_URL,
  MEL_MODELS_FILE relative to the package root, MEL_METRICS_NAMESPACE, MEL_REGION); SSM `/mel/*` fallback in
  `mel/api/wiring.py`. models.yaml is on main and packaged.
- Review (a): the Jev key is read from Secrets Manager via MEL_JEV_SECRET_ARN (refreshed every 5 minutes).
- NOTES-F: System One requires `model` (live 422 without it). `jev-latest` is sent (same as main); JEV_MODEL overrides.
  The key is JEV_API_KEY when that env var is set; otherwise the secret named by MEL_JEV_SECRET_ARN. Infra puts only
  MEL_JEV_SECRET_ARN (an ARN, not the key) on the Lambda and the container; no JEV_API_KEY is set there.
- Failed model calls count: a Bedrock answer cut at max_tokens or not JSON keeps its usage, and its tokens and
  cost are added to the run (input + output + cached input, as Bedrock reports them).
- Deployed packages had no `pack/`: the runtime subset (schemas, rules, crop calendar) ships in `mel/_pack`,
  checked byte-equal to `pack/` by `tests/test_runtime_config.py`.
- NOTES-MODEL: OpenAI requests use `reasoning.effort = low`.
- Review (b): follow-ups returned only for the caller's farmer.
- Review item 3 / NOTES-J: counted outcomes call `record_cap`; `run_decision` checks `cap_count` before any
  model call (status `frequency_capped`, high priority exempt).
- Review item 5: opt-out re-checked after generation, and `put_handoff` is a transaction with a
  ConditionCheck on the OPTOUT item. It raises `FarmerOptedOut`, and run_decision returns `opted_out`.
- Review item 4: a final answer (completed or negative_outcome) writes `ANSWERED#<survey_id>` in the
  same transaction as the response. A later answer for that survey with any response_key is a
  duplicate, the first answer stands, and no follow-up is raised. Partial then complete is still
  allowed. Response sort key is `RESPONSE#<key>#<survey_id>`, so the same key on two surveys is two records.
- Review: nothing called `set_opt_out`; the opt-out route and the opt_out event do now.
- Review item 13 (part): Jev calls take a token from the shared 60/min bucket.
- Security pass on this diff: survey reads answer 404 for another farmer's id (no id oracle); decide replies
  carry reason codes only; body size checked before base64 decoding; deep JSON is a 400.
- **Review PR #21:** its strict-xfail tests for items 3 and 5 pass on this branch, so they XPASS(strict) and
  fail once both PRs are on main. Drop those three `xfail` markers when merging.

## Pack disagreements carried from wave 1 (unchanged)
- NOTES-B: golden_v1 seasonal window is 30..45 days (one-row fit, G-0009).
- NOTES-C: campaign_id / flow_id are uuid5 values found by search; no_survey `reason` is a fixed sentence per code.
- NOTES-D: opt-out on app/web gets sheet_outcome `dismissed`; web window_expired while open gets `dismissed`.
- NOTES-L / NOTES-C: scenario hand-offs embed the hi-IN survey; scenario 6 NoSurvey reason code is
  `generic_information`, the DecisionRecord's is `nothing_to_verify`.
- NOTES-G: `follow_up_at_or_below` limited to [scale_min, scale_max); rationale has no "why now".
- NOTES-I: 25 en-IN render fixtures, not 30; 10-option items cannot be voiced.
