"""Non-answer events: delivery failures, declines, opt-outs and sheet dismissals.

The deployed API has no events route (infra owns the routes), so these arrive on
``POST /surveys/{survey_id}/responses`` with a ``kind`` key. ``mel.api.service`` sends a body with
``kind`` in EVENT_KINDS here and every other body to ``mel.api.intake.submit_response``.

Same rules as intake: identity from the JWT only, the payload forbids unknown keys, every ledger
call is scoped by org_id and farmer_id, and the record is validated against the pack schema
before it is stored.

Duplicates: ``put_response`` is idempotent on ``response_key``. A repeated event returns the
record stored first, with ``duplicate=True`` (HTTP 200). An opt-out is applied to the ledger
whether or not the record was a duplicate (set_opt_out is idempotent).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

from mel.api.auth import Identity
from mel.api.intake import SHEET_CHANNELS, IntakeError, ResponseKey, _load_survey
from mel.models import Attempt, Channel, PutOutcome, ResponseRecord, SheetOutcome
from mel.protocols import Clock, Ledger
from mel.validate import validate_against_pack

log = logging.getLogger("mel.events")

EVENT_KINDS = ("failure", "decline", "opt_out")
FailureCode = Annotated[StrictStr, Field(min_length=1, max_length=40, pattern=r"^[a-z_]+$")]


class EventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    response_key: ResponseKey
    channel: Channel
    kind: Literal["failure", "decline", "opt_out"]
    failure_code: FailureCode | None = None
    sheet_outcome: SheetOutcome | None = None
    delivery_attempt: Annotated[StrictInt, Field(ge=1, le=5)] = 1


@dataclass(frozen=True)
class EventResult:
    record: ResponseRecord
    duplicate: bool = False

    @property
    def http_status(self) -> int:
        return 200 if self.duplicate else 201


def is_event(payload: Any) -> bool:
    return isinstance(payload, Mapping) and payload.get("kind") in EVENT_KINDS


def _parse(payload: Any) -> EventPayload:
    if not isinstance(payload, Mapping):
        raise IntakeError("invalid_request")
    try:
        return EventPayload.model_validate(dict(payload))
    except ValidationError as exc:
        log.info("event rejected payload", extra={"error_types": sorted({e["type"] for e in exc.errors()})})
        raise IntakeError("invalid_request") from None


def _default_apply_event() -> Callable[..., ResponseRecord]:
    from mel.outcomes import apply_event

    return apply_event


def submit_event(
    identity: Identity,
    survey_id: str,
    payload: Any,
    ledger: Ledger,
    clock: Clock,
    codes: Mapping[str, Any],
    *,
    apply_event: Callable[..., ResponseRecord] | None = None,
) -> EventResult:
    body = _parse(payload)
    survey = _load_survey(identity, survey_id, ledger)
    if body.sheet_outcome is not None and body.channel not in SHEET_CHANNELS:
        raise IntakeError("invalid_request")
    if body.kind == "failure" and body.failure_code not in (codes.get("failures") or {}):
        raise IntakeError("invalid_request")

    now = clock.now()
    org, farmer = identity.org_id, identity.farmer_id
    attempt = Attempt(
        survey_id=survey.survey_id,
        farmer_id=farmer,
        channel=body.channel,
        delivery_attempt=body.delivery_attempt,
        response_key=body.response_key,
        language=survey.language,
        source_insight_ids=list(survey.source_insight_ids),
        created_at=now,
    )
    event: dict[str, Any] = {
        "kind": body.kind,
        "channel": body.channel,
        "answers": {},
        "raw": None,
        "failure_code": body.failure_code,
        "sheet_outcome": body.sheet_outcome,
        "farmer_id": farmer,  # the JWT farmer, never a body value
        "at": now,
    }
    build = apply_event or _default_apply_event()
    try:
        record = build(survey, attempt, event, clock, codes)
    except ValueError:  # contradicting event (code not allowed for kind or channel); InvalidAnswer too
        raise IntakeError("invalid_request") from None

    ok, _errors = validate_against_pack(record, "response")  # errors may echo values: not logged
    if not ok or record.farmer_id != farmer or record.survey_id != survey.survey_id:
        log.error("event produced an invalid record")
        raise IntakeError("internal_error")

    duplicate = ledger.put_response(org, record) is PutOutcome.DUPLICATE
    if duplicate:
        stored = ledger.get_response(org, farmer, record.response_key)
        record = stored if stored is not None else record
    if body.kind == "opt_out":
        ledger.set_opt_out(org, farmer, now)
    if record.counts_toward_cap and not duplicate:
        ledger.record_cap(org, farmer, record.survey_id, now)
    log.info(
        "event stored",
        extra={"status": record.status, "failure_code": record.failure_code, "duplicate": duplicate},
    )
    return EventResult(record, duplicate)


__all__ = ["EVENT_KINDS", "EventPayload", "EventResult", "is_event", "submit_event"]
