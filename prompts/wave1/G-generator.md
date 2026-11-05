Model: Opus. Branch: w1-G.
Goal: the survey generator and the bounded repair loop. This is the only place that writes farmer-facing text.
Read first: CLAUDE.md, CONTRACTS.md, mel/models.py, mel/protocols.py, mel/validate.py, evals/prompt_v0.md and models/models.yaml if present, pack/json/scenarios/*/survey.en-IN.json (all 5), pack/json/rules/rules.json survey_by_resolution.asks, pack/json/schemas/survey.schema.json.
You own: mel/generate.py, mel/prompts/survey_system.md, mel/invariants.py, tests/test_generate.py, tests/test_invariants.py, NOTES-G.md.
Deliver: generate_survey(insight, decision, window, language, generator, judge, clock) -> GenerationResult
{survey|None, status: accepted|failed_review|pending_review, attempts, usage, cost_usd, reasons}.
Flow: draft with models.yaml generation model -> mel.validate against survey schema -> invariants
(1..3 items, unique item_id, 2..10 options, label <= 20 code points, scale <= 10 steps and
follow_up_at_or_below within range, one language, rationale <= 400, send_window copied from timing not
from the model) -> on failure one retry with the retry model including the validator errors -> on
failure status failed_review, never no_survey -> judge.check_survey -> ok: accepted; else pending_review.
self_eval.schema_valid is set from our validator. survey_id: "S-" + zero-padded counter from the ledger
sequence passed in. System prompt: the question per resolution type from rules.json asks, the three item
types, the follow_up reason vocabulary from the scenarios, the never-advise and never-ask-personal rules,
stable text so it caches (put nothing per-insight in it). Insight goes in the user turn as JSON.
tests: fake Generator returning canned good and bad drafts; fake Judge; assert the state transitions,
the retry count cap, that a model-supplied schema_valid=true on an invalid draft is ignored.
Done when: tests pass. Report: the invariant list and the prompt word count.
