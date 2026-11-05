"""Integration: Lambda handler and AgentCore entrypoint over in-memory services (offline).

Covers the demo path decide -> survey -> handoff -> advance clock -> respond "spreading" ->
follow-up, scenario 6 (no survey), the events path on the responses route, opt-out, identity
scoping, and that the demo clock can only be moved on the AgentCore path.
"""

from __future__ import annotations

import base64
import copy
import json
from datetime import datetime, timedelta

import pytest

from mel import agent
from mel.api import handler
from mel.api.service import JsonFormatter, Services
from mel.democlock import DemoClock, MemoryClockStore
from mel.fixtures import load_crop_calendar, load_outcome_codes, load_rules
from mel.ledger_mem import InMemoryLedger
from mel.models import IST, JudgeVerdict, Usage

ORG = "org.farmerchat"


class DraftGenerator:
    def __init__(self, draft):
        self.draft = draft
        self.calls = 0

    def generate(self, insight, language, timing_profile, model_key, *, repair_errors=None):
        self.calls += 1
        return copy.deepcopy(self.draft), Usage(model_id="global.openai.gpt-6-luna", input_tokens=900,
                                                output_tokens=250, latency_ms=12.0, cost_usd=0.000215)


class OkJudge:
    def check_survey(self, insight, survey):
        return JudgeVerdict(ok=True, scores={"matches_advice": 0.9, "gives_new_advice": 0.1})


class ListQueue:
    def __init__(self):
        self.sent = []

    def send(self, org_id, item):
        self.sent.append((org_id, item))


def _scenario(scenarios, prefix):
    return next(s for s in scenarios if s["name"].startswith(prefix))


@pytest.fixture
def potato(scenarios):
    return _scenario(scenarios, "3-")


@pytest.fixture
def svc(potato):
    pack = potato["survey_by_lang"]["en-IN"]
    created = datetime.fromisoformat(potato["insight"]["created_at"])
    wall = {"now": created}
    services = Services(
        ledger=InMemoryLedger(),
        clock_store=MemoryClockStore(),
        generator=DraftGenerator({"items": pack["items"], "rationale": pack["rationale"]}),
        judge=OkJudge(),
        rules=load_rules(),
        calendar=load_crop_calendar(),
        codes=load_outcome_codes(),
        queue=ListQueue(),
        wall=lambda: wall["now"],
    )
    services._wall_box = wall  # type: ignore[attr-defined]
    return services


def _event(route, body=None, farmer="F-000245", org=ORG, survey_id=None, b64=False):
    ev = {
        "routeKey": route,
        "requestContext": {"requestId": "r-1", "authorizer": {"jwt": {"claims": {
            "sub": "user-1", "custom:farmer_id": farmer, "custom:org_id": org}}}},
    }
    if survey_id is not None:
        ev["pathParameters"] = {"id": survey_id}
    if body is not None:
        raw = json.dumps(body)
        ev["body"] = base64.b64encode(raw.encode()).decode() if b64 else raw
        ev["isBase64Encoded"] = b64
    return ev


def _call(svc, *args, **kwargs):
    out = handler.handle(_event(*args, **kwargs), svc)
    return out["statusCode"], json.loads(out["body"])


def _decide(svc, insight, **kw):
    return _call(svc, "POST /surveys/decide", insight, **kw)


# --------------------------------------------------------------------------- demo path


def test_potato_demo_path(svc, potato):
    status, body = _decide(svc, potato["insight"])
    assert status == 201, body
    assert body["status"] == "survey_scheduled"
    assert body["decision"]["rule_id"] == "R8"
    survey = body["survey"]
    assert body["handoff"]["survey"]["survey_id"] == survey["survey_id"]
    assert svc.generator.calls == 1

    status, got = _call(svc, "GET /surveys/{id}", survey_id=survey["survey_id"])
    assert status == 200 and got["survey"] == survey

    # Advance the server demo clock into the send window (AgentCore admin action only).
    start = survey["send_window"]["not_before"]
    out = agent.handle({"action": "clock", "identity": {"farmer_id": "F-000245", "org_id": ORG},
                        "payload": {"op": "set", "at": start}}, svc)
    assert out["status"] == 200
    out = agent.handle({"action": "clock", "identity": {"farmer_id": "F-000245", "org_id": ORG},
                        "payload": {"op": "advance", "seconds": 3600}}, svc)
    assert datetime.fromisoformat(out["body"]["now"]) == datetime.fromisoformat(start) + timedelta(hours=1)

    status, body = _call(svc, "POST /surveys/{id}/responses", {
        "response_key": "rk-1", "channel": "whatsapp", "answers": {"q2": "spreading"}},
        survey_id=survey["survey_id"])
    assert status == 201, body
    record = body["response"]
    assert record["needs_follow_up"] is True
    assert record["follow_up_reasons"] == ["crop_or_animal_damaged"]
    assert record["recorded_at"].startswith(start[:10])

    status, body = _call(svc, "GET /follow-ups")
    assert status == 200
    assert [i["survey_id"] for i in body["items"]] == [survey["survey_id"]]
    assert len(svc.queue.sent) == 1

    # Same farmer, same org through the AgentCore path: the same functions answer.
    out = agent.handle({"action": "follow_ups", "identity": {"farmer_id": "F-000245", "org_id": ORG}}, svc)
    assert out["status"] == 200 and len(out["body"]["items"]) == 1


def test_answer_before_window_is_stale_on_real_clock(svc, potato):
    _, body = _decide(svc, potato["insight"])
    sid = body["survey"]["survey_id"]
    svc._wall_box["now"] = datetime.fromisoformat(body["survey"]["send_window"]["not_after"]) + timedelta(days=1)
    status, body = _call(svc, "POST /surveys/{id}/responses", {
        "response_key": "rk-late", "channel": "app", "answers": {"q1": "yes"}}, survey_id=sid)
    assert status == 410 and body["response"]["status"] == "stale"


def test_scenario6_no_survey(svc, scenarios):
    insight = _scenario(scenarios, "6-")["insight"]
    status, body = _decide(svc, insight, farmer=insight["farmer_id"])
    assert status == 200
    assert body["status"] == "no_survey"
    assert body["decision"]["rule_id"] == "R3"
    assert body["no_survey"]["reason_code"] == "generic_information"
    assert svc.generator.calls == 0


# --------------------------------------------------------------------------- events on the responses route


@pytest.fixture
def scheduled(svc, potato):
    _, body = _decide(svc, potato["insight"])
    agent.handle({"action": "clock", "identity": {"farmer_id": "F-000245", "org_id": ORG},
                  "payload": {"op": "set", "at": body["survey"]["send_window"]["not_before"]}}, svc)
    return body["survey"]["survey_id"]


def test_failure_event(svc, scheduled):
    status, body = _call(svc, "POST /surveys/{id}/responses", {
        "response_key": "rk-f", "channel": "app", "kind": "failure", "failure_code": "push_token_invalid"},
        survey_id=scheduled)
    assert status == 201, body
    assert body["response"]["failure_code"] == "push_token_invalid"
    assert body["response"]["retry_decision"] == "fall_back_to_next_channel"
    status, again = _call(svc, "POST /surveys/{id}/responses", {
        "response_key": "rk-f", "channel": "app", "kind": "failure", "failure_code": "push_token_invalid"},
        survey_id=scheduled)
    assert status == 200 and again["response"] == body["response"]


def test_decline_and_opt_out_events(svc, scheduled, potato):
    status, body = _call(svc, "POST /surveys/{id}/responses", {
        "response_key": "rk-d", "channel": "whatsapp", "kind": "decline"}, survey_id=scheduled)
    assert status == 201 and body["response"]["failure_code"] == "farmer_declined"
    status, body = _call(svc, "POST /surveys/{id}/responses", {
        "response_key": "rk-o", "channel": "whatsapp", "kind": "opt_out"}, survey_id=scheduled)
    assert status == 201 and body["response"]["failure_code"] == "farmer_opted_out"
    assert svc.ledger.is_opted_out(ORG, "F-000245")
    status, body = _decide(svc, potato["insight"])
    assert body["status"] == "opted_out"


def test_event_rejects_unknown_code_and_extra_keys(svc, scheduled):
    for bad in ({"response_key": "k", "channel": "app", "kind": "failure", "failure_code": "made_up"},
                {"response_key": "k", "channel": "app", "kind": "failure"},
                {"response_key": "k", "channel": "app", "kind": "decline", "farmer_id": "F-1"},
                {"response_key": "k", "channel": "whatsapp", "kind": "decline", "sheet_outcome": "dismissed"}):
        status, body = _call(svc, "POST /surveys/{id}/responses", bad, survey_id=scheduled)
        assert status == 400 and body == {"error": "invalid_request"}, bad


def test_opt_out_route(svc):
    status, body = _call(svc, "POST /farmers/me/opt-out")
    assert status == 200 and body["opted_out"] is True
    assert svc.ledger.is_opted_out(ORG, "F-000245")


# --------------------------------------------------------------------------- identity and routing


def test_other_farmer_cannot_read_or_answer(svc, scheduled):
    status, body = _call(svc, "GET /surveys/{id}", survey_id=scheduled, farmer="F-000999")
    assert status == 403 and body == {"error": "identity_mismatch"}
    status, body = _call(svc, "POST /surveys/{id}/responses", {
        "response_key": "x", "channel": "app", "answers": {"q1": "yes"}}, survey_id=scheduled, farmer="F-000999")
    assert status == 403
    status, body = _call(svc, "GET /surveys/{id}", survey_id=scheduled, org="org.other")
    assert status == 404 and body == {"error": "unknown_survey"}


def test_follow_ups_are_scoped_to_the_farmer(svc, scheduled):
    _call(svc, "POST /surveys/{id}/responses", {
        "response_key": "rk-1", "channel": "app", "answers": {"q2": "spreading"}}, survey_id=scheduled)
    _, mine = _call(svc, "GET /follow-ups")
    _, other = _call(svc, "GET /follow-ups", farmer="F-000999")
    assert len(mine["items"]) == 1 and other["items"] == []


def test_decide_for_another_farmer_is_refused(svc, potato):
    status, body = _decide(svc, potato["insight"], farmer="F-000999")
    assert status == 403 and body == {"error": "identity_mismatch"}


def test_handler_rejects_bad_requests(svc):
    out = handler.handle({"routeKey": "POST /surveys/decide"}, svc)
    assert out["statusCode"] == 401
    out = handler.handle(_event("DELETE /surveys/{id}"), svc)
    assert out["statusCode"] == 404
    ev = _event("POST /surveys/decide")
    ev["body"] = "{not json"
    assert handler.handle(ev, svc)["statusCode"] == 400
    ev["body"] = json.dumps({"x": "y" * (handler.MAX_BODY_BYTES + 1)})
    assert handler.handle(ev, svc)["statusCode"] == 400
    assert handler.handle(_event("POST /surveys/decide"), svc)["statusCode"] == 400  # no body
    status, _ = _call(svc, "GET /surveys/{id}", survey_id="../../etc")
    assert status == 400


def test_base64_body(svc, scenarios):
    insight = _scenario(scenarios, "6-")["insight"]
    status, body = _decide(svc, insight, farmer=insight["farmer_id"], b64=True)
    assert status == 200 and body["status"] == "no_survey"


def test_clock_is_not_reachable_from_lambda(svc):
    from mel.api.service import dispatch

    ident = agent.identity_from_request({"identity": {"farmer_id": "F-000245", "org_id": ORG}})
    assert dispatch("clock", ident, {"op": "reset"}, svc).status == 400
    assert "clock" not in handler.ROUTES.values()


def test_agent_requires_identity(svc):
    assert agent.handle({"action": "follow_ups"}, svc)["status"] == 401
    assert agent.handle({"action": "follow_ups", "identity": {"farmer_id": "F#1", "org_id": ORG}}, svc)["status"] == 401
    assert agent.handle("nope", svc)["status"] == 400
    out = agent.handle({"action": "nope", "identity": {"farmer_id": "F-1", "org_id": ORG}}, svc)
    assert out == {"status": 400, "body": {"error": "unknown_action"}}


def test_agent_clock_validation(svc):
    ident = {"farmer_id": "F-000245", "org_id": ORG}
    for payload in ({"op": "set", "at": "2027-01-09T07:00:00"},  # naive
                    {"op": "advance", "seconds": -5}, {"op": "advance", "seconds": True},
                    {"op": "set", "at": "2099-01-01T00:00:00+05:30"}, {"op": "jump"}):
        assert agent.handle({"action": "clock", "identity": ident, "payload": payload}, svc)["status"] == 400
    assert agent.handle({"action": "clock", "identity": ident, "payload": {"op": "reset"}}, svc)["body"]["offset_s"] == 0


def test_internal_errors_do_not_leak(svc, potato):
    class Boom:
        def is_opted_out(self, *a):
            raise RuntimeError("secret detail F-000245")

        def __getattr__(self, name):
            return getattr(svc_ledger, name)

    svc_ledger = svc.ledger
    svc.ledger = Boom()
    status, body = _decide(svc, potato["insight"])
    assert status == 500 and body == {"error": "internal_error"}


# --------------------------------------------------------------------------- demo clock, logging


def test_demo_clock_offset_is_per_org():
    store = MemoryClockStore()
    wall = datetime(2026, 11, 5, 9, 0, tzinfo=IST)
    a = DemoClock(store, "org.a", wall=lambda: wall)
    a.set(datetime(2027, 1, 9, 7, 0, tzinfo=IST))
    assert DemoClock(store, "org.a", wall=lambda: wall).now() == datetime(2027, 1, 9, 7, 0, tzinfo=IST)
    assert DemoClock(store, "org.b", wall=lambda: wall).now() == wall
    with pytest.raises(ValueError):
        a.advance(timedelta(seconds=-1))


def test_demo_clock_dynamo_store(monkeypatch):
    for k, v in {"AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing",
                 "AWS_SESSION_TOKEN": "testing", "AWS_DEFAULT_REGION": "us-west-2"}.items():
        monkeypatch.setenv(k, v)
    import boto3
    from moto import mock_aws

    from mel.democlock import DynamoClockStore

    with mock_aws():
        res = boto3.resource("dynamodb", region_name="us-west-2")
        res.create_table(TableName="t", KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"},
                                                   {"AttributeName": "sk", "KeyType": "RANGE"}],
                         AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"},
                                               {"AttributeName": "sk", "AttributeType": "S"}],
                         BillingMode="PAY_PER_REQUEST")
        store = DynamoClockStore(res.meta.client, "t")
        assert store.get_offset("org.a") == timedelta(0)
        store.set_offset("org.a", timedelta(days=65, seconds=7))
        assert store.get_offset("org.a") == timedelta(days=65, seconds=7)


def test_json_log_keeps_only_whitelisted_fields():
    import logging

    rec = logging.LogRecord("mel.x", logging.INFO, __file__, 1, "decision", None, None)
    rec.rule_id = "R8"
    rec.farmer_id = "F-000245"
    rec.insight_text = "spray now"
    out = json.loads(JsonFormatter().format(rec))
    assert out["rule_id"] == "R8" and "farmer_id" not in out and "insight_text" not in out


# --------------------------------------------------------------------------- cap and opt-out race


def test_counted_outcome_caps_the_next_normal_survey(svc, scheduled, potato):
    status, body = _call(svc, "POST /surveys/{id}/responses", {
        "response_key": "rk-c", "channel": "app", "answers": {"q1": "yes", "q2": "no_new", "q3": 4}},
        survey_id=scheduled)
    assert status == 201 and body["response"]["counts_toward_cap"] is True
    status, body = _decide(svc, potato["insight"])
    assert status == 200 and body["status"] == "frequency_capped"
    assert svc.generator.calls == 1  # no model call for the capped decision


def test_opt_out_during_generation_stores_nothing(svc, potato):
    gen = svc.generator
    real = gen.generate

    def generate_then_opt_out(*a, **k):
        svc.ledger.set_opt_out(ORG, "F-000245", datetime(2027, 1, 6, 9, 0, tzinfo=IST))
        return real(*a, **k)

    gen.generate = generate_then_opt_out
    _, body = _decide(svc, potato["insight"])
    assert body["status"] == "opted_out" and body["survey"] is None
    assert svc.ledger.find_survey_owner(ORG, "S-00001") is None
