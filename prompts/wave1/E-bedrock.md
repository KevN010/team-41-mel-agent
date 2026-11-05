Model: Sonnet. Branch: w1-E.
Goal: the Bedrock provider and the rate limiter.
Read first: CLAUDE.md (models, rate limit), mel/protocols.py, models/models.yaml (may not exist yet; read models/candidates.txt), evals/prompt_v0.md if present.
You own: mel/providers/__init__.py, mel/providers/bedrock.py, mel/providers/ratelimit.py, mel/providers/metrics.py, tests/test_providers.py, NOTES-E.md.
Deliver: BedrockChat(model_key) reading models/models.yaml; converse_json(system, user, schema, max_tokens)
-> (dict, usage) using boto3 bedrock-runtime Converse in us-west-2. For OpenAI profiles request strict
JSON via additionalModelRequestFields {"text": {"format": {"type": "json_schema", "strict": true, ...}}};
for Anthropic profiles use toolConfig with one tool and toolChoice forced. Parse, never trust: validate
JSON parses and raise ProviderError otherwise. Retries: 3 with backoff on ThrottlingException only.
ratelimit.py: TokenBucket(rpm=settings.RATE_LIMIT_RPM) shared across the process, asyncio and thread safe,
blocks when empty. metrics.py: put_metric(name, value, unit, dims) to CloudWatch namespace MelAgent,
no-op when settings.METRICS_OFF. Cost per call computed from models.yaml prices.
tests: use botocore Stubber; assert strict schema field, rate limiter timing (fake clock), cost math.
Done when: tests pass. Report: anything in models.yaml you could not honor.
