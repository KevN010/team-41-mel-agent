Model: Sonnet. Branch: stretch-guardrails. Only if time remains after Hindi or Hindi is skipped.
Goal: Bedrock Guardrails on survey text as a second, AWS-native check beside Jev.
You own: infra/stacks/guardrails.py, mel/providers/guardrail.py, tests/test_guardrail.py, NOTES-GR.md.
Deliver: a guardrail with PII (block), prompt attack (block), and a denied topic "new agricultural
treatment recommendation"; applied via ApplyGuardrail to the final survey text before judge; outcome
recorded on the DecisionRecord as guardrail: pass|blocked. Does not replace Jev. Done when: synth clean
and the stubbed test passes. Report: the guardrail id output name.
