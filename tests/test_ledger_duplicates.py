"""Duplicate rule and opt-out-guarded hand-off (review items 4 and 5), both ledger backends."""

from __future__ import annotations

import pytest

from mel import fixtures
from mel.api.intake import submit_response
from mel.ledger_mem import FarmerOptedOut
from mel.models import PutOutcome, ResponseRecord, ScheduleHandoff, Survey
from mel.outcomes import apply_event
from tests.test_ledger import ORG, ledger  # noqa: F401 - the parametrized mem/ddb fixture


def _sc3(scenarios):
    sc = next(s for s in scenarios if s["name"].startswith("3-"))
    return Survey.model_validate(sc["survey_by_lang"]["en-IN"]), ScheduleHandoff.model_validate(sc["handoff"])


def _submit(ledger, survey, key, answers, clock, sheet_outcome=None):  # noqa: F811
    body = {"response_key": key, "channel": "app", "answers": answers}
    if sheet_outcome:
        body["sheet_outcome"] = sheet_outcome
    from mel.api.auth import Identity

    me = Identity(farmer_id=survey.farmer_id, org_id=ORG, sub="s")
    return submit_response(me, survey.survey_id, body, ledger, clock, fixtures.load_outcome_codes(),
                           apply_event=apply_event, queue=None)


FULL = {"q1": "yes", "q2": "no_new", "q3": 4}


def test_second_answer_with_new_key_is_duplicate(ledger, scenarios, clock):  # noqa: F811
    survey, handoff = _sc3(scenarios)
    ledger.put_survey(ORG, survey, handoff.expires_at)
    assert _submit(ledger, survey, "rk-a", FULL, clock).status == "completed"
    second = _submit(ledger, survey, "rk-b", {"q1": "no", "q2": "spreading", "q3": 1}, clock)
    assert second.status == "duplicate"
    assert ledger.get_response(ORG, survey.farmer_id, "rk-b") is None
    assert ledger.get_response(ORG, survey.farmer_id, "rk-a").answers == FULL  # the first answer stands
    assert ledger.list_follow_ups(ORG) == []


def test_same_key_on_another_survey_is_not_duplicate(ledger, scenarios, clock):  # noqa: F811
    survey, handoff = _sc3(scenarios)
    other = survey.model_copy(update={"survey_id": "S-21311"})
    ledger.put_survey(ORG, survey, handoff.expires_at)
    ledger.put_survey(ORG, other, handoff.expires_at)
    assert _submit(ledger, survey, "rk-1", FULL, clock).status == "completed"
    assert _submit(ledger, other, "rk-1", FULL, clock).status == "completed"


def test_partial_then_complete_is_allowed_but_not_after_complete(ledger, scenarios, clock):  # noqa: F811
    survey, handoff = _sc3(scenarios)
    ledger.put_survey(ORG, survey, handoff.expires_at)
    assert _submit(ledger, survey, "p1", {"q1": "yes"}, clock, "closed_partway").status == "partial"
    assert _submit(ledger, survey, "c1", FULL, clock).status == "completed"
    assert _submit(ledger, survey, "p2", {"q1": "no"}, clock, "closed_partway").status == "duplicate"


def test_same_key_resend_is_duplicate_and_first_kept(ledger, scenarios, clock):  # noqa: F811
    survey, handoff = _sc3(scenarios)
    ledger.put_survey(ORG, survey, handoff.expires_at)
    first = _submit(ledger, survey, "rk", FULL, clock)
    assert _submit(ledger, survey, "rk", FULL, clock).status == "duplicate"
    kept = ledger.get_response(ORG, survey.farmer_id, "rk")
    assert isinstance(kept, ResponseRecord) and kept.status == first.status


def test_failure_records_are_not_blocked_by_an_answer(ledger, scenarios, clock):  # noqa: F811
    survey, handoff = _sc3(scenarios)
    ledger.put_survey(ORG, survey, handoff.expires_at)
    _submit(ledger, survey, "rk", FULL, clock)
    from mel.models import Attempt

    att = Attempt(survey_id=survey.survey_id, farmer_id=survey.farmer_id, channel="whatsapp", delivery_attempt=2,
                  response_key="wa-2", language="en-IN", source_insight_ids=survey.source_insight_ids,
                  created_at=clock.now())
    rec = apply_event(survey, att, {"kind": "failure", "channel": "whatsapp", "failure_code": "wa_undelivered",
                                    "farmer_id": survey.farmer_id, "at": clock.now()}, clock,
                      fixtures.load_outcome_codes())
    assert ledger.put_response(ORG, rec) is PutOutcome.WRITTEN


def test_handoff_is_not_written_after_opt_out(ledger, scenarios, clock):  # noqa: F811
    survey, handoff = _sc3(scenarios)
    ledger.put_survey(ORG, survey, handoff.expires_at)
    ledger.set_opt_out(ORG, survey.farmer_id, clock.now())
    with pytest.raises(FarmerOptedOut):
        ledger.put_handoff(ORG, handoff)
    assert ledger.item_ttl(ORG, survey.farmer_id, f"HANDOFF#{handoff.handoff_id}") is None


def test_handoff_written_when_not_opted_out(ledger, scenarios):  # noqa: F811
    survey, handoff = _sc3(scenarios)
    ledger.put_handoff(ORG, handoff)
    assert ledger.item_ttl(ORG, survey.farmer_id, f"HANDOFF#{handoff.handoff_id}") is not None
