# Six-minute demo script

## Summary

The demo has six steps. Steps 1 and 6 are read-aloud steps. Steps 2 to 5 use the simulator.

Every number in this script is a placeholder. Read the real number from `evidence/REPORT.md` on the day you present.

## Before you start (not timed)

- [ ] Open the simulator. LIVE: https://d3eb8n1ufruyva.cloudfront.net . REPLAY: add `?replay=1` to the URL.
- [ ] Sign in with a seeded farmer account. The password is in the local seed file only. Keep it off the screen.
- [ ] Open CloudWatch dashboard `mel-agent` in `us-west-2`.
- [ ] Open `evidence/REPORT.md`. It is built locally. It is not in the repository.
- [ ] Run the whole script once. Present from the second run.

## The six steps

Each step has a time, the click or command, and the sentence to say.
If the API is down, switch to REPLAY and say "REPLAY" aloud before step 2.

1. **0:00 to 0:45. The outcome.** Click: read the "The outcome" card, then tap Mark done. Say: "After advice, we ask one to three short questions, measure what happened, and reconnect farmers who need help."

2. **0:45 to 1:30. Potato insight to survey.** Click: in panel 1, choose scenario 3 (potato), then tap Decide. Say: "The farmer spoke Hindi. The survey is in English, because Hindi is not built yet. Rule R8 says send a survey, and the window is on screen." [REPLAY if API down]

3. **1:30 to 2:45. Clock, sheet, follow-up.** Click: in panel 2, tap Jump to window start. In panel 3, open the Web tab, tap Yes, then Spreading, then 1. Check panel 5 for the new follow-up item. Say: "The farmer says the spots are spreading and rates the advice 1. The system opens a follow-up item for a person to act on." [REPLAY if API down. Follow-up route is missing LIVE. See Known gaps.]

4. **2:45 to 3:15. Zero-tillage insight: no survey.** Click: in panel 1, choose scenario 6 (zero tillage), then tap Decide. Say: "This is a general question. No advice was given, so there is nothing to check. Rule R3 means no survey." [REPLAY if API down]

5. **3:15 to 5:15. Failures.** Click: choose scenario 1 (mustard), tap Decide, tap Jump to window start. In the App tab, tap Fail push_token_invalid. On the next channel, answer one question, then tap Close partway. Tap Duplicate submit. Tap Opt out. Tap Decide again. Say: "A bad app token sends the survey to the next channel. If the farmer stops early, the outcome is partial. A duplicate answer is rejected. After opt-out, Decide returns opted out, so no survey is sent." [REPLAY if API down. Failure and opt-out routes are missing LIVE. See Known gaps.]

6. **5:15 to 6:00. Evidence.** Click: open `evidence/REPORT.md`, then the CloudWatch dashboard `mel-agent`. Tap Mark done. Say: "Golden rule match is [number from evidence/REPORT.md]. Outcome fixtures passing: [number from evidence/REPORT.md]. Latency p50 and p95: [numbers from evidence/REPORT.md]. Cost per accepted survey: [number from evidence/REPORT.md]. The model table and the security controls are in the same report."

## Total time

Steps 1 to 6 take 6:00 in all.

## If something breaks

- Decide returns `identity_mismatch` (403): sign out, sign in again, retry.
- A LIVE call fails: switch to REPLAY (`?replay=1`), say "REPLAY" aloud, and continue.
- Panel 5 is empty LIVE: say "The follow-up route is not deployed yet." Show the REPLAY run.

## Known gaps

- The sim walkthrough card says to use scenario 3 for step 5. Do not. Scenario 3 starts on the web channel, so the app failure is never reached first. Scenario 1 starts on the app channel. This script uses scenario 1.
- LIVE follow-up list needs `GET /follow-ups`. No route exists in `mel/api` yet.
- LIVE failure and opt-out events need `POST /surveys/{id}/events`. No route exists in `mel/api` yet.
- Hindi is not built. Only the English survey is shown.
- Real delivery to any channel is out of scope. Nothing is sent to a farmer.
