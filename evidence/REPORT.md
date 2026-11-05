# mel-agent evidence report

Generated 2026-11-05T07:48:49-05:00 by `evals/survey_eval.py`. Region us-west-2. Numbers below come from `evidence/survey_eval.json` and `evidence/inventory.json`; a section that could not run says so and carries no numbers.

## 1. Decision rules on the golden set

**150/150** golden rows match on survey flag, reason code and rule id.

| Rule | Expected rows | Rows we assigned | Matched |
|---|---|---|---|
| R1 | 14 | 14 | 14 |
| R2 | 6 | 6 | 6 |
| R3 | 12 | 12 | 12 |
| R4 | 10 | 10 | 10 |
| R5 | 10 | 10 | 10 |
| R6 | 2 | 2 | 2 |
| R7 | 1 | 1 | 1 |
| R8 | 95 | 95 | 95 |

Misses: none.

## 2. Timing

`golden_v1` reproduces **95/95** golden R8 send windows (0 timing exceptions).

For information, `rules_v1` (rules.json interpretation) matches 0/95 golden windows with 1 timing exceptions. rules_v1 follows rules.json, not the golden windows; a low match is expected.

## 3. Outcome fixtures

**183/183** pack outcome fixtures pass through `mel.outcomes.apply_event` (10 asserted fields each).

Contradictions: none.

## 4. Generation on the 5 actionable scenarios

Model `global.openai.gpt-6-luna` (retry `global.openai.gpt-6-luna`), **max_tokens 900** (Dwayne's override of the 600 in CLAUDE.md, set with the MAX_TOKENS env var), language en-IN, one run per scenario, live Jev judge model `jev-latest` (key status: loaded).

| Metric | Value |
|---|---|
| Scenarios run | 5 |
| Schema valid (our validator) | 5/5 = 1.00 |
| Accepted (schema valid and Jev ok) | 5/5 |
| Jev verdicts | ok: 5 |
| Model calls | 7 |
| Latency p50 / p95 per model call | 2,577 ms / 4,105 ms |
| Tokens in / out, all calls | 20,349 / 4,110 |
| Of which failed calls (2) in / out | 5,804 / 1,337 ($0.001249) |
| Cost per accepted survey, failed calls counted | $0.000818 |
| Cost per accepted survey, successful calls only | $0.000568 |
| Jev pass count (verdict ok) | 5/5 |
| Jev | available; model `jev-latest`; verdicts ok: 5 |
| Cost per generated survey | $0.000818 |
| Total spend of this run (Bedrock) | $0.004090 |

Prices used: $0.1 in / $0.5 out per 1M tokens, from the CLAUDE.md model table. They are **unverified**, so cost figures are estimates. Jev usage is not billed through Bedrock and is not in the total.

| Scenario | Status | Attempts | Schema | Jev | Calls ms | Tokens in/out | Cost |
|---|---|---|---|---|---|---|---|
| 1-mustard-aphid-spray | accepted | 1 | valid | ok | 1936 | 2881/362 | $0.000469 |
| 2-wheat-irrigation-timing | accepted | 1 | valid | ok | 2577 | 2896/561 | $0.000570 |
| 3-potato-blight-wait | accepted | 2 | valid | ok | 1901/2839 | 5859/1079 | $0.001125 |
| 4-cow-vet-escalation | accepted | 1 | valid | ok | 1731 | 2886/347 | $0.000462 |
| 5-wheat-variety-plan | accepted | 2 | valid | ok | 4105/3884 | 5827/1761 | $0.001463 |

Findings:

- 3-potato-blight-wait needed 2 attempts; the retry produced the accepted survey. First-attempt reasons: attempt1: schema:$.items[1].options[3].label; attempt1: $.items[1].options[3].label: 25 code points, at most 20 allowed (INV-LABEL). Stop reasons per call: end_turn, end_turn; output tokens per call: 437, 642 (max_tokens 900).
- 5-wheat-variety-plan needed 2 attempts; the retry produced the accepted survey. First-attempt reasons: attempt1: generator_error:ProviderError. Stop reasons per call: max_tokens, end_turn; output tokens per call: 900, 861 (max_tokens 900).
- Closest Jev score to its threshold: matches_advice 0.58 on 4-cow-vet-escalation (accept needs at least the matches_advice threshold, 0.5 by default; the other four checks must be at or below theirs).
- Token counts are all input tokens per call (Converse `totalTokens` minus output), cached or not; spend covers every response received, failed parses included. A call that raised before any response carries no usage and is not metered.

## 5. Model selection

Eval: 5 actionable pack scenarios x 3 runs, Converse in us-west-2, max_tokens 600, prompt evals/prompt_v0.md. Pass = full survey validates against pack survey.schema.json and the invariants (1..3 items, unique item_id, 2..10 options, label <= 20 code points, scale <= 10 steps).

| Profile | Pass rate | Avg in tok | Avg out tok | Latency p50 ms | Price in/out per 1M | Cost per call | Cost per accepted survey | Hit max_tokens |
|---|---|---|---|---|---|---|---|---|
| global.openai.gpt-6-luna | 15/15 = 1.00 | 1180 | 184 | 1146 | $0.1/$0.5 (unverified) | $0.000210 | $0.000210 | 0/15 |
| global.anthropic.claude-haiku-5-5 | 13/15 = 0.87 | 2449 | 337 | 2025 | unpriced | n/a | n/a | 0/15 |
| global.anthropic.claude-haiku-4-5-20251001-v1:0 | 9/15 = 0.60 | 2156 | 230 | 1800 | $1.0/$5.0 (unverified) | $0.003307 | $0.005511 | 0/15 |

- generation: global.openai.gpt-6-luna
- retry: global.openai.gpt-6-luna

## 6. AWS resource inventory

Region us-west-2. CDK stack outputs, then `aws resourcegroupstaggingapi get-resources` filtered by tag `Project=MelAgent`.

### CDK stack outputs

The deployed stacks define no CloudFormation outputs; cross-stack values are the `/mel/*` SSM parameters listed in `infra/INFRA.md`. Stacks found: MelAgent-Agent, MelAgent-Api, MelAgent-Auth, MelAgent-Data, MelAgent-Obs, MelAgent-Secrets.

### Tagged resources (44)

- `arn:aws:apigateway:us-west-2::/apis/ib6pvb874g`
- `arn:aws:apigateway:us-west-2::/apis/ib6pvb874g/stages/$default`
- `arn:aws:bedrock-agentcore:us-west-2:423964648384:runtime/mel_agent-vUpOFqHRb4`
- `arn:aws:bedrock-agentcore:us-west-2:423964648384:runtime/mel_agent-vUpOFqHRb4/runtime-endpoint/DEFAULT`
- `arn:aws:bedrock-agentcore:us-west-2:423964648384:workload-identity-directory/default/workload-identity/mel_agent-vUpOFqHRb4`
- `arn:aws:cloudformation:us-west-2:423964648384:stack/CDKToolkit/7ef5b470-d90d-11f1-9ecc-0affc8a46ee9`
- `arn:aws:cloudformation:us-west-2:423964648384:stack/MelAgent-Agent/61e0ad80-d90e-11f1-a774-066ad4150793`
- `arn:aws:cloudformation:us-west-2:423964648384:stack/MelAgent-Api/807692a0-d90e-11f1-ba63-0609bd750f8f`
- `arn:aws:cloudformation:us-west-2:423964648384:stack/MelAgent-Auth/d5b2c0a0-d90d-11f1-ac24-06d1b48a55c5`
- `arn:aws:cloudformation:us-west-2:423964648384:stack/MelAgent-Data/d5ad6970-d90d-11f1-aa3b-0affcd16f033`
- `arn:aws:cloudformation:us-west-2:423964648384:stack/MelAgent-Obs/98edb200-d90e-11f1-8bef-06f5d0a445c3`
- `arn:aws:cloudformation:us-west-2:423964648384:stack/MelAgent-Secrets/d5a727e0-d90d-11f1-974b-02ffd50da131`
- `arn:aws:cloudwatch:us-west-2:423964648384:alarm:mel-followup-dlq-nonempty`
- `arn:aws:cloudwatch:us-west-2:423964648384:alarm:mel-model-calls-over-60`
- `arn:aws:cognito-idp:us-west-2:423964648384:userpool/us-west-2_9ZHQYVRnk`
- `arn:aws:dynamodb:us-west-2:423964648384:table/mel-ledger`
- `arn:aws:ecr:us-west-2:423964648384:repository/cdk-hnb659fds-container-assets-423964648384-us-west-2`
- `arn:aws:ecr:us-west-2:423964648384:repository/mel-agent`
- `arn:aws:lambda:us-west-2:423964648384:function:mel-api`
- `arn:aws:logs:us-west-2:423964648384:log-group:/aws/apigateway/mel-api`
- `arn:aws:logs:us-west-2:423964648384:log-group:/aws/bedrock-agentcore/runtimes/mel_agent-vUpOFqHRb4-DEFAULT`
- `arn:aws:logs:us-west-2:423964648384:log-group:/aws/lambda/mel-api`
- `arn:aws:s3:::cdk-hnb659fds-assets-423964648384-us-west-2`
- `arn:aws:s3:::melagent-data-accesslogs8b620eca-pbuxyfinkfbg`
- `arn:aws:s3:::melagent-data-artifacts82dd59a1-a242w2kuxstu`
- `arn:aws:s3:::melagent-data-simulatorb4e5c957-gepubrdlyxfv`
- `arn:aws:secretsmanager:us-west-2:423964648384:secret:mel/jev-api-key-twLWqn`
- `arn:aws:sqs:us-west-2:423964648384:mel-followups`
- `arn:aws:sqs:us-west-2:423964648384:mel-followups-dlq`
- `arn:aws:ssm:us-west-2:423964648384:parameter/cdk-bootstrap/hnb659fds/version`
- `arn:aws:ssm:us-west-2:423964648384:parameter/mel/agent_role_arn`
- `arn:aws:ssm:us-west-2:423964648384:parameter/mel/agent_runtime_arn`
- `arn:aws:ssm:us-west-2:423964648384:parameter/mel/api_url`
- `arn:aws:ssm:us-west-2:423964648384:parameter/mel/artifacts_bucket`
- `arn:aws:ssm:us-west-2:423964648384:parameter/mel/dashboard_name`
- `arn:aws:ssm:us-west-2:423964648384:parameter/mel/ecr_repo_uri`
- `arn:aws:ssm:us-west-2:423964648384:parameter/mel/followup_dlq_url`
- `arn:aws:ssm:us-west-2:423964648384:parameter/mel/followup_queue_url`
- `arn:aws:ssm:us-west-2:423964648384:parameter/mel/jev_secret_arn`
- `arn:aws:ssm:us-west-2:423964648384:parameter/mel/sim_bucket`
- `arn:aws:ssm:us-west-2:423964648384:parameter/mel/sim_url`
- `arn:aws:ssm:us-west-2:423964648384:parameter/mel/table_name`
- `arn:aws:ssm:us-west-2:423964648384:parameter/mel/user_pool_client_id`
- `arn:aws:ssm:us-west-2:423964648384:parameter/mel/user_pool_id`

Resources that do not support tagging (for example API Gateway routes and the AgentCore endpoint) inherit ownership through their parent stack; `infra/INFRA.md` lists them.

## 7. Security controls and the test that proves each

`make test` runs `tests/` offline. Paths starting `infra/` are CDK template and script tests run with `pytest infra/test_contract.py`.

| Control | Proof |
|---|---|
| farmer_id and org_id come from the Cognito JWT claims only, never the request body | `tests/test_auth.py::test_body_headers_query_and_path_are_ignored`<br>`tests/test_auth.py::test_body_cannot_stand_in_for_missing_claims`<br>`tests/test_intake.py::test_no_body_field_can_override_identity`<br>`tests/test_intake.py::test_stored_record_carries_jwt_identity_not_body` |
| Every ledger read and write is scoped by org_id and farmer_id | `tests/test_ledger.py::test_cross_org_read_returns_nothing`<br>`tests/test_ledger.py::test_cross_farmer_read_returns_nothing`<br>`tests/test_ledger.py::test_ids_that_could_forge_a_key_are_rejected`<br>`tests/test_intake.py::test_every_ledger_call_is_scoped_to_identity`<br>`tests/test_intake.py::test_org_comes_from_identity_for_every_write` |
| A survey cannot be answered by a different farmer (identity_mismatch) or read across orgs | `tests/test_intake.py::test_wrong_farmer_is_identity_mismatch`<br>`tests/test_intake.py::test_wrong_org_looks_like_unknown_survey`<br>`tests/test_ledger.py::test_survey_id_cannot_be_taken_by_another_farmer` |
| Insight and advice text are untrusted data: user turn only, never the system prompt | `tests/test_generate.py::test_system_prompt_is_stable_and_has_no_insight_text`<br>`tests/test_providers.py::test_openai_request_has_strict_schema_and_user_turn_only`<br>`tests/test_judge.py::test_untrusted_text_only_in_state_never_in_questions` |
| Jev checks the final survey; any failure or Jev outage blocks acceptance (pending_review) | `tests/test_judge.py::test_each_failing_check_blocks`<br>`tests/test_judge.py::test_timeout_retries_then_pending`<br>`tests/test_generate.py::test_judge_not_ok_is_pending_review`<br>`tests/test_intake.py::test_unaccepted_survey_is_not_stored_or_handed_off` |
| Jev key is sent only to the allowed host and never logged or shown in repr | `tests/test_judge.py::test_wrong_host_never_sends_key`<br>`tests/test_judge.py::test_key_and_insight_text_never_logged_or_in_repr`<br>`tests/test_judge.py::test_redirect_is_not_followed` |
| No insight, draft or answer text in logs | `tests/test_generate.py::test_reasons_do_not_echo_draft_text`<br>`tests/test_intake.py::test_no_answer_text_in_logs`<br>`tests/test_invariants.py::test_messages_never_echo_values`<br>`tests/test_providers.py::test_bad_output_raises_provider_error_without_echo` |
| Every record is validated against the pack schema before persisting; schema_valid is ours, not the model's | `tests/test_intake.py::test_record_failing_pack_schema_is_not_stored`<br>`tests/test_generate.py::test_model_schema_valid_true_on_invalid_draft_is_ignored`<br>`tests/test_generate.py::test_garbage_drafts_fail_closed` |
| 60 requests/minute process-wide token bucket on all model calls | `tests/test_providers.py::test_bucket_never_exceeds_rpm_in_a_minute`<br>`tests/test_providers.py::test_every_attempt_takes_a_rate_limit_token` |
| Model region fixed to us-west-2 | `tests/test_providers.py::test_region_must_be_us_west_2` |
| Timestamps are Asia/Kolkata with explicit offset; naive datetimes are rejected | `tests/test_models_roundtrip.py::test_naive_datetime_rejected`<br>`tests/test_ledger.py::test_naive_timestamp_is_rejected` |
| Tests never call real APIs (network blocked in make test) | `tests/test_models_roundtrip.py::test_network_is_blocked` |
| API Gateway routes require the JWT authorizer | `infra/test_contract.py::test_routes_use_jwt` |
| DynamoDB: SSE on, point-in-time recovery on, TTL attribute | `infra/test_contract.py::test_dynamodb_contract` |
| S3 block public access and default encryption; CloudFront uses OAC and HTTPS | `infra/test_contract.py::test_s3_and_cloudfront_security` |
| IAM policies list explicit actions (no wildcard actions) | `infra/test_contract.py::test_iam_actions_are_explicit` |
| SQS follow-up queue encrypted with a dead-letter queue | `infra/test_contract.py::test_queue_contract` |

Controls with no unit test, verified live or by configuration only:

- API Gateway stage throttle (rate 1, burst 10), access logs and request payload validation: defined in CDK; HTTP API has no native request validation, so payload validation is in the Lambda (`tests/test_intake.py::test_invalid_request`). See `infra/INFRA.md`.
- Unauthenticated requests are rejected: live smoke result (HTTP 401) recorded in `infra/INFRA.md`.

