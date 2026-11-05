"""Lambda entrypoint for the HTTP API (payload format 2.0). ``mel.api.handler.lambda_handler``.

Routes (fixed by infra/app.py, every one behind the Cognito JWT authorizer):
  POST /surveys/decide            -> decide       (body: the insight JSON)
  GET  /surveys/{id}              -> get_survey
  POST /surveys/{id}/responses    -> respond      (answers, or kind failure|decline|opt_out)
  GET  /follow-ups                -> follow_ups   (this farmer's items)
  POST /farmers/me/opt-out        -> opt_out

Identity comes only from the authorizer's JWT claims (mel.api.auth). The demo clock cannot be
moved from here; that is an AgentCore-only admin action (mel.agent).
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
from collections.abc import Mapping
from typing import Any

from mel.api.auth import Unauthorized, claims_from_event
from mel.api.service import Reply, Services, configure_logging, dispatch

log = logging.getLogger("mel.handler")

MAX_BODY_BYTES = 64 * 1024

ROUTES = {
    "POST /surveys/decide": "decide",
    "GET /surveys/{id}": "get_survey",
    "POST /surveys/{id}/responses": "respond",
    "GET /follow-ups": "follow_ups",
    "POST /farmers/me/opt-out": "opt_out",
}
BODY_ACTIONS = ("decide", "respond")


class BadRequest(Exception):
    pass


def _response(reply: Reply) -> dict[str, Any]:
    return {
        "statusCode": reply.status,
        "headers": {"content-type": "application/json", "cache-control": "no-store"},
        "body": json.dumps(reply.body, default=str),
    }


def _body(event: Mapping[str, Any]) -> Any:
    raw = event.get("body")
    if raw is None or raw == "":
        raise BadRequest
    if not isinstance(raw, str) or len(raw) > MAX_BODY_BYTES * 4 // 3 + 4:
        raise BadRequest
    if event.get("isBase64Encoded"):
        try:
            raw = base64.b64decode(raw, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            raise BadRequest from None
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_BODY_BYTES:
        raise BadRequest
    try:
        return json.loads(raw)
    except (ValueError, RecursionError):
        raise BadRequest from None


def _payload(action: str, event: Mapping[str, Any]) -> Any:
    body = _body(event) if action in BODY_ACTIONS else None
    if action in ("get_survey", "respond"):
        survey_id = (event.get("pathParameters") or {}).get("id")
        return {"survey_id": survey_id, "response": body}
    return body if body is not None else {}


def handle(event: Mapping[str, Any], services: Services | None = None) -> dict[str, Any]:
    route = event.get("routeKey") if isinstance(event, Mapping) else None
    action = ROUTES.get(route or "")
    request_id = ((event.get("requestContext") or {}).get("requestId")) if isinstance(event, Mapping) else None
    if action is None:
        return _response(Reply(404, {"error": "unknown_route"}))
    try:
        identity = claims_from_event(event)
    except Unauthorized:
        return _response(Reply(401, {"error": "unauthorized"}))
    try:
        payload = _payload(action, event)
    except BadRequest:
        return _response(Reply(400, {"error": "invalid_request"}))
    if services is None:
        try:
            from mel.api.wiring import get_services

            services = get_services()
        except Exception as exc:  # noqa: BLE001 - config or AWS client failure; class name only
            log.error("service setup failed", extra={"error_class": type(exc).__name__})
            return _response(Reply(500, {"error": "internal_error"}))
    reply = dispatch(action, identity, payload, services)
    log.info("request", extra={"route": route, "action": action, "http_status": reply.status,
                               "request_id": request_id})
    return _response(reply)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    configure_logging()
    return handle(event)


__all__ = ["ROUTES", "handle", "lambda_handler"]
