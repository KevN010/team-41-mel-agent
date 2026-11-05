"""Review item 5: opt-out raced by a concurrent attempt.

run_decision checks ledger.is_opted_out (step 3), then spends seconds in generation and Jev,
then writes the survey and hand-off with plain puts (step 5). An opt-out that lands during
generation was not seen on main at 816b4a7. PR #23 re-checks the opt-out right before the writes.
This is now a regression test: it needs PR #23 on main.
"""

from __future__ import annotations

from mel.api.decide import run_decision
from mel.ledger_mem import InMemoryLedger

from ._harness import ORG, accepted, decide_deps, identity_for, sc3_parts


def test_opt_out_during_generation_blocks_the_handoff(clock):
    insight, survey, handoff = sc3_parts()
    ledger = InMemoryLedger()

    def generate_while_farmer_opts_out(*args, **kwargs):
        ledger.set_opt_out(ORG, survey.farmer_id, clock.now())  # concurrent POST /farmers/me/opt-out
        return accepted(survey)

    res = run_decision(identity_for(survey.farmer_id), insight,
                       decide_deps(ledger, clock, generate_fn=generate_while_farmer_opts_out))
    stored = ledger.item_ttl(ORG, survey.farmer_id, f"HANDOFF#{handoff.handoff_id}")
    assert res.status != "survey_scheduled" and stored is None
