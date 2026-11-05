"""mel.invariants: every pack survey passes; each invariant catches its own break."""

from __future__ import annotations

import copy

import pytest

from mel import invariants
from mel.invariants import INVARIANT_IDS, check_survey
from mel.validate import validate_against_pack


def _pack_surveys(scenarios):
    return [
        (f"{sc['name']}:{lang}", lang, survey)
        for sc in scenarios
        for lang, survey in sc["survey_by_lang"].items()
    ]


@pytest.fixture
def mustard(scenarios):
    sc = next(s for s in scenarios if s["name"].startswith("1-"))
    return copy.deepcopy(sc["survey_by_lang"]["en-IN"])


@pytest.fixture
def potato(scenarios):
    sc = next(s for s in scenarios if s["name"].startswith("3-"))
    return copy.deepcopy(sc["survey_by_lang"]["en-IN"])


def _check(survey, language="en-IN", window=None):
    return check_survey(survey, language=language, window=window or survey["send_window"])


def _ids(violations):
    return {v.rsplit("(", 1)[-1].rstrip(")") for v in violations if "(INV-" in v}


def test_every_pack_survey_passes(scenarios):
    surveys = _pack_surveys(scenarios)
    assert len(surveys) == 10  # 5 actionable scenarios x en-IN, hi-IN
    for name, lang, survey in surveys:
        assert validate_against_pack(survey, "survey")[0], name
        assert _check(survey, lang) == [], name


def test_invariant_ids_are_documented():
    doc = invariants.__doc__
    for inv in INVARIANT_IDS:
        assert inv in doc


def test_items_count(mustard):
    mustard["items"].append(copy.deepcopy(mustard["items"][0]))
    mustard["items"][-1]["item_id"] = "q4"
    assert "INV-ITEMS" in _ids(_check(mustard))
    mustard["items"] = []
    assert "INV-ITEMS" in _ids(_check(mustard))
    mustard["items"] = "q1"
    assert "INV-ITEMS" in _ids(_check(mustard))


def test_duplicate_item_id(mustard):
    mustard["items"][1]["item_id"] = "q1"
    assert _ids(_check(mustard)) == {"INV-ITEM-ID"}


def test_option_count(mustard):
    mustard["items"][1]["options"] = mustard["items"][1]["options"][:1]
    assert "INV-OPTIONS" in _ids(_check(mustard))
    opts = [{"value": f"v{i}", "label": f"L{i}", "follow_up": "advice_did_not_work"} for i in range(11)]
    mustard["items"][1]["options"] = opts
    assert "INV-OPTIONS" in _ids(_check(mustard))


def test_confirm_needs_exactly_two(mustard):
    mustard["items"][0]["options"].append({"value": "maybe", "label": "Maybe"})
    assert _ids(_check(mustard)) == {"INV-OPTIONS"}


def test_duplicate_option_value(mustard):
    mustard["items"][2]["options"][1]["value"] = "almost_none"
    assert _ids(_check(mustard)) == {"INV-OPTION-VALUE"}


def test_label_21_code_points(mustard):
    mustard["items"][1]["options"][0]["label"] = "x" * 21
    assert _ids(_check(mustard)) == {"INV-LABEL"}
    mustard["items"][1]["options"][0]["label"] = "x" * 20
    assert _check(mustard) == []
    mustard["items"][1]["options"][0]["label"] = "   "
    assert _ids(_check(mustard)) == {"INV-LABEL"}


def test_label_counts_code_points_not_bytes(scenarios):
    sc = next(s for s in scenarios if s["name"].startswith("1-"))
    hi = copy.deepcopy(sc["survey_by_lang"]["hi-IN"])
    label = "हाँ, आसानी से मिला ठीक"  # 22 code points, far more UTF-8 bytes
    assert len(label) > 20
    hi["items"][1]["options"][0]["label"] = label
    assert _ids(_check(hi, "hi-IN")) == {"INV-LABEL"}
    hi["items"][1]["options"][0]["label"] = label[:20]
    assert _check(hi, "hi-IN") == []


def test_scale_steps(potato):
    scale = potato["items"][2]
    scale["scale_min"], scale["scale_max"] = 0, 10  # 11 steps
    assert _ids(_check(potato)) == {"INV-SCALE"}
    scale["scale_min"], scale["scale_max"] = 1, 10  # 10 steps
    assert _check(potato) == []
    scale["scale_min"], scale["scale_max"] = 5, 5
    assert "INV-SCALE" in _ids(_check(potato))


def test_follow_up_at_or_below_in_range(potato):
    scale = potato["items"][2]
    scale["follow_up_at_or_below"] = 0  # below scale_min 1
    assert "INV-FOLLOW-UP-AT" in _ids(_check(potato))
    scale["follow_up_at_or_below"] = 5  # equal to scale_max: every answer would be a follow-up
    assert "INV-FOLLOW-UP-AT" in _ids(_check(potato))
    scale["follow_up_at_or_below"] = 4
    assert _check(potato) == []
    del scale["follow_up_reason"]
    assert "INV-FOLLOW-UP-AT" in _ids(_check(potato))


def test_needs_a_follow_up_route(mustard):
    for item in mustard["items"]:
        for opt in item["options"]:
            opt.pop("follow_up", None)
    assert _ids(_check(mustard)) == {"INV-FOLLOW-UP"}


def test_language_en_rejects_devanagari(mustard):
    mustard["items"][0]["prompt"] = "Did you spray? क्या आपने छिड़काव किया?"
    assert _ids(_check(mustard)) == {"INV-LANGUAGE"}


def test_language_hi_rejects_latin(scenarios):
    sc = next(s for s in scenarios if s["name"].startswith("1-"))
    hi = copy.deepcopy(sc["survey_by_lang"]["hi-IN"])
    hi["items"][0]["options"][0]["label"] = "Yes"
    assert _ids(_check(hi, "hi-IN")) == {"INV-LANGUAGE"}


def test_language_tag_must_match(mustard):
    assert "INV-LANGUAGE" in _ids(_check(mustard, "hi-IN"))
    assert "INV-LANGUAGE" in _ids(_check(mustard, "ta-IN"))  # no script rule: fails closed


def test_rationale(mustard):
    mustard["rationale"] = "r" * 401
    assert _ids(_check(mustard)) == {"INV-RATIONALE"}
    mustard["rationale"] = ""
    assert _ids(_check(mustard)) == {"INV-RATIONALE"}
    mustard["rationale"] = None
    assert _ids(_check(mustard)) == {"INV-RATIONALE"}


def test_window_must_equal_timing(mustard):
    timing = dict(mustard["send_window"])
    mustard["send_window"] = {**timing, "not_after": "2026-12-30T19:00:00+05:30"}
    assert _ids(_check(mustard, window=timing)) == {"INV-WINDOW"}
    empty = {"not_before": timing["not_after"], "not_after": timing["not_before"]}
    mustard["send_window"] = empty
    assert _ids(_check(mustard, window=empty)) == {"INV-WINDOW"}


def test_messages_never_echo_values(mustard):
    secret = "SECRET-TEXT-xyz"
    mustard["items"][0]["prompt"] = secret + " क्या"
    mustard["items"][1]["options"][0]["label"] = secret * 3
    mustard["rationale"] = secret * 40
    violations = _check(mustard)
    assert violations
    assert not any(secret in v for v in violations)


@pytest.mark.parametrize("junk", [None, 3, "x", [], {"items": [None, 3, {"type": "survey-scale"}]}])
def test_malformed_input_never_raises(junk, mustard):
    out = check_survey(junk, language="en-IN", window=mustard["send_window"])
    assert out  # violations, not an exception
