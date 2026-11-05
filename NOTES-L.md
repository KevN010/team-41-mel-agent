# NOTES-L (simulator)

Written for the integration agent. Nothing here changes a file I do not own.

## Assumptions about the API (J and integration: please confirm or tell me the real shape)
- Routes: `POST /surveys/decide`, `POST /surveys/{survey_id}/responses`, `GET /follow-ups`. No route list existed when I built the page.
  Routes are editable in the page.
- decide request: `{"insight": {...}}`. Response is read flexibly: `decision` (or `decision_record`, or a flat DecisionRecord),
  `survey` (or `handoff.survey`), `handoff` (or `schedule_handoff`), `no_survey`.
- response request: see sim/README.md. `kind` is one of `answer`, `failure`, `decline`, `opt_out`. This matches the event kinds in tests/outcome_events.py.
  Response is read as a ResponseRecord, or `{response: ResponseRecord}`.
- follow-ups response: an array, or `{items: [...]}`, or `{follow_ups: [...]}`.
- Opt-out suppression: after an opt-out, the page expects decide to say so with `suppressed` (object or true), or `status: "suppressed"`,
  or an error with `code: "farmer_opted_out"` on HTTP 403 or 409. J decides the real shape. In REPLAY the page shows a red SUPPRESSED box.
- Token: the page sends the Cognito ID token as the Bearer value, because the claims `custom:farmer_id` and `custom:org_id` are ID token claims.

## Clock (needs a decision)
The virtual clock is only in the page. The page sends `at` (virtual time, +05:30) in each response body.
The pack scenarios have windows in Dec 2026 and Jan 2027. A server with a real clock will not see those windows as open.
For the live demo the server needs a demo clock. Do not trust a client header on a production path. Suggested: a setting (off by default)
that makes intake use `at` from the body, only for the demo stack, or a seeded FakeClock endpoint behind an admin claim. Not built here.

## Pack disagreements and choices
- `schedule_handoff.json` for scenario 3 (and the others, same pattern) embeds the hi-IN survey, while `survey.en-IN.json` is the en-IN survey.
  The page puts the en-IN survey into the hand-off it shows. Only the `language` and prompt text differ.
- The pack response fixtures say `language: hi-IN`. The page builds en-IN records. Compared without `language`.
- Replay DecisionRecords use `timing_profile: rules_v1`, because the pack windows start at 07:00. `golden_v1` would start at 09:00.
- R3 DecisionRecord reason is `nothing_to_verify` (CONTRACTS.md). The pack NoSurvey for scenario 6 says `generic_information`. The page shows both.
- A partial answer set that contains a negative answer is recorded as `negative_outcome` in REPLAY. The pack does not say. D's outcomes.py should be the reference.
- The pack bottom_sheet `opens_when` for web lists only `next_web_visit`. There is no "push tapped" on web. The page follows that.

## Checks run (scratchpad, not committed)
- Page renderers vs pack `render/en-IN/{app,web,whatsapp,telegram,voice}.json` for scenarios 1 to 5: 25 files, 0 differences
  (voice `speech` compared by key only, because the pack speech variants are hand-written per question).
- Replay ResponseRecord builder vs 5 channel files under `scenarios/3-potato-blight-wait/responses` and 15 files under `outcomes/`: 20 records, 0 differences
  (ignoring `response_key`, `language`, timestamps, `raw_event`, and voice `items`).
- Headless Chromium on `file://` at 390 px wide: REPLAY walks all 6 steps, no console errors, no network requests, no horizontal scroll.
- LIVE path tested against a local mock server (decide, response, follow-ups, network failure banner). Cognito sign-in was not tested: no pool available.
