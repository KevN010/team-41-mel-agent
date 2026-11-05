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

| Call | Route (editable in the page) | Body |
|---|---|---|
| decide | `POST /surveys/decide` | `{"insight": {...}}` |
| response | `POST /surveys/{survey_id}/responses` | `response_key, channel, kind (answer, failure, decline, opt_out), failure_code, answers, raw_inputs, input_kinds, sheet_outcome, delivery_attempt, at` |
| follow-ups | `GET /follow-ups` | none |

Every call sends `Authorization: Bearer <ID token>`. The page never sends `farmer_id` or `org_id` as its own field.
The only farmer id in a body is the one inside the pack insight. The server must ignore it and use the JWT claims.
The page shows the `custom:farmer_id` and `custom:org_id` claims after sign-in. It decodes the token for display only.

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
