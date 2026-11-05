"""The decision engine reproduces the golden set (150 rows; at least 149 must match)."""

from __future__ import annotations

from collections import Counter

from mel.rules import decide

RULES = [f"R{i}" for i in range(1, 9)]


def test_golden_matches(golden, crop_calendar, rules, clock):
    confusion: Counter[tuple[str, str]] = Counter()
    misses = []
    for row in golden:
        exp = row["expected"]
        d = decide(row["insight"], clock, crop_calendar, rules)
        confusion[(exp["rule"], d.rule_id)] += 1
        got = (d.survey, d.reason_code, d.rule_id)
        want = (exp["survey"], exp.get("reason_code"), exp["rule"])
        if got != want:
            misses.append((row["golden_id"], want, got))

    print("\nconfusion (rows = expected rule, cols = got rule)")
    print("exp\\got " + " ".join(f"{r:>3}" for r in RULES))
    for e in RULES:
        print(f"{e:>7} " + " ".join(f"{confusion[(e, g)]:>3}" for g in RULES))
    matched = len(golden) - len(misses)
    print(f"matched {matched}/{len(golden)}")
    for gid, want, got in misses:
        print(f"MISS {gid}: expected {want}, got {got}")

    assert len(golden) == 150
    assert matched >= 149, f"{matched}/150; misses: " + "; ".join(
        f"{gid} expected {want} got {got}" for gid, want, got in misses
    )


def test_golden_records_are_consistent(golden, crop_calendar, rules, clock):
    """Every record is a valid DecisionRecord and carries the row's ids."""
    for row in golden:
        d = decide(row["insight"], clock, crop_calendar, rules)
        assert d.insight_id == row["insight_id"]
        assert d.farmer_id == row["insight"]["farmer_id"]
        assert d.created_at == clock.now()
        assert d.timing_profile == "golden_v1"
