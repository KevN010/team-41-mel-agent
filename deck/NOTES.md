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
- The Lambda function validates the payload, because an HTTP API has no request validator.
- AgentCore Runtime runs the same agent code as a container.
- Bedrock runs gpt-6-luna through a cross-region inference profile.
- The Jev key stays in Secrets Manager. Jev is outside AWS.
- DynamoDB holds the ledger in one table.
- SQS holds the follow-up queue. A dead-letter queue keeps failed messages.
- S3 holds the simulator page and the artifacts.
- CloudFront serves the simulator page from the private S3 bucket.
- CloudWatch shows the dashboard. 2 alarms watch the DLQ and the model call rate.

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
- The live simulator is at d3eb8n1ufruyva.cloudfront.net.
- The replay uses recorded pack records.
- First, the potato survey in English. Hindi is not built yet. The farmer gets 3 questions.
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
- 183 of 183 outcome fixtures pass.
- Each accepted survey costs $0.000818, with failed calls counted. The prices are not verified.
- Each model call takes 2,577 ms at p50 and 4,105 ms at p95.
- Cost stays low because decisions are code. The eval chose the model.
- Security comes from JWT identity, explicit IAM actions, secrets off clients and the Jev hold.
- Simplicity comes from one package, one table, one static page and one deploy script.
- Every piece of advice gets a measured outcome. Farmers with bad outcomes get help.


## Every number and its source

Sources read on 2026-11-05: main at 5e0b278, evidence/REPORT.md from PR #25, REVIEW.md from PR #21, DEMO.md from PR #20, KNOWN-ISSUES.md from PR #24, infra/INFRA.md on main.

| Slide | Number | Meaning | Source file |
|---|---|---|---|
| 1 | 300 | farmers | pack/README.txt |
| 1 | 6,999 | insights | pack/README.txt |
| 1 | 150 | golden cases | pack/README.txt |
| 1 | 183 | outcome records | pack/README.txt |
| 1, 3 | 1 to 3 | tap questions in a survey | pack/README.txt; models/results/model_select.md |
| 2 | 12 | services drawn (11 AWS, plus Jev) | infra/INFRA.md resource inventory; CLAUDE.md (Jev) |
| 2 | rate 1, burst 10 | API Gateway stage throttle | CLAUDE.md; evidence/REPORT.md section 7 |
| 2 | 2 | CloudWatch alarms | evidence/REPORT.md section 6 (mel-followup-dlq-nonempty, mel-model-calls-over-60) |
| 2, 3, 5 | 5 | Jev checks | mel/settings.py (JEV_THRESHOLD_* x5); CONTRACTS.md |
| 3 | 13 | flow steps | the task brief for this deck |
| 3 | 8, R1 to R8 | decision rules and reason codes | CONTRACTS.md, Rules table |
| 3 | 2 | model calls (generation, Jev) | CLAUDE.md, Fixed decisions |
| 3 | 11 | code-only steps (13 minus 2) | derived from the two rows above |
| 3 | 600 | max_tokens in config | models/models.yaml |
| 3 | 900 | max_tokens used in the eval run | evidence/REPORT.md section 4 |
| 3 | 95 of 95 | golden send windows that golden_v1 matches | evidence/REPORT.md section 2 |
| 3 | 1 to 3, 2 to 10, 20, 10 | survey invariants | models/results/model_select.md |
| 3 | I-005330, 3 days | example insight | pack/json/scenarios/3-potato-blight-wait/insight.json |
| 4 | 6 | demo steps and their names | DEMO.md (PR #20) |
| 4 | d3eb8n1ufruyva.cloudfront.net | simulator URL | infra/INFRA.md, Endpoints |
| 4 | 9 | replay frames | this deck |
| 4 | S-21310, F-000245, q3 = 2 | potato survey and answer | pack/json/scenarios/3-potato-blight-wait/responses/whatsapp.json |
| 4 | 2 of 3, 5 seconds | bottom sheet step and typing wait | pack/json/scenarios/3-potato-blight-wait/render/en-IN/app.json |
| 4 | I-004101, R3 | no-survey insight and rule | pack/json/scenarios/6-zero-tillage-info-no-survey/; proposals/CONFLICTS.md section 2 |
| 4 | S-20931, HTTP 200 | failure records | pack/json/outcomes/app/survey-single-select/*.json |
| 5 | 150 / 150 | golden decisions that match | evidence/REPORT.md section 1 |
| 5 | 183 / 183 | outcome fixtures that pass | evidence/REPORT.md section 3 |
| 5 | $0.000818 | cost per accepted survey, failed calls counted | evidence/REPORT.md section 4 |
| 5 | $0.000568 | cost per accepted survey, successful calls only | evidence/REPORT.md section 4 |
| 5 | 5 of 5 | surveys accepted (schema valid and Jev ok) | evidence/REPORT.md section 4 |
| 5 | 2,577 ms, 4,105 ms | latency p50 and p95 per model call | evidence/REPORT.md section 4 |
| 5 | 7 | model calls in the eval run | evidence/REPORT.md section 4 |
| 5 | 15, 12 | review items, and items closed with PR #23 | REVIEW.md (PR #21) |
| footer | 6:00, 5:00 | talk length and amber point | the task brief |

## Pending chips

None. Dwayne removed the prompt caching claim on 2026-11-05, because it was not measured.

## Disagreements with the pack, the brief and the sources

- The brief asks to draw AWS Budgets. infra/INFRA.md says BUDGET_EMAIL was unset and the budget was skipped. The deck does not draw it.
- The brief asks for "least-privilege IAM, one role per component". KNOWN-ISSUES.md says Lambda and AgentCore share one role (review item 10). The slide says "IAM policies list explicit actions" instead.
- The brief asks for end-to-end p50 and p95 latency. evidence/REPORT.md gives latency per model call only. The tile says "for each model call".
- The brief asks for cost per accepted survey. evidence/REPORT.md gives 2 values. The tile shows $0.000818 (failed calls counted) and names $0.000568. Prices are unverified in both.
- The cost row uses Dwayne's text: "cheapest Bedrock model chosen by eval: gpt-6-luna, 5 of 5 accepted". models/results/model_select.md has no price for claude-haiku-5-5, so "cheapest" is not proven against that model. Prices are unverified.
- CLAUDE.md and models/models.yaml set max_tokens 600. The eval run used 900 (evidence/REPORT.md section 4). Slide 3 shows both.
- The adversarial review count is from REVIEW.md: 12 of 15 items are closed with PR #23. PR #23 is not merged at the time of writing. Update the slide when the integration PR for items 4, 5 and 10 merges.
- DEMO.md times its 6 steps as a full 6:00 talk. This deck gives the demo 2:00 (3:10 to 5:10). The presenter must choose which steps to run live.
- DEMO.md and KNOWN-ISSUES.md say Hindi is not built. The replay shows the en-IN survey and the en-IN app sheet. The pack hi-IN text is shown in grey on frame 1 only.
- The replay uses pack records, the same data that the simulator replay (sim/index.html, ?replay=1) builds from. The pack has push failure, partial, duplicate and opt-out records only for the mustard survey S-20931. Those 4 frames say so.
- The pack potato records use the "spreading" answer on WhatsApp. DEMO.md step 3 uses the Web tab. Frame 3 shows the WhatsApp record.
- The no-survey record for zero tillage uses reason_code generic_information. The golden code for R3 is nothing_to_verify (proposals/CONFLICTS.md section 1). The slide shows both.
- REVIEW.md item 4 says a duplicate is found only on the same response_key. The duplicate frame shows the pack record, not the current code behaviour.
