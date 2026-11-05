Model: Sonnet. Branch: model-selection. Runs in parallel with Wave 0. Needs AWS credentials for us-west-2.

Goal: pick the cheapest model that passes the survey-writing eval, and write models/models.yaml.

Read first: CLAUDE.md (model table), models/candidates.txt, scripts/day0_bedrock.py,
pack/json/scenarios/*/insight.json and survey.en-IN.json (6 scenarios), pack/json/schemas/survey.schema.json.

You own: scripts/day0_bedrock.py (may edit), evals/model_select.py, evals/prompt_v0.md,
models/models.yaml, models/results/*, NOTES-MODEL.md.

Steps:
1. Run `make day0`. Record which profiles answer from us-west-2. If global.openai.gpt-6.1-luna
   answers, it is a candidate. Drop any profile that errors with access denied after you check
   model access in the console once.
2. Write evals/prompt_v0.md: system prompt that writes 1 to 3 tap questions about the advice in the
   insight, in en-IN, as JSON matching survey.schema.json items (item_id q1..q3, type, prompt,
   options with value+label, labels <= 20 characters, scale 1..5 with follow_up_at_or_below).
   Rules in the prompt: ask only about the advice given; never give new advice; never ask for
   personal information; mark bad outcomes with follow_up reasons from the pack.
3. evals/model_select.py: for each candidate, for each of the 5 actionable scenarios, 3 runs:
   call Converse with the prompt and the insight, request strict JSON (OpenAI: additionalModelRequestFields
   text.format strict=true; Claude: tool_use with the schema), validate against the survey schema plus
   these invariants: 1..3 items, unique item_id, 2..10 options, label <= 20 code points, scale <= 10 steps.
   Score = schema pass rate. Record input/output tokens, latency p50, and cost from the table in CLAUDE.md
   (write the price you used next to each number; mark unverified prices).
   Respect 60 rpm: sleep between calls.
4. Selection rule: among candidates with pass rate >= 0.9, take the lowest cost per accepted survey.
   Write models/models.yaml:
     generation: <profile>
     retry: <next better profile, or same>
     region: us-west-2
     max_tokens: 600
     prices: {...}
     chosen_because: "<one line with the numbers>"
5. Write models/results/model_select.md with the table. That table goes in the demo.

Done when: models/models.yaml exists and every number in it has a source. Report: the table and the pick.
Do not: touch mel/ or tests/.
