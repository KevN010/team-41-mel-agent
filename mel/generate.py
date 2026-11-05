"""Survey generation and the bounded repair loop. The only module that writes farmer-facing text.

    result = generate_survey(insight, decision, window, "en-IN", generator, judge, clock,
                             survey_seq=ledger.next_survey_seq(org_id))

Flow (at most two model calls, then one Jev call):

1. Draft with the models.yaml ``generation`` model.
2. Merge: keep only ``items`` and ``rationale`` from the draft. survey_id, farmer_id,
   source_insight_ids, language and send_window come from our code; any self_eval from the
   model is dropped. Nulls inside items are removed (the strict-JSON draft schema writes every
   field; the pack schema wants absent fields).
3. Check: mel.validate against survey.schema.json, then mel.invariants, then the pydantic model.
4. On failure: one retry with the models.yaml ``retry`` model, with the errors as repair_errors.
   On a second failure: status ``failed_review`` (a person looks at it). Never no_survey.
5. Judge (Jev). ok -> ``accepted``; anything else, an error included -> ``pending_review``.

self_eval.schema_valid is set from our validator. gives_new_advice, asks_personal_info and
relevance_score come from Jev scores, never from the model.

Logging: ids, model keys, token counts, latency, status and value-free reasons only. Never the
insight, the draft, or raw validator messages (they can echo text).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from collections.abc import Callable
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Protocol

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from mel import invariants
from mel.models import (
    DecisionRecord,
    Insight,
    JudgeVerdict,
    SelfEval,
    SendWindow,
    Survey,
    Usage,
)
from mel.protocols import Clock, Generator, Judge
from mel.settings import settings
from mel.validate import validate_against_pack

log = logging.getLogger("mel.generate")

GenerationStatus = Literal["accepted", "failed_review", "pending_review"]

MAX_ATTEMPTS = 2
"""One draft plus one repair. The loop is bounded by the two model keys; this is the cap."""

SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "survey_system.md"

# Repair errors go back to the model in the user turn. Keep that turn small.
_MAX_REPAIR_ERRORS = 20
_MAX_REPAIR_ERROR_CHARS = 300

# --------------------------------------------------------------------------- results


class ModelChoice(BaseModel):
    """The two model keys from models/models.yaml."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    generation: str
    retry: str


class GenerationResult(BaseModel):
    """Outcome of generate_survey. Holds no insight text and no draft text."""

    model_config = ConfigDict(frozen=True)

    survey: Survey | None
    status: GenerationStatus
    attempts: int
    usage: list[Usage]
    cost_usd: float
    reasons: list[str]
    model_keys: list[str]
    verdict: JudgeVerdict | None = None
    survey_id: str
    generated_at: datetime


class ModelsFileError(RuntimeError):
    """models/models.yaml is missing or lacks the generation / retry keys."""


def load_model_choice(path: Path | str | None = None) -> ModelChoice:
    """Read ``generation`` and ``retry`` from models.yaml (settings.MODELS_FILE by default).

    No fallback model: a missing file is a deploy error, not something to guess around.
    """
    path = Path(path or settings.MODELS_FILE)
    if not path.is_file():
        raise ModelsFileError(f"{path} not found; the model-selection task writes it")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ModelsFileError(f"{path}: expected a mapping")
    try:
        return ModelChoice.model_validate(data)
    except ValidationError as exc:
        missing = sorted({str(e["loc"][0]) for e in exc.errors() if e.get("loc")})
        raise ModelsFileError(f"{path}: missing or invalid keys {missing}") from None


def format_survey_id(seq: int) -> str:
    """S- plus the ledger sequence, zero-padded to 5 digits (schema: ^S-[0-9]{5,10}$)."""
    if isinstance(seq, bool) or not isinstance(seq, int) or not 0 <= seq < 10**10:
        raise ValueError("survey_seq must be an integer from 0 to 9,999,999,999")
    return f"S-{seq:05d}"


# --------------------------------------------------------------------------- the loop


def generate_survey(
    insight: Insight | dict[str, Any],
    decision: DecisionRecord,
    window: SendWindow | dict[str, Any],
    language: str,
    generator: Generator,
    judge: Judge,
    clock: Clock,
    *,
    survey_seq: int,
    models: ModelChoice | None = None,
) -> GenerationResult:
    """Draft, check, repair once, judge. See the module docstring for the flow."""
    insight = insight if isinstance(insight, Insight) else Insight.model_validate(insight)
    window = window if isinstance(window, SendWindow) else SendWindow.model_validate(window)
    _check_call(insight, decision, language)
    models = models or load_model_choice()
    survey_id = format_survey_id(survey_seq)
    generated_at = clock.now()

    usage: list[Usage] = []
    reasons: list[str] = []
    model_keys: list[str] = []
    repair: list[str] | None = None
    survey: Survey | None = None

    for attempt, model_key in enumerate((models.generation, models.retry)[:MAX_ATTEMPTS], start=1):
        model_keys.append(model_key)
        try:
            draft, call_usage = generator.generate(
                insight, language, decision.timing_profile, model_key, repair_errors=repair
            )
        except Exception as exc:  # noqa: BLE001 - any provider or parse error is a failed attempt
            name = type(exc).__name__
            reasons.append(f"attempt{attempt}: generator_error:{name}")
            repair = [f"the previous attempt failed ({name}); return one JSON object that matches the schema"]
            log.warning("generate attempt failed", extra=_log_extra(insight, survey_id, attempt, model_key, None))
            continue
        usage.append(call_usage)
        survey, errors, safe = _merge_and_check(draft, insight, survey_id, language, window)
        log.info(
            "generate attempt",
            extra=_log_extra(insight, survey_id, attempt, model_key, call_usage, ok=survey is not None,
                             n_errors=len(errors)),
        )
        if survey is not None:
            break
        reasons.extend(f"attempt{attempt}: {r}" for r in safe)
        repair = _repair_lines(errors)

    attempts = len(model_keys)
    cost = sum(u.cost_usd or 0.0 for u in usage)
    if survey is None:
        return _finish(None, "failed_review", attempts, usage, cost, reasons, model_keys, None,
                       survey_id, generated_at, insight)

    verdict = _judge(judge, insight, survey, reasons)
    status: GenerationStatus = "accepted" if verdict is not None and verdict.ok else "pending_review"
    if verdict is not None and not verdict.ok:
        reasons.append("judge:pending_review" if verdict.pending_review else "judge:not_ok")
    final = _with_self_eval(survey, verdict)
    ok, _ = validate_against_pack(final, "survey")
    if not ok:  # cannot happen with in-range scores; fail closed anyway
        reasons.append("final:schema_invalid")
        return _finish(None, "failed_review", attempts, usage, cost, reasons, model_keys, verdict,
                       survey_id, generated_at, insight)
    return _finish(final, status, attempts, usage, cost, reasons, model_keys, verdict,
                   survey_id, generated_at, insight)


def _check_call(insight: Insight, decision: DecisionRecord, language: str) -> None:
    if not decision.survey:
        raise ValueError(f"decision {decision.rule_id} is not a survey decision; nothing to generate")
    if decision.insight_id != insight.insight_id or decision.farmer_id != insight.farmer_id:
        raise ValueError("decision and insight do not belong together")
    if language not in settings.LANGUAGES:
        raise ValueError(f"language {language!r} is not enabled in settings.LANGUAGES")


def _strip_nulls(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_strip_nulls(v) for v in value]
    return value


def merge_draft(
    draft: Any, insight: Insight, survey_id: str, language: str, window: SendWindow
) -> dict[str, Any]:
    """Build the survey dict: our fields plus the draft's items and rationale. Nothing else."""
    draft = draft if isinstance(draft, dict) else {}
    return {
        "survey_id": survey_id,
        "farmer_id": insight.farmer_id,
        "source_insight_ids": [insight.insight_id],
        "language": language,
        "send_window": window.to_pack(),
        "items": _strip_nulls(draft.get("items")),
        "rationale": draft.get("rationale"),
    }


def _merge_and_check(
    draft: Any, insight: Insight, survey_id: str, language: str, window: SendWindow
) -> tuple[Survey | None, list[str], list[str]]:
    """Returns (survey or None, errors for the repair turn, value-free reasons for logs/results)."""
    if not isinstance(draft, dict):
        msg = "$: the draft must be a JSON object with items and rationale"
        return None, [msg], [msg]
    candidate = merge_draft(draft, insight, survey_id, language, window)
    schema_ok, schema_errors = validate_against_pack(candidate, "survey")
    inv_errors = invariants.check_survey(candidate, language=language, window=window)
    errors = [*schema_errors, *inv_errors]
    safe = [_safe_schema_reason(e) for e in schema_errors] + inv_errors
    if errors:
        return None, errors, safe
    candidate["self_eval"] = {"schema_valid": schema_ok}  # True here: computed by our validator
    try:
        return Survey.model_validate(candidate), [], []
    except ValidationError as exc:
        model_errors = [f"$.{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
        safe = [f"model:$.{'.'.join(map(str, e['loc']))}" for e in exc.errors()]
        return None, model_errors, safe


def _safe_schema_reason(error: str) -> str:
    """'$.items[0].label: 'Some text' is too long' -> 'schema:$.items[0].label' (no echoed value)."""
    path = error.split(": ", 1)[0]
    return f"schema:{path}"


def _repair_lines(errors: list[str]) -> list[str]:
    lines = [e[:_MAX_REPAIR_ERROR_CHARS] for e in errors[:_MAX_REPAIR_ERRORS]]
    if len(errors) > _MAX_REPAIR_ERRORS:
        lines.append(f"... and {len(errors) - _MAX_REPAIR_ERRORS} more errors")
    return lines


def _judge(judge: Judge, insight: Insight, survey: Survey, reasons: list[str]) -> JudgeVerdict | None:
    try:
        return judge.check_survey(insight, survey)
    except Exception as exc:  # noqa: BLE001 - Jev fails closed: an error is never ok
        reasons.append(f"judge_error:{type(exc).__name__}")
        return None


def _score(verdict: JudgeVerdict, check: str) -> float | None:
    value = verdict.scores.get(check)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    value = float(value)
    return value if math.isfinite(value) and 0.0 <= value <= 1.0 else None


def _with_self_eval(survey: Survey, verdict: JudgeVerdict | None) -> Survey:
    """schema_valid from our validator; the rest from Jev scores. Unknown stays unset."""
    fields: dict[str, Any] = {"schema_valid": True}
    if verdict is not None and not verdict.pending_review:
        thresholds = settings.jev_thresholds
        relevance = _score(verdict, "matches_advice")
        if relevance is not None:
            fields["relevance_score"] = relevance
        for check in ("gives_new_advice", "asks_personal_info"):
            score = _score(verdict, check)
            if score is not None:
                fields[check] = score > thresholds[check]
            elif verdict.ok:  # ok means every check passed (mel/judge.py)
                fields[check] = False
    return survey.model_copy(update={"self_eval": SelfEval(**fields)})


def _finish(
    survey: Survey | None,
    status: GenerationStatus,
    attempts: int,
    usage: list[Usage],
    cost: float,
    reasons: list[str],
    model_keys: list[str],
    verdict: JudgeVerdict | None,
    survey_id: str,
    generated_at: datetime,
    insight: Insight,
) -> GenerationResult:
    log.info(
        "generate result",
        extra={
            "insight_id": insight.insight_id,
            "survey_id": survey_id,
            "status": status,
            "attempts": attempts,
            "model_keys": model_keys,
            "input_tokens": sum(u.input_tokens for u in usage),
            "output_tokens": sum(u.output_tokens for u in usage),
            "cost_usd": cost,
            "reasons": reasons,
            "prompt_sha": system_prompt_sha(),
        },
    )
    return GenerationResult(
        survey=survey,
        status=status,
        attempts=attempts,
        usage=usage,
        cost_usd=cost,
        reasons=reasons,
        model_keys=model_keys,
        verdict=verdict,
        survey_id=survey_id,
        generated_at=generated_at,
    )


def _log_extra(
    insight: Insight, survey_id: str, attempt: int, model_key: str, usage: Usage | None, **more: Any
) -> dict[str, Any]:
    extra: dict[str, Any] = {
        "insight_id": insight.insight_id,
        "survey_id": survey_id,
        "attempt": attempt,
        "model_key": model_key,
        **more,
    }
    if usage is not None:
        extra |= {
            "model_id": usage.model_id,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "latency_ms": usage.latency_ms,
        }
    return extra


# --------------------------------------------------------------------------- the model call


@lru_cache(maxsize=1)
def system_prompt() -> str:
    """mel/prompts/survey_system.md. Stable text (nothing per insight) so providers can cache it."""
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def system_prompt_sha() -> str:
    """Short hash of the system prompt, logged as the prompt version."""
    return hashlib.sha256(system_prompt().encode("utf-8")).hexdigest()[:12]


_FOLLOW_UP_ENUM = ["advice_did_not_work", "crop_or_animal_damaged", "could_not_get_input", "could_not_reach_expert"]

DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["items", "rationale"],
    "properties": {
        "items": {
            "type": "array",
            "minItems": 1,
            "maxItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "item_id", "type", "prompt", "options", "scale_min", "scale_max",
                    "follow_up_at_or_below", "follow_up_reason",
                ],
                "properties": {
                    "item_id": {"type": "string"},
                    "type": {"type": "string", "enum": ["survey-single-select", "survey-confirm", "survey-scale"]},
                    "prompt": {"type": "string"},
                    "options": {
                        "type": ["array", "null"],
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["value", "label", "follow_up"],
                            "properties": {
                                "value": {"type": "string"},
                                "label": {"type": "string"},
                                "follow_up": {"type": ["string", "null"], "enum": [*_FOLLOW_UP_ENUM, None]},
                            },
                        },
                    },
                    "scale_min": {"type": ["integer", "null"]},
                    "scale_max": {"type": ["integer", "null"]},
                    "follow_up_at_or_below": {"type": ["integer", "null"]},
                    "follow_up_reason": {"type": ["string", "null"], "enum": [*_FOLLOW_UP_ENUM, None]},
                },
            },
        },
        "rationale": {"type": "string"},
    },
}
"""Strict-JSON shape for the draft (OpenAI strict mode: every key required, optional = nullable).
The pack schema stays the judge; this only shapes the model's output."""


class ChatClient(Protocol):
    """What mel.providers.bedrock.BedrockChat gives (task E)."""

    def converse_json(
        self, system: str, user: str, schema: dict[str, Any], max_tokens: int
    ) -> tuple[dict[str, Any], Usage]: ...


def insight_for_model(insight: Insight) -> dict[str, Any]:
    """The insight fields the model needs. No farmer_id, conversation_id or location (data minimisation)."""
    return {
        "resolution_type": insight.resolution_type,
        "concern": insight.concern,
        "severity": insight.severity,
        "asset": insight.asset.to_pack(),
        "query_summary": insight.query_summary,
        "advice_summary": insight.advice_summary,
        "action_window_days": insight.action_window_days,
        "verification_timing": insight.verification.timing,
    }


def build_user_turn(insight: Insight, language: str, repair_errors: list[str] | None = None) -> str:
    """The user turn: JSON data only. Untrusted insight text lives here, never in the system prompt."""
    payload: dict[str, Any] = {"language": language, "insight": insight_for_model(insight)}
    if repair_errors:
        payload["repair_errors"] = list(repair_errors)
    return json.dumps(payload, ensure_ascii=False)


class LlmSurveyGenerator:
    """Generator over a chat client. ``chat_for(model_key)`` returns a ChatClient (BedrockChat).

    timing_profile is not used for the text: the window is fixed in code, after the draft.
    """

    def __init__(self, chat_for: Callable[[str], ChatClient], *, max_tokens: int | None = None) -> None:
        self._chat_for = chat_for
        self._max_tokens = max_tokens or settings.MAX_TOKENS

    def generate(
        self,
        insight: Insight,
        language: str,
        timing_profile: str,
        model_key: str,
        *,
        repair_errors: list[str] | None = None,
    ) -> tuple[dict[str, Any], Usage]:
        chat = self._chat_for(model_key)
        user = build_user_turn(insight, language, repair_errors)
        return chat.converse_json(system_prompt(), user, DRAFT_SCHEMA, self._max_tokens)


__all__ = [
    "DRAFT_SCHEMA",
    "MAX_ATTEMPTS",
    "ChatClient",
    "GenerationResult",
    "GenerationStatus",
    "LlmSurveyGenerator",
    "ModelChoice",
    "ModelsFileError",
    "build_user_turn",
    "format_survey_id",
    "generate_survey",
    "insight_for_model",
    "load_model_choice",
    "merge_draft",
    "system_prompt",
    "system_prompt_sha",
]
