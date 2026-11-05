Model: Haiku. Branch: w1-I. May run before Wave 0 merges (use dicts, not models).
Goal: five channel renderers whose output equals the pack's render fixtures.
Read first: pack/json/scenarios/*/render/en-IN/*.json (30 files), pack/json/schemas/bottom_sheet.schema.json, pack/spreadsheets is excluded, use the JSON.
You own: mel/render/__init__.py, mel/render/{app,web,whatsapp,telegram,voice}.py, tests/test_render_golden.py, NOTES-I.md.
Deliver: render(survey: dict, channel: str, language: str) -> dict. Each module is a template over the
survey items. Match the fixture structure exactly, including the bottom_sheet presentation block for app,
WhatsApp button and list limits, Telegram callback_data, voice keypad prompts. No read receipts or
delivery timestamps are invented by a renderer. tests/test_render_golden.py: for every scenario and
channel in en-IN, rendered == fixture (deep equal). hi-IN fixtures are parametrized but marked xfail
until the Hindi stretch.
Done when: 30 en-IN cases pass. Report: any fixture that could not be reproduced and why.
