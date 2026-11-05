# NOTES-D: outcome state machine

## Delivered
- `mel/outcomes.py`: `apply_event(survey, attempt, event, clock, codes) -> ResponseRecord`.
  Also `update_timestamps(...)` for `delivered` and `opened`, `NonTerminalEvent`, `InvalidAnswer`.
- `tests/test_outcomes_unit.py`: all pass. Every produced record is checked with `validate_against_pack(..., "response")`.
- `tests/test_outcomes_fixtures.py` (D2): 183 of 183 pass, after the one-line `sheet_outcome` pass-through in `tests/outcome_events.py` (approved by Dwayne).
- `make test`: 555 passed. `make lint`: clean.

## Fixture contradictions (resolved)
- The 6 `sheet_interrupted` fixtures (`{app,web}/*/sheet_interrupted.json`, field `sheet_outcome`) failed because D2's event had no way to say
  `interrupted`. `tests/outcome_events.py` now adds `sheet_outcome` for partial records. `apply_event` reads it (`closed_partway` or `interrupted`).
- Not asserted by D2 and not reproduced from D2 events: `items[].raw_input`, `items[].input_kind` (130 items) and `raw_event` on
  `sheet_closed_partway` / `sheet_interrupted` (16 files). D2 events hold one `raw` for the whole event. `apply_event` fills
  per-item values from optional `event["inputs"] = {item_id: {raw, input_kind, attempts}}` and `raw_event` from `event["raw_event"]`.
  With those keys supplied, every other field of all 183 fixtures matches (checked locally, not committed).

## Event contract: what I added to the D prompt
- Optional event keys: `timestamps`, `inputs`, `raw_event`, `sheet_outcome`, `farmerchat_reply`.
- Optional attempt keys (dict form): `sent_at`, `timestamps`, `superseded`. `already_answered` in D2 attempts is ignored. `Attempt` has none of these; `created_at` stands in for `sent`.
- Duplicates are never decided here (Dwayne, decision 4). The ledger does: `put_response` returns DUPLICATE. The caller passes
  `failure_code: "duplicate_answer"` and `apply_event` builds the record shape (all values discarded, status `duplicate`).
  Without that code, applying the same event twice gives the same plain record. There is no `existing` argument.
- `delivered` and `opened` raise `NonTerminalEvent`. They end nothing. Use `update_timestamps`.
- Answer-arrival codes (`duplicate_answer`, `survey_closed`, `survey_replaced`, `identity_mismatch`) arrive as `kind: "answer"`. Priority:
  identity_mismatch, duplicate_answer (caller-supplied), survey_replaced, survey_closed. Late and replaced are only judged for `kind: "answer"`.
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
- `CONTRACTS.md` does not list the optional event keys (`sheet_outcome`, `timestamps`, `inputs`, `raw_event`). Integration should pass them from the channel layer.
- J (draft PR #13, not read here) passes `sheet_outcome` in the event, which `apply_event` reads. J can build duplicates from `put_response` returning DUPLICATE and call `apply_event` with `failure_code: "duplicate_answer"`, or build the record itself.
- Python: `.venv` was missing in this container. I made it with python3.12 (not committed, it is gitignored).
