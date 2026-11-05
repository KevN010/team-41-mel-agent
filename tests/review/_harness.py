"""Shared builders for the review tests. Real InMemoryLedger, real mel.outcomes, pack scenario 3."""

from __future__ import annotations

import copy
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from mel import fixtures
from mel.api.auth import Identity
from mel.api.decide import DecideDeps
from mel.ledger_mem import InMemoryLedger
from mel.models import (
    DecisionRecord,
    ScheduleHandoff,
    SendWindow,
    Survey,
    Usage,
    to_ist,
)

ORG = "org-review"
SC3 = "3-potato-blight-wait"  # survey S-21310, farmer F-000245, priority normal (cap not exempt)


def scenario(name: str = SC3) -> dict[str, Any]:
    return copy.deepcopy(next(s for s in fixtures.load_scenarios() if s["name"] == name))


def sc3_parts() -> tuple[dict[str, Any], Survey, ScheduleHandoff]:
    sc = scenario()
    return sc["insight"], Survey.model_validate(sc["survey_by_lang"]["en-IN"]), ScheduleHandoff.model_validate(sc["handoff"])


def identity_for(farmer_id: str, org_id: str = ORG) -> Identity:
    return Identity(farmer_id=farmer_id, org_id=org_id, sub="sub-review")


def r8_decision(insight: dict[str, Any], window: SendWindow | None = None) -> DecisionRecord:
    return DecisionRecord(
        insight_id=insight["insight_id"], farmer_id=insight["farmer_id"], survey=True, rule_id="R8",
        reason_code=None, timing_profile="golden_v1", send_window=window,
        created_at=to_ist(datetime.fromisoformat(insight["created_at"])),
    )


def accepted(survey: Survey) -> SimpleNamespace:
    return SimpleNamespace(
        status="accepted", survey=survey, attempts=1, reasons=[], cost_usd=0.0,
        usage=[Usage(model_id="global.openai.gpt-6-luna", input_tokens=1, output_tokens=1, latency_ms=1.0)],
    )


def decide_deps(ledger: InMemoryLedger, clock, *, generate_fn=None) -> DecideDeps:
    """run_decision deps with the pure steps faked to return scenario 3, and a real ledger."""
    _insight, survey, handoff = sc3_parts()
    return DecideDeps(
        ledger=ledger, clock=clock, generator=object(), judge=object(),
        rules=fixtures.load_rules(), calendar=fixtures.load_crop_calendar(), languages=["en-IN"],
        decide_fn=lambda ins, clk, cal, rules: r8_decision(ins),
        window_fn=lambda ins, profile, clk, rules: survey.send_window,
        handoff_fn=lambda *a, **k: handoff,
        no_survey_fn=lambda d: (None, d),
        generate_fn=generate_fn or (lambda *a, **k: accepted(survey)),
    )
