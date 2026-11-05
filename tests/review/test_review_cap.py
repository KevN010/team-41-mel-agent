"""Review item 3: frequency cap. rules.json frequency_cap = 1 survey per farmer per 7 days.

On main at 816b4a7 no code called cap_count or record_cap, so the cap was never enforced.
PR #23 records the cap in intake and checks it in run_decision. These are now regression tests:
they need PR #23 on main.
"""

from __future__ import annotations

from mel import fixtures
from mel.api.intake import submit_response
from mel.ledger_mem import InMemoryLedger
from mel.outcomes import apply_event

from ._harness import ORG, identity_for, sc3_parts


def test_counting_outcome_is_recorded_against_the_cap(clock):
    _insight, survey, handoff = sc3_parts()
    ledger = InMemoryLedger()
    ledger.put_survey(ORG, survey, handoff.expires_at)
    me = identity_for(survey.farmer_id)

    rec = submit_response(
        me, survey.survey_id,
        {"response_key": "rk-cap-1", "channel": "app", "answers": {"q1": "yes", "q2": "no_new", "q3": 4}},
        ledger, clock, fixtures.load_outcome_codes(), apply_event=apply_event, queue=None,
    )
    assert rec.status == "completed" and rec.counts_toward_cap is True
    assert ledger.cap_count(ORG, survey.farmer_id, 7, clock.now()) == 1


def test_second_normal_priority_survey_inside_cap_window_is_not_scheduled(clock):
    from datetime import timedelta

    from mel.api.decide import run_decision

    from ._harness import decide_deps

    insight, survey, _handoff = sc3_parts()
    ledger = InMemoryLedger()
    # The farmer already had a counted survey yesterday (max_surveys 1, window_days 7, priority normal).
    assert ledger.record_cap(ORG, survey.farmer_id, "S-00001", clock.now() - timedelta(days=1))
    res = run_decision(identity_for(survey.farmer_id), insight, decide_deps(ledger, clock))
    assert res.status != "survey_scheduled"
