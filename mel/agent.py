"""AgentCore Runtime entrypoint (container CMD ``python -m mel.agent``).

Request: ``{"action": "decide|get_survey|respond|follow_ups|opt_out|clock", "identity":
{"farmer_id", "org_id", "sub"?}, "payload": {...}}``. Reply: ``{"status": <http-like int>, "body": {...}}``.

Trust: InvokeAgentRuntime is authorised by IAM SigV4, so the caller is a trusted backend
(FarmerChat, or the operator running the demo). It asserts the farmer identity, which is checked
with the same patterns as the JWT claims. The ``clock`` admin action exists only on this path.
Same functions as the Lambda path (mel.api.service.dispatch); no business logic here.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mel.api.auth import Unauthorized, claims_from_event
from mel.api.service import Reply, Services, configure_logging, dispatch


def identity_from_request(request: Mapping[str, Any]) -> Any:
    raw = request.get("identity")
    if not isinstance(raw, Mapping):
        raise Unauthorized("no identity")
    claims = {
        "custom:farmer_id": raw.get("farmer_id"),
        "custom:org_id": raw.get("org_id"),
        "sub": raw.get("sub") or "agentcore-caller",
    }
    # Reuse the JWT claim checks: same id patterns, same refusal on a missing value.
    return claims_from_event({"requestContext": {"authorizer": {"claims": claims}}})


def handle(request: Any, services: Services | None = None) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        return {"status": 400, "body": {"error": "invalid_request"}}
    try:
        identity = identity_from_request(request)
    except Unauthorized:
        return {"status": 401, "body": {"error": "unauthorized"}}
    if services is None:
        try:
            from mel.api.wiring import get_services

            services = get_services()
        except Exception:  # noqa: BLE001 - config or AWS client failure
            return {"status": 500, "body": {"error": "internal_error"}}
    reply: Reply = dispatch(str(request.get("action")), identity, request.get("payload") or {}, services, admin=True)
    return {"status": reply.status, "body": reply.body}


def _make_app() -> Any:
    from bedrock_agentcore.runtime import BedrockAgentCoreApp

    app = BedrockAgentCoreApp()

    @app.entrypoint
    def invoke(payload: Any) -> dict[str, Any]:
        return handle(payload)

    return app


if __name__ == "__main__":
    configure_logging()
    _make_app().run()
