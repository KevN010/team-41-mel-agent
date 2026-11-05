# Six-minute demo script

## Summary

The demo has six steps. Steps 1 and 6 are read-aloud steps. Steps 2 to 5 use the simulator.

The step 6 numbers come from `evidence/REPORT.md` on main, from the evals run. Re-read them on the day you present, in case the report changes.

## Before you start (not timed)

- [ ] Open the simulator. LIVE: https://d3eb8n1ufruyva.cloudfront.net . REPLAY: add `?replay=1` to the URL.
- [ ] Set the server demo clock to the window start for scenario 3. The sim's Jump button moves only the sim clock, not the server clock. Run `.venv/bin/python scripts/e2e_run.py --set-clock <ISO>` for org `org.farmerchat`. Use the `not_before` value in `pack/json/scenarios/3-potato-blight-wait/survey.en-IN.json`. This command is on PR #23.
- [ ] Sign in with seeded farmer A. The password is in the local seed file only. Keep it off the screen.
- [ ] Open CloudWatch dashboard `mel-agent` in `us-west-2`.
- [ ] Open `evidence/REPORT.md`. It is on main.
- [ ] Run the whole script once. Present from the second run, with a fresh farmer B for step 5 and a new farmer A if you need one.

## The six steps

Each step has a time, the click or command, and the sentence to say.
If the API is down, switch to REPLAY and say "REPLAY" aloud before step 2.

1. **0:00 to 0:45. The outcome.** Click: read the "The outcome" card, then tap Mark done. Say: "After advice, we ask one to three short questions, measure what happened, and reconnect farmers who need help."

2. **0:45 to 1:30. Potato insight to survey.** Click: in panel 1, choose scenario 3 (potato), then tap Decide. Say: "The farmer spoke Hindi. The survey is in English, because Hindi is not built yet. Rule R8 says send a survey, and the window is on screen." [REPLAY if API down]

3. **1:30 to 2:45. Clock, sheet, follow-up.** Click: in panel 2, tap Jump to window start. In panel 3, open the Web tab, tap Yes, then Spreading, then 1. Check panel 5 for the new follow-up item. Say: "The farmer says the spots are spreading and rates the advice 1. The system opens a follow-up item for a person to act on." [REPLAY if API down. Farmer A, same as step 2. Server clock must be set first, see Before you start.]

4. **2:45 to 3:15. Zero-tillage insight: no survey.** Click: in panel 1, choose scenario 6 (zero tillage), then tap Decide. Say: "This is a general question. No advice was given, so there is nothing to check. Rule R3 means no survey." [REPLAY if API down] Presenter note, do not say aloud: rule R3 gives the internal reason `nothing_to_verify` in `mel/rules.yaml`. The no-survey record shows `generic_information`, per CONTRACTS.md.

5. **3:15 to 5:15. Failures.** Click: sign in as farmer B. Set the server clock to scenario 1's window start (its `not_before` in `pack/json/scenarios/1-mustard-aphid-spray/survey.en-IN.json`). Choose scenario 1 (mustard), tap Decide, tap Jump to window start. In the App tab, tap Fail push_token_invalid. On the next channel, answer one question, then tap Close partway. Tap Duplicate submit. Tap Opt out. Tap Decide again. Say: "A bad app token sends the survey to the next channel. If the farmer stops early, the outcome is partial. A duplicate answer is rejected. After opt-out, Decide returns opted out, so no survey is sent." [REPLAY if API down. Farmer B, because farmer A is capped by step 3 and opted out here would block the next run.]

6. **5:15 to 6:00. Evidence.** Click: open `evidence/REPORT.md`, then the CloudWatch dashboard `mel-agent`. Tap Mark done. Say: "All 150 golden rows match the rules. All 95 golden send windows match the default timing. All 183 outcome fixtures pass. Each model call takes 2,577 milliseconds at the median and 4,105 milliseconds at the 95th percentile. Cost per accepted survey is $0.000818, with failed calls counted. Prices are unverified, so that cost is an estimate. The model table and the security controls are in the same report."

## Total time

Steps 1 to 6 take 6:00 in all.

## If something breaks

- Decide returns `identity_mismatch` (403): sign out, sign in again, retry.
- Decide returns `frequency_capped` or `opted_out` for farmer A or B: use a different seeded farmer. The cap is 1 survey per farmer per 7 days, and an opt-out is not undone by the demo.
- Decide shows a window in the past, or no window, LIVE: the server clock was not set. Run the `--set-clock` command again.
- A LIVE call fails: switch to REPLAY (`?replay=1`), say "REPLAY" aloud, and continue.

## Known gaps

- The sim walkthrough card says to use scenario 3 for step 5. Do not. Scenario 3 starts on the web channel, so the app failure is never reached first. Scenario 1 starts on the app channel. This script uses scenario 1.
- The routes for follow-ups (`GET /follow-ups`) and for failures and opt-outs (`POST /surveys/{id}/responses` with `kind`) are on PR #23, not on main. The sim uses them.
- PR #23 says the Lambda path with a sign-in is not traced end to end yet. The trace runs through the AgentCore Runtime. Treat LIVE steps 2 to 5 as untested through the sign-in path until the integration thread confirms.
- The server clock is separate from the sim clock. See Before you start.
- Frequency cap and opt-out persist per farmer. Use a fresh farmer when you rerun.
- PR #23 notes that pack hand-offs embed the hi-IN survey. The sim shows the en-IN survey. Check on the day which one the sim shows.
- Hindi is not built. Only the English survey is shown.
- Real delivery to any channel is out of scope. Nothing is sent to a farmer.
