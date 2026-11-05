# NOTES-H (ledger)

## Disagreements and gaps
- Env var: CLAUDE.md says the table name comes from `MEL_TABLE`, but `mel.settings` reads `LEDGER_TABLE`. `DynamoLedger` uses the `table_name` argument, then `MEL_TABLE`, then `settings.LEDGER_TABLE`. Integration should align settings.
- Task text says "returns Duplicate" and "Opted out" with the protocol's `PutOutcome`. Used `PutOutcome.DUPLICATE` and `PutOutcome.OPTED_OUT`.
- Prompt lists no item for `find_survey_owner` and no survey counter. Added two org-level items (pk `ORG#<org_id>`): `SURVEYOWNER#<survey_id>` (farmer_id, strongly consistent read, written in one transaction with the survey) and `COUNTER#SURVEY` (atomic ADD). Both are still scoped by org_id.
- `put_survey` raises `SurveyIdConflict` (defined in `mel/ledger_mem.py`) if a different farmer already owns that survey_id in the org. Callers (J intake) should treat it as a server error.
- ATTEMPT ttl: the Attempt model has no expires_at, so ttl is copied from the stored SURVEY item (expires_at + 7 days). If the survey is not in the ledger, ttl = attempt.created_at + 30 days.
- `list_follow_ups` reads GSI1 (eventually consistent). Table needs GSI1 with keys `gsi1pk` (S) and `gsi1sk` (S), projection ALL. Follow-up items set `gsi1pk = ORG#<org_id>`, `gsi1sk = FOLLOWUP#<created_at>#<id>`. CDK (infra) must match; TTL attribute name is `ttl`.
- `ledger_ddb.py` imports key helpers from `ledger_mem.py` so both backends build identical keys (I may only own these two files).
- Both classes have a non-protocol test helper `item_ttl(org, farmer, sk)`.
- Real DynamoDB and moto both use the short code `ConditionalCheckFailed` in `CancellationReasons`; handled.
- `org_id` and `farmer_id` containing `#` or empty raise ValueError (stops key forging across orgs).
- Local env runs Python 3.13, not 3.12.
