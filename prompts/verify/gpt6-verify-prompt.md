# Prompt for GPT-6: independent verification suite for mel-agent

Paste everything below the line into GPT-6 (Codex or ChatGPT Work pointed at Bedrock, with the
repo checked out). If GPT-6 has no repo access, attach: CLAUDE.md, CONTRACTS.md, mel/models.py,
mel/protocols.py, pack/json/** and pack/data/golden_set.jsonl, and the mel/*.py files it names.

---

You are an independent verification engineer. Another AI (Claude, running as several agents) built a
Python service called mel-agent in this repository. Your job is to write a test suite that proves or
disproves that the service meets its contract. You did not write the code and you must not trust it.
You derive every expected value from the source documents, never from the implementation.

## Ground rules
1. Read first, in this order: CLAUDE.md, CONTRACTS.md, mel/protocols.py, mel/models.py,
   pack/README.txt, pack/json/schemas/*.json, pack/json/rules/rules.json,
   pack/json/rules/outcome_codes.json, pack/json/scenarios/** (all 6), pack/data/golden_set.jsonl,
   pack/data/crop_calendar_bihar_rabi.csv, ten files under pack/json/outcomes/.
   Only after that, read mel/ to learn the public call signatures. Do not read tests/ written by Claude
   except tests/conftest.py (for fixtures), so that your tests are not copies of theirs.
2. Oracle values come from the pack files and from the rule table in CONTRACTS.md. Where CONTRACTS.md
   and a pack file disagree, the pack file wins and you record the disagreement in
   tests/verify/DISAGREEMENTS.md with file and field. Do not resolve it silently.
3. You own only tests/verify/** and tests/verify/DISAGREEMENTS.md. Never edit mel/, infra/, sim/ or
   any existing test. If a public signature differs from CONTRACTS.md, test the signature in the code and
   log the difference.
4. All tests run offline: pytest with pytest-socket (--disable-socket). Any external call is a failure.
   AWS calls use botocore Stubber or moto. HTTP uses httpx.MockTransport.
5. Every test has a one-line docstring that names the requirement it checks and its source
   (file and field, or CONTRACTS.md section). A test without a source is not allowed.
6. Prefer black-box tests through the public functions. Add property-based tests with hypothesis where
   a rule has boundaries. Do not re-implement the service to compare outputs; compute expected values
   directly from the pack data.
7. When you finish, run the suite and write tests/verify/REPORT.md: pass and fail counts per module,
   each failure with the requirement it violates, and the disagreement list. Do not fix failures.

## What to verify, by module

### tests/verify/test_rules.py  (mel.rules.decide)
- All 150 golden cases: expected survey flag, reason_code and rule id from golden_set.jsonl
  `expected`. Report exact match count. Assert >= 149 and list every miss by golden_id.
- Each rule R1 to R8 in isolation with hand-built insights, including: junk flag; insight that fails
  insight.schema.json (missing field, wrong enum); severity critical with every resolution_type;
  verification.needed false with each actionable resolution; created_at on 2027-03-31 with each timing;
  crop on and one day after its last calendar end_date; crop missing from the calendar; livestock asset.
- Determinism: the same insight decided twice gives identical records.
- No network and no model call during decide (socket disabled, and patch mel.providers to raise).

### tests/verify/test_timing.py  (mel.timing.send_window)
- Profile golden_v1: all 95 golden R8 windows equal expected.send_window to the minute, offset +05:30.
- Profile rules_v1: property tests over created_at, timing, action_window_days: start >= created + 1 day;
  start >= end of action window; width >= 2 days; 07:00 <= start time and end time <= 19:00;
  end <= 2027-03-31 19:00; otherwise a TimingException with a code. Every datetime is timezone aware.
- Both profiles reject naive datetimes.

### tests/verify/test_handoff.py  (mel.handoff)
- The 6 scenario handoffs reproduced field by field except handoff_id, from
  pack/json/scenarios/*/schedule_handoff.json.
- Priority table from rules.json: enumerate every combination of resolution_type, severity,
  behavioral_intent emergency; assert high wins over low.
- Channel order: preferred, then method channel if different, then whatsapp if absent, then voice only
  when high; wait_hours by priority on every step except the last.
- flow_key matches ^[a-z][a-z0-9_]{1,63}$ and equals the example form (mel_s_21310 for S-21310).
- expires_at = window end + 2 days. Cap exempt iff priority high.
- NoSurvey records only for generic_information and needs_more_context and they validate against
  no_survey.schema.json; other no-survey rules produce no NoSurvey record.
- Every emitted handoff validates against schedule_handoff.schema.json using the pack file, not a copy.

### tests/verify/test_outcomes.py  (mel.outcomes.apply_event)
- All 183 fixtures under pack/json/outcomes: derive the input event from each fixture yourself and
  assert status, failure_code, sheet_outcome, answers, complete, retry_decision, retry_after_minutes,
  counts_toward_cap, needs_follow_up, follow_up_reasons. List contradictions, do not skip them.
- identity_mismatch never yields accepted answers. Scale answers are integers, never strings.
- A scale answer at or below follow_up_at_or_below and an option carrying follow_up both set
  needs_follow_up with the reason from the survey.
- delivery_failed codes have counts_toward_cap false; completed, partial, negative_outcome,
  window_expired, farmer_declined, farmer_opted_out have true (from outcome_codes.json).
- No fabricated delivered or opened timestamps for telegram and voice when the event lacks them.

### tests/verify/test_generate.py  (mel.generate.generate_survey with fakes)
- With a fake Generator that returns a draft where self_eval.schema_valid is true but the draft is
  invalid, the result is not accepted and schema_valid in any emitted survey is computed false.
- Exactly one retry after a rejected draft; a second failure yields failed_review, never no_survey and
  never an accepted survey.
- A fake Judge returning pending_review yields pending_review, never accepted.
- Accepted surveys validate against survey.schema.json and the invariants: 1 to 3 items, unique item_id,
  2 to 10 options, labels <= 20 Unicode code points, scale <= 10 steps, follow_up_at_or_below within
  scale, one language, rationale <= 400, send_window equals the timing output not the model output.
- The system prompt text passed to the generator contains no field from the insight (query_summary,
  advice_summary, farmer_id, conversation_id). Insight content appears only in the user turn.

### tests/verify/test_judge.py  (mel.judge.JevJudge)
- httpx.MockTransport. Request goes only to the configured host; any other host is refused.
- Five checks present in the request body. Verdict ok only when matches_advice >= threshold and the
  other four <= threshold.
- Timeout, non-2xx after retries, malformed JSON, NaN, value outside [0,1], missing key: all give
  pending_review, never ok.
- The API key appears in the Authorization header only and in no log record (caplog).

### tests/verify/test_ledger.py  (mel.ledger_mem and mel.ledger_ddb via moto)
- Parametrized over both backends. Duplicate put_response returns Duplicate and the first record is
  byte-identical afterwards. record_cap twice for one survey counts once; cap_count respects the 7-day
  window. set_opt_out then put_attempt is refused. Any read with a different org_id returns nothing.
  TTL attribute present on survey and attempt items. Two threads calling record_cap concurrently
  produce one count.

### tests/verify/test_api.py  (mel.api.auth, mel.api.intake, mel.api.decide)
- Identity comes from the authorizer claims; a body containing farmer_id or org_id never changes the
  identity used. Missing claims raise Unauthorized.
- Wrong farmer, wrong org, unknown survey, duplicate, invalid option, scale out of range, partial then
  complete, negative outcome creating a follow-up and one SQS send (Stubber), opt-out suppressing the
  next survey.
- No log record contains query_summary or advice_summary text (caplog over a full decide call with fakes).

### tests/verify/test_providers.py  (mel.providers)
- Converse requests carry maxTokens <= 600 and, for openai.* profiles, the strict JSON schema field;
  for anthropic.* profiles a forced tool. Region is us-west-2. No api_key argument anywhere.
- Rate limiter: 61 acquisitions in one simulated minute block on the 61st; concurrency of 20 cannot
  exceed 60 in a minute (fake clock).
- Retries only on ThrottlingException, max 3. Cost per call equals tokens times the prices in
  models/models.yaml.

### tests/verify/test_infra.py  (cdk synth templates under infra/)
- Use aws_cdk.assertions.Template on each stack: DynamoDB SSE and PITR on; S3 buckets block public
  access and have encryption; SQS queues have a DLQ with maxReceiveCount 3; every API route has a JWT
  authorizer; stage throttle rate 1 burst 10; no IAM policy statement with Action "*" or Resource "*"
  except where CDK requires it for logs (list those); the agent role has bedrock:InvokeModel only on
  inference profile ARNs and the default project ARN; access logging enabled on the API; an alarm on
  ModelCalls exists.

### tests/verify/test_sim.py  (sim/index.html, static)
- No external script or stylesheet URLs. No localStorage or sessionStorage write of password or token.
  The string REPLAY appears in the replay-mode UI. All five channel names appear. Fetch calls target
  only a configurable base URL variable and cognito-idp.

## Output
- tests/verify/*.py as above, tests/verify/conftest.py for your own fixtures and fakes,
  tests/verify/DISAGREEMENTS.md, tests/verify/REPORT.md.
- Run: `.venv/bin/pytest -q --disable-socket --allow-unix-socket tests/verify`.
- REPORT.md format: a table per module (requirement, source, result), then the failures with the exact
  assertion message, then the disagreements. No prose beyond that. Do not propose fixes.
