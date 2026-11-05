Model: Sonnet. Branch: w1-J.
Goal: the response intake and follow-up logic behind the API routes.
Read first: CLAUDE.md (security), CONTRACTS.md, mel/protocols.py, mel/models.py, pack/json/schemas/response.schema.json, pack/json/scenarios/3-potato-blight-wait/responses/*.json.
You own: mel/api/__init__.py, mel/api/intake.py, mel/api/decide.py, mel/api/auth.py, tests/test_intake.py, tests/test_auth.py, NOTES-J.md.
Deliver: auth.py: claims_from_event(event) -> Identity{farmer_id, org_id, sub} from the API Gateway JWT
authorizer context only; raise Unauthorized if missing. intake.py: submit_response(identity, survey_id,
payload, ledger, clock, codes) -> ResponseRecord: load survey scoped by identity.org_id; identity_mismatch
if survey.farmer_id != identity.farmer_id; reject unknown flow; validate option values and scale ints;
build event and call mel.outcomes.apply_event; persist via ledger.put_response (duplicate -> status
duplicate, first record untouched); on needs_follow_up create a follow-up item {source_insight_ids,
survey_id, reasons, accepted_answers} via ledger.put_follow_up and enqueue to SQS (boto3, stubbed in tests);
partial progress: payload may carry answered subset and sheet_outcome. decide.py: run_decision(identity,
insight_dict, deps) wiring rules -> timing -> handoff -> generate -> ledger, emitting metrics per step.
tests: wrong farmer, wrong org, unknown survey, duplicate, invalid choice, scale out of range, partial
then complete, negative outcome creates follow-up, no body field can override identity.
Done when: tests pass. Report: the list of rejection codes and HTTP statuses.
