"""Identity from the API Gateway JWT authorizer context. Nothing else.

farmer_id and org_id come from the verified Cognito JWT claims that API Gateway puts in
``event["requestContext"]["authorizer"]``. They never come from the request body, the query
string, a path parameter or a header. API Gateway has already checked the signature; this
module only reads the result and refuses to continue when a claim is missing.

Claims: ``sub``, ``custom:farmer_id``, ``custom:org_id``.

Two authorizer shapes exist and both carry the same claims:
  HTTP API JWT authorizer:  requestContext.authorizer.jwt.claims
  REST API Cognito pool:    requestContext.authorizer.claims
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# Same shapes the pack and the DynamoDB keys allow. Keeps odd characters out of key strings.
_FARMER_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
_ORG_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_SUB_RE = re.compile(r"^[A-Za-z0-9._:@-]{1,128}$")


class Unauthorized(Exception):
    """No usable identity in the authorizer context. Map to HTTP 401.

    The message names the missing claim but never echoes a claim value.
    """

    http_status = 401
    code = "unauthorized"


@dataclass(frozen=True, slots=True)
class Identity:
    farmer_id: str
    org_id: str
    sub: str

    def __repr__(self) -> str:  # keep ids out of accidental log lines
        return "Identity(<redacted>)"


def _claims(event: Mapping[str, Any]) -> Mapping[str, Any]:
    ctx = event.get("requestContext") if isinstance(event, Mapping) else None
    authorizer = ctx.get("authorizer") if isinstance(ctx, Mapping) else None
    if not isinstance(authorizer, Mapping):
        raise Unauthorized("no authorizer context")
    jwt = authorizer.get("jwt")
    if isinstance(jwt, Mapping) and isinstance(jwt.get("claims"), Mapping):
        return jwt["claims"]
    if isinstance(authorizer.get("claims"), Mapping):
        return authorizer["claims"]
    raise Unauthorized("no JWT claims in authorizer context")


def _require(claims: Mapping[str, Any], name: str, pattern: re.Pattern[str]) -> str:
    value = claims.get(name)
    if not isinstance(value, str) or not value.strip():
        raise Unauthorized(f"missing claim {name}")
    value = value.strip()
    if not pattern.fullmatch(value):
        raise Unauthorized(f"malformed claim {name}")
    return value


def claims_from_event(event: Mapping[str, Any]) -> Identity:
    """Identity{farmer_id, org_id, sub} from the authorizer context, or raise Unauthorized."""
    claims = _claims(event)
    return Identity(
        farmer_id=_require(claims, "custom:farmer_id", _FARMER_ID_RE),
        org_id=_require(claims, "custom:org_id", _ORG_ID_RE),
        sub=_require(claims, "sub", _SUB_RE),
    )


__all__ = ["Identity", "Unauthorized", "claims_from_event"]
