"""Run every outcome fixture through mel.outcomes.apply_event.

Each of the 183 files under pack/json/outcomes is an expected ResponseRecord.
The inputs come from outcome_events.py. Until mel/outcomes.py exists, every
case skips at the apply_event fixture.
"""

from __future__ import annotations

from typing import Any

import pytest
from outcome_events import (
    FixedClock,
    attempt_from_fixture,
    case_id,
    event_from_fixture,
    load_codes,
    load_fixture,
    load_survey,
    outcome_paths,
)

ASSERTED_FIELDS = (
    "status",
    "failure_code",
    "sheet_outcome",
    "answers",
    "complete",
    "retry_decision",
    "retry_after_minutes",
    "counts_toward_cap",
    "needs_follow_up",
    "follow_up_reasons",
)


@pytest.fixture(scope="module")
def apply_event():
    outcomes = pytest.importorskip("mel.outcomes")
    return outcomes.apply_event


@pytest.fixture(scope="module")
def codes() -> dict[str, Any]:
    return load_codes()


def _field(record: Any, name: str) -> Any:
    if isinstance(record, dict):
        return record[name]
    return getattr(record, name)


@pytest.mark.parametrize("path", outcome_paths(), ids=case_id)
def test_outcome_fixture(path, apply_event, codes):
    fixture = load_fixture(path)
    survey = load_survey(fixture["survey_id"], fixture["language"])
    attempt = attempt_from_fixture(fixture)
    event = event_from_fixture(fixture)
    clock = FixedClock(fixture["recorded_at"])

    record = apply_event(survey, attempt, event, clock, codes)

    for name in ASSERTED_FIELDS:
        actual = _field(record, name)
        if name == "follow_up_reasons":
            actual = list(actual)
        assert actual == fixture[name], f"{name} differs for {path.name}"
