"""Outcome state machine: one delivery or answer event in, one ResponseRecord out.

Pure code. No model calls, no I/O, no logging. Insight text is never read here, and answer
text (``raw`` inputs) is stored in the record but never written anywhere else.

Public API
----------
``apply_event(survey, attempt, event, clock, codes) -> ResponseRecord``

``survey``   a :class:`mel.models.Survey` or its pack dict.
``attempt``  a :class:`mel.models.Attempt` or a dict with the same keys. A dict may also carry
             ``sent_at``, ``timestamps`` and ``superseded`` (see below).
``event``    ``{kind, channel, farmer_id, at, failure_code?, answers?, raw?, input_kind?, ...}``
             ``kind`` is one of delivered, opened, answer, failure, opt_out, decline.
``clock``    anything with ``now()``. ``recorded_at`` is ``clock.now()``.
``codes``    ``pack/json/rules/outcome_codes.json`` as a dict (``mel.fixtures.load_outcome_codes()``).

Optional event keys beyond the D contract (all ignored when absent):
``timestamps`` (sent/delivered/opened/answered the channel reported), ``inputs``
(``{item_id: {raw, input_kind, attempts}}``), ``raw_event`` (a channel event that is not an
answer), ``sheet_outcome`` (``closed_partway`` or ``interrupted``, app and web only),
``farmerchat_reply`` (the real reply, when the caller has it).

Decisions that are not in the pack are listed in NOTES-D.md.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from mel.models import ResponseRecord, Survey, SurveyItem, to_ist

# --------------------------------------------------------------------------- constants

EVENT_KINDS = frozenset({"delivered", "opened", "answer", "failure", "opt_out", "decline"})
NON_TERMINAL_KINDS = frozenset({"delivered", "opened"})

# Answer-arrival codes: the farmer's tap reached us but is not stored as an answer.
ARRIVAL_CODES = frozenset({"duplicate_answer", "identity_mismatch", "survey_closed", "survey_replaced"})
# Priority when more than one applies. Identity first: never keep another farmer's answers.
ARRIVAL_PRIORITY = ("identity_mismatch", "duplicate_answer", "survey_replaced", "survey_closed")

# Codes whose record keeps the answers accepted before the problem.
INVALID_INPUT_CODES = frozenset({"free_text_instead_of_choice", "keypad_out_of_range", "speech_not_understood"})
KEEPS_ANSWERS_CODES = INVALID_INPUT_CODES | {"voice_call_dropped"}
# Attempts recorded on the invalid item: voice codes mean "twice" in outcome_codes.json.
INVALID_ATTEMPTS = {"free_text_instead_of_choice": 1, "keypad_out_of_range": 2, "speech_not_understood": 2}

# Codes where the farmer never interacted, so answered_by and timestamps.answered stay null.
NO_INTERACTION_CODES = frozenset(
    {
        "push_token_invalid", "client_cannot_render", "wa_session_window_closed", "wa_undelivered",
        "tg_bot_blocked", "voice_no_answer", "voice_busy", "window_expired", "push_not_opened",
    }
)
NEVER_OPENED_CODES = frozenset({"push_token_invalid", "client_cannot_render", "push_not_opened"})
SHEET_CHANNELS = frozenset({"app", "web"})
MAX_RAW = 256


class NonTerminalEvent(Exception):
    """``delivered`` and ``opened`` do not end an attempt. Use :func:`update_timestamps`."""


class InvalidAnswer(ValueError):
    """An app or web event carried a value the sheet cannot produce, or an unknown item_id.

    The pack has no outcome code for this on app and web (the sheet only offers valid taps),
    so no record is made. The API layer maps it to HTTP 422 ``invalid_answer``.
    """


# --------------------------------------------------------------------------- small helpers


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _time(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return to_ist(value)  # naive datetimes raise ValueError


def _cut(text: Any) -> str | None:
    if text is None:
        return None
    return str(text)[:MAX_RAW]


def _reports_opened(channel: str) -> bool:
    """Telegram has no read receipts, so ``opened`` is never set there."""
    return channel != "telegram"


def _as_survey(survey: Survey | dict[str, Any]) -> Survey:
    return survey if isinstance(survey, Survey) else Survey.model_validate(survey)


# --------------------------------------------------------------------------- answers


def _valid_value(item: SurveyItem, value: Any) -> bool:
    """Option values or integer scale values in range only. Bools and numeric strings are out."""
    if item.type == "survey-scale":
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
            and item.scale_min is not None
            and item.scale_max is not None
            and item.scale_min <= value <= item.scale_max
        )
    return isinstance(value, str) and any(opt.value == value for opt in item.options or [])


def _follow_up_reason(item: SurveyItem, value: Any) -> str | None:
    if item.type == "survey-scale":
        if item.follow_up_at_or_below is not None and value <= item.follow_up_at_or_below:
            return item.follow_up_reason
        return None
    for opt in item.options or []:
        if opt.value == value:
            return opt.follow_up
    return None


def _split_answers(survey: Survey, answers: dict[str, Any], *, strict_ids: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split arriving values into (accepted, invalid), keyed by item_id."""
    items = {it.item_id: it for it in survey.items}
    accepted: dict[str, Any] = {}
    invalid: dict[str, Any] = {}
    for item_id, value in answers.items():
        item = items.get(item_id)
        if item is None:
            if strict_ids:
                raise InvalidAnswer("answer for an item that is not in the survey")
            continue
        (accepted if _valid_value(item, value) else invalid)[item_id] = value
    return accepted, invalid


# --------------------------------------------------------------------------- record parts


def _item_input(ev: dict[str, Any], item_id: str, n_values: int) -> tuple[str | None, str | None, int | None]:
    """raw_input, input_kind, attempts for one item, from event['inputs'] or a single-value event."""
    given = (ev.get("inputs") or {}).get(item_id)
    if given is not None:
        return _cut(given.get("raw")), given.get("input_kind"), given.get("attempts")
    if n_values == 1:  # event-level raw/input_kind can only describe a single value
        return _cut(ev.get("raw")), ev.get("input_kind"), None
    return None, None, None


def _item(survey_item: SurveyItem, result: str, value: Any = None, raw: str | None = None,
          kind: str | None = None, attempts: int = 0) -> dict[str, Any]:
    return {
        "item_id": survey_item.item_id,
        "item_type": survey_item.type,
        "result": result,
        "value": value,
        "raw_input": raw,
        "input_kind": kind,
        "attempts": attempts,
    }


def _timestamps(att: Any, ev: dict[str, Any], channel: str, interacted: bool, at: datetime) -> dict[str, datetime | None]:
    """Merge what the attempt already knew with what the event reports. Never invent a step."""
    ts: dict[str, datetime | None] = {"sent": None, "delivered": None, "opened": None, "answered": None}
    ts["sent"] = _time(_get(att, "sent_at")) or _time(_get(att, "created_at"))
    for source in (_get(att, "timestamps"), ev.get("timestamps")):
        for key in ts:
            value = _time(_get(source, key)) if source else None
            if value is not None:
                ts[key] = value
    if ts["answered"] is None and interacted:
        ts["answered"] = at
    if not _reports_opened(channel):
        ts["opened"] = None
    return ts


def update_timestamps(current: dict[str, Any] | None, event: dict[str, Any], channel: str) -> dict[str, datetime | None]:
    """Apply a ``delivered`` or ``opened`` event to a timestamps dict. No new attempt is made.

    ``opened`` is ignored on Telegram. Nothing is written for a step the event does not report.
    """
    ts: dict[str, datetime | None] = {"sent": None, "delivered": None, "opened": None, "answered": None}
    for key in ts:
        ts[key] = _time(_get(current, key)) if current else None
    kind = event.get("kind")
    at = _time(event.get("at"))
    if kind == "delivered" and at is not None and ts["delivered"] is None:
        ts["delivered"] = at
    elif kind == "opened" and at is not None and _reports_opened(channel) and ts["opened"] is None:
        ts["opened"] = at
    return ts


def _shown(ts: dict[str, datetime | None], channel: str) -> bool:
    """Was the first question put in front of the farmer? Opened where the channel says so."""
    return ts["opened"] is not None if _reports_opened(channel) else ts["delivered"] is not None


def _arrival_code(
    ev: dict[str, Any], att: Any, survey: Survey, mismatch: bool, at: datetime
) -> str | None:
    """Why an arriving answer is not stored, if it is not.

    Duplicates are never decided here: the ledger does that (``put_response`` returns DUPLICATE).
    The caller passes ``failure_code: "duplicate_answer"`` and this builds the record shape.
    """
    found: set[str] = set()
    if ev.get("failure_code") in ARRIVAL_CODES:
        found.add(ev["failure_code"])
    if mismatch:
        found.add("identity_mismatch")
    if ev["kind"] == "answer" and _get(att, "superseded"):
        found.add("survey_replaced")
    if ev["kind"] == "answer" and at > survey.send_window.not_after:
        found.add("survey_closed")
    return next((c for c in ARRIVAL_PRIORITY if c in found), None)


def _resolve_code(
    kind: str, ev: dict[str, Any], att: Any, survey: Survey,
    mismatch: bool, at: datetime, codes: dict[str, Any],
) -> str | None:
    """The outcome code the event leads to. None means the answer path decides the status."""
    code = ev.get("failure_code")
    forced = {"opt_out": "farmer_opted_out", "decline": "farmer_declined"}.get(kind)
    if forced is not None:
        if code not in (None, forced):
            raise ValueError(f"{kind} event carries a different failure_code")
        code = forced
    elif kind == "failure" and code is None:
        raise ValueError("failure event needs a failure_code")
    elif kind == "answer" and code is not None and code not in ARRIVAL_CODES | KEEPS_ANSWERS_CODES:
        raise ValueError(f"answer event cannot carry failure_code {code!r}")
    if code is not None and code not in codes["failures"]:
        raise ValueError(f"unknown failure_code: {code!r}")
    # Identity beats everything: a STOP or an answer from the wrong farmer changes nothing.
    return _arrival_code(ev, att, survey, mismatch, at) or code


def _derive_invalid_code(channel: str, input_kind: str | None) -> str:
    if channel in ("whatsapp", "telegram"):
        return "free_text_instead_of_choice"
    if channel == "voice":
        return "speech_not_understood" if input_kind == "speech" else "keypad_out_of_range"
    raise InvalidAnswer("value is not an option or in range")  # app, web


def _farmerchat_reply(code: str | None, status: str, channel: str, has_answers: bool) -> dict[str, Any] | None:
    if code == "duplicate_answer":
        return {"http_status": 200, "outcome": "duplicate"}
    if code == "survey_replaced":
        return {"http_status": 404, "outcome": "unknown_flow"}
    sent = status in ("completed", "partial", "negative_outcome") or (
        status == "invalid_input" and channel == "voice"
    )  # voice sends the answers it has when the call moves on; chat channels wait for a retry
    if sent and has_answers:
        return {"http_status": 201, "outcome": "accepted"}
    return None


# --------------------------------------------------------------------------- apply_event


def apply_event(
    survey: Survey | dict[str, Any],
    attempt: Any,
    event: dict[str, Any],
    clock: Any,
    codes: dict[str, Any],
) -> ResponseRecord:
    """Turn one terminal event of one attempt into a ResponseRecord.

    Raises NonTerminalEvent for ``delivered`` and ``opened`` (use :func:`update_timestamps`),
    InvalidAnswer for app or web values the sheet cannot produce, and ValueError for events
    that contradict the survey, the attempt or the code table.
    """
    survey = _as_survey(survey)
    ev = dict(event)
    kind = ev.get("kind")
    if kind not in EVENT_KINDS:
        raise ValueError(f"unknown event kind: {kind!r}")
    if kind in NON_TERMINAL_KINDS:
        raise NonTerminalEvent(kind)

    # The attempt must belong to this survey and farmer. These are our own records.
    if _get(attempt, "survey_id") != survey.survey_id or _get(attempt, "farmer_id") != survey.farmer_id:
        raise ValueError("attempt does not belong to this survey")
    channel = _get(attempt, "channel")
    if ev.get("channel") not in (None, channel):
        raise ValueError("event channel differs from the attempt channel")

    at = _time(ev.get("at"))
    if at is None:
        raise ValueError("event has no 'at' time")
    now = to_ist(clock.now())
    response_key = _get(attempt, "response_key")
    delivery_attempt = _get(attempt, "delivery_attempt")  # a transport retry keeps it; never bumped here

    event_farmer = ev.get("farmer_id") or survey.farmer_id
    mismatch = event_farmer != survey.farmer_id

    # ---- which outcome code, if any
    code = _resolve_code(kind, ev, attempt, survey, mismatch, at, codes)
    # A refusal carries no answers, whatever else the event holds.
    answers_in: dict[str, Any] = {} if kind in ("opt_out", "decline") else dict(ev.get("answers") or {})

    # ---- validate arriving values (never for events that are discarded)
    discard = code in ARRIVAL_CODES
    accepted: dict[str, Any] = {}
    invalid: dict[str, Any] = {}
    if not discard:
        accepted, invalid = _split_answers(survey, answers_in, strict_ids=True)
        if invalid:
            # A bad value turns the event into invalid_input on chat and voice channels.
            if code is None or code == "window_expired":
                code = _derive_invalid_code(channel, ev.get("input_kind"))
            elif code not in INVALID_INPUT_CODES:
                raise ValueError(f"values arrived with failure_code {code!r}")
        if code is None and not accepted:
            raise ValueError("answer event carries no values")
        if accepted and code is not None and code not in KEEPS_ANSWERS_CODES and code != "window_expired":
            raise ValueError(f"failure_code {code!r} cannot carry answers")
        if code == "window_expired" and accepted:
            code = None  # answered some, then the window closed: that is a partial, not an expiry

    # ---- build items and read status from the code table
    n_values = len(answers_in)
    items: list[dict[str, Any]] = []
    follow_ups: list[str] = []
    # A call that dropped before any answer had no real interaction.
    interacted = code not in NO_INTERACTION_CODES and not (code == "voice_call_dropped" and not accepted)
    ts = _timestamps(attempt, ev, channel, interacted, at)

    if code in ARRIVAL_CODES:
        info = codes["failures"][code]
        for it in survey.items:
            if it.item_id in answers_in:
                value = answers_in[it.item_id]
                raw, kind_in, attempts = _item_input(ev, it.item_id, n_values)
                items.append(_item(it, "discarded", value if _valid_value(it, value) else None, raw, kind_in, attempts or 1))
            else:
                items.append(_item(it, "not_reached"))
        status = info["status"]
        accepted = {}
    else:
        invalid_code_attempts = INVALID_ATTEMPTS.get(code or "", 1)
        invalid_slot = None
        if code in INVALID_INPUT_CODES:
            # The first item that holds no accepted answer is the one that failed.
            invalid_slot = next((i for i in survey.items if i.item_id in invalid), None) or next(
                (i for i in survey.items if i.item_id not in accepted), None
            )
        shown = _shown(ts, channel)
        first_gap_done = False
        for it in survey.items:
            if it.item_id in accepted:
                raw, kind_in, attempts = _item_input(ev, it.item_id, n_values)
                items.append(_item(it, "answered", accepted[it.item_id], raw, kind_in, attempts or 1))
                reason = _follow_up_reason(it, accepted[it.item_id])
                if reason and reason not in follow_ups:
                    follow_ups.append(reason)
            elif invalid_slot is not None and it.item_id == invalid_slot.item_id:
                raw = _cut(invalid.get(it.item_id)) if it.item_id in invalid else _cut((ev.get("inputs") or {}).get(it.item_id, {}).get("raw"))
                kind_in = (ev.get("inputs") or {}).get(it.item_id, {}).get("input_kind")
                items.append(_item(it, "invalid", None, raw, kind_in, invalid_code_attempts))
            elif code is None:
                items.append(_item(it, "skipped", attempts=1))  # shown, not answered
            elif code == "sheet_dismissed" or (code == "window_expired" and shown):
                items.append(_item(it, "skipped" if not first_gap_done else "not_reached", attempts=0 if first_gap_done else 1))
                first_gap_done = True
            else:
                items.append(_item(it, "not_reached"))

        if code is None:
            if len(accepted) == len(survey.items):
                status = "negative_outcome" if follow_ups else "completed"
            else:
                status = "negative_outcome" if follow_ups else "partial"
            info = codes["success"][status]
        else:
            info = codes["failures"][code]
            if channel not in info["channels"]:
                raise ValueError(f"{code} cannot happen on {channel}")
            status = info["status"]

    complete = bool(code is None and len(accepted) == len(survey.items))

    # ---- sheet outcome: app and web only
    sheet_outcome: str | None = None
    if channel in SHEET_CHANNELS:
        if code is None:
            if complete:
                sheet_outcome = "finished"
            else:
                asked = ev.get("sheet_outcome")
                sheet_outcome = asked if asked in ("closed_partway", "interrupted") else "closed_partway"
        elif code in ARRIVAL_CODES:
            sheet_outcome = "finished"
        elif code in NEVER_OPENED_CODES:
            sheet_outcome = "never_opened"
        elif code == "window_expired":
            sheet_outcome = "dismissed" if _shown(ts, channel) else "never_opened"
        else:
            sheet_outcome = "dismissed"  # sheet_dismissed, farmer_opted_out

    # ---- raw_event: a channel event that is not an answer
    if "raw_event" in ev:
        raw_event = _cut(ev["raw_event"])
    elif kind in ("opt_out", "decline") or (kind == "failure" and not accepted):
        raw_event = _cut(ev.get("raw"))
    else:
        raw_event = None

    reply = ev.get("farmerchat_reply") or _farmerchat_reply(code, status, channel, bool(accepted))

    data = {
        "response_key": response_key,
        "survey_id": survey.survey_id,
        "farmer_id": survey.farmer_id,
        "source_insight_ids": list(_get(attempt, "source_insight_ids") or survey.source_insight_ids),
        "channel": channel,
        "language": _get(attempt, "language") or survey.language,
        "status": status,
        "failure_code": code,
        "answers": dict(accepted),
        "items": items,
        "complete": complete,
        "delivery_attempt": delivery_attempt,
        "timestamps": ts,
        "recorded_at": now,
        "answered_by": event_farmer if interacted else None,
        "sheet_outcome": sheet_outcome,
        "raw_event": raw_event,
        "retry_decision": info["retry_decision"],
        "retry_after_minutes": info.get("retry_after_minutes"),
        "counts_toward_cap": info["counts_toward_cap"],
        "farmerchat_reply": reply,
        "needs_follow_up": bool(follow_ups),
        "follow_up_reasons": follow_ups,
    }
    return ResponseRecord.model_validate(data)
