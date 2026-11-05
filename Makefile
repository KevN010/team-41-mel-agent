.PHONY: test lint golden day0
test:
	.venv/bin/pytest -q --disable-socket --allow-unix-socket tests
lint:
	.venv/bin/ruff check mel tests
golden:
	.venv/bin/pytest -q --disable-socket tests/test_rules_golden.py -s
day0:
	.venv/bin/python scripts/day0_bedrock.py
