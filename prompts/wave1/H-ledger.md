Model: Sonnet. Branch: w1-H.
Goal: the DynamoDB ledger and its in-memory twin.
Read first: CLAUDE.md, mel/protocols.py (Ledger), mel/models.py, pack/json/rules/rules.json frequency_cap.
You own: mel/ledger_mem.py, mel/ledger_ddb.py, tests/test_ledger.py, NOTES-H.md.
Deliver: both classes implement Ledger. Single table mel-ledger, pk = ORG#<org_id>#FARMER#<farmer_id>,
sk in {SURVEY#<id>, HANDOFF#<id>, ATTEMPT#<survey_id>#<n>, RESPONSE#<response_key>, CAP#<survey_id>,
OPTOUT, FOLLOWUP#<id>}; GSI1 on org_id + sk prefix FOLLOWUP for list_follow_ups. put_response uses a
condition attribute_not_exists(sk) and returns Duplicate when it fails; record_cap uses the same
condition so a survey counts once; set_opt_out writes OPTOUT and every later put_attempt checks it in
a transact_write; ttl = expires_at + 7 days on SURVEY and ATTEMPT items. Never read without org_id.
tests: parametrized over both implementations (moto for DynamoDB): duplicate rejected and first answer
kept, count-once under two concurrent record_cap calls, opt-out blocks a later attempt, cross-org read
returns nothing, TTL attribute present.
Done when: tests pass for both backends. Report: the key design in 6 lines.
