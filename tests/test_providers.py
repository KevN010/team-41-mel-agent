"""Bedrock provider, rate limiter and metrics. Offline: botocore Stubber, fake clocks."""

from __future__ import annotations

import asyncio
import json
import threading

import boto3
import pytest
from botocore.stub import Stubber

from mel.providers import bedrock, metrics
from mel.providers.bedrock import (
    BedrockChat,
    ProviderError,
    compute_cost,
    load_models,
    resolve_model,
)
from mel.providers.ratelimit import TokenBucket
from mel.settings import Settings

SCHEMA = {
    "type": "object",
    "properties": {"q": {"type": "string"}},
    "required": ["q"],
    "additionalProperties": False,
}

MODELS_YAML = """
generation: gpt6_luna
retry: haiku55
region: us-west-2
max_tokens: 600
models:
  gpt6_luna:
    profile: global.openai.gpt-6-luna
    input_per_m: 0.10
    output_per_m: 0.50
  haiku55:
    profile: global.anthropic.claude-haiku-5-5
prices:
  haiku55: {input: 1.0, output: 5.0}
"""


class FakeTime:
    """Fake monotonic clock whose sleep() moves time forward."""

    def __init__(self) -> None:
        self.t = 1000.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.t += s


@pytest.fixture
def models_file(tmp_path):
    p = tmp_path / "models.yaml"
    p.write_text(MODELS_YAML)
    return p


@pytest.fixture
def cw(monkeypatch):
    """Metrics go to a recording stub client."""
    sent: list[dict] = []

    class Rec:
        def put_metric_data(self, **kw):
            sent.append(kw)

    monkeypatch.setattr(metrics, "settings", Settings.from_env({}))
    metrics.set_client(Rec())
    yield sent
    metrics.set_client(None)


def _runtime():
    return boto3.client(
        "bedrock-runtime",
        region_name="us-west-2",
        aws_access_key_id="x",
        aws_secret_access_key="x",
    )


def _ok(content, in_tok=100, out_tok=50, stop="end_turn"):
    return {
        "output": {"message": {"role": "assistant", "content": content}},
        "stopReason": stop,
        "usage": {"inputTokens": in_tok, "outputTokens": out_tok, "totalTokens": in_tok + out_tok},
        "metrics": {"latencyMs": 12},
    }


def _chat(models_file, key, stubber_client, bucket=None, sleeps=None):
    return BedrockChat(
        key,
        client=stubber_client,
        bucket=bucket or TokenBucket(60, monotonic=FakeTime().monotonic, sleep=lambda s: None),
        models_file=models_file,
        sleep=(sleeps.append if sleeps is not None else (lambda s: None)),
    )


# ----------------------------------------------------------------------------- models.yaml


def test_resolve_keys_prices_and_families(models_file):
    cfg = load_models(models_file)
    gen = resolve_model("generation", cfg)
    assert (gen.key, gen.profile_id, gen.family) == ("gpt6_luna", "global.openai.gpt-6-luna", "openai")
    assert (gen.input_per_m, gen.output_per_m, gen.max_tokens) == (0.10, 0.50, 600)
    retry = resolve_model("retry", cfg)
    assert retry.family == "anthropic"
    assert (retry.input_per_m, retry.output_per_m) == (1.0, 5.0)  # from the prices: block
    direct = resolve_model("global.openai.gpt-6-luna", cfg)  # profile id used directly
    assert direct.family == "openai" and direct.input_per_m is None


def test_unknown_key_and_missing_file(models_file, tmp_path):
    with pytest.raises(ProviderError):
        resolve_model("nope", load_models(models_file))
    with pytest.raises(ProviderError):
        load_models(tmp_path / "absent.yaml")


def test_region_must_be_us_west_2(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text("region: eu-west-1\nmodels:\n  a: {profile: global.openai.x}\n")
    with pytest.raises(ProviderError):
        BedrockChat("a", client=object(), models_file=p)


# ----------------------------------------------------------------------------- cost math


def test_cost_math(models_file):
    spec = resolve_model("gpt6_luna", load_models(models_file))
    # 1,000 in at $0.10/M + 600 out at $0.50/M = 0.0001 + 0.0003
    assert compute_cost(spec, 1000, 600) == pytest.approx(0.0004)
    assert compute_cost(spec, 0, 0) == 0.0
    nospec = resolve_model("global.openai.gpt-6-luna", load_models(models_file))
    assert compute_cost(nospec, 10, 10) is None


# ----------------------------------------------------------------------------- OpenAI strict JSON


def test_openai_request_has_strict_schema_and_user_turn_only(models_file):
    client = _runtime()
    expected = {
        "modelId": "global.openai.gpt-6-luna",
        "system": [{"text": "SYS"}],
        "messages": [{"role": "user", "content": [{"text": "INSIGHT TEXT"}]}],
        "inferenceConfig": {"maxTokens": 600},
        "additionalModelRequestFields": {
            "text": {"format": {"type": "json_schema", "name": "survey", "strict": True, "schema": SCHEMA}},
            "reasoning": {"effort": "low"},
        },
    }
    with Stubber(client) as st:
        st.add_response("converse", _ok([{"text": json.dumps({"q": "hi"})}], 1000, 600), expected)
        chat = _chat(models_file, "generation", client)
        out, usage = chat.converse_json("SYS", "INSIGHT TEXT", SCHEMA, schema_name="survey")
        st.assert_no_pending_responses()
    assert out == {"q": "hi"}
    assert usage.model_id == "global.openai.gpt-6-luna"
    assert (usage.input_tokens, usage.output_tokens) == (1000, 600)
    assert usage.cost_usd == pytest.approx(0.0004)
    assert usage.latency_ms >= 0


def test_openai_skips_reasoning_blocks(models_file):
    client = _runtime()
    content = [{"reasoningContent": {"reasoningText": {"text": "thinking"}}}, {"text": '{"q": "x"}'}]
    with Stubber(client) as st:
        st.add_response("converse", _ok(content))
        out, _ = _chat(models_file, "generation", client).converse_json("s", "u", SCHEMA)
    assert out == {"q": "x"}


# ----------------------------------------------------------------------------- Anthropic tool use


def test_anthropic_forced_tool_choice(models_file):
    client = _runtime()
    expected = {
        "modelId": "global.anthropic.claude-haiku-5-5",
        "system": [{"text": "SYS"}],
        "messages": [{"role": "user", "content": [{"text": "U"}]}],
        "inferenceConfig": {"maxTokens": 300},
        "toolConfig": {
            "tools": [
                {
                    "toolSpec": {
                        "name": bedrock.TOOL_NAME,
                        "description": "Return the answer as one JSON object that matches the schema.",
                        "inputSchema": {"json": SCHEMA},
                    }
                }
            ],
            "toolChoice": {"tool": {"name": bedrock.TOOL_NAME}},
        },
    }
    tool = {"toolUse": {"toolUseId": "t1", "name": bedrock.TOOL_NAME, "input": {"q": "tool"}}}
    with Stubber(client) as st:
        st.add_response("converse", _ok([tool], 200, 100, stop="tool_use"), expected)
        out, usage = _chat(models_file, "retry", client).converse_json("SYS", "U", SCHEMA, max_tokens=300)
    assert out == {"q": "tool"}
    assert usage.cost_usd == pytest.approx((200 * 1.0 + 100 * 5.0) / 1e6)


# ----------------------------------------------------------------------------- parse, never trust


@pytest.mark.parametrize(
    "content,stop",
    [
        ([{"text": "not json at all"}], "end_turn"),
        ([{"text": "[1, 2]"}], "end_turn"),
        ([{"text": '"a string"'}], "end_turn"),
        ([{"text": "   "}], "end_turn"),
        ([], "end_turn"),
        ([{"text": '{"q": "cut'}], "max_tokens"),
        ([{"toolUse": {"toolUseId": "t", "name": "n", "input": ["x"]}}], "tool_use"),
    ],
)
def test_bad_output_raises_provider_error_without_echo(models_file, content, stop):
    client = _runtime()
    with Stubber(client) as st:
        st.add_response("converse", _ok(content, stop=stop))
        with pytest.raises(ProviderError) as ei:
            _chat(models_file, "generation", client).converse_json("s", "u", SCHEMA)
    msg = str(ei.value)
    assert "not json at all" not in msg and '"cut' not in msg


# ----------------------------------------------------------------------------- retries


def test_throttling_retries_with_backoff_then_succeeds(models_file):
    client = _runtime()
    sleeps: list[float] = []
    with Stubber(client) as st:
        for _ in range(3):
            st.add_client_error("converse", service_error_code="ThrottlingException", http_status_code=429)
        st.add_response("converse", _ok([{"text": '{"q": "ok"}'}]))
        out, _ = _chat(models_file, "generation", client, sleeps=sleeps).converse_json("s", "u", SCHEMA)
        st.assert_no_pending_responses()
    assert out == {"q": "ok"}
    assert sleeps == [1.0, 2.0, 4.0]


def test_throttling_gives_up_after_three_retries(models_file):
    client = _runtime()
    with Stubber(client) as st:
        for _ in range(4):
            st.add_client_error("converse", service_error_code="ThrottlingException", http_status_code=429)
        with pytest.raises(ProviderError, match="ThrottlingException"):
            _chat(models_file, "generation", client).converse_json("s", "u", SCHEMA)
        st.assert_no_pending_responses()


@pytest.mark.parametrize("code", ["ValidationException", "AccessDeniedException", "ModelTimeoutException"])
def test_other_errors_are_not_retried(models_file, code):
    client = _runtime()
    sleeps: list[float] = []
    with Stubber(client) as st:
        st.add_client_error("converse", service_error_code=code, http_status_code=400)
        with pytest.raises(ProviderError, match=code):
            _chat(models_file, "generation", client, sleeps=sleeps).converse_json("s", "u", SCHEMA)
        st.assert_no_pending_responses()
    assert sleeps == []


def test_every_attempt_takes_a_rate_limit_token(models_file):
    client = _runtime()
    ft = FakeTime()
    bucket = TokenBucket(60, monotonic=ft.monotonic, sleep=ft.sleep)
    with Stubber(client) as st:
        st.add_client_error("converse", service_error_code="ThrottlingException", http_status_code=429)
        st.add_response("converse", _ok([{"text": '{"q": "ok"}'}]))
        _chat(models_file, "generation", client, bucket=bucket).converse_json("s", "u", SCHEMA)
    assert bucket._tokens < 1.0  # two attempts drew from the bucket


# ----------------------------------------------------------------------------- rate limiter


def test_bucket_blocks_when_empty_with_fake_clock():
    ft = FakeTime()
    b = TokenBucket(60, monotonic=ft.monotonic, sleep=ft.sleep)  # 1 per second, burst 1
    assert b.acquire() == 0.0  # first call is free
    assert b.acquire() == pytest.approx(1.0)
    assert b.acquire() == pytest.approx(1.0)
    ft.t += 5  # idle: bucket refills to burst, not beyond
    assert b.acquire() == 0.0
    assert b.acquire() == pytest.approx(1.0)
    assert ft.slept == [pytest.approx(1.0)] * 3


def test_bucket_never_exceeds_rpm_in_a_minute():
    ft = FakeTime()
    b = TokenBucket(60, monotonic=ft.monotonic, sleep=ft.sleep)
    start = ft.t
    stamps = []
    for _ in range(120):
        b.acquire()
        stamps.append(ft.t - start)
    in_first_minute = sum(1 for s in stamps if s < 60.0)
    assert in_first_minute <= 60


def test_bucket_burst_and_slow_rate():
    ft = FakeTime()
    b = TokenBucket(30, burst=3, monotonic=ft.monotonic, sleep=ft.sleep)  # one per 2 s
    assert [b.acquire() for _ in range(3)] == [0.0, 0.0, 0.0]
    assert b.acquire() == pytest.approx(2.0)


def test_bucket_rejects_bad_args():
    with pytest.raises(ValueError):
        TokenBucket(0)
    with pytest.raises(ValueError):
        TokenBucket(60, burst=0)


def test_bucket_threads_get_distinct_slots():
    ft = FakeTime()
    waits: list[float] = []
    b = TokenBucket(60, monotonic=ft.monotonic, sleep=lambda s: None)
    lock = threading.Lock()

    def work():
        w = b.acquire()
        with lock:
            waits.append(round(w, 6))

    threads = [threading.Thread(target=work) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(waits) == [float(i) for i in range(10)]  # 0,1,2,..9 s: no two share a slot


def test_bucket_async():
    ft = FakeTime()
    b = TokenBucket(6000, monotonic=ft.monotonic)  # 100/s: real sleeps of ~10 ms

    async def run():
        return await asyncio.gather(*(b.acquire_async() for _ in range(4)))

    waits = sorted(asyncio.run(run()))
    assert waits[0] == 0.0
    assert waits[1:] == [pytest.approx(0.01), pytest.approx(0.02), pytest.approx(0.03)]


def test_aconverse_json(models_file):
    client = _runtime()
    with Stubber(client) as st:
        st.add_response("converse", _ok([{"text": '{"q": "a"}'}]))
        chat = _chat(models_file, "generation", client)
        out, _ = asyncio.run(chat.aconverse_json("s", "u", SCHEMA))
    assert out == {"q": "a"}


# ----------------------------------------------------------------------------- metrics


def test_call_emits_metrics_in_namespace(models_file, cw):
    client = _runtime()
    with Stubber(client) as st:
        st.add_response("converse", _ok([{"text": '{"q": "a"}'}], 1000, 600))
        _chat(models_file, "generation", client).converse_json("s", "u", SCHEMA)
    assert {c["Namespace"] for c in cw} == {"MelAgent"}
    names = [c["MetricData"][0]["MetricName"] for c in cw]
    assert names == ["ModelCalls", "ModelTokens", "ModelTokens", "LatencyMs", "CostUsd"]
    tokens = {}
    for c in cw:
        d = c["MetricData"][0]
        if d["MetricName"] == "ModelTokens":
            direction = next(x["Value"] for x in d["Dimensions"] if x["Name"] == "Direction")
            tokens[direction] = d["Value"]
    assert tokens == {"input": 1000.0, "output": 600.0}
    # dimensions hold the model id only, never prompt text
    assert all("INSIGHT" not in json.dumps(c) for c in cw)


def test_metrics_noop_when_off(monkeypatch):
    sent = []

    class Rec:
        def put_metric_data(self, **kw):
            sent.append(kw)

    monkeypatch.setattr(metrics, "settings", Settings.from_env({"METRICS_OFF": "true"}))
    metrics.set_client(Rec())
    try:
        assert metrics.put_metric("ModelCalls", 1, "Count", {"a": "b"}) is False
    finally:
        metrics.set_client(None)
    assert sent == []


def test_metrics_never_raise(monkeypatch):
    class Boom:
        def put_metric_data(self, **kw):
            raise RuntimeError("secret text")

    monkeypatch.setattr(metrics, "settings", Settings.from_env({}))
    metrics.set_client(Boom())
    try:
        assert metrics.put_metric("CostUsd", 0.1) is False
    finally:
        metrics.set_client(None)


def test_metrics_real_client_stubbed(monkeypatch):
    client = boto3.client(
        "cloudwatch", region_name="us-west-2", aws_access_key_id="x", aws_secret_access_key="x"
    )
    monkeypatch.setattr(metrics, "settings", Settings.from_env({}))
    metrics.set_client(client)
    try:
        with Stubber(client) as st:
            st.add_response(
                "put_metric_data",
                {},
                {
                    "Namespace": "MelAgent",
                    "MetricData": [
                        {
                            "MetricName": "DecisionsByRule",
                            "Value": 1.0,
                            "Unit": "Count",
                            "Dimensions": [{"Name": "RuleId", "Value": "R8"}],
                        }
                    ],
                },
            )
            assert metrics.put_metric("DecisionsByRule", 1, "Count", {"RuleId": "R8"}) is True
            st.assert_no_pending_responses()
    finally:
        metrics.set_client(None)
