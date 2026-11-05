Model: Haiku. Branch: w1-Z. Runs in parallel with Wave 0.
Goal: document the pack conflicts and propose a versioned no_survey schema.
Read first: pack/json/schemas/no_survey.schema.json, pack/data/golden_set.jsonl (expected.reason_code values), pack/json/rules/rules.json farmerchat_flow.flow_key, pack/json/scenarios/*/schedule_handoff.json farmerchat_flow.
You own: proposals/no_survey.v1.1.schema.json, proposals/CONFLICTS.md.
Deliver: schema v1.1 = v1 plus reason_code enum of all 8 golden codes plus rule_id (R1..R8). CONFLICTS.md:
one section per conflict (reason vocabulary, golden windows vs rules.json, late answers, flow_key
hyphen vs underscore, impossible windows), each with: evidence (file and field), what we do in the
build, what we ask the client. Plain English, short.
Done when: v1.1 validates all 150 golden expected blocks when reshaped to {insight_id, farmer_id,
decision, reason_code, reason, rule_id}. Report: nothing beyond "done" and the validation count.
