# MEL survey simulator

One file: `sim/index.html`. No build step. No external scripts. Open it from disk (`file://`) or from S3.

## Run it

- REPLAY (no API): open `sim/index.html?replay=1`, or tick "Replay mode". The top bar turns red and says REPLAY.
- LIVE: type the API base URL and the Cognito details. Tap Sign in. The page calls
  `cognito-idp.<region>.amazonaws.com` (`InitiateAuth`, `USER_PASSWORD_AUTH`) and keeps the ID token in memory only.
  The password field is cleared on submit. Nothing is written to storage. A reload forgets the token.
- Optional URL parameters: `api`, `pool`, `client`, `user`, `replay=1`. Never put a password in a URL.

## Panels

1. Insight and decision. Six pack scenarios are embedded. Decide shows rule id, DecisionRecord, survey, hand-off window, channel order.
2. Virtual clock. +1 hour, +1 day, jump to window start, past window end, reset. The clock is IST (+05:30) and virtual.
3. Channel view: app, web, WhatsApp, Telegram, voice. The sheet and messages are drawn from the survey with the same rules as the pack
   `render/en-IN/*.json` files. Each tab has a "Render JSON" block. The bottom sheet (app, web) opens only when the clock is inside
   the send window and "Chat idle" is on. WhatsApp, Telegram and voice also need the send hours (07:00 to 19:00).
4. Answers and failures. Tap answers. Buttons: Fail push_token_invalid (app), Fail client_cannot_render (app, web), Close partway,
   Duplicate submit, Opt out. A delivery failure moves to the next channel in the hand-off. The ResponseRecord is shown as JSON.
5. Follow-ups. GET list. Refreshes after every response that needs follow-up.

The "Demo walkthrough" card at the top lists the six demo steps in order and ticks them as you go.
Steps 1 and 6 are text cards: they have no numbers, because numbers belong in `evidence/REPORT.md`.

## Routes the page calls (LIVE)

Shapes follow `mel/api/intake.py` and `mel/api/decide.py` from PR #13 (branch of thread "Wave 1 J").

| Call | Route (editable in the page) | Body |
|---|---|---|
| decide | `POST /surveys/decide` | the insight JSON itself. `farmer_id` is set to the token's `custom:farmer_id` (else the server answers 403 `identity_mismatch`) |
| answer | `POST /surveys/{survey_id}/responses` | `response_key, channel, answers, delivery_attempt`, plus `sheet_outcome` (app, web only) and `input_kind` when set |
| failure, decline, opt-out | `POST /surveys/{survey_id}/events` | `response_key, channel, delivery_attempt, kind, failure_code`, plus `sheet_outcome`. **No such route exists in J's code. See NOTES-L.md.** |
| follow-ups | `GET /follow-ups` | none. The ledger has `list_follow_ups`, but J has no route for it. |

The answer body has only the keys `ResponsePayload` allows (it forbids all others, so identity keys would be a 400).
Every call sends `Authorization: Bearer <ID token>`. The page never sends `farmer_id` or `org_id` as a body field of its own.
The page shows the `custom:farmer_id` and `custom:org_id` claims after sign-in. It decodes the token for display only.

Errors: the page shows `HTTP <status>: <error code>` from a `{"error": "<code>"}` body.
Codes from J: `invalid_request` 400, `unauthorized` 401, `identity_mismatch` 403, `unknown_survey` 404, `unknown_flow` 404, `invalid_answer` 422, `internal_error` 500.
Decide statuses the page understands: `survey_scheduled`, `no_survey`, `opted_out`, `timing_exception`, `failed_review`, `pending_review`.

## REPLAY details

REPLAY uses the embedded pack data: insight, en-IN survey and hand-off for each scenario, plus the `outcome_codes.json` table.
The page builds each ResponseRecord itself. It checked equal to 20 pack response and outcome files (see NOTES-L.md).
REPLAY records are not server records. The page says so on every record.

## Not included

- hi-IN rendering. The embedded data is en-IN only.
- Real delivery. Nothing is sent to WhatsApp, Telegram, push or phone.

## Needed on the AWS side

- The Cognito app client must allow `ALLOW_USER_PASSWORD_AUTH`.
- API Gateway CORS must allow the page origin (`null` for `file://`) and the `Authorization` and `Content-Type` headers.
