"""In-memory Ledger. Same semantics as mel/ledger_ddb.py, used by tests and the simulator.

Items live in a dict keyed (pk, sk) with the same key design as the DynamoDB table:

    pk = ORG#<org_id>#FARMER#<farmer_id>   sk = SURVEY#<id> | HANDOFF#<id> | ATTEMPT#<survey_id>#<n>
                                                | RESPONSE#<response_key>#<survey_id> | ANSWERED#<survey_id> | CAP#<survey_id> | OPTOUT
                                                | FOLLOWUP#<id>
    pk = ORG#<org_id>                      sk = COUNTER#SURVEY | SURVEYOWNER#<survey_id>

Every key is built from org_id first, so a read can never cross an org. Records are stored as
JSON text (``to_pack()``) and rebuilt on read, so callers never share mutable state with the store.
Insight and advice text sits inside those records: nothing here logs it.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from mel.models import (
    Attempt,
    FollowUpItem,
    PutOutcome,
    ResponseRecord,
    ScheduleHandoff,
    Survey,
    to_ist,
)

TTL_GRACE = timedelta(days=7)
"""SURVEY, HANDOFF and ATTEMPT items expire this long after the survey/hand-off expires."""

ATTEMPT_FALLBACK_TTL = timedelta(days=30)
"""ATTEMPT ttl when the survey item is not in the ledger: attempt.created_at + this."""

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class SurveyIdConflict(Exception):
    """put_survey: this survey_id already belongs to a different farmer in the org."""


class FarmerOptedOut(Exception):
    """put_handoff: the farmer's OPTOUT item exists, so the hand-off was not written."""


# Duplicate rule (outcome_codes.json duplicate_answer: "The first answer stands"). A final answer
# (completed or negative_outcome) writes ANSWERED#<survey_id>; once it exists, any later answer
# record for that survey (also partial) is a DUPLICATE, whatever its response_key. Partial records
# do not write the marker, so partial then complete stays allowed. Non-answer records (delivery
# failures, declines) are keyed by response_key only.
FINAL_ANSWER_STATUSES = frozenset({"completed", "negative_outcome"})
ANSWER_STATUSES = FINAL_ANSWER_STATUSES | {"partial"}


# --------------------------------------------------------------------------- key helpers
# Shared with mel/ledger_ddb.py so both backends build identical keys.


def check_id(name: str, value: str) -> str:
    """Reject ids that could forge another partition key. '#' is the key separator."""
    if not isinstance(value, str) or not value or "#" in value:
        raise ValueError(f"invalid {name}: must be a non-empty string without '#'")
    return value


def org_pk(org_id: str) -> str:
    return f"ORG#{check_id('org_id', org_id)}"


def farmer_pk(org_id: str, farmer_id: str) -> str:
    return f"ORG#{check_id('org_id', org_id)}#FARMER#{check_id('farmer_id', farmer_id)}"


def to_ttl(when: datetime) -> int:
    """Epoch seconds of ``when + 7 days`` (DynamoDB TTL attribute)."""
    return int((to_ist(when) + TTL_GRACE).timestamp())


def to_micros(when: datetime) -> int:
    """Exact integer microseconds since the Unix epoch (no float rounding at window edges)."""
    return (to_ist(when) - _EPOCH) // timedelta(microseconds=1)


def dump(model: Any) -> str:
    return json.dumps(model.to_pack(), separators=(",", ":"), sort_keys=True)


def followup_gsi_sk(item: FollowUpItem) -> str:
    return f"FOLLOWUP#{item.created_at.isoformat(timespec='seconds')}#{item.follow_up_id}"


def attempt_sk(attempt: Attempt) -> str:
    return f"ATTEMPT#{attempt.survey_id}#{attempt.delivery_attempt}"


def response_prefix(response_key: str) -> str:
    """RESPONSE#<response_key>#: response keys cannot contain '#', so the prefix is unambiguous."""
    return f"RESPONSE#{check_id('response_key', response_key)}#"


def response_sk(record: ResponseRecord) -> str:
    """The same response_key on two surveys is two records, not a duplicate."""
    return response_prefix(record.response_key) + record.survey_id


def answered_sk(survey_id: str) -> str:
    return f"ANSWERED#{survey_id}"


# --------------------------------------------------------------------------- implementation


class InMemoryLedger:
    """Thread-safe dict-backed Ledger. One lock makes every method atomic."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = threading.RLock()

    # -- counters and surveys

    def next_survey_seq(self, org_id: str) -> int:
        with self._lock:
            item = self._items.setdefault((org_pk(org_id), "COUNTER#SURVEY"), {"seq": 0})
            item["seq"] += 1
            return item["seq"]

    def put_survey(self, org_id: str, survey: Survey, expires_at: datetime) -> None:
        owner_key = (org_pk(org_id), f"SURVEYOWNER#{survey.survey_id}")
        with self._lock:
            owner = self._items.get(owner_key)
            if owner is not None and owner["farmer_id"] != survey.farmer_id:
                raise SurveyIdConflict(survey.survey_id)
            self._items[owner_key] = {"farmer_id": survey.farmer_id}
            self._items[(farmer_pk(org_id, survey.farmer_id), f"SURVEY#{survey.survey_id}")] = {
                "data": dump(survey),
                "ttl": to_ttl(expires_at),
            }

    def get_survey(self, org_id: str, farmer_id: str, survey_id: str) -> Survey | None:
        with self._lock:
            item = self._items.get((farmer_pk(org_id, farmer_id), f"SURVEY#{survey_id}"))
        return None if item is None else Survey.model_validate_json(item["data"])

    def find_survey_owner(self, org_id: str, survey_id: str) -> str | None:
        with self._lock:
            owner = self._items.get((org_pk(org_id), f"SURVEYOWNER#{survey_id}"))
        return None if owner is None else owner["farmer_id"]

    # -- hand-off and attempts

    def put_handoff(self, org_id: str, handoff: ScheduleHandoff) -> None:
        """Raises FarmerOptedOut instead of writing when the farmer has opted out."""
        pk = farmer_pk(org_id, handoff.survey.farmer_id)
        with self._lock:
            if (pk, "OPTOUT") in self._items:
                raise FarmerOptedOut
            self._items[(pk, f"HANDOFF#{handoff.handoff_id}")] = {
                "data": dump(handoff),
                "ttl": to_ttl(handoff.expires_at),
            }

    def put_attempt(self, org_id: str, attempt: Attempt) -> PutOutcome:
        pk = farmer_pk(org_id, attempt.farmer_id)
        with self._lock:
            if (pk, "OPTOUT") in self._items:
                return PutOutcome.OPTED_OUT
            survey = self._items.get((pk, f"SURVEY#{attempt.survey_id}"))
            ttl = survey["ttl"] if survey else int((attempt.created_at + ATTEMPT_FALLBACK_TTL).timestamp())
            self._items[(pk, attempt_sk(attempt))] = {"data": dump(attempt), "ttl": ttl}
        return PutOutcome.WRITTEN

    # -- responses

    def put_response(self, org_id: str, record: ResponseRecord) -> PutOutcome:
        pk = farmer_pk(org_id, record.farmer_id)
        key = (pk, response_sk(record))
        marker = (pk, answered_sk(record.survey_id))
        with self._lock:
            if key in self._items:
                return PutOutcome.DUPLICATE
            if record.status in ANSWER_STATUSES and marker in self._items:
                return PutOutcome.DUPLICATE
            self._items[key] = {"data": dump(record)}
            if record.status in FINAL_ANSWER_STATUSES:
                self._items[marker] = {"response_key": record.response_key}
        return PutOutcome.WRITTEN

    def get_response(self, org_id: str, farmer_id: str, response_key: str) -> ResponseRecord | None:
        """The record stored under response_key (the first survey's, in sort order, if several)."""
        pk, prefix = farmer_pk(org_id, farmer_id), response_prefix(response_key)
        with self._lock:
            sks = sorted(sk for (item_pk, sk) in self._items if item_pk == pk and sk.startswith(prefix))
            item = self._items[(pk, sks[0])] if sks else None
        return None if item is None else ResponseRecord.model_validate_json(item["data"])

    # -- frequency cap

    def cap_count(self, org_id: str, farmer_id: str, window_days: int, now: datetime) -> int:
        pk = farmer_pk(org_id, farmer_id)
        upper = to_micros(now)
        lower = upper - int(timedelta(days=window_days) / timedelta(microseconds=1))
        with self._lock:
            return sum(
                1
                for (item_pk, sk), item in self._items.items()
                if item_pk == pk and sk.startswith("CAP#") and lower < item["at_us"] <= upper
            )

    def record_cap(self, org_id: str, farmer_id: str, survey_id: str, at: datetime) -> bool:
        key = (farmer_pk(org_id, farmer_id), f"CAP#{survey_id}")
        with self._lock:
            if key in self._items:
                return False
            self._items[key] = {"at_us": to_micros(at)}
        return True

    # -- opt-out

    def set_opt_out(self, org_id: str, farmer_id: str, at: datetime) -> None:
        key = (farmer_pk(org_id, farmer_id), "OPTOUT")
        with self._lock:
            self._items.setdefault(key, {"at": to_ist(at).isoformat(timespec="seconds")})

    def is_opted_out(self, org_id: str, farmer_id: str) -> bool:
        with self._lock:
            return (farmer_pk(org_id, farmer_id), "OPTOUT") in self._items

    # -- follow-ups

    def put_follow_up(self, org_id: str, item: FollowUpItem) -> None:
        with self._lock:
            self._items[(farmer_pk(org_id, item.farmer_id), f"FOLLOWUP#{item.follow_up_id}")] = {
                "data": dump(item),
                "gsi1pk": org_pk(org_id),
                "gsi1sk": followup_gsi_sk(item),
            }

    def list_follow_ups(self, org_id: str) -> list[FollowUpItem]:
        gsi1pk = org_pk(org_id)
        with self._lock:
            rows = [i for i in self._items.values() if i.get("gsi1pk") == gsi1pk and i["gsi1sk"].startswith("FOLLOWUP#")]
        rows.sort(key=lambda i: i["gsi1sk"])
        return [FollowUpItem.model_validate_json(i["data"]) for i in rows]

    # -- inspection (tests only; not part of the Ledger protocol)

    def item_ttl(self, org_id: str, farmer_id: str, sk: str) -> int | None:
        """The ``ttl`` attribute of one item, or None if the item or attribute is missing."""
        with self._lock:
            item = self._items.get((farmer_pk(org_id, farmer_id), sk))
        return None if item is None else item.get("ttl")
