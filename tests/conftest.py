"""Shared offline fixtures. Network is blocked for every test (pytest-socket)."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest
from pytest_socket import disable_socket

# Make the repo root importable without an install step (there is no pyproject yet).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mel import fixtures as pack
from mel.models import IST
from mel.protocols import FakeClock

# Default test time: the hackathon day, 09:00 India time.
TEST_NOW = datetime(2026, 11, 5, 9, 0, tzinfo=IST)


def pytest_runtest_setup(item):
    # Belt and braces: `make test` passes --disable-socket too.
    disable_socket(allow_unix_socket=True)


@pytest.fixture
def clock() -> FakeClock:
    """In-memory clock at 2026-11-05T09:00:00+05:30. Moves only on clock.advance(td)."""
    return FakeClock(TEST_NOW)


@pytest.fixture(scope="session")
def insights():
    return pack.load_insights()


@pytest.fixture(scope="session")
def golden():
    return pack.load_golden()


@pytest.fixture(scope="session")
def crop_calendar():
    return pack.load_crop_calendar()


@pytest.fixture(scope="session")
def scenarios():
    return pack.load_scenarios()


@pytest.fixture(scope="session")
def outcomes():
    return pack.load_outcomes()


@pytest.fixture(scope="session")
def rules():
    return pack.load_rules()


@pytest.fixture(scope="session")
def outcome_codes():
    return pack.load_outcome_codes()
