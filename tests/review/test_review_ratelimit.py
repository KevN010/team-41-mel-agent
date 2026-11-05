"""Review item 13: rate limiter bypass by concurrency.

CLAUDE.md: 60 requests/minute process-wide for ALL model calls, and Jev (mel/judge.py) is one
of the two model calls. (a) JevJudge never takes a token from mel.providers.ratelimit, so Jev
calls are unlimited. (b) The bucket is per process; the mel-api Lambda has no reserved
concurrency, so N concurrent requests run in N fresh processes, each with its own 60 rpm.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest

from mel.judge import JevJudge
from mel.models import Insight, Survey
from mel.providers import ratelimit
from mel.settings import JEV_CHECKS

from ._harness import sc3_parts

ROOT = Path(__file__).resolve().parents[2]


class CountingBucket(ratelimit.TokenBucket):
    def __init__(self) -> None:
        super().__init__(60)
        self.taken = 0

    def acquire(self) -> float:
        self.taken += 1
        return 0.0

    async def acquire_async(self) -> float:
        self.taken += 1
        return 0.0


@pytest.mark.xfail(strict=True, reason="REVIEW item 13: Jev calls bypass the shared token bucket")
def test_jev_call_takes_a_token_from_the_shared_bucket(monkeypatch):
    bucket = CountingBucket()
    monkeypatch.setattr(ratelimit, "_shared", bucket)
    insight_raw, survey, _h = sc3_parts()
    body = {"answers": {c: {"noul": 0.9 if c == "matches_advice" else 0.01} for c in JEV_CHECKS}}
    judge = JevJudge(
        url="https://api.typesafe.ai/v1/systemone", api_key="k", thresholds={c: 0.5 for c in JEV_CHECKS},
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=body)), sleep=lambda s: None,
    )
    verdict = judge.check_survey(Insight.model_validate(insight_raw), Survey.model_validate(survey.to_pack()))
    assert verdict.ok
    assert bucket.taken >= 1


@pytest.mark.xfail(strict=True, reason="REVIEW item 13: per-process bucket; Lambda scales out with no cap")
def test_api_lambda_concurrency_is_pinned_so_the_bucket_is_global():
    app = (ROOT / "infra" / "app.py").read_text(encoding="utf-8")
    fn = re.search(r'lambda_\.Function\(self, "Handler".*?\)\n', app, re.DOTALL)
    assert fn is not None
    assert re.search(r"reserved_concurrent_executions\s*=\s*1\b", fn.group(0))
