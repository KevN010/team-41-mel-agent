# NOTES-G (survey generator)

## Final signature (for J decide.py and integration)

```python
from mel.generate import generate_survey, GenerationResult, ModelChoice, LlmSurveyGenerator

generate_survey(
    insight,          # Insight | dict
    decision,         # DecisionRecord, must be survey=True (R8) and match insight ids
    window,           # SendWindow | dict, from mel.timing; copied into the survey as is
    language,         # "en-IN" (hi-IN only when in settings.LANGUAGES)
    generator,        # Generator, e.g. LlmSurveyGenerator(BedrockChat)
    judge,            # Judge, e.g. JevJudge()
    clock,            # Clock
    *,
    survey_seq: int,  # ledger.next_survey_seq(org_id); survey_id = f"S-{survey_seq:05d}"
    models: ModelChoice | None = None,  # None: read models/models.yaml
) -> GenerationResult  # survey|None, status accepted|failed_review|pending_review, attempts,
                       # usage, cost_usd, reasons, model_keys, verdict, survey_id, generated_at
```

## For integration
- `models/models.yaml` is not on main yet. `load_model_choice()` raises `ModelsFileError` when it is missing. There is no fallback model. It reads `generation` and `retry` (prompt 01 format) and passes each value to `Generator.generate(..., model_key)` as is. `BedrockChat(model_key)` (task E) must accept the same value that models.yaml holds. Prompt 01 writes a profile id there, and CLAUDE.md calls these "keys" (`gpt6_luna`).
- CLAUDE.md names `gpt61_terra` as the retry tier. Team memory says that gpt-6.1-terra is unavailable (marketplace access denied). models.yaml must name a retry model that answers. The same model as `generation` is acceptable.
- `mel/prompts/survey_system.md` is a data file that is loaded at runtime. The Lambda zip and the agent container must include it (scripts/package_lambda.sh, which infra owns).
- Settings reads `MODELS_FILE`. CLAUDE.md lists `MEL_MODELS_FILE`. The same `MEL_` prefix mismatch applies to the other env vars in mel/settings.py (wave0 owns that file).
- The signature has two additions to the prompt's list: the keyword-only `survey_seq` (from `ledger.next_survey_seq(org_id)`) and the optional `models` (`ModelChoice`). If `models` is omitted, the function reads models.yaml.
- `GenerationResult` has these extra fields: `model_keys`, `verdict`, `survey_id` and `generated_at` (from the clock).
- The concrete generator is `LlmSurveyGenerator(chat_for=BedrockChat)`. It calls `converse_json(system, user, DRAFT_SCHEMA, settings.MAX_TOKENS)`. `DRAFT_SCHEMA` is in OpenAI strict form: every key is required and an optional key is nullable. Nulls are removed before validation.
- The `timing_profile` argument of `Generator.generate` is not used for the text. The code sets the window after the draft.
- The prompt asks for two blind `except Exception` catches (marked `noqa: BLE001`): generator errors become a failed attempt, and judge errors become pending_review. Both record only the exception class name.

## Disagreements with the pack
- The rationale in the pack scenarios gives "why now" (for example "Ask from day 2"). The model does not see the send window, so its rationale gives only why these questions. The schema description says "Why this survey, why now".
- `follow_up_at_or_below` must be in [scale_min, scale_max). The schema allows any value from 0 to 100. A value equal to scale_max would send every answer to follow-up.
- INV-FOLLOW-UP (at least one answer routes to follow-up) and INV-OPTION-VALUE (option values unique in an item) are in addition to the prompt's list. The schema does not have them. All 10 pack surveys pass them.
- Pack `self_eval` has no `relevance_score`. Ours sets it from the Jev `matches_advice` score when Jev returns one. `gives_new_advice` and `asks_personal_info` come from Jev scores, never from the model.
- All 5 actionable scenario insights have `conversation_language` hi-IN, but the pack also ships en-IN surveys for them. `generate_survey` writes in the `language` that the caller gives. hi-IN is refused unless it is in `settings.LANGUAGES`.
