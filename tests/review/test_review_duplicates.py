"""Review item 4: duplicate answer overwrites the first.

outcome_codes.json duplicate_answer: "A second answer to a survey already answered. The first
answer stands." On main at 816b4a7 a duplicate was found only when the client re-sent the same
response_key, and a key reused on another survey was a false duplicate. PR #24 applies the
duplicate rule per survey. These are now regression tests: they need PR #24 on main.
"""

from __future__ import annotations

from mel import fixtures
from mel.api.intake import submit_response
from mel.ledger_mem import InMemoryLedger
from mel.outcomes import apply_event

from ._harness import ORG, identity_for, sc3_parts


def _setup():
    _insight, survey, handoff = sc3_parts()
    ledger = InMemoryLedger()
    ledger.put_survey(ORG, survey, handoff.expires_at)
    return survey, handoff, ledger, identity_for(survey.farmer_id), fixtures.load_outcome_codes()


def _submit(me, sid, body, ledger, clock, codes):
    return submit_response(me, sid, body, ledger, clock, codes, apply_event=apply_event, queue=None)


def test_second_answer_with_new_response_key_is_duplicate(clock):
    survey, _h, ledger, me, codes = _setup()
    first = _submit(me, survey.survey_id, {"response_key": "rk-a", "channel": "app",
                                           "answers": {"q1": "yes", "q2": "no_new", "q3": 4}}, ledger, clock, codes)
    assert first.status == "completed"
    second = _submit(me, survey.survey_id, {"response_key": "rk-b", "channel": "app",
                                            "answers": {"q1": "no", "q2": "spreading", "q3": 1}}, ledger, clock, codes)
    assert second.status == "duplicate"
    assert ledger.get_response(ORG, survey.farmer_id, "rk-b") is None or \
        ledger.get_response(ORG, survey.farmer_id, "rk-b").status == "duplicate"
    assert ledger.list_follow_ups(ORG) == []  # the second (negative) answer must not raise a follow-up


def test_same_response_key_on_another_survey_is_not_a_duplicate(clock):
    survey, handoff, ledger, me, codes = _setup()
    other = survey.model_copy(update={"survey_id": "S-21311"})
    ledger.put_survey(ORG, other, handoff.expires_at)
    body = {"response_key": "rk-1", "channel": "app", "answers": {"q1": "yes", "q2": "no_new", "q3": 4}}
    assert _submit(me, survey.survey_id, body, ledger, clock, codes).status == "completed"
    assert _submit(me, other.survey_id, body, ledger, clock, codes).status == "completed"
