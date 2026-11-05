Model: Haiku. Branch: wave2-evals.
Goal: the numbers for the last demo slide and the evidence bundle.
Read first: CLAUDE.md, tests/test_rules_golden.py output, tests/test_outcomes_fixtures.py output, models/results/*, evidence/*.md, infra outputs.
You own: evals/survey_eval.py, scripts/evidence_bundle.py, evidence/REPORT.md.
Deliver: evals/survey_eval.py runs rules on all 150 golden (per-rule table, misses), timing golden_v1 match
count, outcome fixtures pass count and contradiction list, and, if AWS creds present, generation on the
5 actionable scenarios with the chosen model: schema pass rate, Jev verdicts, p50 and p95 latency,
tokens, cost per accepted survey, total spend of the run. evidence/REPORT.md: those tables, the model
selection table, the AWS resource inventory (cdk outputs plus `aws resourcegroupstaggingapi` filtered by
the MelAgent tag), the security controls list with the test that proves each. scripts/evidence_bundle.py
zips evidence/, models/results/, REVIEW.md, KNOWN-ISSUES.md, proposals/ and uploads to the artifacts bucket.
Never include keys, .env, or farmer rows beyond the 6 scenarios.
Done when: evidence/REPORT.md has no placeholder numbers. Report: the cost per accepted survey line.
