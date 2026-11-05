# NOTES-W2-EVALS (evals-evidence thread)

Problems with files I do not own. I changed none of them.

- `mel/judge.py`: the first live run got HTTP 422 from Jev on all 4 calls that reached it. The request carries no
  `model` field unless `JEV_MODEL` is set (see NOTES-F.md). `reference_jev_service.py` always sends one. Unconfirmed
  cause; the value of `JEV_MODEL` for System One is not in the repo. Until fixed every survey ends `pending_review`.
- `mel/providers/bedrock.py`: `Usage.input_tokens` is Converse `usage.inputTokens`. For gpt-6-luna that was 2 tokens
  per call in the live run, against about 1,180 in the model-selection run, so prompt tokens that Bedrock reports
  separately (cached) are not counted and `cost_usd` is understated. Use `totalTokens - outputTokens`.
  `evals/survey_eval.py` records the raw usage itself and does not depend on `Usage`.
- `mel/providers/bedrock.py`: when `_extract` raises (for example `max_tokens`), the usage of that response is dropped,
  so the failed call is never metered. `evals/survey_eval.py` wraps the client to count it.
- Scenario 5 (wheat-variety-plan) failed both attempts with `ProviderError` in both live runs. The second run recorded
  the stop reason: `max_tokens` at 600 output tokens on both attempts (about 2,900 input tokens). The other four
  scenarios used 321-564 output tokens. `max_tokens` 600 is too tight for this scenario with the production prompt
  (`CLAUDE.md` fixes 600; the generator owner or integration decides). The model-selection prompt averaged 1,180 input
  tokens, so its cost per accepted survey ($0.000210) does not carry over: this run's cost per generated survey is
  about $0.00076.
- The `Usage` problem above was found in the first run (2 input tokens per call reported). The second run, with the
  harness recording raw usage, shows about 2,900 input tokens per call.
- `.gitignore` lists `evidence/`; `evidence/REPORT.md` is committed with `git add -f`.
