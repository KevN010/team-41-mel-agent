"""Bedrock Converse provider: one JSON object out, strict schema in.

All LLM calls in mel go through ``BedrockChat.converse_json``. SigV4 comes from the normal boto3
credential chain; there are no API keys. Region is us-west-2.

Safety rules kept here:
  * ``system`` is the caller's fixed instruction text. Insight, advice and retrieved text are
    untrusted and belong in ``user``. This module sends them as the user turn only.
  * Prompt text and model output are never logged and never put in an exception message.
    Logs carry model id, token counts and latency only.
  * Model output is parsed, not trusted: bad JSON, a non-object, or a cut-off reply raises
    ProviderError.

models/models.yaml (written by the model-selection thread). Read as follows:

    generation: gpt6_luna          # a key under ``models``, or a profile id
    retry: gpt61_terra
    region: us-west-2
    max_tokens: 600
    models:                        # optional; key -> details
      gpt6_luna:
        profile: global.openai.gpt-6-luna
        family: openai             # optional; guessed from the profile id when missing
        input_per_m: 0.10          # USD per 1M tokens; "in"/"input" also accepted
        output_per_m: 0.50
    prices:                        # optional; key or profile id -> prices
      global.openai.gpt-6-luna: {input_per_m: 0.10, output_per_m: 0.50}
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
import yaml
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from mel.models import Usage
from mel.providers import metrics
from mel.providers.ratelimit import TokenBucket, get_bucket
from mel.settings import settings

log = logging.getLogger(__name__)

THROTTLE_RETRIES = 3  # retries after the first attempt, ThrottlingException only
BACKOFF_BASE_S = 1.0  # 1 s, 2 s, 4 s
TOOL_NAME = "emit_json"
REASONING_EFFORT = "low"  # OpenAI family only

_INPUT_KEYS = ("input_per_m", "input", "in")
_OUTPUT_KEYS = ("output_per_m", "output", "out")


class ProviderError(Exception):
    """A model call failed or returned something unusable. The message never holds model text."""


@dataclass(frozen=True)
class ModelSpec:
    key: str
    profile_id: str
    family: str  # "openai" | "anthropic"
    region: str
    max_tokens: int
    input_per_m: float | None = None
    output_per_m: float | None = None


def _first(d: dict[str, Any], names: tuple[str, ...]) -> float | None:
    for name in names:
        if name in d and d[name] is not None:
            return float(d[name])
    return None


def _family(profile_id: str, declared: str | None) -> str:
    if declared:
        return declared.lower()
    lowered = profile_id.lower()
    if "anthropic" in lowered or "claude" in lowered:
        return "anthropic"
    if "openai" in lowered:
        return "openai"
    raise ProviderError("cannot tell the model family from the profile id; set 'family' in models.yaml")


def load_models(path: Path | str | None = None) -> dict[str, Any]:
    """Read models.yaml. Raises ProviderError when it is missing or not a mapping."""
    file = Path(path) if path is not None else Path(settings.MODELS_FILE)
    try:
        data = yaml.safe_load(file.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ProviderError(f"models file not readable: {file.name}") from exc
    except yaml.YAMLError as exc:
        raise ProviderError(f"models file is not valid YAML: {file.name}") from exc
    if not isinstance(data, dict):
        raise ProviderError(f"models file must be a mapping: {file.name}")
    return data


def resolve_model(model_key: str, config: dict[str, Any]) -> ModelSpec:
    """Turn a key ("generation", "retry", a models key, or a profile id) into a ModelSpec."""
    key = model_key
    if key in ("generation", "retry") and isinstance(config.get(key), str):
        key = config[key]
    models = config.get("models") or {}
    prices = config.get("prices") or {}
    entry = models.get(key) if isinstance(models, dict) else None
    if isinstance(entry, dict):
        profile = entry.get("profile") or entry.get("profile_id") or entry.get("model_id")
        if not profile:
            raise ProviderError(f"models.yaml entry '{key}' has no profile")
        price_src = {**(prices.get(key) or {}), **(prices.get(profile) or {}), **entry}
        declared = entry.get("family")
    elif "." in key:  # a profile id used directly
        profile = key
        price_src = prices.get(key) or {}
        declared = None
    else:
        raise ProviderError(f"unknown model key '{model_key}' in models.yaml")
    return ModelSpec(
        key=key,
        profile_id=str(profile),
        family=_family(str(profile), declared),
        region=str(config.get("region") or settings.REGION),
        max_tokens=int(config.get("max_tokens") or settings.MAX_TOKENS),
        input_per_m=_first(price_src, _INPUT_KEYS) if isinstance(price_src, dict) else None,
        output_per_m=_first(price_src, _OUTPUT_KEYS) if isinstance(price_src, dict) else None,
    )


def compute_cost(spec: ModelSpec, input_tokens: int, output_tokens: int) -> float | None:
    """USD for one call from the models.yaml prices. None when a price is missing."""
    if spec.input_per_m is None or spec.output_per_m is None:
        return None
    return (input_tokens * spec.input_per_m + output_tokens * spec.output_per_m) / 1_000_000


def _default_client(region: str) -> Any:
    # Our own retry loop counts every attempt against the rate limiter, so botocore must not retry.
    cfg = Config(retries={"max_attempts": 1, "mode": "standard"}, read_timeout=60, connect_timeout=5)
    return boto3.client("bedrock-runtime", region_name=region, config=cfg)


class BedrockChat:
    def __init__(
        self,
        model_key: str,
        *,
        client: Any = None,
        bucket: TokenBucket | None = None,
        models_file: Path | str | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.spec = resolve_model(model_key, load_models(models_file))
        if self.spec.region != "us-west-2":
            raise ProviderError("region is fixed to us-west-2")
        self._client = client if client is not None else _default_client(self.spec.region)
        self._bucket = bucket if bucket is not None else get_bucket()
        self._sleep = sleep

    # ------------------------------------------------------------------ request building

    def _request(self, system: str, user: str, schema: dict[str, Any], max_tokens: int, name: str) -> dict[str, Any]:
        req: dict[str, Any] = {
            "modelId": self.spec.profile_id,
            "system": [{"text": system}],
            "messages": [{"role": "user", "content": [{"text": user}]}],
            "inferenceConfig": {"maxTokens": max_tokens},
        }
        if self.spec.family == "openai":
            req["additionalModelRequestFields"] = {
                "text": {
                    "format": {"type": "json_schema", "name": name, "strict": True, "schema": schema}
                },
                # NOTES-MODEL: without low effort luna spent the 600-token cap on reasoning (12/15 cut off).
                "reasoning": {"effort": REASONING_EFFORT},
            }
        elif self.spec.family == "anthropic":
            req["toolConfig"] = {
                "tools": [
                    {
                        "toolSpec": {
                            "name": TOOL_NAME,
                            "description": "Return the answer as one JSON object that matches the schema.",
                            "inputSchema": {"json": schema},
                        }
                    }
                ],
                "toolChoice": {"tool": {"name": TOOL_NAME}},
            }
        else:
            raise ProviderError(f"unsupported model family '{self.spec.family}'")
        return req

    # ------------------------------------------------------------------ calling

    def _call(self, request: dict[str, Any]) -> dict[str, Any]:
        """One Converse call with the rate limit and throttle retries. No retry on anything else."""
        attempt = 0
        while True:
            self._bucket.acquire()
            try:
                return self._client.converse(**request)
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "Unknown")
                if code == "ThrottlingException" and attempt < THROTTLE_RETRIES:
                    delay = BACKOFF_BASE_S * (2**attempt)
                    attempt += 1
                    log.warning("bedrock throttled model=%s retry=%d in=%.1fs", self.spec.profile_id, attempt, delay)
                    self._sleep(delay)
                    continue
                raise ProviderError(f"bedrock error {code}") from None
            except BotoCoreError as exc:
                raise ProviderError(f"bedrock client error {type(exc).__name__}") from None

    @staticmethod
    def _extract(response: dict[str, Any]) -> dict[str, Any]:
        stop = response.get("stopReason")
        if stop == "max_tokens":
            raise ProviderError("model output was cut off at max_tokens")
        blocks = (((response.get("output") or {}).get("message") or {}).get("content")) or []
        for block in blocks:  # Anthropic forced tool call
            tool = block.get("toolUse") if isinstance(block, dict) else None
            if tool is not None:
                out = tool.get("input")
                if not isinstance(out, dict):
                    raise ProviderError("tool input is not a JSON object")
                return out
        text = "".join(b["text"] for b in blocks if isinstance(b, dict) and isinstance(b.get("text"), str))
        if not text.strip():
            raise ProviderError("model returned no text")
        try:
            out = json.loads(text)
        except ValueError as exc:
            raise ProviderError(f"model output is not valid JSON (char {getattr(exc, 'pos', '?')})") from None
        if not isinstance(out, dict):
            raise ProviderError("model output is not a JSON object")
        return out

    def converse_json(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        max_tokens: int | None = None,
        *,
        schema_name: str = "response",
    ) -> tuple[dict[str, Any], Usage]:
        """Ask for one JSON object that matches ``schema``. Returns (object, Usage).

        The caller still validates the object against the pack schema; this method only
        guarantees it parsed as a JSON object.
        """
        limit = max_tokens if max_tokens is not None else self.spec.max_tokens
        request = self._request(system, user, schema, limit, schema_name)
        started = time.perf_counter()
        response = self._call(request)
        latency_ms = (time.perf_counter() - started) * 1000.0
        usage_in = response.get("usage") or {}
        # OpenAI on Bedrock reports cached prompt tokens apart from inputTokens (live: inputTokens=2).
        # Count them at the full rate, as evals/model_select.py does: cost is an upper bound.
        in_tok = int(usage_in.get("inputTokens", 0)) + int(usage_in.get("cacheReadInputTokens", 0)) + int(
            usage_in.get("cacheWriteInputTokens", 0)
        )
        out_tok = int(usage_in.get("outputTokens", 0))
        cost = compute_cost(self.spec, in_tok, out_tok)
        usage = Usage(
            model_id=self.spec.profile_id,
            input_tokens=in_tok,
            output_tokens=out_tok,
            latency_ms=round(latency_ms, 1),
            cost_usd=cost,
        )
        log.info(
            "model_call model=%s in=%d out=%d latency_ms=%.0f", usage.model_id, in_tok, out_tok, latency_ms
        )
        self._emit_metrics(usage)
        return self._extract(response), usage

    async def aconverse_json(self, *args: Any, **kwargs: Any) -> tuple[dict[str, Any], Usage]:
        """Async wrapper: runs converse_json in a worker thread. The shared bucket is thread safe."""
        return await asyncio.to_thread(self.converse_json, *args, **kwargs)

    def _emit_metrics(self, usage: Usage) -> None:
        dims = {"ModelId": usage.model_id}
        metrics.put_metric("ModelCalls", 1, "Count", dims)
        metrics.put_metric("ModelTokens", usage.input_tokens, "Count", {**dims, "Direction": "input"})
        metrics.put_metric("ModelTokens", usage.output_tokens, "Count", {**dims, "Direction": "output"})
        metrics.put_metric("LatencyMs", usage.latency_ms, "Milliseconds", dims)
        if usage.cost_usd is not None:
            metrics.put_metric("CostUsd", usage.cost_usd, "None", dims)
