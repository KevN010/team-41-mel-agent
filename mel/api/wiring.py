"""Build the real Services from the deployed environment. Used by the Lambda handler and mel.agent.

Configuration (CLAUDE.md): MEL_* environment variables first, SSM parameters under /mel/ when a
variable is unset. The Jev key is JEV_API_KEY when that env var is set; otherwise it is read from
Secrets Manager (MEL_JEV_SECRET_ARN, the name infra deploys) and refreshed
every JEV_KEY_TTL_S, so a key set by hand after deploy is picked up without a redeploy. The key
value is never logged; a placeholder (REPLACE_ME) counts as no key, and the judge then fails closed
(pending_review, jev_key_missing).

Nothing here runs at import time; ``get_services()`` builds once per process.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

from mel.api.service import CloudWatchMetrics, Services
from mel.models import Insight, JudgeVerdict, Survey

log = logging.getLogger("mel.wiring")

JEV_KEY_TTL_S = 300.0
# System One requires "model" (HTTP 422 without it). jev-latest matches main (Dwayne, 2026-11-05);
# JEV_MODEL overrides it.
DEFAULT_JEV_MODEL = "jev-latest"
PLACEHOLDERS = {"", "REPLACE_ME", "replace_me", "CHANGEME"}
SSM_NAMES = {
    "MEL_TABLE": "table_name",
    "MEL_FOLLOWUP_QUEUE_URL": "followup_queue_url",
    "MEL_JEV_SECRET_ARN": "jev_secret_arn",
}

_services: Services | None = None
_lock = threading.Lock()


def _region() -> str:
    from mel.settings import settings

    return settings.REGION


def config_value(name: str, ssm_client: Any = None) -> str | None:
    """Env var ``name``, else SSM /mel/<param>, else None."""
    value = os.environ.get(name)
    if value:
        return value
    param = SSM_NAMES.get(name)
    if param is None:
        return None
    try:
        import boto3

        ssm = ssm_client or boto3.client("ssm", region_name=_region())
        return ssm.get_parameter(Name="/mel/" + param)["Parameter"]["Value"]
    except Exception as exc:  # noqa: BLE001 - missing config is reported by the caller
        log.warning("ssm fallback failed", extra={"error_class": type(exc).__name__})
        return None


def parse_secret(secret: str | None) -> str | None:
    """Plain string, or JSON with api_key / key / JEV_API_KEY. Placeholders count as missing."""
    if secret is None:
        return None
    value = secret.strip()
    if value.startswith("{"):
        try:
            data = json.loads(value)
        except ValueError:
            return None
        value = next((str(data[k]).strip() for k in ("api_key", "key", "JEV_API_KEY") if data.get(k)), "")
    return None if value in PLACEHOLDERS else value


class RefreshingJevJudge:
    """Judge that reads the Jev key from Secrets Manager, cached for JEV_KEY_TTL_S."""

    def __init__(self, secret_arn: str | None, client: Any = None, *, ttl_s: float = JEV_KEY_TTL_S) -> None:
        self._arn = secret_arn
        self._client = client
        self._ttl_s = ttl_s
        self._judge: Any = None
        self._loaded_at = -1e18
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return "RefreshingJevJudge(<key hidden>)"

    def _key(self) -> str | None:
        # JEV_API_KEY (settings) wins when it is set; otherwise the secret named by MEL_JEV_SECRET_ARN,
        # which is what infra puts on the Lambda and the container.
        from mel.settings import settings

        if settings.JEV_API_KEY is not None:
            return parse_secret(settings.JEV_API_KEY.get_secret_value())
        if not self._arn:
            return None
        try:
            if self._client is None:
                import boto3

                self._client = boto3.client("secretsmanager", region_name=_region())
            return parse_secret(self._client.get_secret_value(SecretId=self._arn).get("SecretString"))
        except Exception as exc:  # noqa: BLE001 - no key means the judge fails closed
            log.warning("jev key unavailable", extra={"error_class": type(exc).__name__})
            return None

    def _current(self) -> Any:
        from mel.judge import JevJudge

        with self._lock:
            if self._judge is None or time.monotonic() - self._loaded_at > self._ttl_s:
                key = self._key()
                # api_key="" (not None) keeps JevJudge from falling back to settings.JEV_API_KEY.
                self._judge = JevJudge(api_key=key or "", model=os.environ.get("JEV_MODEL") or DEFAULT_JEV_MODEL)
                self._loaded_at = time.monotonic()
            return self._judge

    def check_survey(self, insight: Insight, survey: Survey) -> JudgeVerdict:
        from mel.providers.ratelimit import get_bucket

        get_bucket().acquire()  # Jev counts against the same 60/min process-wide budget (CLAUDE.md)
        return self._current().check_survey(insight, survey)


def build_services() -> Services:
    import boto3

    from mel.api.intake import SqsFollowUpQueue
    from mel.democlock import DynamoClockStore
    from mel.fixtures import load_crop_calendar, load_outcome_codes, load_rules
    from mel.generate import LlmSurveyGenerator
    from mel.ledger_ddb import DynamoLedger
    from mel.providers.bedrock import BedrockChat
    from mel.settings import settings

    region = _region()
    table = config_value("MEL_TABLE") or settings.LEDGER_TABLE
    queue_url = config_value("MEL_FOLLOWUP_QUEUE_URL") or settings.FOLLOW_UP_QUEUE_URL
    ddb = boto3.resource("dynamodb", region_name=region).meta.client
    chats: dict[str, BedrockChat] = {}

    def chat_for(model_key: str) -> BedrockChat:
        if model_key not in chats:
            chats[model_key] = BedrockChat(model_key)
        return chats[model_key]

    return Services(
        ledger=DynamoLedger(table, region, client=ddb),
        clock_store=DynamoClockStore(ddb, table),
        generator=LlmSurveyGenerator(chat_for),
        judge=RefreshingJevJudge(config_value("MEL_JEV_SECRET_ARN")),
        rules=load_rules(),
        calendar=load_crop_calendar(),
        codes=load_outcome_codes(),
        queue=SqsFollowUpQueue(boto3.client("sqs", region_name=region), queue_url) if queue_url else None,
        metrics=CloudWatchMetrics(),
    )


def get_services() -> Services:
    global _services
    with _lock:
        if _services is None:
            _services = build_services()
        return _services


def set_services(services: Services | None) -> None:
    """Tests inject in-memory services; None rebuilds from the environment on next use."""
    global _services
    with _lock:
        _services = services


__all__ = ["RefreshingJevJudge", "build_services", "config_value", "get_services", "parse_secret", "set_services"]
