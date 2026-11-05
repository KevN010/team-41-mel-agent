"""claims_from_event reads the authorizer context only."""

from __future__ import annotations

import json

import pytest

from mel.api.auth import Identity, Unauthorized, claims_from_event

CLAIMS = {"sub": "sub-123", "custom:farmer_id": "F-000245", "custom:org_id": "org-digitalgreen"}


def http_event(claims=CLAIMS, **extra):
    return {"requestContext": {"authorizer": {"jwt": {"claims": dict(claims)}}}, **extra}


def rest_event(claims=CLAIMS):
    return {"requestContext": {"authorizer": {"claims": dict(claims)}}}


def test_http_api_authorizer():
    ident = claims_from_event(http_event())
    assert ident == Identity(farmer_id="F-000245", org_id="org-digitalgreen", sub="sub-123")


def test_rest_api_authorizer():
    assert claims_from_event(rest_event()).farmer_id == "F-000245"


@pytest.mark.parametrize("missing", ["sub", "custom:farmer_id", "custom:org_id"])
def test_missing_claim(missing):
    claims = {k: v for k, v in CLAIMS.items() if k != missing}
    with pytest.raises(Unauthorized) as exc:
        claims_from_event(http_event(claims))
    assert missing in str(exc.value)
    assert exc.value.http_status == 401


@pytest.mark.parametrize("bad", ["", "   ", None, 7, ["F-1"], "F 1", "F-1;DROP", "x" * 65])
def test_bad_farmer_claim(bad):
    with pytest.raises(Unauthorized):
        claims_from_event(http_event({**CLAIMS, "custom:farmer_id": bad}))


@pytest.mark.parametrize("event", [{}, {"requestContext": {}}, {"requestContext": {"authorizer": None}},
                                   {"requestContext": {"authorizer": {}}}, None, "x"])
def test_no_authorizer_context(event):
    with pytest.raises(Unauthorized):
        claims_from_event(event)


def test_body_headers_query_and_path_are_ignored():
    event = http_event(
        {"sub": "s", "custom:farmer_id": "F-1", "custom:org_id": "org-a"},
        body=json.dumps({"farmer_id": "F-999", "org_id": "org-b"}),
        headers={"x-farmer-id": "F-999", "x-org-id": "org-b"},
        queryStringParameters={"farmer_id": "F-999", "org_id": "org-b"},
        pathParameters={"farmer_id": "F-999"},
    )
    ident = claims_from_event(event)
    assert (ident.farmer_id, ident.org_id) == ("F-1", "org-a")


def test_body_cannot_stand_in_for_missing_claims():
    event = {"requestContext": {"authorizer": {"jwt": {"claims": {"sub": "s"}}}},
             "body": json.dumps({"farmer_id": "F-1", "org_id": "org-a"})}
    with pytest.raises(Unauthorized):
        claims_from_event(event)


def test_identity_repr_hides_ids():
    assert "F-000245" not in repr(claims_from_event(http_event()))
    assert "F-000245" not in str(Unauthorized("missing claim custom:farmer_id"))


def test_identity_is_frozen():
    ident = claims_from_event(http_event())
    with pytest.raises(AttributeError):
        ident.farmer_id = "F-2"  # type: ignore[misc]
