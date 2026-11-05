"""WhatsApp: an approved opening template, then one interactive message per question.

Choices of up to three become reply buttons. More than three become a list message. WhatsApp
limits: 3 buttons, 20 characters per button title, 10 list rows, 24 characters per row title.
"""

from __future__ import annotations

from typing import Any

from mel.render import choices

HOW_IT_ARRIVES = (
    "Days after the chat, so outside WhatsApp's 24-hour reply window. The first message must be an "
    "approved template; the questions follow once the farmer taps Start."
)
RECIPIENT = "<farmer WhatsApp number>"
TEMPLATE_NAME = "mel_survey_invite"
APPROVAL_BODY = "A short question from FarmerChat about the advice you got. It takes one minute."
APPROVAL_QUICK_REPLIES = ["Start", "Not now"]
BUTTON_MAX_CHOICES = 3
BUTTON_TITLE_MAX = 20
LIST_MAX_ROWS = 10
ROW_TITLE_MAX = 24
LIST_BUTTON = "Choose"
LIST_SECTION_TITLE = "Choose one"


def _opening_template(survey_id: str) -> dict[str, Any]:
    def button(index: int, payload: str) -> dict[str, Any]:
        return {
            "type": "button",
            "sub_type": "quick_reply",
            "index": str(index),
            "parameters": [{"type": "payload", "payload": payload}],
        }

    return {
        "messaging_product": "whatsapp",
        "to": RECIPIENT,
        "type": "template",
        "template": {
            "name": TEMPLATE_NAME,
            "language": {"code": "en"},
            "components": [
                button(0, f"{survey_id}|start"),
                button(1, f"{survey_id}|later"),
            ],
        },
    }


def _reply_id(survey_id: str, item_id: str, value: Any) -> str:
    return f"{survey_id}|{item_id}|{value}"


def _question(survey_id: str, item: dict[str, Any]) -> dict[str, Any]:
    options = choices(item)
    item_id = item["item_id"]
    if len(options) <= BUTTON_MAX_CHOICES:
        buttons = []
        for c in options:
            _check_length(c["label"], BUTTON_TITLE_MAX, "button title", item_id)
            buttons.append({"type": "reply", "reply": {"id": _reply_id(survey_id, item_id, c["value"]), "title": c["label"]}})
        interactive: dict[str, Any] = {
            "type": "button",
            "body": {"text": item["prompt"]},
            "action": {"buttons": buttons},
        }
    else:
        if len(options) > LIST_MAX_ROWS:
            raise ValueError(f"question {item_id!r} has {len(options)} choices; a WhatsApp list takes 10")
        rows = []
        for c in options:
            _check_length(c["label"], ROW_TITLE_MAX, "row title", item_id)
            rows.append({"id": _reply_id(survey_id, item_id, c["value"]), "title": c["label"]})
        interactive = {
            "type": "list",
            "body": {"text": item["prompt"]},
            "action": {
                "button": LIST_BUTTON,
                "sections": [{"title": LIST_SECTION_TITLE, "rows": rows}],
            },
        }
    return {"messaging_product": "whatsapp", "to": RECIPIENT, "type": "interactive", "interactive": interactive}


def _check_length(text: str, limit: int, what: str, item_id: str) -> None:
    if len(text) > limit:
        raise ValueError(f"{what} for question {item_id!r} is longer than {limit} characters")


def render(survey: dict[str, Any]) -> dict[str, Any]:
    survey_id = survey["survey_id"]
    return {
        "channel": "whatsapp",
        "how_it_arrives": HOW_IT_ARRIVES,
        "opening_template": _opening_template(survey_id),
        "template_text_for_approval": {
            "body": APPROVAL_BODY,
            "quick_replies": list(APPROVAL_QUICK_REPLIES),
        },
        "messages": [_question(survey_id, item) for item in survey["items"]],
    }
