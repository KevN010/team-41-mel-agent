Model: Opus. Branch: wave0. Time box: 60 minutes. Everything else waits on you, so ship a usable draft at 40 minutes and refine after.

Goal: freeze the contracts every other agent imports.

Read first: CLAUDE.md, pack/README.txt, pack/json/schemas/*.json, pack/json/rules/rules.json,
pack/json/rules/outcome_codes.json, pack/json/scenarios/3-potato-blight-wait/** (all files),
one file under pack/json/outcomes/, first 3 lines of pack/data/golden_set.jsonl, reference_jev_service.py.

You own: mel/__init__.py, mel/models.py, mel/protocols.py, mel/settings.py, mel/fixtures.py,
mel/validate.py (schema validation only), tests/conftest.py, tests/test_models_roundtrip.py,
CONTRACTS.md, infra/README.md (one paragraph: stacks and their names, nothing else).

Deliver:
1. mel/models.py: Pydantic v2 models for Insight, Survey (+SurveyItem, Option, SendWindow),
   NoSurvey, ScheduleHandoff, ResponseRecord (+ResponseItem), BottomSheet, plus our own
   DecisionRecord {insight_id, farmer_id, survey: bool, rule_id: R1..R8, reason_code, timing_profile,
   send_window|None, created_at}. Field names and enums copied exactly from the schemas.
2. mel/validate.py: validate_against_pack(obj, schema_name) using jsonschema and the pack files.
   Returns (ok, errors). Resolve the $ref between schemas (handoff and response reference survey).
3. mel/protocols.py (typing.Protocol):
   Clock.now() -> datetime (tz +05:30); Clock.advance(td)
   Ledger: put_survey, get_survey, put_handoff, put_attempt, put_response (idempotent on response_key),
     cap_count(farmer_id, window_days), record_cap(farmer_id, survey_id) count-once, set_opt_out,
     is_opted_out, put_follow_up, list_follow_ups(org_id). Every method takes org_id first.
   Generator.generate(insight, language, timing_profile, model_key) -> (survey_dict, usage)
   Judge.check_survey(insight, survey) -> JudgeVerdict{ok, scores: dict[str,float], reason}
   Renderer.render(survey, channel, language) -> dict matching pack render files
4. mel/settings.py: pydantic-settings style, env driven: REGION=us-west-2, LANGUAGES=["en-IN"],
   TIMING_PROFILE=golden_v1, RATE_LIMIT_RPM=60, MODELS_FILE=models/models.yaml, JEV_URL,
   JEV_TIMEOUT_S=2, thresholds for the five Jev checks (default 0.5), SEASON_END=2027-03-31.
5. mel/fixtures.py: load_insights(), load_golden(), load_crop_calendar() -> {crop: last end_date},
   load_scenarios() -> list of {insight, survey_by_lang, handoff, render, responses},
   load_outcomes() -> list of (path, record). Paths relative to pack/.
6. tests/conftest.py: fixtures for the loaders and an in-memory Clock. pytest-socket on.
7. tests/test_models_roundtrip.py: every scenario survey, handoff, response and all 183 outcome
   files parse into the models and re-validate against the pack schema with zero errors.
8. CONTRACTS.md: one page. The protocols, the DecisionRecord, the rule table R1..R8 below,
   the timing profiles, the file ownership table (copy from KICKOFF.md), and the NOTES-<X>.md rule.

Rule table to put in CONTRACTS.md (verified at 149/150 on golden v1; R7 with >= may give 150):
R1 quality_flag==junk OR fails insight schema -> no survey, junk_insight
R2 severity==critical -> critical_needs_human_call
R3 resolution_type==generic_information -> nothing_to_verify
R4 resolution_type==needs_more_context -> waiting_for_details
R5 verification.needed==false -> no_check_needed
R6 created + send_window_days[timing].lo > 2027-03-31 -> window_after_season
R7 asset.category==crop and created >= last calendar end_date[crop] -> crop_already_harvested
R8 otherwise -> survey
Golden windows (profile golden_v1): start = created + lo days at 09:00, end = created + hi days at 19:00,
except same_day: start = created time, end = created + 4h. Document that rules_v1 differs.

Done when: `make test` passes offline. Report: file list, test count, any schema ambiguity you resolved.
