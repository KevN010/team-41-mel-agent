"""Channel renderers for the MEL survey.

``render(survey, channel, language)`` turns a survey dict (the pack's survey.schema.json shape)
into one channel's payload. For en-IN the output equals the pack fixture
``render/en-IN/<channel>.json``. Renderers are templates over the survey items: no model calls,
no clock, no storage, no read receipts or delivery timestamps.

Survey text (prompts, option labels) is farmer-facing data. It is copied into the payload as is and
never logged. Error messages name ids only.
"""

from __future__ import annotations

from typing import Any

CHANNELS = ("app", "web", "whatsapp", "telegram", "voice")
SUPPORTED_LANGUAGES = ("en-IN",)

CONFIRM = "survey-confirm"
SINGLE_SELECT = "survey-single-select"
SCALE = "survey-scale"


def choices(item: dict[str, Any]) -> list[dict[str, Any]]:
    """The answer choices of one survey item, in display order, as ``{"label", "value"}``.

    A scale item has no listed options: its choices are the integers ``scale_min..scale_max``,
    shown as their own digits.
    """
    if item["type"] == SCALE:
        return [{"label": str(n), "value": n} for n in range(item["scale_min"], item["scale_max"] + 1)]
    return [{"label": opt["label"], "value": opt["value"]} for opt in item["options"]]


def check_request(survey: dict[str, Any], channel: str, language: str) -> None:
    """Reject unknown channels, unsupported languages and mismatched surveys before rendering."""
    if channel not in CHANNELS:
        raise ValueError(f"unknown channel {channel!r}")
    if language not in SUPPORTED_LANGUAGES:
        raise NotImplementedError(f"no renderer for language {language!r} yet")
    if survey.get("language") != language:
        raise ValueError(f"survey {survey.get('survey_id')!r} is not in language {language!r}")


def render(survey: dict[str, Any], channel: str, language: str) -> dict[str, Any]:
    """Render one survey for one channel. Returns a new dict; the survey is not changed."""
    check_request(survey, channel, language)
    # Imported here: the channel modules import the helpers above from this package.
    from mel.render import app, telegram, voice, web, whatsapp

    modules = {"app": app, "web": web, "whatsapp": whatsapp, "telegram": telegram, "voice": voice}
    return modules[channel].render(survey)
