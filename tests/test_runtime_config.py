"""Deployed-runtime configuration: MEL_* env names, the packaged pack subset, the Jev key."""

from __future__ import annotations

import filecmp
from pathlib import Path

from mel.api.wiring import RefreshingJevJudge, config_value, parse_secret
from mel.settings import REPO_ROOT, RUNTIME_PACK_DIR, Settings


def test_runtime_pack_is_identical_to_pack():
    files = sorted(p for p in RUNTIME_PACK_DIR.rglob("*") if p.is_file())
    assert {f.name for f in files} >= {"rules.json", "outcome_codes.json", "survey.schema.json",
                                       "response.schema.json", "crop_calendar_bihar_rabi.csv"}
    for f in files:
        twin = REPO_ROOT / "pack" / f.relative_to(RUNTIME_PACK_DIR)
        assert filecmp.cmp(f, twin, shallow=False), f.name
    # every schema the validator can load is shipped
    shipped = {f.name for f in (RUNTIME_PACK_DIR / "json" / "schemas").iterdir()}
    assert shipped == {f.name for f in (REPO_ROOT / "pack" / "json" / "schemas").iterdir()}


def test_runtime_pack_dir_works_for_validation_and_rules(monkeypatch):
    from mel import fixtures, validate

    s = Settings.from_env({"PACK_DIR": str(RUNTIME_PACK_DIR)})
    monkeypatch.setattr(fixtures, "settings", s)
    monkeypatch.setattr(validate, "settings", s)
    assert "frequency_cap" in fixtures.load_rules()
    assert fixtures.load_crop_calendar()
    assert "failures" in fixtures.load_outcome_codes()


def test_mel_env_names_are_read():
    s = Settings.from_env({"MEL_TABLE": "mel-ledger-x", "MEL_FOLLOWUP_QUEUE_URL": "https://q",
                           "MEL_MODELS_FILE": "models/models.yaml", "MEL_METRICS_NAMESPACE": "Ns",
                           "MEL_REGION": "us-west-2"})
    assert s.LEDGER_TABLE == "mel-ledger-x"
    assert s.FOLLOW_UP_QUEUE_URL == "https://q"
    assert s.MODELS_FILE == REPO_ROOT / "models" / "models.yaml"
    assert s.METRICS_NAMESPACE == "Ns"
    assert Settings.from_env({"MEL_TABLE": "a", "LEDGER_TABLE": "b"}).LEDGER_TABLE == "b"


def test_config_value_prefers_env_then_ssm(monkeypatch):
    class Ssm:
        def get_parameter(self, Name):
            assert Name == "/mel/table_name"
            return {"Parameter": {"Value": "from-ssm"}}

    monkeypatch.delenv("MEL_TABLE", raising=False)
    assert config_value("MEL_TABLE", Ssm()) == "from-ssm"
    monkeypatch.setenv("MEL_TABLE", "from-env")
    assert config_value("MEL_TABLE", Ssm()) == "from-env"


def test_parse_secret():
    assert parse_secret("REPLACE_ME") is None
    assert parse_secret("  ") is None
    assert parse_secret(None) is None
    assert parse_secret("abc123") == "abc123"
    assert parse_secret('{"api_key": "k1"}') == "k1"
    assert parse_secret('{"other": "x"}') is None
    assert parse_secret("{broken") is None


def test_placeholder_key_fails_closed(scenarios):
    class Sm:
        def get_secret_value(self, SecretId):
            return {"SecretString": "REPLACE_ME"}

    from mel.models import Insight, Survey

    sc = next(s for s in scenarios if s["name"].startswith("3-"))
    survey = Survey.model_validate(sc["survey_by_lang"]["en-IN"])
    insight = Insight.model_validate(sc["insight"])
    judge = RefreshingJevJudge("arn:aws:secretsmanager:us-west-2:1:secret:x", Sm())
    verdict = judge.check_survey(insight, survey)
    assert verdict.ok is False and verdict.pending_review is True
    assert "REPLACE_ME" not in repr(judge)


def test_handler_module_path_matches_infra():
    text = (REPO_ROOT / "infra" / "app.py").read_text()
    assert 'handler="mel.api.handler.lambda_handler"' in text
    from mel.api.handler import ROUTES

    for route in ROUTES:
        assert f'"{route}"' in text, route
    assert Path(REPO_ROOT / "mel" / "agent.py").is_file()


def test_jev_request_names_a_model():
    import json

    import httpx
    import pytest

    from mel.judge import JevError, JevJudge

    seen = {}

    def transport(request):
        seen.update(json.loads(request.content))
        return httpx.Response(400)

    class Sm:
        def get_secret_value(self, SecretId):
            return {"SecretString": "real-looking-key"}

    inner = RefreshingJevJudge("arn:x", Sm())._current()
    assert isinstance(inner, JevJudge)
    inner._transport = httpx.MockTransport(transport)
    with pytest.raises(JevError):
        inner._post({"x": 1}, inner._monotonic())
    assert seen["model"] == "jev-latest"


def test_cached_input_tokens_are_counted():
    import boto3
    from botocore.stub import Stubber

    from mel.providers.bedrock import BedrockChat
    from mel.providers.ratelimit import TokenBucket

    client = boto3.client("bedrock-runtime", region_name="us-west-2", aws_access_key_id="x",
                          aws_secret_access_key="x")
    with Stubber(client) as st:
        st.add_response("converse", {
            "output": {"message": {"role": "assistant", "content": [{"text": "{\"a\": 1}"}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 2, "outputTokens": 10, "totalTokens": 1012, "cacheReadInputTokens": 1000},
            "metrics": {"latencyMs": 5},
        })
        chat = BedrockChat("generation", client=client, bucket=TokenBucket(6000))
        _, usage = chat.converse_json("S", "U", {"type": "object"})
    assert usage.input_tokens == 1002
