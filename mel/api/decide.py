"""run_decision: one insight in, one decision (and for R8 a stored survey and hand-off) out.

Pipeline, in order:  rules -> timing -> opt-out check -> generate -> handoff -> ledger.

  1. mel.rules.decide        pure code, R1..R8. R1..R7 end here (R3/R4 also give a NoSurvey record).
  2. mel.timing.send_window  pure code, profile from settings.TIMING_PROFILE. A TimingException
                             ends the run with status timing_exception.
  3. ledger.is_opted_out     an opted-out farmer gets no survey and no model call.
  4. mel.generate            the only model-writing step (plus Jev inside it). Not accepted
                             (failed_review, pending_review): nothing is stored, nothing is sent.
  5. mel.handoff             pure code. Survey and hand-off are checked against the pack schema,
                             then stored with ledger.put_survey and ledger.put_handoff.

Security: identity comes from the JWT (mel.api.auth). The insight's farmer_id must match it.
Every ledger call uses identity.org_id. Insight text is untrusted: it is passed to the
generator (user turn) and never logged. Metrics carry rule ids, model ids, step names and
counts, never text or ids of farmers.

Metrics (namespace MelAgent): DecisionsByRule{rule_id}, LatencyMs{step}, ModelCalls{step},
ModelTokens{model_id,direction}, CostUsd{step}, JudgeVerdicts{verdict}.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, Self

from mel.api.auth import Identity
from mel.api.intake import IntakeError
from mel.models import (
    DecisionRecord,
    Insight,
    NoSurvey,
    ScheduleHandoff,
    SendWindow,
    Survey,
    Usage,
)
from mel.protocols import Clock, Generator, Judge, Ledger
from mel.validate import validate_against_pack

log = logging.getLogger("mel.decide")

DecisionStatus = Literal[
    "survey_scheduled",  # R8, accepted by validation and Jev, stored with a hand-off
    "no_survey",         # R1..R7
    "timing_exception",  # R8 but no legal send window
    "opted_out",         # R8 but the farmer asked for no more surveys
    "failed_review",     # generation failed validation after the one retry
    "pending_review",    # Jev flagged the survey or could not answer (fails closed)
]


class MetricsSink(Protocol):
    def emit(self, name: str, value: float, **dimensions: str) -> None: ...


class NullMetrics:
    def emit(self, name: str, value: float, **dimensions: str) -> None:
        return None


class LogMetrics:
    """Writes metrics as log lines (CloudWatch EMF can replace this in the provider module)."""

    def emit(self, name: str, value: float, **dimensions: str) -> None:
        log.info("metric", extra={"metric": name, "value": value, **dimensions})


@dataclass
class DecideDeps:
    """Everything run_decision needs. Step callables default to the sibling modules."""

    ledger: Ledger
    clock: Clock
    generator: Generator
    judge: Judge
    rules: Mapping[str, Any]          # rules.json
    calendar: Mapping[str, Any]       # {crop: last end date}
    timing_profile: Literal["golden_v1", "rules_v1"] | None = None   # None: settings.TIMING_PROFILE
    languages: list[str] | None = None                               # None: settings.LANGUAGES
    metrics: MetricsSink = field(default_factory=NullMetrics)
    # Step functions. None means "import the real one on first use".
    decide_fn: Callable[..., DecisionRecord] | None = None
    window_fn: Callable[..., Any] | None = None
    handoff_fn: Callable[..., ScheduleHandoff] | None = None
    no_survey_fn: Callable[..., tuple[NoSurvey | None, DecisionRecord]] | None = None
    generate_fn: Callable[..., Any] | None = None


@dataclass(frozen=True)
class DecisionResult:
    status: DecisionStatus
    decision: DecisionRecord
    no_survey: NoSurvey | None = None
    survey: Survey | None = None
    handoff: ScheduleHandoff | None = None
    reasons: tuple[str, ...] = ()
    cost_usd: float = 0.0


# --------------------------------------------------------------------------- default step adapters


def _decide(deps: DecideDeps) -> Callable[..., DecisionRecord]:
    if deps.decide_fn:
        return deps.decide_fn
    from mel.rules import decide

    return decide


def _window(deps: DecideDeps) -> Callable[..., Any]:
    if deps.window_fn:
        return deps.window_fn
    from mel.timing import send_window

    return send_window


def _handoff(deps: DecideDeps) -> Callable[..., ScheduleHandoff]:
    if deps.handoff_fn:
        return deps.handoff_fn
    from mel.handoff import build_handoff

    return build_handoff


def _no_survey(deps: DecideDeps) -> Callable[..., tuple[NoSurvey | None, DecisionRecord]]:
    if deps.no_survey_fn:
        return deps.no_survey_fn
    from mel.handoff import build_no_survey

    return build_no_survey


def _generate(deps: DecideDeps) -> Callable[..., Any]:
    if deps.generate_fn:
        return deps.generate_fn
    from mel.generate import generate_survey

    return generate_survey


def _call_generate(
    fn: Callable[..., Any], insight: Insight, decision: DecisionRecord, window: SendWindow,
    language: str, deps: DecideDeps, seq: int,
) -> Any:
    """generate_survey(insight, decision, window, language, generator, judge, clock, *, survey_seq)."""
    return fn(insight, decision, window, language, deps.generator, deps.judge, deps.clock, survey_seq=seq)


# --------------------------------------------------------------------------- helpers


class _Timer:
    def __init__(self, deps: DecideDeps, step: str) -> None:
        self._deps, self._step = deps, step

    def __enter__(self) -> Self:
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        ms = (time.perf_counter() - self._t0) * 1000
        self._deps.metrics.emit("LatencyMs", ms, step=self._step)


def _usages(raw: Any) -> list[Usage]:
    if raw is None:
        return []
    if isinstance(raw, Usage):
        return [raw]
    if isinstance(raw, Iterable):
        return [u for u in raw if isinstance(u, Usage)]
    return []


def _emit_generation_metrics(deps: DecideDeps, result: Any) -> float:
    usages = _usages(getattr(result, "usage", None))
    attempts = getattr(result, "attempts", None)
    calls = attempts if isinstance(attempts, int) and attempts > 0 else len(usages)
    deps.metrics.emit("ModelCalls", float(calls), step="generate")
    for u in usages:
        deps.metrics.emit("ModelTokens", float(u.input_tokens), model_id=u.model_id, direction="input")
        deps.metrics.emit("ModelTokens", float(u.output_tokens), model_id=u.model_id, direction="output")
    cost = getattr(result, "cost_usd", None)
    if cost is None:
        cost = sum(u.cost_usd or 0.0 for u in usages)
    deps.metrics.emit("CostUsd", float(cost), step="generate")
    return float(cost)


def _language(insight: Insight, deps: DecideDeps) -> str:
    from mel.settings import settings

    allowed = deps.languages if deps.languages is not None else settings.LANGUAGES
    return insight.conversation_language if insight.conversation_language in allowed else allowed[0]


# --------------------------------------------------------------------------- entry point


def run_decision(identity: Identity, insight_dict: Mapping[str, Any], deps: DecideDeps) -> DecisionResult:
    """Decide, and for R8 generate, check and store the survey and its hand-off."""
    if not isinstance(insight_dict, Mapping):
        raise IntakeError("invalid_request")
    # The insight must belong to the caller. Junk rows that fail the schema still need this check.
    if insight_dict.get("farmer_id") != identity.farmer_id:
        raise IntakeError("identity_mismatch")

    from mel.settings import settings

    profile = deps.timing_profile or settings.TIMING_PROFILE
    org = identity.org_id
    ledger, clock, metrics = deps.ledger, deps.clock, deps.metrics

    # 1. rules
    with _Timer(deps, "rules"):
        decision = _decide(deps)(insight_dict, clock, deps.calendar, deps.rules)
    metrics.emit("DecisionsByRule", 1.0, rule_id=decision.rule_id)
    if not decision.survey:
        with _Timer(deps, "no_survey"):
            no_survey, decision = _no_survey(deps)(decision)
        return DecisionResult("no_survey", decision, no_survey=no_survey)

    insight = Insight.model_validate(dict(insight_dict))  # R1 already filtered schema failures

    # 2. timing
    with _Timer(deps, "timing"):
        try:
            window = _window(deps)(insight, profile, clock, deps.rules)
        except Exception as exc:  # TimingException may be raised or returned (agent B)
            if type(exc).__name__ != "TimingException":
                raise
            window = exc
    if not isinstance(window, SendWindow):
        log.info("timing exception", extra={"code": str(getattr(window, "code", "unknown"))})
        return DecisionResult("timing_exception", decision, reasons=(str(getattr(window, "code", "unknown")),))
    if decision.send_window != window:
        decision = decision.model_copy(update={"send_window": window})

    # 3. opt-out: no survey and no model call for a farmer who asked to stop
    if ledger.is_opted_out(org, identity.farmer_id):
        return DecisionResult("opted_out", decision)

    # 4. generate (model + Jev)
    seq = ledger.next_survey_seq(org)
    with _Timer(deps, "generate"):
        result = _call_generate(_generate(deps), insight, decision, window, _language(insight, deps), deps, seq)
    cost = _emit_generation_metrics(deps, result)
    status = getattr(result, "status", "failed_review")
    metrics.emit("JudgeVerdicts", 1.0, verdict=str(status))
    reasons = tuple(str(r) for r in (getattr(result, "reasons", None) or ()))
    survey = getattr(result, "survey", None)
    if status != "accepted" or survey is None:
        out = status if status in ("failed_review", "pending_review") else "failed_review"
        return DecisionResult(out, decision, survey=None, reasons=reasons, cost_usd=cost)

    # 5. validate, hand-off, store
    ok, _errors = validate_against_pack(survey, "survey")  # errors may echo values: not logged
    if not ok or survey.farmer_id != identity.farmer_id:
        return DecisionResult("failed_review", decision, reasons=("survey_schema",), cost_usd=cost)
    with _Timer(deps, "handoff"):
        handoff = _handoff(deps)(survey, insight, decision, clock, deps.rules)
    ok, _errors = validate_against_pack(handoff, "schedule_handoff")
    if not ok or handoff.survey.farmer_id != identity.farmer_id:
        return DecisionResult("failed_review", decision, reasons=("handoff_schema",), cost_usd=cost)
    with _Timer(deps, "ledger"):
        ledger.put_survey(org, survey, handoff.expires_at)
        ledger.put_handoff(org, handoff)
    return DecisionResult("survey_scheduled", decision, survey=survey, handoff=handoff,
                          reasons=reasons, cost_usd=cost)


__all__ = [
    "DecideDeps",
    "DecisionResult",
    "DecisionStatus",
    "LogMetrics",
    "MetricsSink",
    "NullMetrics",
    "run_decision",
]
