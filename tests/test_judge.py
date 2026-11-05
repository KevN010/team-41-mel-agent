"""Offline tests for mel/judge.py. Jev is faked with httpx.MockTransport; no sockets."""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from mel.judge import (
    ALLOWED_HOSTS,
    QUESTIONS,
    JevJudge,
    build_state,
    decide,
    url_is_safe,
)
from mel.models import Insight, JudgeVerdict, Survey
from mel.protocols import Judge
from mel.settings import JEV_CHECKS, Settings

URL = "https://api.typesafe.ai/v1/systemone"
KEY = "sk-test-secret-key-123"
GOOD = {
    "matches_advice": 0.95,
    "gives_new_advice": 0.02,
    "asks_personal_info": 0.01,
    "inappropriate_content": 0.01,
    "language_matches_tag": 0.03,
}
THRESHOLDS = {check: 0.5 for check in JEV_CHECKS}


@pytest.fixture(scope="module")
def scenario(scenarios):
    return next(s for s in scenarios if s["name"] == "3-potato-blight-wait")


@pytest.fixture(scope="module")
def insight(scenario) -> Insight:
    return Insight.model_validate(scenario["insight"])


@pytest.fixture(scope="module")
def survey(scenario) -> Survey:
    return Survey.model_validate(scenario["survey_by_lang"]["en-IN"])


def answers_body(scores: dict) -> dict:
    return {"answers": {check: {"noul": value} for check, value in scores.items()}}


class FakeJev:
    """Records requests and replays a script of responses (or exceptions)."""

    def __init__(self, *script):
        self.script = list(script)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(step, Exception):
            raise step
        return step


def ok_response(scores=None) -> httpx.Response:
    return httpx.Response(200, json=answers_body(scores or GOOD))


def make_judge(fake: FakeJev, **kwargs) -> tuple[JevJudge, list[float]]:
    sleeps: list[float] = []
    judge = JevJudge(
        url=kwargs.pop("url", URL),
        api_key=kwargs.pop("api_key", KEY),
        thresholds=kwargs.pop("thresholds", THRESHOLDS),
        transport=httpx.MockTransport(fake),
        sleep=sleeps.append,
        **kwargs,
    )
    return judge, sleeps


def assert_pending(verdict: JudgeVerdict, reason_prefix: str | None = None):
    assert verdict.pending_review is True
    assert verdict.ok is False
    if reason_prefix:
        assert verdict.reason and verdict.reason.startswith(reason_prefix)


# --------------------------------------------------------------------------- protocol / request


def test_implements_judge_protocol():
    assert isinstance(JevJudge(api_key=KEY), Judge)


def test_ok_verdict_and_single_request(insight, survey):
    fake = FakeJev(ok_response())
    judge, _ = make_judge(fake)
    verdict = judge.check_survey(insight, survey)
    assert verdict.ok is True and verdict.pending_review is False and verdict.reason is None
    assert verdict.scores == GOOD
    assert len(fake.requests) == 1


def test_request_shape(insight, survey):
    fake = FakeJev(ok_response())
    judge, _ = make_judge(fake)
    judge.check_survey(insight, survey)
    request = fake.requests[0]
    assert request.method == "POST" and str(request.url) == URL
    assert request.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(request.content)
    assert set(body["questions"]) == set(JEV_CHECKS)
    assert all(q["type"] == "noul" for q in body["questions"].values())
    state = body["state"]
    assert set(state) == {"insight", "survey"}
    assert set(state["insight"]) == {"query_summary", "advice_summary", "resolution_type", "concern", "asset"}
    assert state["insight"]["advice_summary"] == insight.advice_summary
    assert state["insight"]["asset"]["name"] == "potato"
    assert state["survey"]["language"] == "en-IN"
    assert [i["item_id"] for i in state["survey"]["items"]] == ["q1", "q2", "q3"]
    assert state["survey"]["items"][1]["options"][0] == "No new spots"
    assert state["survey"]["items"][2]["scale_min"] == 1


def test_untrusted_text_only_in_state_never_in_questions(insight, survey):
    state = build_state(insight, survey)
    questions = json.dumps(QUESTIONS)
    assert insight.advice_summary not in questions and insight.query_summary not in questions
    assert insight.advice_summary in json.dumps(state)


def test_model_defaults_to_jev_1_14_0_and_can_be_overridden(insight, survey, monkeypatch):
    monkeypatch.delenv("JEV_MODEL", raising=False)
    fake = FakeJev(ok_response())
    judge, _ = make_judge(fake)
    judge.check_survey(insight, survey)
    assert json.loads(fake.requests[0].content)["model"] == "jev-1.14.0"
    monkeypatch.setenv("JEV_MODEL", "from-env")
    fake = FakeJev(ok_response())
    judge, _ = make_judge(fake)
    judge.check_survey(insight, survey)
    assert json.loads(fake.requests[0].content)["model"] == "from-env"
    fake = FakeJev(ok_response())
    judge, _ = make_judge(fake, model="system-one-x")
    judge.check_survey(insight, survey)
    assert json.loads(fake.requests[0].content)["model"] == "system-one-x"


def test_request_body_matches_the_working_system_one_shape(insight, survey, monkeypatch):
    """Offline guard for the 422 seen in the live run: POST .../v1/systemone, bearer header, and a body of
    exactly model + state + questions, with questions a dict keyed by check name and every question typed noul."""
    monkeypatch.delenv("JEV_MODEL", raising=False)
    fake = FakeJev(ok_response())
    judge, _ = make_judge(fake, url="https://api.typesafe.ai/v1/systemone")
    judge.check_survey(insight, survey)
    request = fake.requests[0]
    assert request.method == "POST" and str(request.url) == "https://api.typesafe.ai/v1/systemone"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(request.content)
    assert set(body) == {"model", "state", "questions"}
    assert body["model"] == "jev-1.14.0"
    assert isinstance(body["state"], dict)
    assert isinstance(body["questions"], dict) and list(body["questions"]) == list(JEV_CHECKS)
    for name, question in body["questions"].items():
        assert question["type"] == "noul", name
        assert isinstance(question["instructions"], str) and question["instructions"], name


# --------------------------------------------------------------------------- thresholds


@pytest.mark.parametrize(
    ("check", "bad_value"),
    [
        ("matches_advice", 0.2),
        ("gives_new_advice", 0.9),
        ("asks_personal_info", 0.9),
        ("inappropriate_content", 0.9),
        ("language_matches_tag", 0.9),
    ],
)
def test_each_failing_check_blocks(insight, survey, check, bad_value):
    fake = FakeJev(ok_response({**GOOD, check: bad_value}))
    judge, _ = make_judge(fake)
    verdict = judge.check_survey(insight, survey)
    assert verdict.ok is False and verdict.pending_review is False
    assert verdict.reason == f"failed:{check}"
    assert verdict.scores[check] == bad_value


def test_several_failures_listed_in_check_order(insight, survey):
    scores = {**GOOD, "language_matches_tag": 0.9, "matches_advice": 0.1}
    judge, _ = make_judge(FakeJev(ok_response(scores)))
    assert judge.check_survey(insight, survey).reason == "failed:matches_advice,language_matches_tag"


def test_boundaries_are_inclusive():
    scores = {check: 0.5 for check in JEV_CHECKS}
    assert decide(scores, THRESHOLDS) == []
    assert decide({**scores, "matches_advice": 0.4999}, THRESHOLDS) == ["matches_advice"]
    assert decide({**scores, "gives_new_advice": 0.5001}, THRESHOLDS) == ["gives_new_advice"]


def test_extremes_zero_and_one_are_valid(insight, survey):
    scores = {"matches_advice": 1, "gives_new_advice": 0, "asks_personal_info": 0.0,
              "inappropriate_content": 0, "language_matches_tag": 0}
    judge, _ = make_judge(FakeJev(ok_response(scores)))
    assert judge.check_survey(insight, survey).ok is True


def test_thresholds_come_from_settings(insight, survey):
    cfg = Settings.from_env({"JEV_API_KEY": KEY, "JEV_THRESHOLD_MATCHES_ADVICE": "0.99"})
    fake = FakeJev(ok_response())
    judge = JevJudge(cfg, transport=httpx.MockTransport(fake), sleep=lambda s: None)
    verdict = judge.check_survey(insight, survey)
    assert verdict.reason == "failed:matches_advice"  # 0.95 < 0.99
    assert str(fake.requests[0].url) == URL


# --------------------------------------------------------------------------- failure: fail closed


def test_timeout_retries_then_pending(insight, survey):
    fake = FakeJev(httpx.ReadTimeout("slow"))
    judge, sleeps = make_judge(fake, max_retries=2)
    verdict = judge.check_survey(insight, survey)
    assert_pending(verdict, "jev_timeout")
    assert verdict.scores == {}
    assert len(fake.requests) == 3 and len(sleeps) == 2


def test_timeout_then_success_recovers(insight, survey):
    fake = FakeJev(httpx.ConnectTimeout("slow"), ok_response())
    judge, _ = make_judge(fake)
    assert judge.check_survey(insight, survey).ok is True
    assert len(fake.requests) == 2


def test_deadline_stops_retries(insight, survey):
    ticks = iter([0.0, 0.0, 10.0, 10.0, 10.0, 10.0])
    fake = FakeJev(httpx.ReadTimeout("slow"))
    judge, _ = make_judge(fake, deadline_s=6.0, monotonic=lambda: next(ticks))
    assert_pending(judge.check_survey(insight, survey), "jev_deadline")
    assert len(fake.requests) == 1


@pytest.mark.parametrize("status", [500, 503, 429])
def test_retryable_status_retried_then_pending(insight, survey, status):
    fake = FakeJev(httpx.Response(status, json={"error": "x"}))
    judge, sleeps = make_judge(fake)
    verdict = judge.check_survey(insight, survey)
    assert_pending(verdict, f"jev_http_{status}")
    assert len(fake.requests) == 3 and len(sleeps) == 2


def test_retry_after_header_is_used_and_capped(insight, survey):
    fake = FakeJev(httpx.Response(429, headers={"retry-after": "60"}), ok_response())
    judge, sleeps = make_judge(fake)
    assert judge.check_survey(insight, survey).ok is True
    assert sleeps == [2.0]


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_non_retryable_status_not_retried(insight, survey, status):
    fake = FakeJev(httpx.Response(status, json={"error": "x"}))
    judge, sleeps = make_judge(fake)
    assert_pending(judge.check_survey(insight, survey), f"jev_http_{status}")
    assert len(fake.requests) == 1 and sleeps == []


def test_redirect_is_not_followed(insight, survey):
    fake = FakeJev(httpx.Response(302, headers={"location": "https://evil.example/steal"}))
    judge, _ = make_judge(fake)
    assert_pending(judge.check_survey(insight, survey), "jev_http_302")
    assert len(fake.requests) == 1


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not json at all"),
        httpx.Response(200, content=b'{"answers": {"matches_advice": '),
        httpx.Response(200, json={"no_answers": 1}),
        httpx.Response(200, json=[1, 2, 3]),
        httpx.Response(200, json={"answers": "nope"}),
        httpx.Response(200, json={"answers": []}),
    ],
)
def test_malformed_response_is_pending(insight, survey, response):
    fake = FakeJev(response)
    judge, _ = make_judge(fake)
    assert_pending(judge.check_survey(insight, survey), "jev_")
    assert len(fake.requests) == 1  # unreadable 200 is not retried


def test_missing_answer_is_pending(insight, survey):
    scores = dict(GOOD)
    del scores["asks_personal_info"]
    judge, _ = make_judge(FakeJev(ok_response(scores)))
    assert_pending(judge.check_survey(insight, survey), "jev_missing_answer:asks_personal_info")


def test_answer_without_noul_key_is_pending(insight, survey):
    body = answers_body(GOOD)
    body["answers"]["gives_new_advice"] = {"choice": "yes"}
    judge, _ = make_judge(FakeJev(httpx.Response(200, json=body)))
    assert_pending(judge.check_survey(insight, survey), "jev_missing_answer:gives_new_advice")


@pytest.mark.parametrize(
    "raw",
    ["NaN", "Infinity", "-Infinity", "1.0000001", "-0.0001", "2", "-1", '"0.1"', "true", "null", "[0.1]", "{}"],
)
def test_invalid_value_is_pending(insight, survey, raw):
    # Hand-written JSON, because json.dumps cannot be trusted to emit NaN the way a server might.
    fields = ",".join(f'"{c}":{{"noul":{GOOD[c]}}}' for c in JEV_CHECKS if c != "gives_new_advice")
    content = f'{{"answers":{{{fields},"gives_new_advice":{{"noul":{raw}}}}}}}'.encode()
    judge, _ = make_judge(FakeJev(httpx.Response(200, content=content, headers={"content-type": "application/json"})))
    verdict = judge.check_survey(insight, survey)
    assert_pending(verdict, "jev_invalid_score:gives_new_advice")
    assert verdict.scores == {}


def test_nan_in_matches_advice_never_ok(insight, survey):
    content = (
        b'{"answers":{"matches_advice":{"noul":NaN},"gives_new_advice":{"noul":0},'
        b'"asks_personal_info":{"noul":0},"inappropriate_content":{"noul":0},"language_matches_tag":{"noul":0}}}'
    )
    judge, _ = make_judge(FakeJev(httpx.Response(200, content=content)))
    verdict = judge.check_survey(insight, survey)
    assert_pending(verdict, "jev_invalid_score:matches_advice")


def test_unexpected_exception_is_pending(insight, survey):
    fake = FakeJev(RuntimeError("boom"))
    judge, _ = make_judge(fake)
    assert_pending(judge.check_survey(insight, survey), "jev_unexpected_error")


# --------------------------------------------------------------------------- wrong host / no key


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/v1/systemone",
        "https://api.typesafe.ai.evil.example/v1/systemone",
        "https://evil.example/api.typesafe.ai",
        "http://api.typesafe.ai/v1/systemone",
        "https://api.typesafe.ai:8443/v1/systemone",
        "https://user@evil.example/v1/systemone",
        "ftp://api.typesafe.ai/v1/systemone",
        "",
    ],
)
def test_wrong_host_never_sends_key(insight, survey, url):
    fake = FakeJev(ok_response())
    judge, _ = make_judge(fake, url=url)
    assert_pending(judge.check_survey(insight, survey), "jev_url_not_allowed")
    assert fake.requests == []


def test_url_is_safe():
    assert ALLOWED_HOSTS == {"api.typesafe.ai"}
    assert url_is_safe(URL) and url_is_safe("https://api.typesafe.ai:443/x")
    assert not url_is_safe(None) and not url_is_safe("https://typesafe.ai/")


@pytest.mark.parametrize("key", [None, ""])
def test_missing_key_is_pending_without_request(insight, survey, key):
    fake = FakeJev(ok_response())
    judge = JevJudge(
        Settings.from_env({}), api_key=key, thresholds=THRESHOLDS, transport=httpx.MockTransport(fake)
    )
    assert_pending(judge.check_survey(insight, survey), "jev_key_missing")
    assert fake.requests == []


# --------------------------------------------------------------------------- no leaks


def test_key_and_insight_text_never_logged_or_in_repr(insight, survey, caplog):
    caplog.set_level(logging.DEBUG)
    fakes = [
        FakeJev(ok_response()),
        FakeJev(ok_response({**GOOD, "matches_advice": 0.1})),
        FakeJev(httpx.ReadTimeout("slow")),
        FakeJev(httpx.Response(500, text=insight.advice_summary)),
        FakeJev(httpx.Response(200, text=insight.query_summary)),
        FakeJev(RuntimeError(KEY + insight.advice_summary)),
    ]
    for fake in fakes:
        judge, _ = make_judge(fake)
        assert KEY not in repr(judge)
        judge.check_survey(insight, survey)
    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert caplog.records
    assert KEY not in log_text
    assert insight.advice_summary not in log_text and insight.query_summary not in log_text
    for item in survey.items:
        assert item.prompt not in log_text


def test_settings_secret_key_is_used(insight, survey):
    cfg = Settings.from_env({"JEV_API_KEY": KEY})
    assert KEY not in repr(cfg)
    fake = FakeJev(ok_response())
    judge = JevJudge(cfg, transport=httpx.MockTransport(fake))
    judge.check_survey(insight, survey)
    assert fake.requests[0].headers["authorization"] == f"Bearer {KEY}"
