"""Telegram: an intro message, then one message per question with inline buttons.

Each choice gets its own row, except a scale, whose numbers share one row. callback_data is
``mel|<survey_id>|<item_id>|<value>`` and must fit Telegram's 64-byte limit.
"""

from __future__ import annotations

from typing import Any

from mel.render import SCALE, choices

HOW_IT_ARRIVES = (
    "The bot can message a farmer who has started it at any time. Scale numbers share one row; other "
    "choices get one row each."
)
CHAT_ID = "<telegram chat id>"
INTRO = "A short question from FarmerChat about the advice you got. It takes one minute."
CALLBACK_PREFIX = "mel"
CALLBACK_MAX_BYTES = 64


def _button(survey_id: str, item_id: str, choice: dict[str, Any]) -> dict[str, Any]:
    data = f"{CALLBACK_PREFIX}|{survey_id}|{item_id}|{choice['value']}"
    if len(data.encode("utf-8")) > CALLBACK_MAX_BYTES:
        raise ValueError(f"callback_data for question {item_id!r} is longer than {CALLBACK_MAX_BYTES} bytes")
    return {"text": choice["label"], "callback_data": data}


def _question(survey_id: str, item: dict[str, Any]) -> dict[str, Any]:
    options = choices(item)
    item_id = item["item_id"]
    if item["type"] == SCALE:
        keyboard = [[_button(survey_id, item_id, c) for c in options]]
    else:
        keyboard = [[_button(survey_id, item_id, c)] for c in options]
    return {
        "method": "sendMessage",
        "chat_id": CHAT_ID,
        "text": item["prompt"],
        "reply_markup": {"inline_keyboard": keyboard},
    }


def render(survey: dict[str, Any]) -> dict[str, Any]:
    survey_id = survey["survey_id"]
    messages: list[dict[str, Any]] = [{"method": "sendMessage", "chat_id": CHAT_ID, "text": INTRO}]
    messages.extend(_question(survey_id, item) for item in survey["items"])
    return {"channel": "telegram", "how_it_arrives": HOW_IT_ARRIVES, "messages": messages}
