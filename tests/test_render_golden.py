"""Golden tests for the channel renderers.

Every en-IN render must deep-equal the pack fixture render/en-IN/<channel>.json. The hi-IN
fixtures are parametrised and marked xfail (strict) until the Hindi stretch adds a renderer.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from mel import fixtures as pack
from mel.render import CHANNELS, render
from mel.validate import validate_against_pack

SCENARIOS = [sc for sc in pack.load_scenarios() if sc["render"]]
SCENARIO_NAMES = [sc["name"] for sc in SCENARIOS]

EN_CASES = [
    pytest.param(sc, ch, id=f"{sc['name']}-{ch}") for sc in SCENARIOS for ch in CHANNELS
]
HI_CASES = [
    pytest.param(
        sc,
        ch,
        id=f"{sc['name']}-{ch}-hi-IN",
        marks=pytest.mark.xfail(
            strict=True,
            raises=NotImplementedError,
            reason="hi-IN renderers wait for the Hindi stretch",
        ),
    )
    for sc in SCENARIOS
    for ch in CHANNELS
]


def _survey(items: list[dict[str, Any]], survey_id: str = "S-90001") -> dict[str, Any]:
    return {"survey_id": survey_id, "language": "en-IN", "items": items}


def _confirm(item_id: str = "q1", prompt: str = "Did you do it?") -> dict[str, Any]:
    return {
        "item_id": item_id,
        "type": "survey-confirm",
        "prompt": prompt,
        "options": [{"value": "yes", "label": "Yes"}, {"value": "no", "label": "No"}],
    }


def _choices(count: int, item_id: str = "q1", label_len: int = 6) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "type": "survey-single-select",
        "prompt": "Pick one.",
        "options": [
            {"value": f"v{n}", "label": ("x" * label_len) if label_len else f"Option {n}"}
            for n in range(count)
        ],
    }


@pytest.mark.parametrize(("sc", "channel"), EN_CASES)
def test_en_in_render_equals_fixture(sc: dict[str, Any], channel: str) -> None:
    survey = sc["survey_by_lang"]["en-IN"]
    before = copy.deepcopy(survey)

    rendered = render(survey, channel, "en-IN")

    assert rendered == sc["render"]["en-IN"][channel]
    assert survey == before, "render must not change the survey"


@pytest.mark.parametrize(("sc", "channel"), HI_CASES)
def test_hi_in_render_equals_fixture(sc: dict[str, Any], channel: str) -> None:
    survey = sc["survey_by_lang"]["hi-IN"]

    assert render(survey, channel, "hi-IN") == sc["render"]["hi-IN"][channel]


@pytest.mark.parametrize("sc", SCENARIOS, ids=SCENARIO_NAMES)
@pytest.mark.parametrize("channel", ["app", "web"])
def test_bottom_sheet_block_validates_against_pack_schema(sc: dict[str, Any], channel: str) -> None:
    rendered = render(sc["survey_by_lang"]["en-IN"], channel, "en-IN")
    # The schema allows only presentation and sheet; channel and how_it_arrives are envelope fields.
    block = {"presentation": rendered["presentation"], "sheet": rendered["sheet"]}

    ok, errors = validate_against_pack(block, "bottom_sheet")

    assert ok, errors


def test_unknown_channel_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown channel"):
        render(_survey([_confirm()]), "sms", "en-IN")


def test_hindi_has_no_renderer_yet() -> None:
    survey = _survey([_confirm()])
    survey["language"] = "hi-IN"

    with pytest.raises(NotImplementedError):
        render(survey, "app", "hi-IN")


def test_survey_language_must_match_request() -> None:
    survey = _survey([_confirm()])
    survey["language"] = "hi-IN"

    with pytest.raises(ValueError, match="not in language"):
        render(survey, "app", "en-IN")


def test_app_rejects_more_than_three_questions() -> None:
    items = [_confirm(f"q{n}") for n in range(1, 5)]

    with pytest.raises(ValueError, match="takes 1 to 3"):
        render(_survey(items), "app", "en-IN")


def test_voice_rejects_more_than_nine_choices() -> None:
    with pytest.raises(ValueError, match="keypad takes 9"):
        render(_survey([_choices(10)]), "voice", "en-IN")


def test_whatsapp_button_title_limit_is_enforced() -> None:
    with pytest.raises(ValueError, match="longer than 20 characters"):
        render(_survey([_choices(2, label_len=21)]), "whatsapp", "en-IN")


def test_telegram_callback_data_limit_is_enforced() -> None:
    survey = _survey([_confirm()], survey_id="S-" + "9" * 60)

    with pytest.raises(ValueError, match="longer than 64 bytes"):
        render(survey, "telegram", "en-IN")


def test_whatsapp_uses_buttons_up_to_three_and_list_above() -> None:
    three = render(_survey([_choices(3)]), "whatsapp", "en-IN")["messages"][0]
    four = render(_survey([_choices(4)]), "whatsapp", "en-IN")["messages"][0]

    assert three["interactive"]["type"] == "button"
    assert four["interactive"]["type"] == "list"
    assert len(four["interactive"]["action"]["sections"][0]["rows"]) == 4


def test_scale_numbers_are_integers_in_app_and_digits_in_callbacks() -> None:
    scale = {
        "item_id": "q1",
        "type": "survey-scale",
        "prompt": "How useful?",
        "scale_min": 1,
        "scale_max": 5,
        "follow_up_at_or_below": 1,
        "follow_up_reason": "advice_did_not_work",
    }
    survey = _survey([scale])

    app = render(survey, "app", "en-IN")
    telegram = render(survey, "telegram", "en-IN")

    answers = [o["answer"] for o in app["sheet"]["steps"][0]["options"]]
    assert answers == [1, 2, 3, 4, 5]
    assert telegram["messages"][1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "mel|S-90001|q1|1"
