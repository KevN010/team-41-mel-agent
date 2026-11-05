"""Rebuild the inputs of apply_event from each outcome fixture.

Each file under pack/json/outcomes is an expected ResponseRecord. This module
derives the event, attempt, survey and clock that the state machine would
receive, using only that fixture and its scenario survey. Nothing here imports
mel, so it works before mel/outcomes.py exists.

Event kinds follow the D-outcomes contract: answer, failure, decline, opt_out.
Answer-arrival codes (duplicate_answer, identity_mismatch, survey_closed,
survey_replaced) arrive as kind "answer" with their failure_code, because the
tap did reach FarmerChat. See NOTES-D2.md.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

PACK_JSON = Path(__file__).resolve().parents[1] / "pack" / "json"
OUTCOMES_ROOT = PACK_JSON / "outcomes"
SCENARIOS_ROOT = PACK_JSON / "scenarios"
CODES_PATH = PACK_JSON / "rules" / "outcome_codes.json"

# Codes that describe an answer arriving late, twice, or from the wrong phone.
ANSWER_ARRIVAL_CODES = frozenset(
    {"duplicate_answer", "identity_mismatch", "survey_closed", "survey_replaced"}
)
DECISION_KINDS = {"farmer_declined": "decline", "farmer_opted_out": "opt_out"}


def outcome_paths() -> list[Path]:
    """All outcome fixtures, sorted by channel, question type, then name."""
    return sorted(OUTCOMES_ROOT.glob("*/*/*.json"))


def case_id(path: Path) -> str:
    """Readable pytest id such as 'web/survey-confirm/completed'."""
    return "/".join(path.relative_to(OUTCOMES_ROOT).with_suffix("").parts)


def load_fixture(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_codes() -> dict[str, Any]:
    return json.loads(CODES_PATH.read_text(encoding="utf-8"))


def load_survey(survey_id: str, language: str) -> dict[str, Any]:
    """The pack scenario survey whose survey_id and language match the fixture."""
    for path in sorted(SCENARIOS_ROOT.glob(f"*/survey.{language}.json")):
        survey = json.loads(path.read_text(encoding="utf-8"))
        if survey["survey_id"] == survey_id:
            return survey
    raise LookupError(f"no scenario survey {survey_id} for {language}")


def event_kind(fixture: dict[str, Any]) -> str:
    code = fixture["failure_code"]
    if code is None:
        return "answer"
    if code in DECISION_KINDS:
        return DECISION_KINDS[code]
    if code in ANSWER_ARRIVAL_CODES:
        return "answer"
    return "failure"


def _first_non_null(items: list[dict[str, Any]], field: str) -> Any:
    for item in items:
        if item[field] is not None:
            return item[field]
    return None


def arriving_answers(fixture: dict[str, Any]) -> dict[str, Any]:
    """Values that reached FarmerChat, accepted or not.

    Answered items are accepted. Discarded items arrived but were not stored, so
    the state machine must reject them. Invalid items carry no value.
    """
    return {
        item["item_id"]: item["value"]
        for item in fixture["items"]
        if item["result"] in ("answered", "discarded") and item["value"] is not None
    }


def event_from_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    timestamps = fixture["timestamps"]
    kind = event_kind(fixture)
    at = timestamps["answered"] if kind == "answer" and timestamps["answered"] else None
    return {
        "kind": kind,
        "channel": fixture["channel"],
        "failure_code": fixture["failure_code"],
        "answers": arriving_answers(fixture),
        "raw": _first_non_null(fixture["items"], "raw_input") or fixture["raw_event"],
        "input_kind": _first_non_null(fixture["items"], "input_kind"),
        # answered_by differs from farmer_id only on identity_mismatch.
        "farmer_id": fixture["answered_by"] or fixture["farmer_id"],
        "at": at or fixture["recorded_at"],
        "timestamps": dict(timestamps),
        # closed_partway or interrupted tells a partial answer set apart; null otherwise.
        "sheet_outcome": fixture["sheet_outcome"] if fixture["status"] == "partial" else None,
    }


def attempt_from_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    """The send-side record, plus two facts the event alone cannot carry."""
    code = fixture["failure_code"]
    return {
        "response_key": fixture["response_key"],
        "survey_id": fixture["survey_id"],
        "farmer_id": fixture["farmer_id"],
        "channel": fixture["channel"],
        "language": fixture["language"],
        "delivery_attempt": fixture["delivery_attempt"],
        "source_insight_ids": list(fixture["source_insight_ids"]),
        "sent_at": fixture["timestamps"]["sent"],
        # Ledger facts: a prior accepted answer, and a newer survey for the farmer.
        "already_answered": code == "duplicate_answer",
        "superseded": code == "survey_replaced",
    }


class FixedClock:
    """A clock frozen at the fixture's recorded_at. Callable and has now()."""

    def __init__(self, iso_time: str) -> None:
        self._now = datetime.fromisoformat(iso_time)

    def now(self) -> datetime:
        return self._now

    def __call__(self) -> datetime:
        return self._now
