# NOTES-E (Bedrock provider)

## models/models.yaml: not honored, not present yet
- `models/models.yaml` does not exist on main (model-selection thread owns it). Its schema was not given.
  `mel/providers/bedrock.py` reads it as documented in the module docstring:
  `generation`, `retry`, `region`, `max_tokens`, optional `models: {key: {profile, family, input_per_m, output_per_m}}`,
  optional `prices: {key-or-profile: {input_per_m|input|in, output_per_m|output|out}}`.
  A key may also be a profile id. If the file is missing, `BedrockChat` raises `ProviderError`; there is no built-in fallback.
- Family is taken from `family:` or guessed from the profile id (`openai`/`anthropic`/`claude`). Other families raise `ProviderError`.
- Prices missing -> `Usage.cost_usd` is `None`, and no `CostUsd` metric is sent.

## Choices where the prompt was open
- "Retries: 3": one call plus up to 3 retries (1 s, 2 s, 4 s) on `ThrottlingException` only. Every attempt takes a rate-limit token.
  botocore's own retries are off (`max_attempts=1`) so the count is exact.
- Bucket `burst` defaults to 1: calls spaced `60/rpm` s apart; never more than rpm+1 in any 60 s window.
- `max_tokens`: caller value, else `models.yaml max_tokens`, else `settings.MAX_TOKENS`. Not clamped.
- `converse_json(system, user, schema, max_tokens=None, *, schema_name="response")` also has `aconverse_json` (thread worker).
- Metrics sent per call (dim `ModelId`): `ModelCalls`, `ModelTokens` (dim `Direction`), `LatencyMs`, `CostUsd`.
  The other metric names (`DecisionsByRule`, `JudgeVerdicts`) are sent by callers through `put_metric`.
- OpenAI strict mode needs a schema with `additionalProperties: false` and all properties required. The pack survey schema may not
  meet that. Owner G must check what the Bedrock OpenAI profile accepts; this module passes the schema through unchanged.
- Pack disagreements: none.
