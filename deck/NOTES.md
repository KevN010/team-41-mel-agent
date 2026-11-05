# Pitch deck notes

The deck is `deck/index.html`. Open it from file://. It needs no network.

## Keys

- Right arrow, Down arrow, Space, Enter or a click: go to the next step or slide.
- Left arrow, Up arrow or a click on the left 15% of the screen: go back.
- P: show or hide the presenter notes.
- L on slide 4: switch between live and replay.
- 1 to 6 on slide 4: tick a demo step.
- Hash routes #1 to #5 open a slide directly.
- The timer starts on the first key press or click. It turns amber at 5:00.

## Speaker script (6 minutes)

The same text is embedded in the deck. Press P to show it.

### Slide 1. Situation and task. 0:00 to 0:50

- Digital Green's FarmerChat gives advice to farmers in Bihar.
- After the advice, FarmerChat does not learn what happened.
- Note the limit first. There is no real delivery, and all data is synthetic.
- Our task has 5 parts. The agent decides which conversations get a follow-up survey.
- It writes 1 to 3 tap questions in the farmer's language.
- It schedules the survey in a send window. It records the answers.
- It routes bad outcomes back for help.
- The pack has 300 farmers, 6,999 insights, 150 golden cases and 183 outcome records.
- 3 constraints shape every choice: cost, security and simplicity.

### Slide 2. Action: architecture. 0:50 to 2:00

Press the right arrow for each service.

- This is the deployed system in AWS us-west-2.
- Green arrows show the request path. Blue arrows show the data path.
- Cognito signs in the farmer and issues a JWT.
- API Gateway checks the JWT and sends the request to the Lambda function.
- AgentCore Runtime runs the same agent code as a container.
- Bedrock runs gpt-6-luna through a cross-region inference profile.
- The Jev key stays in Secrets Manager. Jev is outside AWS.
- DynamoDB holds the ledger in one table.
- SQS holds the follow-up queue. A dead-letter queue keeps failed messages.
- S3 holds the simulator page and the artifacts.
- CloudFront is pending. Do not talk about it until infra/INFRA.md confirms it.
- CloudWatch shows the dashboard and alarms. AWS Budgets sets a monthly budget.

### Slide 3. Action: application flow. 2:00 to 3:10

Press the right arrow for each step.

- Follow one insight through the agent.
- Code checks the insight against the pack schema.
- 8 rules decide survey or no survey. The first match wins. The rules make no model call.
- The timing profile sets the send window. The handoff builds the schedule record.
- Bedrock writes the survey. This is the first model call.
- Code validates the survey against the schema and the invariants.
- Jev answers 5 typed questions about the survey. This is the second model call.
- If Jev fails, the survey waits for review.
- The ledger stores the survey. A virtual clock moves time to the send window.
- The renderer builds the channel view. The simulator records the answer.
- Code maps the answer to an outcome code. A bad outcome goes to the follow-up queue.

### Slide 4. Action shown live. 3:10 to 5:10

- If the live system fails, press L to show the replay.
- Follow the 6 steps in DEMO.md. Tick each step on the slide when you finish it.
- The replay uses recorded pack records.
- First, the potato survey in Hindi. The farmer gets 3 questions.
- Next, the bottom sheet in the app. It shows one question for each step.
- The farmer taps Spreading. The status becomes negative_outcome.
- The agent creates a follow-up item with the reason crop_or_animal_damaged.
- Next, an insight with no survey. The zero tillage insight gives only information, so rule R3 applies.
- Next, the push address fails. The agent falls back to the next channel.
- Next, the farmer closes the sheet early. The status is partial.
- Next, a second copy of an answer arrives. The ledger keeps the first answer.
- Last, the farmer opts out. The agent stops all future surveys to this farmer.

### Slide 5. Result. 5:10 to 6:00

- Do not read a pending chip as a number. Say that the number is pending.
- The rules match 150 of 150 golden decisions with 0 model calls.
- Generation costs $0.000210 for each accepted survey in the eval. The list price is not verified.
- Cost stays low because decisions are code. The eval chose the model.
- Security comes from JWT identity, least-privilege IAM, secrets off clients and the Jev hold.
- Simplicity comes from one package, one table, one static page and one deploy script.
- Every piece of advice gets a measured outcome. Farmers with bad outcomes get help.

## Every number and its source

| Slide | Number | Meaning | Source file |
|---|---|---|---|
| 1 | 300 | farmers | pack/README.txt |
| 1 | 6,999 | insights | pack/README.txt |
| 1 | 150 | golden cases | pack/README.txt |
| 1 | 183 | outcome records | pack/README.txt |
| 1, 3 | 1 to 3 | tap questions in a survey | pack/README.txt; models/results/model_select.md |
| 2 | 13 | services drawn | infra/README.md (6 stacks), CLAUDE.md (Bedrock, Jev) |
| 2 | rate 1, burst 10 | API Gateway stage throttle | CLAUDE.md |
| 2, 3, 5 | 5 | Jev checks | mel/settings.py (JEV_THRESHOLD_* x5); CONTRACTS.md (`JEV_THRESHOLD_<CHECK>` x5) |
| 3 | 13 | flow steps | the task brief for this deck |
| 3 | 8, R1 to R8 | decision rules and reason codes | CONTRACTS.md, Rules table |
| 3 | 2 | model calls (generation, Jev) | CLAUDE.md, Fixed decisions |
| 3 | 11 | code-only steps (13 minus 2) | derived from the two rows above |
| 3 | 600 | max output tokens | CLAUDE.md; models/models.yaml `max_tokens` |
| 3 | 1 to 3, 2 to 10, 20, 10 | survey invariants | models/results/model_select.md |
| 3 | I-005330, 3 days | example insight | pack/json/scenarios/3-potato-blight-wait/insight.json |
| 4 | 6 | demo steps | the task brief (DEMO.md is missing) |
| 4 | 9 | replay frames | this deck |
| 4 | S-21310, F-000245, q3 = 2 | potato survey and answer | pack/json/scenarios/3-potato-blight-wait/responses/whatsapp.json |
| 4 | 3 in 3 steps, 5 seconds | bottom sheet steps and typing wait | pack/json/scenarios/3-potato-blight-wait/render/hi-IN/app.json |
| 4 | I-004101, R3 | no-survey insight and rule | pack/json/scenarios/6-zero-tillage-info-no-survey/; proposals/CONFLICTS.md section 2 |
| 4 | S-20931, HTTP 200 | failure records | pack/json/outcomes/app/survey-single-select/*.json |
| 5 | 150 / 150 | golden decisions that match (wave 0 rule check) | CONTRACTS.md, Rules heading |
| 5 | 183 | outcome fixture total | pack/README.txt |
| 5 | $0.000210 | cost per accepted survey, generation only, eval | models/results/model_select.md; models/models.yaml |
| 5 | 15 of 15 | eval pass count for gpt-6-luna | models/results/model_select.md |
| 5 | 1146 ms | model call p50 in the eval | models/results/model_select.md |
| footer | 6:00, 5:00 | talk length and amber point | the task brief |

## Pending chips

Each chip is amber on the slide. A later run fills it from the named file.

1. Slide 2, CloudFront node and its 2 arrows: confirm in infra/INFRA.md. infra/README.md does not list CloudFront.
2. Slide 4, demo steps 1 to 6: text from DEMO.md.
3. Slide 4, live mode: the simulator URL from infra/INFRA.md.
4. Slide 5, tile 1: golden-set matches out of 150 from evidence/REPORT.md. The slide shows 150 / 150 from the wave 0 check in CONTRACTS.md until then.
5. Slide 5, tile 2: outcome fixtures that pass out of 183, from evidence/REPORT.md.
6. Slide 5, tile 3: cost per accepted survey from evidence/REPORT.md. The slide shows $0.000210 from the model eval until then.
7. Slide 5, tile 4: end-to-end latency p50 and p95 from evidence/REPORT.md.
8. Slide 5, cost row: prompt caching. No listed file says the build uses it.
9. Slide 5, security row: adversarial review pass count from REVIEW.md.

## Files missing on main (read on 2026-11-05, main at 8ef904e)

- infra/INFRA.md. The architecture uses infra/README.md instead.
- evidence/REPORT.md.
- DEMO.md.
- REVIEW.md.
- sim/index.html. The replay uses the pack worked examples instead.

## Disagreements with the pack and the brief

- The brief asks for a replay built from sim/index.html or evidence/. Neither exists on main. The replay uses recorded pack records from pack/json/scenarios and pack/json/outcomes.
- The brief asks for the potato scenario for every replay frame. The pack has push failure, partial, duplicate and opt-out records only for the mustard survey S-20931. Those 4 frames use S-20931 and say so.
- The pack potato records use the "spreading" answer on WhatsApp, not in the app. Frame 3 shows the WhatsApp record. Frame 2 shows the app bottom sheet with the same option tapped.
- The brief asks for "the cheapest Bedrock model chosen by eval". models/results/model_select.md has no price for claude-haiku-5-5, so "cheapest" is not proven. The slide says "the lowest priced cost".
- The gpt-6-luna price is marked unverified in models/models.yaml. The slide says so.
- The no-survey record for zero tillage uses reason_code generic_information. The golden code for R3 is nothing_to_verify (proposals/CONFLICTS.md section 1). The slide shows both.
- CONTRACTS.md says the rules match 150/150 with R7 `>=`. evidence/REPORT.md must confirm this for the deployed build.
