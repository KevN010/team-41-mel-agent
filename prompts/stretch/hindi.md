Model: Sonnet. Branch: stretch-hindi. Only start if evidence/e2e-run-1.md exists.
Goal: hi-IN surveys.
Read first: mel/generate.py, mel/prompts/survey_system.md, mel/judge.py, pack/json/scenarios/*/survey.hi-IN.json, pack/json/scenarios/*/render/hi-IN/*.json.
You own: mel/prompts/survey_system.md (language section only), mel/generate.py (language param only), tests/test_generate_hi.py, mel/render/* hi-IN label tables, NOTES-HI.md.
Deliver: LANGUAGES=["en-IN","hi-IN"]: generation prompt asks for the farmer-language copy with English
rationale kept separate; option values stay English snake_case, labels Hindi <= 20 code points; Jev
language_matches_tag check must pass on the Hindi artifact; render hi-IN fixtures un-xfailed. Keep the
English path untouched. Done when: 5 scenarios produce valid hi-IN surveys in tests with a fake
generator and the 30 hi-IN render cases pass. Report: label-length violations found.
