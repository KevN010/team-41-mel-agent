"""mel.generate: state transitions, retry cap, our fields over the model's, prompt hygiene."""

from __future__ import annotations

import copy
import json
import logging
import re
from datetime import datetime

import pytest

import mel.generate as gen
from mel.generate import (
    DRAFT_SCHEMA,
    MAX_ATTEMPTS,
    GenerationResult,
    LlmSurveyGenerator,
    ModelChoice,
    ModelsFileError,
    build_user_turn,
    format_survey_id,
    generate_survey,
    load_model_choice,
    system_prompt,
)
from mel.models import IST, DecisionRecord, Insight, JudgeVerdict, SendWindow, Usage
from mel.protocols import Generator, Judge
from mel.settings import Settings
from mel.validate import validate_against_pack

MODELS = ModelChoice(generation="gen_model", retry="retry_model")
OK_VERDICT = JudgeVerdict(ok=True, scores={})

# --------------------------------------------------------------------------- fakes


class FakeGenerator:
    """Returns canned drafts in order; records every call."""

    def __init__(self, *drafts):
        self.drafts = list(drafts)
        self.calls: list[dict] = []

    def generate(self, insight, language, timing_profile, model_key, *, repair_errors=None):
        self.calls.append(
            {"model_key": model_key, "language": language, "timing_profile": timing_profile,
             "repair_errors": repair_errors}
        )
        draft = self.drafts[min(len(self.calls), len(self.drafts)) - 1]
        if isinstance(draft, Exception):
            raise draft
        usage = Usage(model_id=f"id-{model_key}", input_tokens=1000, output_tokens=200, latency_ms=50.0,
                      cost_usd=0.0002)
        return copy.deepcopy(draft), usage


class FakeJudge:
    def __init__(self, verdict: JudgeVerdict | Exception = OK_VERDICT):
        self.verdict = verdict
        self.calls = 0
        self.seen = None

    def check_survey(self, insight, survey):
        self.calls += 1
        self.seen = survey
        if isinstance(self.verdict, Exception):
            raise self.verdict
        return self.verdict


def _scenario(scenarios, prefix):
    return next(s for s in scenarios if s["name"].startswith(prefix))


def _setup(sc, lang="en-IN"):
    pack = sc["survey_by_lang"][lang]
    insight = Insight.model_validate(sc["insight"])
    window = SendWindow.model_validate(pack["send_window"])
    decision = DecisionRecord(
        insight_id=insight.insight_id,
        farmer_id=insight.farmer_id,
        survey=True,
        rule_id="R8",
        reason_code=None,
        timing_profile="golden_v1",
        send_window=window,
        created_at=insight.created_at.replace(microsecond=0),
    )
    good = {"items": copy.deepcopy(pack["items"]), "rationale": pack["rationale"]}
    seq = int(pack["survey_id"].removeprefix("S-"))
    return pack, insight, window, decision, good, seq


def _bad(good):
    bad = copy.deepcopy(good)
    bad["items"][0]["options"][0]["label"] = "x" * 25  # schema and INV-LABEL
    return bad


def _run(insight, decision, window, generator, judge, clock, seq=1, lang="en-IN"):
    return generate_survey(insight, decision, window, lang, generator, judge, clock,
                           survey_seq=seq, models=MODELS)


@pytest.fixture
def potato(scenarios):
    return _setup(_scenario(scenarios, "3-"))


# --------------------------------------------------------------------------- golden


@pytest.mark.parametrize("prefix", ["1-", "2-", "3-", "4-", "5-"])
def test_good_draft_reproduces_pack_survey(scenarios, clock, prefix):
    pack, insight, window, decision, good, seq = _setup(_scenario(scenarios, prefix))
    g, j = FakeGenerator(good), FakeJudge()
    res = _run(insight, decision, window, g, j, clock, seq)
    assert res.status == "accepted"
    assert res.attempts == 1
    assert res.survey.to_pack() == pack
    assert validate_against_pack(res.survey, "survey")[0]


@pytest.mark.parametrize("prefix", ["1-", "3-", "4-"])
def test_hindi_reproduces_pack_survey(scenarios, clock, monkeypatch, prefix):
    monkeypatch.setattr(gen, "settings", Settings.from_env({"LANGUAGES": "en-IN,hi-IN"}))
    pack, insight, window, decision, good, seq = _setup(_scenario(scenarios, prefix), "hi-IN")
    res = _run(insight, decision, window, FakeGenerator(good), FakeJudge(), clock, seq, lang="hi-IN")
    assert res.status == "accepted"
    assert res.survey.to_pack() == pack


def test_hindi_off_by_default(potato, clock):
    _, insight, window, decision, good, _ = potato
    with pytest.raises(ValueError, match="LANGUAGES"):
        _run(insight, decision, window, FakeGenerator(good), FakeJudge(), clock, lang="hi-IN")


def test_fakes_satisfy_protocols():
    assert isinstance(FakeGenerator(), Generator)
    assert isinstance(FakeJudge(), Judge)


# --------------------------------------------------------------------------- state transitions


def test_accepted_first_try(potato, clock):
    _, insight, window, decision, good, _ = potato
    g, j = FakeGenerator(good), FakeJudge()
    res = _run(insight, decision, window, g, j, clock, seq=42)
    assert (res.status, res.attempts, res.reasons) == ("accepted", 1, [])
    assert res.model_keys == ["gen_model"]
    assert g.calls[0]["repair_errors"] is None
    assert g.calls[0]["timing_profile"] == "golden_v1"
    assert res.survey.survey_id == "S-00042" == res.survey_id
    assert res.survey.self_eval.schema_valid is True
    assert j.calls == 1
    assert res.generated_at == clock.now()


def test_bad_then_good_uses_retry_model_with_errors(potato, clock):
    _, insight, window, decision, good, _ = potato
    g, j = FakeGenerator(_bad(good), good), FakeJudge()
    res = _run(insight, decision, window, g, j, clock)
    assert res.status == "accepted"
    assert res.attempts == 2
    assert [c["model_key"] for c in g.calls] == ["gen_model", "retry_model"]
    repair = g.calls[1]["repair_errors"]
    assert repair and any("options[0].label" in e for e in repair)
    assert any("INV-LABEL" in e for e in repair)
    assert len(res.usage) == 2
    assert res.cost_usd == pytest.approx(0.0004)


def test_bad_twice_is_failed_review_and_cap_holds(potato, clock):
    _, insight, window, decision, good, _ = potato
    g, j = FakeGenerator(_bad(good)), FakeJudge()  # every call returns the bad draft
    res = _run(insight, decision, window, g, j, clock)
    assert res.status == "failed_review"
    assert res.survey is None
    assert res.attempts == MAX_ATTEMPTS == 2
    assert len(g.calls) == 2
    assert j.calls == 0  # nothing to judge
    assert res.reasons and all(r.startswith(("attempt1:", "attempt2:")) for r in res.reasons)
    assert res.status != "no_survey"


def test_generator_errors_count_as_attempts(potato, clock):
    _, insight, window, decision, good, _ = potato
    g = FakeGenerator(RuntimeError("boom with text"), good)
    res = _run(insight, decision, window, g, FakeJudge(), clock)
    assert res.status == "accepted"
    assert res.attempts == 2
    assert res.reasons == ["attempt1: generator_error:RuntimeError"]
    assert g.calls[1]["repair_errors"]

    g = FakeGenerator(RuntimeError("x"))
    res = _run(insight, decision, window, g, FakeJudge(), clock)
    assert (res.status, res.attempts, len(g.calls), res.usage) == ("failed_review", 2, 2, [])


@pytest.mark.parametrize("draft", [None, [], "not json", {"rationale": "no items"}, {"items": [{}]}])
def test_garbage_drafts_fail_closed(potato, clock, draft):
    _, insight, window, decision, _, _ = potato
    res = _run(insight, decision, window, FakeGenerator(draft), FakeJudge(), clock)
    assert res.status == "failed_review"
    assert res.attempts == 2


def test_judge_not_ok_is_pending_review(potato, clock):
    _, insight, window, decision, good, _ = potato
    verdict = JudgeVerdict(ok=False, scores={"matches_advice": 0.9, "gives_new_advice": 0.95,
                                             "asks_personal_info": 0.1})
    g, j = FakeGenerator(good), FakeJudge(verdict)
    res = _run(insight, decision, window, g, j, clock)
    assert res.status == "pending_review"
    assert res.attempts == 1  # no regeneration on a judge failure
    assert res.survey is not None
    assert res.survey.self_eval.gives_new_advice is True
    assert res.survey.self_eval.asks_personal_info is False
    assert res.survey.self_eval.relevance_score == 0.9
    assert "judge:not_ok" in res.reasons


def test_judge_pending_review_and_errors(potato, clock):
    _, insight, window, decision, good, _ = potato
    pending = JudgeVerdict(ok=False, scores={}, pending_review=True)
    res = _run(insight, decision, window, FakeGenerator(good), FakeJudge(pending), clock)
    assert res.status == "pending_review"
    assert res.survey.self_eval.gives_new_advice is None  # unknown stays unset
    assert "judge:pending_review" in res.reasons

    res = _run(insight, decision, window, FakeGenerator(good), FakeJudge(TimeoutError()), clock)
    assert res.status == "pending_review"
    assert res.verdict is None
    assert "judge_error:TimeoutError" in res.reasons
    assert validate_against_pack(res.survey, "survey")[0]


def test_judge_ok_scores_fill_self_eval(potato, clock):
    _, insight, window, decision, good, _ = potato
    verdict = JudgeVerdict(ok=True, scores={"matches_advice": 0.8, "gives_new_advice": 0.1,
                                            "asks_personal_info": 0.0, "bad": float("nan")})
    res = _run(insight, decision, window, FakeGenerator(good), FakeJudge(verdict), clock)
    se = res.survey.self_eval
    assert (se.schema_valid, se.relevance_score, se.gives_new_advice, se.asks_personal_info) == (
        True, 0.8, False, False)


# --------------------------------------------------------------------------- the model is not trusted


def test_model_schema_valid_true_on_invalid_draft_is_ignored(potato, clock):
    _, insight, window, decision, good, _ = potato
    bad = _bad(good)
    bad["self_eval"] = {"schema_valid": True, "gives_new_advice": False}
    g = FakeGenerator(bad)
    res = _run(insight, decision, window, g, FakeJudge(), clock)
    assert res.status == "failed_review"
    assert len(g.calls) == 2  # the claim did not short-cut the retry


def test_model_schema_valid_false_on_valid_draft_is_ignored(potato, clock):
    _, insight, window, decision, good, _ = potato
    good = {**good, "self_eval": {"schema_valid": False, "gives_new_advice": True, "relevance_score": 0.0}}
    res = _run(insight, decision, window, FakeGenerator(good), FakeJudge(), clock)
    assert res.status == "accepted"
    assert res.survey.self_eval.schema_valid is True
    assert res.survey.self_eval.gives_new_advice is False
    assert res.survey.self_eval.relevance_score is None


def test_our_fields_win_over_the_model(potato, clock):
    _, insight, window, decision, good, _ = potato
    hostile = {
        **good,
        "survey_id": "S-99999",
        "farmer_id": "F-ATTACKER",
        "source_insight_ids": ["I-OTHER"],
        "language": "hi-IN",
        "send_window": {"not_before": "2030-01-01T07:00:00+05:30", "not_after": "2030-01-02T19:00:00+05:30"},
    }
    res = _run(insight, decision, window, FakeGenerator(hostile), FakeJudge(), clock, seq=7)
    s = res.survey
    assert s.survey_id == "S-00007"
    assert s.farmer_id == insight.farmer_id
    assert s.source_insight_ids == [insight.insight_id]
    assert s.language == "en-IN"
    assert s.send_window == window


def test_strict_json_nulls_are_stripped(potato, clock):
    pack, insight, window, decision, good, _ = potato
    nulled = copy.deepcopy(good)
    for item in nulled["items"]:
        for key in DRAFT_SCHEMA["properties"]["items"]["items"]["required"]:
            item.setdefault(key, None)
        for opt in item.get("options") or []:
            opt.setdefault("follow_up", None)
    res = _run(insight, decision, window, FakeGenerator(nulled), FakeJudge(), clock,
               seq=int(pack["survey_id"][2:]))
    assert res.status == "accepted"
    assert res.survey.to_pack() == pack


def test_extra_item_keys_are_rejected(potato, clock):
    _, insight, window, decision, good, _ = potato
    bad = copy.deepcopy(good)
    bad["items"][0]["advice"] = "spray more"
    res = _run(insight, decision, window, FakeGenerator(bad), FakeJudge(), clock)
    assert res.status == "failed_review"


def test_reasons_do_not_echo_draft_text(potato, clock, caplog):
    _, insight, window, decision, good, _ = potato
    secret = "SECRET-DRAFT-TEXT"
    bad = copy.deepcopy(good)
    bad["items"][0]["options"][0]["label"] = secret * 3
    bad["rationale"] = secret * 50
    with caplog.at_level(logging.DEBUG, logger="mel.generate"):
        res = _run(insight, decision, window, FakeGenerator(bad), FakeJudge(), clock)
    assert res.status == "failed_review"
    dumped = json.dumps(res.model_dump(mode="json"))
    assert secret not in dumped
    for rec in caplog.records:
        assert secret not in json.dumps(rec.__dict__, default=str)
        assert insight.advice_summary not in json.dumps(rec.__dict__, default=str)


# --------------------------------------------------------------------------- inputs


def test_rejects_no_survey_decision(potato, clock):
    _, insight, window, decision, good, _ = potato
    no = decision.model_copy(update={"survey": False, "rule_id": "R5", "reason_code": "no_check_needed",
                                     "send_window": None})
    with pytest.raises(ValueError, match="not a survey decision"):
        _run(insight, no, window, FakeGenerator(good), FakeJudge(), clock)


def test_rejects_mismatched_decision(potato, clock):
    _, insight, window, decision, good, _ = potato
    other = decision.model_copy(update={"farmer_id": "F-999"})
    with pytest.raises(ValueError, match="belong together"):
        _run(insight, other, window, FakeGenerator(good), FakeJudge(), clock)


@pytest.mark.parametrize("seq,expected", [(0, "S-00000"), (42, "S-00042"), (123456, "S-123456")])
def test_survey_id_format(seq, expected):
    assert format_survey_id(seq) == expected
    assert re.fullmatch(r"S-[0-9]{5,10}", expected)


@pytest.mark.parametrize("seq", [-1, 10**10, True, "5", 1.0])
def test_survey_id_rejects_bad_seq(seq):
    with pytest.raises(ValueError):
        format_survey_id(seq)


def test_load_model_choice(tmp_path):
    f = tmp_path / "models.yaml"
    f.write_text("generation: global.openai.gpt-6-luna\nretry: global.openai.gpt-6-luna\n"
                 "region: us-west-2\nmax_tokens: 600\n")
    assert load_model_choice(f) == ModelChoice(generation="global.openai.gpt-6-luna",
                                               retry="global.openai.gpt-6-luna")
    with pytest.raises(ModelsFileError, match="not found"):
        load_model_choice(tmp_path / "missing.yaml")
    f.write_text("generation: x\n")
    with pytest.raises(ModelsFileError, match="retry"):
        load_model_choice(f)


def test_result_type(potato, clock):
    _, insight, window, decision, good, _ = potato
    res = _run(insight, decision, window, FakeGenerator(good), FakeJudge(), clock)
    assert isinstance(res, GenerationResult)
    assert isinstance(res.generated_at, datetime) and res.generated_at.utcoffset() == IST.utcoffset(None)


# --------------------------------------------------------------------------- prompt and user turn


def test_system_prompt_has_every_ask_and_vocabulary(rules, scenarios):
    prompt = system_prompt()
    for rtype, spec in rules["survey_by_resolution"].items():
        if spec["survey"]:
            assert rtype in prompt
            assert spec["asks"] in prompt
    for kind in ("survey-single-select", "survey-confirm", "survey-scale"):
        assert kind in prompt
    reasons = {
        opt["follow_up"]
        for sc in scenarios for s in sc["survey_by_lang"].values() for it in s["items"]
        for opt in it.get("options", []) if "follow_up" in opt
    } | {
        it["follow_up_reason"]
        for sc in scenarios for s in sc["survey_by_lang"].values() for it in s["items"]
        if "follow_up_reason" in it
    }
    assert reasons == set(DRAFT_SCHEMA["properties"]["items"]["items"]["properties"]["follow_up_reason"]["enum"]) - {None}
    for reason in reasons:
        assert reason in prompt
    assert "Never give advice" in prompt
    assert "Never ask for personal information" in prompt


def test_system_prompt_is_stable_and_has_no_insight_text(insights, scenarios):
    prompt = system_prompt()
    assert not re.search(r"\{[a-z_]+\}", prompt)  # no template slots: nothing per insight
    for sc in scenarios:
        assert sc["insight"]["advice_summary"] not in prompt
        assert sc["insight"]["query_summary"] not in prompt
        assert sc["insight"]["farmer_id"] not in prompt


def test_examples_in_prompt_are_valid_drafts(potato, clock):
    _, insight, window, decision, _, _ = potato
    prompt = system_prompt()
    examples = re.findall(r"^\{\"items\": \[\{.*\}$", prompt, flags=re.MULTILINE)
    assert len(examples) == 3
    for ex in examples:
        res = _run(insight, decision, window, FakeGenerator(json.loads(ex)), FakeJudge(), clock)
        assert res.status == "accepted", ex[:60]


def test_user_turn_is_json_data_without_identity(potato):
    _, insight, _, _, _, _ = potato
    turn = json.loads(build_user_turn(insight, "en-IN", ["$.items[0]: bad"]))
    assert turn["language"] == "en-IN"
    assert turn["insight"]["advice_summary"] == insight.advice_summary
    assert turn["repair_errors"] == ["$.items[0]: bad"]
    flat = json.dumps(turn)
    for leak in (insight.farmer_id, insight.conversation_id, insight.location.district):
        assert leak not in flat
    assert "repair_errors" not in json.loads(build_user_turn(insight, "en-IN"))


def test_llm_generator_puts_insight_in_user_turn_only(potato):
    _, insight, _, _, good, _ = potato

    class Chat:
        def __init__(self, key):
            self.key = key
            Chat.made.append(self)

        def converse_json(self, system, user, schema, max_tokens):
            self.call = (system, user, schema, max_tokens)
            return good, Usage(model_id=self.key, input_tokens=1, output_tokens=1, latency_ms=1.0)

    Chat.made = []
    g = LlmSurveyGenerator(Chat)
    assert isinstance(g, Generator)
    draft, _usage = g.generate(insight, "en-IN", "golden_v1", "gen_model", repair_errors=["e1"])
    system, user, schema, max_tokens = Chat.made[0].call
    assert Chat.made[0].key == "gen_model"
    assert system == system_prompt()
    assert insight.advice_summary not in system
    assert insight.advice_summary in user
    assert json.loads(user)["repair_errors"] == ["e1"]
    assert schema is DRAFT_SCHEMA
    assert max_tokens == 600
    assert draft == good


def test_draft_schema_is_strict_mode_shaped():
    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                assert node.get("additionalProperties") is False
                assert set(node["required"]) == set(node["properties"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(DRAFT_SCHEMA)


def test_prompt_word_count_is_reported():
    words = len(system_prompt().split())
    assert 600 <= words <= 2000, words
