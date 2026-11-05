# CONTRACTS (frozen at wave 0)

Import these; do not redefine them. Changes go through the integration agent. Owner of every
file below: wave0. If a contract is wrong for you, write it in `NOTES-<your letter>.md` and work
around it; never edit `mel/models.py`, `mel/protocols.py` or this file.

## Modules
| Module | What it gives you |
|---|---|
| `mel.models` | Pydantic v2 records. Pack: `Insight`, `Survey` (`SurveyItem`, `Option`, `SendWindow`, `SelfEval`), `NoSurvey`, `ScheduleHandoff`, `ResponseRecord` (`ResponseItem`, `Timestamps`), `BottomSheet`. Ours: `DecisionRecord`, `Attempt`, `FollowUpItem`, `Usage`, `JudgeVerdict`, `PutOutcome`. Enums as `Literal`s (`Channel`, `RuleId`, `ReasonCode`, `FailureCode`, ...). `IST`, `to_ist()`. |
| `mel.validate` | `validate_against_pack(obj, "survey") -> (ok, errors)`. dict or model. Cross-schema `$ref` resolved. Errors may echo values: never log them. |
| `mel.protocols` | `Clock`, `Ledger`, `Generator`, `Judge`, `Renderer`; `SystemClock`, `FakeClock`. |
| `mel.settings` | `settings` (env driven): `REGION`, `LANGUAGES`, `TIMING_PROFILE`, `RATE_LIMIT_RPM`, `MODELS_FILE`, `PACK_DIR`, `SEASON_END`, `MAX_TOKENS`, `JEV_URL`, `JEV_TIMEOUT_S`, `JEV_API_KEY` (SecretStr), `JEV_THRESHOLD_<CHECK>` x5, `LEDGER_TABLE`, `FOLLOW_UP_QUEUE_URL`, `METRICS_NAMESPACE`, `METRICS_OFF`. |
| `mel.fixtures` | `load_insights()`, `load_golden()`, `load_crop_calendar() -> {crop: last end_date}`, `load_scenarios()`, `load_outcomes() -> [(path, record)]`, `load_rules()`, `load_outcome_codes()`, `scenario_surveys_by_id()`. Raw dicts. |
| `tests/conftest.py` | fixtures `clock` (FakeClock 2026-11-05T09:00+05:30), `insights`, `golden`, `crop_calendar`, `scenarios`, `outcomes`, `rules`, `outcome_codes`. Sockets blocked. |

Serialisation: `model.to_pack()` gives the pack's exact JSON. Unset optional fields are left out;
required-nullable fields are written as `null`. Timestamps are aware datetimes in +05:30; naive is
rejected; other offsets are converted; `IstTime` drops microseconds.

## Protocols (`mel/protocols.py`)
```
Clock.now() -> datetime(+05:30)            Clock.advance(td)
Ledger  (org_id first on every method; scoped by org_id + farmer_id)
  next_survey_seq(org) -> int               put_survey(org, survey, expires_at)
  get_survey(org, farmer, survey_id) -> Survey|None
  find_survey_owner(org, survey_id) -> farmer_id|None   # identity_mismatch only, no content
  put_handoff(org, handoff)                 put_attempt(org, attempt) -> WRITTEN|OPTED_OUT
  put_response(org, record) -> WRITTEN|DUPLICATE (idempotent on response_key, first kept)
  get_response(org, farmer, response_key) -> ResponseRecord|None
  cap_count(org, farmer, window_days, now) -> int
  record_cap(org, farmer, survey_id, at) -> bool (count once)
  set_opt_out(org, farmer, at)   is_opted_out(org, farmer) -> bool
  put_follow_up(org, FollowUpItem)          list_follow_ups(org) -> [FollowUpItem]
Generator.generate(insight, language, timing_profile, model_key, *, repair_errors=None) -> (dict, Usage)
Judge.check_survey(insight, survey) -> JudgeVerdict{ok, scores: {check: float}, reason, pending_review}
Renderer.render(survey, channel, language) -> dict  # equals pack render/<lang>/<channel>.json
```

## DecisionRecord
`{insight_id, farmer_id, survey: bool, rule_id: R1..R8, reason_code, timing_profile: golden_v1|rules_v1,
send_window: SendWindow|None, created_at}`. `survey` is True exactly for R8; then `reason_code` is None.
No-survey rows carry one of the 7 golden codes below and `send_window` None. Mapping to the 2-code
`no_survey` schema (R3 -> generic_information, R4 -> needs_more_context; others emit no NoSurvey) is
done in `mel/handoff.py`.

## Rules (first match wins; checked 150/150 on golden v1 with R7 `>=`, 149/150 with `>`)
| Id | Condition | reason_code |
|---|---|---|
| R1 | quality_flag == junk OR fails insight schema | junk_insight |
| R2 | severity == critical | critical_needs_human_call |
| R3 | resolution_type == generic_information | nothing_to_verify |
| R4 | resolution_type == needs_more_context | waiting_for_details |
| R5 | verification.needed == false | no_check_needed |
| R6 | created + send_window_days[timing].lo > 2027-03-31 | window_after_season |
| R7 | asset.category == crop and created.date >= last calendar end_date[crop] | crop_already_harvested |
| R8 | otherwise | (None) survey |

## Timing profiles (`settings.TIMING_PROFILE`, default golden_v1)
golden_v1, as specified: start = created + lo days at 09:00, end = created + hi days at 19:00
(lo, hi from `rules.json send_window_days`); same_day: start = created, end = created + 4h.
That matches 82/95 golden R8 windows. Measured at wave 0, the golden set actually follows
(94/95): **same_day**: start = created + 4h; if that is after 19:00, start = next day 09:00;
end = start + 4h. **Other timings**: as above, then end = min(end, SEASON_END 19:00) (G-0145).
G-0009 (seasonal, action_window_days 16) expects day 30..45, unexplained. No R8 row has timing `none`;
for it use from_action_window (start aw+1, end aw+7, aw default 2). Owner B decides; record in NOTES-B.md.
rules_v1: `rules.json window_rules` exactly (07:00..19:00, earliest start day 1, start not before
action window end, min width 2 days, nothing after season end, impossible -> TimingException).
The pack scenario surveys use 07:00 starts (rules_v1 style), not golden 09:00.

## File ownership
| Owner | Files |
|---|---|
| wave0 | mel/__init__.py, mel/models.py, mel/protocols.py, mel/settings.py, mel/fixtures.py, mel/validate.py, tests/conftest.py, tests/test_models_roundtrip.py, CONTRACTS.md, infra/README.md |
| model-selection | scripts/day0_bedrock.py, evals/model_select.py, evals/prompt_v0.md, models/models.yaml, models/results/*, NOTES-MODEL.md |
| cdk / K | infra/** (except infra/README.md), scripts/deploy.sh, scripts/seed_users.py, NOTES-K.md |
| A rules | mel/rules.py, mel/rules.yaml, tests/test_rules_golden.py, tests/test_rules_edges.py |
| B timing | mel/timing.py, tests/test_timing_golden.py, tests/test_timing_rules.py |
| C handoff | mel/handoff.py, tests/test_handoff_scenarios.py, tests/test_handoff_rules.py |
| D outcomes | mel/outcomes.py, tests/test_outcomes_unit.py |
| D2 | tests/test_outcomes_fixtures.py, tests/outcome_events.py |
| E bedrock | mel/providers/{__init__,bedrock,ratelimit,metrics}.py, tests/test_providers.py |
| F jev | mel/judge.py, tests/test_judge.py |
| G generator | mel/generate.py, mel/prompts/survey_system.md, mel/invariants.py, tests/test_generate.py, tests/test_invariants.py |
| H ledger | mel/ledger_mem.py, mel/ledger_ddb.py, tests/test_ledger.py |
| I renderers | mel/render/{__init__,app,web,whatsapp,telegram,voice}.py, tests/test_render_golden.py |
| J intake | mel/api/{__init__,intake,decide,auth}.py, tests/test_intake.py, tests/test_auth.py |
| L simulator | sim/index.html, sim/README.md |
| Z | proposals/no_survey.v1.1.schema.json, proposals/CONFLICTS.md |
| wave2 | integration: cross-cutting; review: tests/review/**, REVIEW.md; evals: evals/survey_eval.py, scripts/evidence_bundle.py, evidence/REPORT.md; docs: README.md, DEMO.md |

Each agent also owns `NOTES-<letter>.md`. Problems with any file you do not own go there, never into the file.
