"""Review item 5: opt-out raced by a concurrent attempt.

run_decision checks ledger.is_opted_out (step 3), then spends seconds in generation and Jev,
then writes the survey and hand-off with plain puts (step 5). An opt-out that lands during
generation is not seen: the hand-off is stored and the survey goes to FarmerChat anyway.
ledger.put_attempt has the right guarded write (ConditionCheck on OPTOUT), but nothing calls it.
"""

from __future__ import annotations

import pytest

from mel.api.decide import run_decision
from mel.ledger_mem import InMemoryLedger

from ._harness import ORG, accepted, decide_deps, identity_for, sc3_parts


@pytest.mark.xfail(strict=True, reason="REVIEW item 5: survey/hand-off writes are not conditional on OPTOUT")
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
