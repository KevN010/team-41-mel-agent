Model: Sonnet. Branch: w1-L.
Goal: one static HTML page that demos the whole flow against the API, with a virtual clock.
Read first: CLAUDE.md, CONTRACTS.md, pack/json/scenarios/3-potato-blight-wait/** and 6-zero-tillage-info-no-survey/**, pack/json/schemas/bottom_sheet.schema.json, mel/api/* if merged (routes).
You own: sim/index.html (single file, no build step, no external scripts except none), sim/README.md, NOTES-L.md.
Deliver: config box for API base URL and Cognito (user pool id, client id, username, password; token via
InitiateAuth USER_PASSWORD_AUTH using fetch to cognito-idp, never stored). Panels: 1 pick a scenario
insight (the 6 from the pack embedded as JSON) and POST /surveys/decide -> show DecisionRecord, rule id,
survey, handoff window; 2 virtual clock with buttons +1h, +1 day, jump to window start; 3 channel tabs
app/web/whatsapp/telegram/voice rendering the survey like the pack fixtures, bottom sheet opens only
after the clock is inside the window and "chat idle" toggle is on; 4 answer taps -> POST responses ->
show ResponseRecord; buttons for simulate failure (push_token_invalid, client_cannot_render),
close partway, duplicate submit, opt-out; 5 follow-ups list GET /follow-ups. A "replay mode" switch
that uses embedded recorded responses when the API is unreachable, labelled REPLAY in red.
Works at phone width. No secrets persisted.
Done when: page loads from file://, replay mode walks all 6 steps of the demo script in DEMO.md order.
Report: route list the page calls.
