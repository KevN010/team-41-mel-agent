"""Every pack record parses into mel.models, serialises back byte-for-byte equal, and the
serialised form validates against the pack schema with zero errors."""

from __future__ import annotations

import socket
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from pytest_socket import SocketBlockedError

from mel import fixtures as pack
from mel.models import (
    IST,
    BottomSheet,
    DecisionRecord,
    Insight,
    JudgeVerdict,
    NoSurvey,
    ResponseRecord,
    ScheduleHandoff,
    SendHours,
    SendWindow,
    Survey,
)
from mel.protocols import Clock, FakeClock, SystemClock
from mel.settings import Settings
from mel.validate import validate_against_pack

SCENARIOS = pack.load_scenarios()
OUTCOMES = pack.load_outcomes()


def _cases(kind: str):
    out = []
    for sc in SCENARIOS:
        name = sc["name"]
        if kind == "insight":
            out.append(pytest.param(sc["insight"], id=name))
        elif kind == "survey":
            out += [pytest.param(s, id=f"{name}/{lang}") for lang, s in sc["survey_by_lang"].items()]
        elif kind == "handoff" and sc["handoff"]:
            out.append(pytest.param(sc["handoff"], id=name))
        elif kind == "response":
            out += [pytest.param(r, id=f"{name}/{ch}") for ch, r in sc["responses"].items()]
        elif kind == "no_survey" and sc["no_survey"]:
            out.append(pytest.param(sc["no_survey"], id=name))
        elif kind == "bottom_sheet":
            for lang, by_ch in sc["render"].items():
                out += [pytest.param(by_ch[ch], id=f"{name}/{lang}/{ch}") for ch in ("app", "web") if ch in by_ch]
    return out


def _roundtrip(model, raw, schema):
    obj = model.model_validate(raw)
    dumped = obj.to_pack()
    assert dumped == raw
    ok, errors = validate_against_pack(dumped, schema)
    assert ok, errors
    # and the model object itself is accepted by the validator
    assert validate_against_pack(obj, schema) == (True, [])


def test_pack_counts():
    assert len(SCENARIOS) == 6
    assert len(OUTCOMES) == 183
    assert len(_cases("survey")) == 10
    assert len(_cases("handoff")) == 5
    assert len(_cases("response")) == 25


@pytest.mark.parametrize("raw", _cases("insight"))
def test_scenario_insight(raw):
    _roundtrip(Insight, raw, "insight")


@pytest.mark.parametrize("raw", _cases("survey"))
def test_scenario_survey(raw):
    _roundtrip(Survey, raw, "survey")


@pytest.mark.parametrize("raw", _cases("handoff"))
def test_scenario_handoff(raw):
    _roundtrip(ScheduleHandoff, raw, "schedule_handoff")


@pytest.mark.parametrize("raw", _cases("response"))
def test_scenario_response(raw):
    _roundtrip(ResponseRecord, raw, "response")


@pytest.mark.parametrize("raw", _cases("no_survey"))
def test_scenario_no_survey(raw):
    _roundtrip(NoSurvey, raw, "no_survey")


@pytest.mark.parametrize("render", _cases("bottom_sheet"))
def test_scenario_bottom_sheet(render):
    sheet = BottomSheet.from_render(render)
    assert sheet.to_pack() == {k: render[k] for k in ("presentation", "sheet")}
    assert validate_against_pack(sheet, "bottom_sheet") == (True, [])


@pytest.mark.parametrize(("path", "raw"), OUTCOMES, ids=[p for p, _ in OUTCOMES])
def test_outcome_fixture(path, raw):
    _roundtrip(ResponseRecord, raw, "response")


def test_insight_model_agrees_with_schema(insights):
    """Model parse succeeds exactly when the pack schema accepts the row (all 6,999)."""
    disagree = []
    for raw in insights:
        schema_ok, _ = validate_against_pack(raw, "insight")
        try:
            Insight.model_validate(raw)
            model_ok = True
        except ValidationError:
            model_ok = False
        if schema_ok != model_ok:
            disagree.append(raw.get("insight_id"))
    assert not disagree


# --------------------------------------------------------------------------- validate


def test_validate_reports_errors_and_resolves_refs(scenarios):
    handoff = dict(next(s["handoff"] for s in scenarios if s["handoff"]))
    survey = dict(handoff["survey"], survey_id="bad")
    ok, errors = validate_against_pack(dict(handoff, survey=survey), "schedule_handoff.schema.json")
    assert not ok
    assert any("survey_id" in e for e in errors)

    response = dict(scenarios[0]["responses"]["app"], recorded_at="2027-01-09T07:25:00Z")
    ok, errors = validate_against_pack(response, "response")
    assert not ok and any("recorded_at" in e for e in errors)


def test_validate_unknown_schema():
    with pytest.raises(KeyError):
        validate_against_pack({}, "nope")


def test_survey_item_rules(scenarios):
    survey = scenarios[2]["survey_by_lang"]["en-IN"]
    scale = dict(survey["items"][2])
    with pytest.raises(ValidationError):
        Survey.model_validate(dict(survey, items=[dict(scale, options=survey["items"][0]["options"])]))
    confirm = dict(survey["items"][0])
    with pytest.raises(ValidationError):
        Survey.model_validate(dict(survey, items=[dict(confirm, scale_min=1)]))
    three = confirm["options"] + [{"value": "maybe", "label": "Maybe"}]
    with pytest.raises(ValidationError):
        Survey.model_validate(dict(survey, items=[dict(confirm, options=three)]))
    no_reason = {k: v for k, v in scale.items() if k != "follow_up_reason"}
    with pytest.raises(ValidationError):
        Survey.model_validate(dict(survey, items=[no_reason]))


# --------------------------------------------------------------------------- time


def test_naive_datetime_rejected():
    with pytest.raises(ValidationError):
        SendWindow(not_before=datetime(2027, 1, 9, 7), not_after=datetime(2027, 1, 11, 19))


def test_other_offset_string_rejected():
    with pytest.raises(ValidationError):
        SendWindow.model_validate({"not_before": "2027-01-09T01:30:00Z", "not_after": "2027-01-11T19:00:00+05:30"})


def test_aware_datetime_converted_to_ist_whole_seconds():
    utc = datetime(2027, 1, 9, 1, 30, 0, 123456, tzinfo=UTC)
    w = SendWindow(not_before=utc, not_after=utc + timedelta(days=2))
    assert w.to_pack()["not_before"] == "2027-01-09T07:00:00+05:30"


def test_send_hours_alias():
    hours = SendHours.model_validate({"from": "07:00", "to": "19:00"})
    assert hours.from_ == "07:00"
    assert hours.to_pack() == {"from": "07:00", "to": "19:00"}


# --------------------------------------------------------------------------- our records


def _decision(**kw):
    base = {
        "insight_id": "I-005330",
        "farmer_id": "F-000245",
        "survey": True,
        "rule_id": "R8",
        "reason_code": None,
        "timing_profile": "golden_v1",
        "send_window": {"not_before": "2027-01-08T09:00:00+05:30", "not_after": "2027-01-11T19:00:00+05:30"},
        "created_at": "2027-01-06T08:05:00+05:30",
    }
    return DecisionRecord.model_validate(base | kw)


def test_decision_record_shapes():
    d = _decision()
    assert d.to_pack()["reason_code"] is None  # required-nullable fields are written as null
    no = _decision(survey=False, rule_id="R2", reason_code="critical_needs_human_call", send_window=None)
    assert no.to_pack()["send_window"] is None
    for bad in (
        {"rule_id": "R9"},
        {"survey": False},
        {"reason_code": "junk_insight"},
        {"survey": False, "rule_id": "R1", "reason_code": "junk_insight"},  # window must be None
        {"timing_profile": "golden_v2"},
    ):
        with pytest.raises(ValidationError):
            _decision(**bad)


def test_judge_verdict_pending_never_ok():
    assert not JudgeVerdict(ok=False, scores={}, pending_review=True).ok
    with pytest.raises(ValidationError):
        JudgeVerdict(ok=True, scores={}, pending_review=True)


# --------------------------------------------------------------------------- plumbing


def test_clocks():
    start = datetime(2026, 11, 5, 9, 0, tzinfo=IST)
    clock = FakeClock(start)
    assert isinstance(clock, Clock) and isinstance(SystemClock(), Clock)
    clock.advance(timedelta(days=3))
    assert clock.now() == start + timedelta(days=3)
    assert clock.now().utcoffset() == timedelta(hours=5, minutes=30)
    with pytest.raises(ValueError):
        clock.advance(timedelta(seconds=-1))
    assert SystemClock().now().utcoffset() == timedelta(hours=5, minutes=30)


def test_settings_defaults_and_env():
    s = Settings.from_env({})
    assert s.REGION == "us-west-2" and s.LANGUAGES == ["en-IN"] and s.TIMING_PROFILE == "golden_v1"
    assert s.RATE_LIMIT_RPM == 60 and s.JEV_TIMEOUT_S == 2 and str(s.SEASON_END) == "2027-03-31"
    assert set(s.jev_thresholds.values()) == {0.5} and len(s.jev_thresholds) == 5
    s = Settings.from_env({"LANGUAGES": "en-IN,hi-IN", "JEV_API_KEY": "sk-test", "TIMING_PROFILE": "rules_v1"})
    assert s.LANGUAGES == ["en-IN", "hi-IN"] and s.TIMING_PROFILE == "rules_v1"
    assert "sk-test" not in repr(s)
    with pytest.raises(ValidationError):
        Settings.from_env({"REGION": "us-east-1"})


def test_crop_calendar_and_golden(crop_calendar, golden):
    assert str(crop_calendar["wheat"]) == "2027-04-25"
    assert str(crop_calendar["potato"]) == "2027-03-31"
    assert len(golden) == 150


def test_network_is_blocked():
    with pytest.raises(SocketBlockedError):
        socket.create_connection(("api.typesafe.ai", 443), timeout=1)
