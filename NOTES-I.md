# NOTES-I (wave 1, task I: channel renderers)

## Disagreements with the pack

- The prompt says 30 en-IN render fixtures. The pack has 25: five scenarios x five channels. Scenario 6 (no-survey) has no `render/` folder. The hi-IN count is also 25. All 25 en-IN cases pass; the 25 hi-IN cases are strict xfail.
- The survey schema allows 2 to 10 options per single-select item. A voice keypad has digits 1 to 9, so a 10-option item cannot be rendered for voice. The renderer raises `ValueError` for that case. No pack fixture has more than 3 options or a scale of more than 5.
- The prompt says `pack/spreadsheets` is excluded. The pack copy has no `spreadsheets/` folder at all. This does not affect renderers.

## Rules the fixtures show but the pack does not state

- WhatsApp: up to 3 choices become reply buttons, more than 3 become a list message. Both sides of the threshold appear in the fixtures (3 options = buttons, 4 options = list).
- Telegram: a scale's numbers share one row. Other choices get one row each.
- Voice confirm synonyms: `yes` speaks as "Yes", "yes", "yes I did". `no` speaks as "No", "no", "not yet". These are constant in the fixtures and are keyed by value in code.
- Voice scale speech: `[str(n), word]` for n in 1..10. The fixtures cover 1..5 only.
- Voice opening: "one short question" for a single-question survey. No fixture has one question, so this wording is my choice.
- Scale choices: label is the digit as text, answer is the integer. Question type is copied from the survey item type.

## Limits enforced at render time (platform limits, not pack)

- WhatsApp: 3 reply buttons, button title at most 20 characters, list at most 10 rows, row title at most 24 characters.
- Telegram: `callback_data` at most 64 bytes.
- App and web: 1 to 3 questions per sheet (pack schema).
- Voice: at most 9 choices per question (keypad).

Error messages name the question id only. They never echo survey text.

## Not done here

- hi-IN renderers (Hindi stretch). `render(..., "hi-IN")` raises `NotImplementedError`.
- Delivery timestamps and read receipts are not produced by renderers, by design.
