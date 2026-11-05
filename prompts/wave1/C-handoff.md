Model: Sonnet. Branch: w1-C.
Goal: build the schedule_handoff and the no_survey/decision records.
Read first: CLAUDE.md, CONTRACTS.md, mel/models.py, pack/json/rules/rules.json, pack/json/scenarios/*/schedule_handoff.json, pack/json/schemas/schedule_handoff.schema.json, pack/json/schemas/no_survey.schema.json.
You own: mel/handoff.py, tests/test_handoff_scenarios.py, tests/test_handoff_rules.py, NOTES-C.md.
Deliver: build_handoff(survey, insight, decision, clock, rules) -> ScheduleHandoff and
build_no_survey(decision) -> (NoSurvey | None, DecisionRecord). Priority: high if escalate_to_expert or
severity high/critical or behavioral_intent emergency; low if plan_created or do_not_act; else normal;
high wins. Channel order: preferred_channel, then channel_by_method[method] if different, then whatsapp,
then voice only if high; wait_hours by priority on every step except the last (null). Cap key
mel:farmer:{farmer_id}, max 1, 7 days, exempt = priority high. expires_at = window end + 2 days.
flow_key = "mel_" + survey_id lowercased with "-" replaced by "_" (matches mel_s_21310). campaign and
flow ids from rules.json. NoSurvey only for R3 (generic_information) and R4 (needs_more_context); for the
other no-survey rules return None plus the DecisionRecord, and put the golden reason_code in the record.
tests/test_handoff_scenarios.py: all 6 scenario handoffs reproduced field by field (ignore handoff_id).
Done when: tests pass and every output validates against the pack schema. Report: diffs vs scenarios.
