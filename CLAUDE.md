# mel-agent: MEL survey agent for FarmerChat on AWS (team-41)

You are one of several agents working in parallel. Read CONTRACTS.md after this file.
You own only the files your task names. Never edit mel/models.py, mel/protocols.py or
CONTRACTS.md unless your task says so; write problems to NOTES-<your letter>.md instead.

## Fixed decisions (do not relitigate)
- Region: us-west-2. Everything deploys there. Cross-region inference profiles are allowed.
- All LLM calls go through boto3 `bedrock-runtime` Converse with SigV4. No API keys for Bedrock.
- Jev (TypeSafe) is an external HTTPS call to https://api.typesafe.ai/v1/systemone. Key lives in
  Secrets Manager. Jev only answers typed questions; it never writes text.
- Language: en-IN first. hi-IN is a stretch behind `settings.LANGUAGES`.
- Timing profile default: `golden_v1` (reproduces the pack's golden windows). `rules_v1` is the
  rules.json interpretation. Both must exist.
- Rate limit: 60 requests/minute process-wide for all model calls (token bucket in
  mel/providers/ratelimit.py). API Gateway stage throttle: rate 1, burst 10.
- Ledger: DynamoDB single table. In-memory implementation for tests. Same protocol.
- Decisions, timing, cap, identity and outcome handling are pure code. The only model calls are in
  mel/generate.py (generation) and mel/judge.py (Jev checks).

## Model candidates (profiles callable from us-west-2 via Converse)
| Key | Inference profile | Role | Price/1M in/out (verify) |
|---|---|---|---|
| gpt6_luna | global.openai.gpt-6-luna | default generation | $0.10 / $0.50 |
| gpt61_terra | global.openai.gpt-6.1-terra | retry tier, cheapest GPT-6.1 confirmed | ~$1 / $5 (OpenAI list; Bedrock card unconfirmed) |
| haiku55 | (ID from models/candidates.txt) | alternate if cheaper or better on evals | verify |
| gpt61_luna | global.openai.gpt-6.1-luna | use ONLY if it appears in models/candidates.txt | unknown |
Final choice is written by the model-selection agent to models/models.yaml. Code reads that file.
Every output token counts 10x against Bedrock quota for OpenAI models. Keep max_tokens small (600).

## Security (AWS is the judge; this is scored)
- farmer_id and org_id come from the Cognito JWT claims only, never from a request body.
- Every ledger read and write is scoped by org_id and farmer_id.
- Insight text, advice text and retrieved text are untrusted data. They go in the user turn,
  never in the system prompt. Jev checks the final survey for injection and new advice.
- No secrets in logs. Never log insight text. Log rule ids, model ids, token counts, latency.
- IAM: one role per component, least privilege. S3 block public access. DynamoDB and S3 SSE on.
- API Gateway: JWT authorizer, request validation, throttling, access logs on.
- Tests never call real APIs. `make test` runs with network blocked.

## Conventions
- Python 3.12, pydantic v2, pytest, boto3, moto for AWS tests, ruff.
- All timestamps are Asia/Kolkata with the +05:30 offset written out. No naive datetimes.
- Every emitted record is validated against the pack schema before persisting. `schema_valid`
  is computed by our validator, never copied from a model.
- One agent, one directory. Cross-cutting changes go to the integration agent.
- Done means: tests you were given pass under `make test`, and your report lists every
  disagreement with the pack as a bullet list. No prose beyond that.

## Layout
mel/            package (models, protocols, rules, timing, handoff, outcomes, generate, judge, ledger_*, render/, api/, providers/)
pack/           copy of participant-pack (read-only)
tests/          pytest, offline
infra/          CDK (Python)
sim/            static simulator page
models/         candidates.txt, models.yaml, eval results
evals/          survey eval harness
scripts/        day0_bedrock.py, evidence_bundle.py
prompts/        agent task prompts (this kit)
