Model: Haiku. Branch: stretch-fc-patch. Works in ../../FarmerChat, not in mel-agent. Only if time remains.
Goal: point the existing FarmerChat OpenAI client at Bedrock in us-west-2 without changing behaviour.
Read first: FarmerChat/rag_service/openai_service.py, django_core/config.py, .config.env lines 170-180, tests/test_openai_service.py.
You own: rag_service/openai_service.py (client construction only), django_core/config.py (new settings only), tests/test_openai_service.py (one new test), NOTES-FC.md.
Deliver: settings LLM_PROVIDER=openai|bedrock, BEDROCK_REGION=us-west-2, BEDROCK_MODEL_MAP json
{"gpt-6-luna": "global.openai.gpt-6-luna", "gpt-6.1-terra": "global.openai.gpt-6.1-terra"}. When bedrock:
AsyncOpenAI(base_url="https://bedrock-runtime.us-west-2.amazonaws.com/openai/v1", api_key=<Bedrock API
key from env>) and model ids mapped. Keep chat.completions (Bedrock Runtime supports it). One test that
asserts the base_url and mapped model with a mocked client. Do not touch the pipeline. Report: diff size.
