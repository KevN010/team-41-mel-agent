Model: Opus. Fresh context: do not read NOTES or evidence, read only code and infra. Read-only.
Goal: adversarial security and correctness review. AWS judges on security.
Read: CLAUDE.md security section, mel/api/**, mel/ledger_ddb.py, mel/judge.py, mel/generate.py, mel/providers/**, infra/**, sim/index.html.
For each item, either write a failing test under tests/review/ that proves the bug or write "closed, because <reason>":
1 identity from body overrides JWT; 2 cross-org read of a survey or follow-up; 3 cap bypass by
retrying a failed delivery; 4 duplicate answer overwrites the first; 5 opt-out raced by a concurrent
attempt; 6 Jev timeout leads to an accepted survey; 7 model-supplied schema_valid trusted; 8 insight text
reaching the system prompt; 9 secret or insight text in any log call; 10 IAM role with wildcard action or
resource; 11 S3 or DynamoDB without encryption; 12 API route without authorizer or throttle; 13 rate
limiter bypass by concurrency; 14 simulator storing a password or token; 15 Converse request without
max_tokens.
Deliver: REVIEW.md with a table (item, status, file:line, test path). You own only tests/review/** and REVIEW.md.
Report: the table only.
