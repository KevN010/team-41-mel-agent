"""Response intake: the logic behind POST /surveys/{survey_id}/responses.

Security rules (CLAUDE.md):
  * ``identity`` (farmer_id, org_id) comes from the JWT claims via mel.api.auth. The payload
    model forbids every unknown key, so a body that carries farmer_id, org_id, answered_by or
    anything else is refused with ``invalid_request``. No payload field can set identity.
  * Every ledger read and write uses identity.org_id and identity.farmer_id.
  * Answer text is untrusted. It is checked against the survey's own option values or scale
    range, and it is never logged.

Rejections raise IntakeError (code + HTTP status). Accepted submissions return a
ResponseRecord (status completed, partial, negative_outcome, duplicate, or stale).

Duplicates: the ledger decides. put_response is idempotent on response_key and returns
DUPLICATE; the first record stays untouched. Intake then asks apply_event (agent D) only to
shape the duplicate record (same event plus failure_code "duplicate_answer").

Rejection codes
  invalid_request   400  payload is not valid JSON-shape (extra key, wrong type, bad survey id)
  unauthorized      401  raised by mel.api.auth.Unauthorized, not here
  identity_mismatch 403  survey exists in this org but belongs to another farmer
  unknown_survey    404  no such survey for this org and farmer (wrong org looks the same)
  unknown_flow      404  payload flow_key does not match the survey's FarmerChat flow
  invalid_answer    422  unknown item, option value not offered, scale not an int in range
  internal_error    500  the produced record failed the pack schema (nothing is stored)
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Annotated, Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

from mel.api.auth import Identity
from mel.models import (
    Attempt,
    Channel,
    FollowUpItem,
    InputKind,
    LanguageTag,
    PutOutcome,
    ResponseRecord,
    SheetOutcome,
    Survey,
    SurveyItem,
)
from mel.protocols import Clock, Ledger
from mel.validate import validate_against_pack

log = logging.getLogger("mel.intake")

ResponseKey = Annotated[StrictStr, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")]
SURVEY_ID_RE = re.compile(r"^S-[0-9]{5,10}$")
SHEET_CHANNELS = ("app", "web")

# code -> HTTP status. The single source for the route and the docs.
REJECTIONS: dict[str, int] = {
    "invalid_request": 400,
    "unauthorized": 401,
    "identity_mismatch": 403,
    "unknown_survey": 404,
    "unknown_flow": 404,
    "invalid_answer": 422,
    "internal_error": 500,
}


class IntakeError(Exception):
    """A rejected submission. ``str(exc)`` is the code only: no ids, no answer text."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
        self.http_status = REJECTIONS[code]

    def to_response(self) -> dict[str, Any]:
        """API Gateway proxy response. The body holds the code and nothing from the request."""
        return {
            "statusCode": self.http_status,
            "headers": {"content-type": "application/json"},
            "body": json.dumps({"error": self.code}),
        }


def success_status(record: ResponseRecord) -> int:
    """HTTP status for a handled submission: 201 stored answer, 200 duplicate, 410 stale (late tap)."""
    return {"duplicate": 200, "stale": 410}.get(record.status, 201)


class ResponsePayload(BaseModel):
    """What a client may send. extra="forbid": identity fields in the body are a 400."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    response_key: ResponseKey
    channel: Channel
    answers: dict[str, Any] = Field(default_factory=dict, max_length=3)
    sheet_outcome: SheetOutcome | None = None
    delivery_attempt: Annotated[StrictInt, Field(ge=1, le=5)] = 1
    language: LanguageTag | None = None
    flow_key: Annotated[StrictStr, Field(max_length=80)] | None = None
    input_kind: InputKind | None = None


# --------------------------------------------------------------------------- follow-up queue


class FollowUpQueue(Protocol):
    def send(self, org_id: str, item: FollowUpItem) -> None: ...


class SqsFollowUpQueue:
    """Sends one follow-up item per message to the FarmerChat follow-up queue (SQS)."""

    def __init__(self, client: Any, queue_url: str) -> None:
        self._client = client
        self._queue_url = queue_url

    def send(self, org_id: str, item: FollowUpItem) -> None:
        body = {"org_id": org_id, **item.to_pack()}
        self._client.send_message(QueueUrl=self._queue_url, MessageBody=json.dumps(body))


def default_queue() -> FollowUpQueue | None:
    """SQS queue from settings.FOLLOW_UP_QUEUE_URL, or None when it is not configured."""
    from mel.settings import settings

    if not settings.FOLLOW_UP_QUEUE_URL:
        return None
    import boto3

    return SqsFollowUpQueue(boto3.client("sqs", region_name=settings.REGION), settings.FOLLOW_UP_QUEUE_URL)


# --------------------------------------------------------------------------- helpers


def expected_flow_key(survey_id: str) -> str:
    """mel_s_21310 for S-21310 (CONTRACTS handoff rule)."""
    return "mel_" + survey_id.lower().replace("-", "_")


def _load_survey(identity: Identity, survey_id: str, ledger: Ledger) -> Survey:
    if not SURVEY_ID_RE.fullmatch(survey_id or ""):
        raise IntakeError("invalid_request")
    survey = ledger.get_survey(identity.org_id, identity.farmer_id, survey_id)
    if survey is None:
        owner = ledger.find_survey_owner(identity.org_id, survey_id)
        if owner is not None and owner != identity.farmer_id:
            raise IntakeError("identity_mismatch")
        raise IntakeError("unknown_survey")
    if survey.farmer_id != identity.farmer_id:  # defence in depth: the ledger is already scoped
        raise IntakeError("identity_mismatch")
    return survey


def _check_answer(item: SurveyItem, value: Any) -> None:
    if item.type == "survey-scale":
        if isinstance(value, bool) or not isinstance(value, int):
            raise IntakeError("invalid_answer")
        if not (item.scale_min <= value <= item.scale_max):  # type: ignore[operator]
            raise IntakeError("invalid_answer")
        return
    allowed = {opt.value for opt in item.options or []}
    if not isinstance(value, str) or value not in allowed:
        raise IntakeError("invalid_answer")


def _validate_answers(survey: Survey, answers: Mapping[str, Any]) -> dict[str, Any]:
    items = {item.item_id: item for item in survey.items}
    for item_id, value in answers.items():
        if item_id not in items:
            raise IntakeError("invalid_answer")
        _check_answer(items[item_id], value)
    return dict(answers)


def _parse_payload(payload: Any) -> ResponsePayload:
    if isinstance(payload, ResponsePayload):
        return payload
    if not isinstance(payload, Mapping):
        raise IntakeError("invalid_request")
    try:
        return ResponsePayload.model_validate(dict(payload))
    except ValidationError as exc:
        # Pydantic errors can echo input values. Log the error types only.
        log.info("intake rejected payload", extra={"error_types": sorted({e["type"] for e in exc.errors()})})
        raise IntakeError("invalid_request") from None


def _follow_up_item(record: ResponseRecord, now: datetime) -> FollowUpItem:
    digest = hashlib.sha256(f"{record.survey_id}|{record.response_key}".encode()).hexdigest()[:12]
    return FollowUpItem(
        follow_up_id=f"FU-{record.survey_id}-{digest}",
        farmer_id=record.farmer_id,
        survey_id=record.survey_id,
        response_key=record.response_key,
        source_insight_ids=list(record.source_insight_ids),
        reasons=list(record.follow_up_reasons),
        accepted_answers=dict(record.answers),
        created_at=now,
    )


def _build(
    build: Callable[..., ResponseRecord], survey: Survey, attempt: Any, event: dict[str, Any],
    clock: Clock, codes: Mapping[str, Any], **kwargs: Any,
) -> ResponseRecord:
    try:
        return build(survey, attempt, event, clock, codes, **kwargs)
    except Exception as exc:  # mel.outcomes.InvalidAnswer: a value the sheet cannot produce
        if type(exc).__name__ != "InvalidAnswer":
            raise
        raise IntakeError("invalid_answer") from None


def _default_apply_event() -> Callable[..., ResponseRecord]:
    from mel.outcomes import apply_event

    return apply_event


# --------------------------------------------------------------------------- entry point


def submit_response(
    identity: Identity,
    survey_id: str,
    payload: Any,
    ledger: Ledger,
    clock: Clock,
    codes: Mapping[str, Any],
    *,
    apply_event: Callable[..., ResponseRecord] | None = None,
    queue: FollowUpQueue | None = None,
) -> ResponseRecord:
    """Validate, record and (when needed) queue one response. See the module docstring.

    ``payload``: dict with response_key, channel, answers (item_id -> option value or scale
    int; may be a subset), sheet_outcome (app/web only), delivery_attempt, language, flow_key,
    input_kind. ``apply_event`` and ``queue`` are injectable; defaults are mel.outcomes and SQS.
    """
    body = _parse_payload(payload)
    survey = _load_survey(identity, survey_id, ledger)

    if body.flow_key is not None and body.flow_key != expected_flow_key(survey.survey_id):
        raise IntakeError("unknown_flow")
    if body.language is not None and body.language != survey.language:
        raise IntakeError("invalid_request")
    if body.sheet_outcome is not None and body.channel not in SHEET_CHANNELS:
        raise IntakeError("invalid_request")  # schema: sheet_outcome is app and web only
    if not body.answers and body.sheet_outcome is None:
        raise IntakeError("invalid_request")  # nothing to record
    answers = _validate_answers(survey, body.answers)

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
        "kind": "answer",
        "channel": body.channel,
        "answers": answers,
        "raw": None,
        "input_kind": body.input_kind,
        "sheet_outcome": body.sheet_outcome,
        "farmer_id": farmer,  # the JWT farmer, never a body value
        "at": now,
    }
    build = apply_event or _default_apply_event()
    record = _build(build, survey, attempt, event, clock, codes)

    # Every emitted record is validated against the pack schema before persisting.
    ok, _errors = validate_against_pack(record, "response")  # errors may echo values: not logged
    if not ok or record.farmer_id != farmer or record.survey_id != survey.survey_id:
        log.error("intake produced an invalid record")
        raise IntakeError("internal_error")

    # Duplicate detection belongs to the ledger: put_response is idempotent on response_key.
    if ledger.put_response(org, record) is PutOutcome.DUPLICATE:
        # The state machine only shapes the duplicate record; the first record stays untouched.
        dup = _build(build, survey, attempt, {**event, "failure_code": "duplicate_answer"}, clock, codes)
        ok, _errors = validate_against_pack(dup, "response")
        if not ok or dup.farmer_id != farmer or dup.status != "duplicate":
            log.error("intake produced an invalid duplicate record")
            raise IntakeError("internal_error")
        return dup

    log.info("intake stored", extra={"status": record.status, "failure_code": record.failure_code})
    if record.needs_follow_up:
        _queue_follow_up(org, record, ledger, queue, now)
    return record


def _queue_follow_up(
    org_id: str, record: ResponseRecord, ledger: Ledger, queue: FollowUpQueue | None, now: datetime
) -> None:
    item = _follow_up_item(record, now)
    ledger.put_follow_up(org_id, item)  # source of truth: survives a failed enqueue
    queue = queue if queue is not None else default_queue()
    if queue is None:
        log.warning("follow-up queue not configured; item kept in ledger only")
        return
    try:
        queue.send(org_id, item)
    except Exception as exc:  # noqa: BLE001 - the answer is stored; do not fail the farmer's request
        log.error("follow-up enqueue failed", extra={"error_class": type(exc).__name__})


__all__ = [
    "REJECTIONS",
    "FollowUpQueue",
    "IntakeError",
    "ResponsePayload",
    "SqsFollowUpQueue",
    "expected_flow_key",
    "submit_response",
    "success_status",
]
