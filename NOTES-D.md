# NOTES-D: outcome state machine

## Delivered
- `mel/outcomes.py`: `apply_event(survey, attempt, event, clock, codes, *, existing=None) -> ResponseRecord`.
  Also `update_timestamps(...)` for `delivered` and `opened`, `NonTerminalEvent`, `InvalidAnswer`.
- `tests/test_outcomes_unit.py`: 109 tests, all pass. Every produced record is checked with `validate_against_pack(..., "response")`.
- `tests/test_outcomes_fixtures.py` (D2): 177 of 183 pass. The 6 failures are listed below.

## Fixture contradictions (D2 tests against D contract)
- `pack/json/outcomes/{app,web}/{survey-confirm,survey-single-select,survey-scale}/sheet_interrupted.json`
  (6 files), field `sheet_outcome`: fixture says `interrupted`, `apply_event` returns `closed_partway`.
  The event D2 builds has no way to tell the two apart (`raw` holds the first answer, not the channel event).
  `apply_event` reads an optional `event["sheet_outcome"]` (`closed_partway` or `interrupted`).
  Fix is in D2's `tests/outcome_events.py`: add `"sheet_outcome": fixture["sheet_outcome"]` to the event when `failure_code` is null.
- Not asserted by D2 and not reproduced from D2 events: `items[].raw_input`, `items[].input_kind` (130 items) and `raw_event` on
  `sheet_closed_partway` / `sheet_interrupted` (16 files). D2 events hold one `raw` for the whole event. `apply_event` fills
  per-item values from optional `event["inputs"] = {item_id: {raw, input_kind, attempts}}` and `raw_event` from `event["raw_event"]`.
  With those keys supplied, every other field of all 183 fixtures matches (checked locally, not committed).

## Event contract: what I added to the D prompt
- Optional event keys: `timestamps`, `inputs`, `raw_event`, `sheet_outcome`, `farmerchat_reply`.
- Optional attempt keys (dict form): `sent_at`, `timestamps`, `already_answered`, `superseded`. `Attempt` has none of these; `created_at` stands in for `sent`.
- Keyword `existing`: the ledger's record for this `response_key`. A second answer when `existing.answers` is non-empty is `duplicate_answer`.
  The same event applied again (same `response_key`, `delivery_attempt`, `answered` time) returns `existing` unchanged. That is the transport retry case.
- `delivered` and `opened` raise `NonTerminalEvent`. They end nothing. Use `update_timestamps`.
- Answer-arrival codes (`duplicate_answer`, `survey_closed`, `survey_replaced`, `identity_mismatch`) arrive as `kind: "answer"`. Priority:
  identity_mismatch, duplicate_answer, survey_replaced, survey_closed. Late and duplicate are only judged for `kind: "answer"`.
  A `window_expired` event is recorded after `not_after` by design and is not stale.
- `survey_closed` is `event.at > send_window.not_after`. An answer at exactly `not_after` is accepted.
- `identity_mismatch` wins over every kind, so a STOP from the wrong farmer does not opt the surveyed farmer out.
- `recorded_at` is `clock.now()`. Event time is `at`.

## Decisions the pack does not make
- App and web: a value the sheet cannot produce (not an option, scale out of range, bool, numeric string, float) raises `InvalidAnswer`.
  No outcome code exists for it on those channels. The API layer should answer 422 `invalid_answer`.
- WhatsApp and Telegram: any bad value is `free_text_instead_of_choice`. Voice: `speech_not_understood` if `input_kind` is `speech`, else `keypad_out_of_range`.
  Accepted answers given before the bad one are kept. The first item without an accepted answer is `invalid`; later answered items stay `answered`.
- An unknown `item_id` raises `InvalidAnswer` on every channel (except in discarded events, where it is ignored).
- `opt_out` and `decline` drop any answers in the event. A refusal record carries none.
- `window_expired` with accepted answers becomes `partial` (the pack's meaning of partial).
- Other codes that cannot carry answers raise `ValueError` if answers are present.
- Discarded items keep `value` only when it is a valid option or in-range integer. Otherwise `null`. Raw input is cut to 256 characters.
- `needs_follow_up` and `follow_up_reasons` come from accepted answers whatever the status (also `invalid_input`, `voice_call_dropped`).
- `farmerchat_reply`: `accepted/201` for completed, partial, negative_outcome, and for voice `invalid_input` with answers;
  `duplicate/200` for duplicate_answer; `unknown_flow/404` for survey_replaced; otherwise null. This copies the fixtures.
- `answered_by` is null when the farmer did not interact (delivery failures, `window_expired`, `push_not_opened`, a dropped call with no answer).
- `opened` is always null on Telegram, even if the event carries one.
- An item is `skipped` (shown) on `window_expired` only when the farmer was shown the question: `opened` is set, or `delivered` on Telegram.

## Disagreements with the pack
- `farmer_opted_out` on app and web gets `sheet_outcome: "dismissed"`, as the fixtures do. The pack defines `dismissed` as closed before answering anything; an opt-out button tap fits poorly.
- `window_expired` on web where the sheet was opened gets `dismissed`. The pack gives no value for "open when the window closed". Guess.
- Chat `invalid_input` sends nothing (`farmerchat_reply` null) but voice `invalid_input` sends its answers. Both are in the fixtures; the pack gives no rule.
- `voice_call_dropped` keeps answers and counts toward the cap, but the status is `delivery_failed` and `farmerchat_reply` is null.
- `CONTRACTS.md` lists no `existing` argument and no sheet or per-item input fields in `apply_event`. Integration should pass `existing` from `Ledger.get_response`.
- Python: `.venv` was missing in this container. I made it with python3.12 (not committed, it is gitignored).
- From J (draft PR #13, not read here): J passes `sheet_outcome` in the event, which `apply_event` reads. J builds the `duplicate_answer` record itself because `Attempt` has no `already_answered` field. `apply_event` can do it instead: pass `existing=` (ledger record) or `already_answered` in the attempt dict. Integration should pick one path.
