"""CloudWatch custom metrics (namespace from settings.METRICS_NAMESPACE, default MelAgent).

Metric names in use: DecisionsByRule, ModelCalls, ModelTokens, JudgeVerdicts, LatencyMs, CostUsd.
``put_metric`` never raises and never logs values it was not given as dimensions. It is a
no-op when settings.METRICS_OFF is true.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import boto3

from mel.settings import settings

log = logging.getLogger(__name__)

_client: Any = None
_client_lock = threading.Lock()


def set_client(client: Any) -> None:
    """Use this CloudWatch client (tests). Pass None to go back to the default."""
    global _client
    with _client_lock:
        _client = client


def _get_client() -> Any:
    global _client
    with _client_lock:
        if _client is None:
            _client = boto3.client("cloudwatch", region_name=settings.REGION)
        return _client


def put_metric(
    name: str,
    value: float,
    unit: str = "None",
    dims: dict[str, str] | None = None,
) -> bool:
    """Send one data point. Returns True when it was sent, False when skipped or failed."""
    if settings.METRICS_OFF:
        return False
    datum: dict[str, Any] = {"MetricName": name, "Value": float(value), "Unit": unit}
    if dims:
        datum["Dimensions"] = [{"Name": k, "Value": str(v)} for k, v in sorted(dims.items())]
    try:
        _get_client().put_metric_data(Namespace=settings.METRICS_NAMESPACE, MetricData=[datum])
    except Exception as exc:  # noqa: BLE001 - metrics must never break a request
        log.warning("put_metric failed metric=%s error=%s", name, type(exc).__name__)
        return False
    return True
