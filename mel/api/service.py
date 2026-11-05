"""One dispatch function shared by the Lambda handler and the AgentCore Runtime entrypoint.

    dispatch(action, identity, payload, services) -> Reply(status, body)

No business logic lives here: each action calls the module that owns it (decide, intake, events,
ledger, demo clock) and turns the result into JSON.

Actions
  decide      payload: the insight dict                      -> run_decision
  get_survey  payload: {survey_id}                           -> ledger.get_survey (scoped)
  respond     payload: {survey_id, response: {...}}          -> intake.submit_response, or
                                                                events.submit_event when response.kind is
                                                                failure | decline | opt_out
  follow_ups  payload: {}                                    -> ledger.list_follow_ups, this farmer only
  opt_out     payload: {}                                    -> ledger.set_opt_out
  clock       payload: {op: get|set|advance|reset, at?, seconds?}   ADMIN_ACTIONS: AgentCore only

``identity`` is always the caller's verified identity: JWT claims on the Lambda path
(mel.api.auth), the IAM-authenticated caller's assertion on the AgentCore path (mel.agent).
Nothing here reads identity from the payload.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, ClassVar

from mel.api.auth import Identity, Unauthorized
from mel.api.decide import (
    DecideDeps,
    DecisionResult,
    MetricsSink,
    NullMetrics,
    run_decision,
)
from mel.api.events import is_event, submit_event
from mel.api.intake import (
    SURVEY_ID_RE,
    FollowUpQueue,
    IntakeError,
    _load_survey,
    submit_response,
    success_status,
)
from mel.democlock import ClockStore, DemoClock
from mel.models import to_ist
from mel.protocols import Generator, Judge, Ledger

log = logging.getLogger("mel.service")

PUBLIC_ACTIONS = ("decide", "get_survey", "respond", "follow_ups", "opt_out")
ADMIN_ACTIONS = ("clock",)


@dataclass
class Services:
    ledger: Ledger
    clock_store: ClockStore
    generator: Generator
    judge: Judge
    rules: Mapping[str, Any]
    calendar: Mapping[str, Any]
    codes: Mapping[str, Any]
    queue: FollowUpQueue | None = None
    metrics: MetricsSink = field(default_factory=NullMetrics)
    wall: Callable[[], datetime] | None = None  # tests pin the wall clock

    def clock(self, org_id: str) -> DemoClock:
        if self.wall is None:
            return DemoClock(self.clock_store, org_id)
        return DemoClock(self.clock_store, org_id, wall=self.wall)


@dataclass(frozen=True)
class Reply:
    status: int
    body: dict[str, Any]


def _error(code: str, status: int) -> Reply:
    return Reply(status, {"error": code})


def _json(model: Any) -> Any:
    if model is None:
        return None
    if hasattr(model, "to_pack"):
        return model.to_pack()
    return model.model_dump(mode="json")


def _decision_body(result: DecisionResult) -> dict[str, Any]:
    return {
        "status": result.status,
        "decision": _json(result.decision),
        "no_survey": _json(result.no_survey),
        "survey": _json(result.survey),
        "handoff": _json(result.handoff),
        # Reason codes only: "generator_error:ThrottlingException" -> "generator_error". Details stay in logs.
        "reasons": sorted({r.split(":", 1)[0] for r in result.reasons}),
        "cost_usd": result.cost_usd,
    }


# --------------------------------------------------------------------------- actions


def _decide(identity: Identity, payload: Any, svc: Services) -> Reply:
    clock = svc.clock(identity.org_id)
    deps = DecideDeps(
        ledger=svc.ledger, clock=clock, generator=svc.generator, judge=svc.judge,
        rules=svc.rules, calendar=svc.calendar, metrics=svc.metrics,
    )
    started = time.perf_counter()
    result = run_decision(identity, payload, deps)
    log.info(
        "decision",
        extra={
            "rule_id": result.decision.rule_id,
            "status": result.status,
            "reason_code": result.decision.reason_code,
            "insight_id": result.decision.insight_id,
            "survey_id": result.survey.survey_id if result.survey else None,
            "cost_usd": result.cost_usd,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        },
    )
    return Reply(201 if result.status == "survey_scheduled" else 200, _decision_body(result))


def _survey_id(payload: Any) -> str:
    survey_id = payload.get("survey_id") if isinstance(payload, Mapping) else None
    if not isinstance(survey_id, str) or not SURVEY_ID_RE.fullmatch(survey_id):
        raise IntakeError("invalid_request")
    return survey_id


def _get_survey(identity: Identity, payload: Any, svc: Services) -> Reply:
    try:
        survey = _load_survey(identity, _survey_id(payload), svc.ledger)
    except IntakeError as exc:
        # Survey ids are sequential: a read must not tell "someone else's" from "does not exist".
        if exc.code == "identity_mismatch":
            raise IntakeError("unknown_survey") from None
        raise
    return Reply(200, {"survey": _json(survey)})


def _respond(identity: Identity, payload: Any, svc: Services) -> Reply:
    survey_id = _survey_id(payload)
    body = payload.get("response")
    clock = svc.clock(identity.org_id)
    if is_event(body):
        result = submit_event(identity, survey_id, body, svc.ledger, clock, svc.codes)
        record, status = result.record, result.http_status
    else:
        record = submit_response(identity, survey_id, body, svc.ledger, clock, svc.codes, queue=svc.queue)
        status = success_status(record)
    log.info(
        "response",
        extra={"survey_id": survey_id, "status": record.status, "failure_code": record.failure_code,
               "http_status": status},
    )
    return Reply(status, {"response": _json(record)})


def _follow_ups(identity: Identity, payload: Any, svc: Services) -> Reply:
    items = [i for i in svc.ledger.list_follow_ups(identity.org_id) if i.farmer_id == identity.farmer_id]
    return Reply(200, {"items": [_json(i) for i in items]})


def _opt_out(identity: Identity, payload: Any, svc: Services) -> Reply:
    at = svc.clock(identity.org_id).now()
    svc.ledger.set_opt_out(identity.org_id, identity.farmer_id, at)
    log.info("opt_out stored")
    return Reply(200, {"opted_out": True, "at": at.isoformat()})


def _clock(identity: Identity, payload: Any, svc: Services) -> Reply:
    if not isinstance(payload, Mapping):
        raise IntakeError("invalid_request")
    clock = svc.clock(identity.org_id)
    op = payload.get("op", "get")
    try:
        if op == "set":
            at = payload.get("at")
            if not isinstance(at, str):
                raise IntakeError("invalid_request")
            clock.set(to_ist(datetime.fromisoformat(at)))
        elif op == "advance":
            seconds = payload.get("seconds")
            if isinstance(seconds, bool) or not isinstance(seconds, int) or abs(seconds) > 10**9:
                raise IntakeError("invalid_request")
            clock.advance(timedelta(seconds=seconds))
        elif op == "reset":
            clock.reset()
        elif op != "get":
            raise IntakeError("invalid_request")
    except (ValueError, OverflowError):  # naive or malformed time, negative advance, out of range
        raise IntakeError("invalid_request") from None
    log.info("demo clock", extra={"op": op, "offset_s": int(clock.offset.total_seconds())})
    return Reply(200, {"now": clock.now().isoformat(), "offset_s": int(clock.offset.total_seconds())})


_ACTIONS: dict[str, Callable[[Identity, Any, Services], Reply]] = {
    "decide": _decide,
    "get_survey": _get_survey,
    "respond": _respond,
    "follow_ups": _follow_ups,
    "opt_out": _opt_out,
    "clock": _clock,
}


def dispatch(action: str, identity: Identity, payload: Any, svc: Services, *, admin: bool = False) -> Reply:
    """Run one action. ``admin`` is True only on the IAM-authenticated AgentCore path."""
    allowed = PUBLIC_ACTIONS + (ADMIN_ACTIONS if admin else ())
    if action not in allowed:
        return _error("unknown_action", 400)
    try:
        return _ACTIONS[action](identity, payload, svc)
    except IntakeError as exc:
        return _error(exc.code, exc.http_status)
    except Unauthorized:
        return _error("unauthorized", 401)
    except Exception as exc:  # noqa: BLE001 - never echo internals; class name only in the log
        log.error("action failed", extra={"action": action, "error_class": type(exc).__name__})
        return _error("internal_error", 500)


# --------------------------------------------------------------------------- logging and metrics

# Only these extra fields reach the log. Never insight, survey or answer text; never farmer ids.
LOG_FIELDS = (
    "action", "route", "http_status", "request_id", "trace_id", "rule_id", "reason_code", "status",
    "failure_code", "duplicate", "insight_id", "survey_id", "model_id", "model_key", "model_keys",
    "input_tokens", "output_tokens", "latency_ms", "cost_usd", "attempt", "attempts", "reasons",
    "prompt_sha", "step", "metric", "value", "verdict", "error_class", "error_types", "op", "offset_s",
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for name in LOG_FIELDS:
            if name in record.__dict__:
                out[name] = record.__dict__[name]
        return json.dumps(out, default=str)


def configure_logging() -> None:
    """mel.* at INFO as one JSON line each. Other libraries keep their defaults."""
    logger = logging.getLogger("mel")
    if any(getattr(h, "_mel_json", False) for h in logger.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler._mel_json = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


class CloudWatchMetrics:
    """MetricsSink for run_decision: CloudWatch custom metrics via mel.providers.metrics."""

    _UNITS: ClassVar[dict[str, str]] = {"LatencyMs": "Milliseconds", "CostUsd": "None"}

    def emit(self, name: str, value: float, **dimensions: str) -> None:
        from mel.providers.metrics import put_metric

        dims = {"".join(p.title() for p in k.split("_")): str(v) for k, v in dimensions.items()}
        put_metric(name, value, self._UNITS.get(name, "Count"), dims)
        log.info("metric", extra={"metric": name, "value": value})


__all__ = [
    "ADMIN_ACTIONS",
    "PUBLIC_ACTIONS",
    "CloudWatchMetrics",
    "JsonFormatter",
    "Reply",
    "Services",
    "configure_logging",
    "dispatch",
]
