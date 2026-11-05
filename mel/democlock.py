"""Server-side demo clock: wall clock plus a per-org offset kept in the ledger table.

Why: the pack scenarios have send windows in Dec 2026 and Jan 2027. A server on the real clock
never sees those windows open, and the simulator's virtual clock cannot be sent to the API
(``ResponsePayload`` has no time field, and a client-set time must never be trusted).

How: one item per org, ``pk = ORG#<org_id>``, ``sk = DEMOCLOCK``, attribute ``offset_s`` (number of
seconds). With no item the offset is zero and the clock is the wall clock. The offset is read once
when the clock is built, so one request sees one consistent time base.

Who can move it: only the AgentCore Runtime action ``clock`` (``mel.api.service``), which is
invoked with IAM SigV4. No API Gateway route can change it, so a farmer's JWT cannot move time.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Protocol

from mel.ledger_mem import org_pk
from mel.models import IST, to_ist

CLOCK_SK = "DEMOCLOCK"
MAX_OFFSET = timedelta(days=3 * 365)  # a typo should not push the demo into the next decade


class ClockStore(Protocol):
    def get_offset(self, org_id: str) -> timedelta: ...
    def set_offset(self, org_id: str, offset: timedelta) -> None: ...


class MemoryClockStore:
    def __init__(self) -> None:
        self._offsets: dict[str, timedelta] = {}

    def get_offset(self, org_id: str) -> timedelta:
        return self._offsets.get(org_pk(org_id), timedelta(0))

    def set_offset(self, org_id: str, offset: timedelta) -> None:
        self._offsets[org_pk(org_id)] = offset


class DynamoClockStore:
    """Reads and writes the DEMOCLOCK item. ``client`` is the resource-level client the ledger uses
    (``boto3.resource("dynamodb").meta.client``): plain Python values, no type descriptors."""

    def __init__(self, client: Any, table_name: str) -> None:
        self._client = client
        self._table = table_name

    def get_offset(self, org_id: str) -> timedelta:
        item = self._client.get_item(
            TableName=self._table,
            Key={"pk": org_pk(org_id), "sk": CLOCK_SK},
            ConsistentRead=True,
        ).get("Item")
        if not item or "offset_s" not in item:
            return timedelta(0)
        return timedelta(seconds=int(item["offset_s"]))

    def set_offset(self, org_id: str, offset: timedelta) -> None:
        self._client.put_item(
            TableName=self._table,
            Item={"pk": org_pk(org_id), "sk": CLOCK_SK, "offset_s": int(offset.total_seconds())},
        )


def _wall() -> datetime:
    return datetime.now(IST)


class DemoClock:
    """Implements ``mel.protocols.Clock`` for one org."""

    def __init__(self, store: ClockStore, org_id: str, *, wall: Callable[[], datetime] = _wall) -> None:
        self._store = store
        self._org = org_id
        self._wall = wall
        self._offset = store.get_offset(org_id)

    @property
    def offset(self) -> timedelta:
        return self._offset

    def now(self) -> datetime:
        return to_ist(self._wall() + self._offset)

    def advance(self, td: timedelta) -> None:
        if td < timedelta(0):
            raise ValueError("a clock only moves forward")
        self._save(self._offset + td)

    def set(self, at: datetime) -> None:
        """Jump to ``at`` (aware datetime). May move back: the operator resets between scenarios."""
        if at.tzinfo is None:
            raise ValueError("naive datetime")
        self._save(at - self._wall())

    def reset(self) -> None:
        self._save(timedelta(0))

    def _save(self, offset: timedelta) -> None:
        if abs(offset) > MAX_OFFSET:
            raise ValueError("demo clock offset is out of range")
        offset = timedelta(seconds=int(offset.total_seconds()))
        self._store.set_offset(self._org, offset)
        self._offset = offset


__all__ = ["CLOCK_SK", "ClockStore", "DemoClock", "DynamoClockStore", "MemoryClockStore"]
