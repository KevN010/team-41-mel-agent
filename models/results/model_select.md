# Model selection results

Eval: 5 actionable pack scenarios x 3 runs, Converse in us-west-2, max_tokens 600, prompt evals/prompt_v0.md. Pass = full survey validates against pack survey.schema.json and the invariants (1..3 items, unique item_id, 2..10 options, label <= 20 code points, scale <= 10 steps).

| Profile | Pass rate | Avg in tok | Avg out tok | Latency p50 ms | Price in/out per 1M | Cost per call | Cost per accepted survey | Hit max_tokens |
|---|---|---|---|---|---|---|---|---|
| global.openai.gpt-6-luna | 15/15 = 1.00 | 1180 | 184 | 1146 | $0.1/$0.5 (unverified) | $0.000210 | $0.000210 | 0/15 |
| global.anthropic.claude-haiku-5-5 | 13/15 = 0.87 | 2449 | 337 | 2025 | unpriced | n/a | n/a | 0/15 |
| global.anthropic.claude-haiku-4-5-20251001-v1:0 | 9/15 = 0.60 | 2156 | 230 | 1800 | $1.0/$5.0 (unverified) | $0.003307 | $0.005511 | 0/15 |

## Most common failures

- global.openai.gpt-6-luna: none
- global.anthropic.claude-haiku-4-5-20251001-v1:0: call_or_parse_error: AttributeError: 'str' object has no attribute 'get' (x2); $.items[N].options[N].label: maxLength (x2); label longer than N code points (x2)
- global.anthropic.claude-haiku-5-5: $.items[N].options[N].label: maxLength (x2); label longer than N code points (x2)

## Request features

- global.openai.gpt-6-luna: used format, reasoning
- global.anthropic.claude-haiku-4-5-20251001-v1:0: used tool_use
- global.anthropic.claude-haiku-5-5: used tool_use

## Pick

- generation: global.openai.gpt-6-luna
- retry: global.openai.gpt-6-luna
- global.openai.gpt-6-luna: pass rate 1.00, $0.000210 per accepted survey.
