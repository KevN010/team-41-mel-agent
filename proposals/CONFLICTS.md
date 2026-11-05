# Conflicts in the participant pack

Each section: what disagrees, the evidence, what the build does, what we ask Digital Green.
Paths are relative to the repo root. Counts come from `pack/data/golden_set.jsonl` (150 rows: 95 survey, 55 no-survey).

## 1. Reason vocabulary

- **Disagreement:** The v1 schema allows only two reason codes. The golden set uses seven different no-survey codes.
- **Evidence:** `pack/json/schemas/no_survey.schema.json`, field `reason_code.enum` = `generic_information`, `needs_more_context`. Golden `expected.reason_code` for the 55 no-survey rows = `junk_insight` (14), `nothing_to_verify` (12), `no_check_needed` (10), `waiting_for_details` (10), `critical_needs_human_call` (6), `window_after_season` (2), `crop_already_harvested` (1). The two v1 values never appear in the golden set. They are resolution types, not reasons.
- **Build:** v1.1 accepts the union: the two v1 values plus the seven golden codes. Nine values in total.
- **Ask:** Confirm the seven golden codes are the official list. Say whether the two v1 values stay.

## 2. Rule ids

- **Disagreement:** The brief said rule ids R1 to R8 on a no-survey record. Only R1 to R7 appear on no-survey rows. R8 is the survey rule.
- **Evidence:** Golden `expected.rule`: R1 to R7 on the 55 no-survey rows; R8 on all 95 survey rows. Each no-survey code maps to exactly one rule: R1 junk_insight, R2 critical_needs_human_call, R3 nothing_to_verify, R4 waiting_for_details, R5 no_check_needed, R6 window_after_season, R7 crop_already_harvested.
- **Build:** v1.1 `rule_id` accepts R1 to R7 only. The if/then rules in v1.1 enforce the pairs above. A no-survey record with R8 fails validation.
- **Ask:** Confirm R1 to R7 are the no-survey rules, and that the code-to-rule pairs above are correct.

## 3. The reshape cannot cover all 150 golden blocks

- **Disagreement:** The brief said v1.1 validates all 150 golden blocks reshaped to a no-survey record. That cannot be done.
- **Evidence:** 95 golden blocks have `expected.survey = true`. They carry a send window and survey items, not a reason code. They are survey decisions, not no-survey records. The golden blocks also have no `farmer_id` (it comes from `insight.farmer_id`) and no reason text.
- **Build:** The check validates the 55 no-survey rows. For `reason`, we use the reason code string as a placeholder, because the golden set has no reason text. The placeholder is only in the test shim, not in the schema.
- **Ask:** Confirm the 55 no-survey rows are the set to validate. Ask whether the golden set will get real reason text.

## 4. Send windows: golden set vs rules.json and the index page

Four separate disagreements here.

**4a. Window opens before the action window ends.**
- **Evidence:** `pack/index.html` says the window "never opens on the day of the advice or before the farmer's action window ends". `rules.json` `window_rules.start_not_before_action_window_end` = true. Golden: 75 of 95 survey windows start before the action window ends. Example: G-0002 has `action_window_days` 8 and a window starting on day 7.
- **Build:** We follow `rules.json` (start is not before the action window ends). This will not match 75 golden windows.
- **Ask:** Which rule is the real one?

**4b. Timing bands.**
- **Evidence:** `rules.json` `send_window_days.same_day` = [0,1], `next_day` = [1,2]. `index.html` says same_day "1 to 3" and next_day "1 to 3". Golden same_day rows (11 of them) start on day 0 or 1 and end on the same day, so each window is 0 days wide.
- **Build:** We follow `rules.json`. Note the golden same_day windows break `min_width_days` = 2 (see 4c).
- **Ask:** Which bands are correct? Are same_day windows allowed to be 0 days wide?

**4c. Window width and start time.**
- **Evidence:** `rules.json` `window_rules.min_width_days` = 2, `not_before_time` = "07:00", `send_hours.from` = "07:00". Golden: 12 survey windows are under 2 days wide (11 are same_day). 88 of 95 golden windows open at 09:00, not 07:00. 7 open at other times (10:26 to 15:53) and are 4 hours wide.
- **Build:** We follow `rules.json` (07:00 open, at least 2 days wide). Golden rows will fail.
- **Ask:** Is 09:00 the real opening time? Where do the 4-hour windows come from?

**4d. Seasonal band.**
- **Evidence:** `rules.json` seasonal = [21,45]. Golden G-0009 uses days 30 to 45.
- **Build:** We follow `rules.json`. One row differs.
- **Ask:** Which is correct?

## 5. Windows that fall after the season

- **Disagreement:** `rules.json` says nothing is sent after the season ends, but it has no rule for a window that falls entirely after it. The golden set returns no-survey with R6 for these.
- **Evidence:** `rules.json` `window_rules.season_end` = "2027-03-31". Golden G-0146 (created 2027-03-30) and G-0148 (created 2027-03-31) are R6 `window_after_season`, timing `three_to_ten_days`.
- **Build:** We return no-survey with R6 when the whole window falls after season end. We do not clip windows to the season end.
- **Ask:** Is R6 the intended outcome, or should the window be clipped to the season end?

## 6. Critical severity: no-survey vs high-priority survey

- **Disagreement:** `rules.json` says critical severity gets a high-priority survey. The golden set returns no-survey for six critical insights.
- **Evidence:** `rules.json` `priority.high_if_severity` = ["high", "critical"]. Golden R2 `critical_needs_human_call`: 6 rows, all `severity` = critical, resolution direct_action (4), plan_created (1), needs_more_context (1).
- **Build:** We follow the golden set for R2 (no survey, reason critical_needs_human_call). This is a design choice we need confirmed.
- **Ask:** Should critical insights that need a human call get a survey, or no survey?

## 7. Late answers

- **Disagreement:** The schedule hand-off says late answers are kept and marked late. The answer record has no late status and no late failure code.
- **Evidence:** `pack/index.html`, schedule hand-off row for `expires_at`: "late answers are kept but marked late". Answer record `status` enum (index.html): completed, partial, negative_outcome, expired, declined, delivery_failed, invalid_input, stale, duplicate, identity_mismatch. `failure_code` enum: no late value. `pack/json/rules/outcome_codes.json`: no late value. The only "late" in the pack is a survey answer label ("Yes, but later", answer "late") in the hi-IN irrigation example.
- **Build:** Late answers are stored in our own ledger with a `late` flag. The emitted pack record uses `expired` with `window_expired`, because the pack schema has no late field. The `late` flag does not go into the emitted record.
- **Ask:** Is there a late status we should emit? Or is `window_expired` the right code?

## 8. flow_key: hyphen vs underscore

- **Disagreement:** The rule gives a hyphen. The worked examples use an underscore.
- **Evidence:** `rules.json` `farmerchat_flow.flow_key` = "mel_{survey_id_lower}". For survey_id "S-20931" that gives "mel_s-20931". `pack/json/scenarios/1-mustard-aphid-spray/schedule_handoff.json` `farmerchat_flow.flow_key` = "mel_s_20931". The same pattern holds in scenarios 2 to 5.
- **Build:** We use the underscore form from the worked examples (replace "-" with "_" in the lowercased survey id). Tests lock this in.
- **Ask:** Which form does the FarmerChat flow registry accept?
