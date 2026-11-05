# NOTES-MODEL

Pick: `global.openai.gpt-6-luna` for generation. Eval table: `models/results/model_select.md` (raw rows in `model_select.json`).

## Needs a decision or a fix outside my files

- Retry tier is the same model as generation. `global.openai.gpt-6.1-terra` fails day0 with AccessDeniedException (AWS Marketplace private-marketplace eligibility, not a code problem). `claude-haiku-5-5` passed 13/15 (0.87, below the 0.9 bar) and has no known price. Fix terra access in the Bedrock console, then `make day0` and `.venv/bin/python evals/model_select.py` again, or decide that retry stays on luna.
- `anthropic.claude-haiku-5-5` has no price in CLAUDE.md. Re-run with `--price anthropic.claude-haiku-5-5=IN,OUT` to rank it.

## Caveats on the numbers

- Prices are unverified. luna $0.10/$0.50 comes from the CLAUDE.md table, which marks it "verify". Haiku 4.5 $1/$5 is Anthropic's list price, not from the pack.
- Input cost counts cached input tokens at the full rate, so it is an upper bound.
- Sample is 15 runs per model (5 scenarios x 3). A 1.00 pass rate on 15 runs does not rule out a rate near 0.8.
- Pass means schema plus the stated invariants. It does not measure relevance, "no new advice", or "no personal info". Those need the Jev judge or a human read.
- Test input is the pack's 5 actionable insights, sent as slimmed JSON without farmer_id or location. Survey id, farmer id and send window are added by code in the harness, not by the model.
- luna was called with strict json_schema output and `reasoning.effort=low`; Bedrock accepted both. The first run without low reasoning effort hit the 600-token cap on 12 of 15 calls, so any code path that calls luna must keep reasoning effort low.
- Haiku 4.5 failed 6 of 15: 2 with a label over 20 characters, 2 where tool_use returned `items` as a string, 2 with an empty rationale. Haiku 5.5 failed 2 of 15, both for a label over 20 characters.

## Files changed

- `scripts/day0_bedrock.py`: maxTokens 8 -> 16 (OpenAI minimum), parses `models/candidates.txt` as JSON (it is `aws bedrock list-foundation-models` output), tries `global.` and `us.` Haiku profiles, drops gpt-6.1-luna unless it is in the candidate list.
- `evals/prompt_v0.md`, `evals/model_select.py`, `models/models.yaml`, `models/results/*`, `models/day0.json` (day0 output, kept as evidence).
- `models/results/` is in .gitignore. The results files are force-added.
