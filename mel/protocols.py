"""The interfaces every component codes against (typing.Protocol), plus the two clocks.

Security rule for the Ledger: every method takes org_id first, and every read and write is
scoped by org_id and farmer_id. org_id and farmer_id come from the Cognito JWT claims
(mel/api/auth.py), never from a request body. The one org-scoped call is
find_survey_owner, which returns only the owning farmer_id so intake can record an
identity_mismatch; it never returns survey content.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from mel.models import (
    IST,
    Attempt,
    Channel,
    FollowUpItem,
    Insight,
    JudgeVerdict,
    PutOutcome,
    ResponseRecord,
    ScheduleHandoff,
    Survey,
    TimingProfile,
    Usage,
    to_ist,
)

# --------------------------------------------------------------------------- clock


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime:
        """Current time, timezone-aware, +05:30."""
        ...

    def advance(self, td: timedelta) -> None:
        """Move this clock forward (virtual time for the simulator and tests)."""
        ...


class SystemClock:
    """Wall clock in India time, with an optional virtual offset for the demo."""

    def __init__(self) -> None:
        self._offset = timedelta(0)

    def now(self) -> datetime:
        return datetime.now(IST) + self._offset

    def advance(self, td: timedelta) -> None:
        if td < timedelta(0):
            raise ValueError("a clock only moves forward")
        self._offset += td


class FakeClock:
    """Fixed clock for tests. Starts at ``start`` and moves only on advance()."""

    def __init__(self, start: datetime) -> None:
        self._now = to_ist(start)

    def now(self) -> datetime:
        return self._now

    def advance(self, td: timedelta) -> None:
        if td < timedelta(0):
            raise ValueError("a clock only moves forward")
        self._now += td


# --------------------------------------------------------------------------- ledger


@runtime_checkable
class Ledger(Protocol):
    """Durable store. DynamoDB (mel/ledger_ddb.py) and in-memory (mel/ledger_mem.py)."""

    def next_survey_seq(self, org_id: str) -> int:
        """Atomic counter for survey ids: survey_id = f"S-{seq:05d}"."""
        ...

    def put_survey(self, org_id: str, survey: Survey, expires_at: datetime) -> None:
        """Store a survey under survey.farmer_id. TTL = expires_at + 7 days."""
        ...

    def get_survey(self, org_id: str, farmer_id: str, survey_id: str) -> Survey | None:
        ...

    def find_survey_owner(self, org_id: str, survey_id: str) -> str | None:
        """farmer_id that owns survey_id in this org, or None. Used only to detect identity_mismatch."""
        ...

    def put_handoff(self, org_id: str, handoff: ScheduleHandoff) -> None:
        """Store under handoff.survey.farmer_id. TTL = handoff.expires_at + 7 days."""
        ...

    def put_attempt(self, org_id: str, attempt: Attempt) -> PutOutcome:
        """WRITTEN, or OPTED_OUT (nothing written) when the farmer has opted out."""
        ...

    def put_response(self, org_id: str, record: ResponseRecord) -> PutOutcome:
        """Idempotent on response_key: WRITTEN, or DUPLICATE with the first record untouched."""
        ...

    def get_response(self, org_id: str, farmer_id: str, response_key: str) -> ResponseRecord | None:
        ...

    def cap_count(self, org_id: str, farmer_id: str, window_days: int, now: datetime) -> int:
        """Surveys counted toward the cap in (now - window_days, now]."""
        ...

    def record_cap(self, org_id: str, farmer_id: str, survey_id: str, at: datetime) -> bool:
        """Count survey_id once. True if counted by this call, False if already counted."""
        ...

    def set_opt_out(self, org_id: str, farmer_id: str, at: datetime) -> None:
        ...

    def is_opted_out(self, org_id: str, farmer_id: str) -> bool:
        ...

    def put_follow_up(self, org_id: str, item: FollowUpItem) -> None:
        ...

    def list_follow_ups(self, org_id: str) -> list[FollowUpItem]:
        ...


# --------------------------------------------------------------------------- model calls


@runtime_checkable
class Generator(Protocol):
    def generate(
        self,
        insight: Insight,
        language: str,
        timing_profile: TimingProfile,
        model_key: str,
        *,
        repair_errors: list[str] | None = None,
    ) -> tuple[dict[str, Any], Usage]:
        """Draft a survey dict (untrusted until mel.validate passes). repair_errors: validator
        errors from the previous draft, for the single retry. Insight goes in the user turn."""
        ...


@runtime_checkable
class Judge(Protocol):
    def check_survey(self, insight: Insight, survey: Survey) -> JudgeVerdict:
        """Jev checks on the final survey. Fails closed: errors give pending_review, never ok."""
        ...


@runtime_checkable
class Renderer(Protocol):
    def render(self, survey: Survey | dict[str, Any], channel: Channel, language: str) -> dict[str, Any]:
        """Channel payload matching pack/json/scenarios/*/render/<language>/<channel>.json."""
        ...


__all__ = [
    "Clock",
    "FakeClock",
    "Generator",
    "Judge",
    "Ledger",
    "Renderer",
    "SystemClock",
]
