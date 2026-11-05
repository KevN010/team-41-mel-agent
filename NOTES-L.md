# NOTES-L (simulator)

Written for the integration agent. Nothing here changes a file I do not own.

## Alignment with J (PR #13, `mel/api/intake.py`, `mel/api/decide.py`)
Done in the page:
- Answer body is limited to `ResponsePayload` keys: `response_key, channel, answers, sheet_outcome, delivery_attempt, input_kind`.
  `language` and `flow_key` are not sent (both are optional and checked against the survey).
- `sheet_outcome` is sent for app and web only.
- Decide body is the insight JSON. `farmer_id` is replaced with the token's `custom:farmer_id`, because `run_decision` returns 403 `identity_mismatch`
  when the insight farmer is not the JWT farmer. The pack insights carry other farmer ids.
- Error body `{"error": "<code>"}` is read. Duplicate is HTTP 200 with a `duplicate` record, stored answers HTTP 201.
- Decide response: `DecisionResult` fields `status, decision, no_survey, survey, handoff, reasons` are read. `status: opted_out` shows the red SUPPRESSED box.
  `timing_exception`, `failed_review` and `pending_review` show "Not sent".
- Follow-up items use J's `FollowUpItem` fields.

Gaps (integration must add, or the demo steps below cannot run LIVE):
1. **No route for non-answer events.** Intake only handles `kind: answer`. Demo step 5 needs push_token_invalid, client_cannot_render, opt-out,
   and Decline. The page posts them to `POST /surveys/{survey_id}/events` with `kind` (`failure`, `decline`, `opt_out`), `failure_code`, `sheet_outcome`.
   That route is my guess. It must call `apply_event` for the failure kinds, and `ledger.set_opt_out` for `opt_out`. Returned record: same as intake.
   The page shows a clear message if the route answers 404 without an `error` code.
2. **Closing the sheet with no answer** (`sheet_dismissed`) goes through the same events route. Intake rejects an empty body without `sheet_outcome`.
3. **No `decide` or `follow-ups` route exists yet** (only functions). The page assumes `POST /surveys/decide` and `GET /follow-ups`
   returning an array, `{items: []}` or `{follow_ups: []}`. Editable in the page.
4. **Fallback after delivery failure** needs the record's `retry_decision == fall_back_to_next_channel`. The page then moves to the next channel in the
   hand-off and uses `delivery_attempt + 1` in the next `response_key`. J stores partial and complete as two records with two keys, same as the page.
5. Opt-out suppression: `run_decision` returns status `opted_out` only after rules and timing pass, so Decide on a no-survey insight still returns `no_survey`.

## Clock (needs a decision)
The virtual clock is only in the page. `ResponsePayload` has no time field, so the page cannot send it (an `at` key would be a 400).
The pack scenarios have windows in Dec 2026 and Jan 2027. A server with a real clock does not see those windows as open, and `SystemClock` stamps the records.
For the live demo the server needs its own demo clock (for example a `FakeClock` set by the deploy for the demo stack). Do not trust a client header on a production path.
Not built here.

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
- LIVE path tested against a local mock server that rejects extra body keys like `ResponsePayload` and returns J's `{"error": code}` and decide `status` values. Covered: decide, answer, events-route-missing message, opted_out suppression, network failure banner. Cognito sign-in was not tested: no pool available.
