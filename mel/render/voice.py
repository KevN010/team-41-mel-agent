"""Voice call script: a spoken prompt per question, answered by keypad or speech.

Keypad digits are 1..9, so a question takes at most nine choices. A scale takes its numbers as
keypad digits and speech.
"""

from __future__ import annotations

from typing import Any

from mel.render import CONFIRM, SCALE, choices

HOW_IT_ARRIVES = (
    "An outbound call from FarmerChat's number inside send hours. Two silent prompts in a row end the "
    "call and the answers so far are saved as partial."
)
KEYPAD_MAX_CHOICES = 9
TIMEOUT_SECONDS = 8
REPEAT_IF_NO_INPUT = 1
CLOSING = "Thank you. Your answers help us give better advice."
CLOSING_IF_FOLLOW_UP = "Thank you. We have noted this. FarmerChat will contact you again about it."
COUNT_WORDS = {1: "one", 2: "two", 3: "three"}
NUMBER_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}
# Spoken synonyms for a yes/no question, keyed by the survey value.
CONFIRM_SPEECH = {"yes": ["Yes", "yes", "yes I did"], "no": ["No", "no", "not yet"]}


def _opening(count: int) -> str:
    noun = "question" if count == 1 else "questions"
    return (
        f"Hello, this is a call from FarmerChat. We have {COUNT_WORDS[count]} short {noun} about the "
        "advice you got. You can press a key or say your answer."
    )


def _item(item: dict[str, Any]) -> dict[str, Any]:
    options = choices(item)
    item_id = item["item_id"]
    if len(options) > KEYPAD_MAX_CHOICES:
        raise ValueError(f"question {item_id!r} has {len(options)} choices; a keypad takes 9")
    keypad = {str(number): c["value"] for number, c in enumerate(options, start=1)}
    if item["type"] == SCALE:
        say = f"{item['prompt']} Press or say a number from {item['scale_min']} to {item['scale_max']}."
        speech = {str(c["value"]): _number_speech(c["value"]) for c in options}
    else:
        presses = [f"For {c['label']}, press {number}." for number, c in enumerate(options, start=1)]
        say = " ".join([item["prompt"], *presses])
        speech = {}
        for c in options:
            value = str(c["value"])
            if item["type"] == CONFIRM and value in CONFIRM_SPEECH:
                speech[value] = list(CONFIRM_SPEECH[value])
            else:
                speech[value] = [c["label"]]
    return {
        "item_id": item_id,
        "say": say,
        "keypad": keypad,
        "speech": speech,
        "timeout_seconds": TIMEOUT_SECONDS,
        "repeat_if_no_input": REPEAT_IF_NO_INPUT,
    }


def _number_speech(value: int) -> list[str]:
    words = NUMBER_WORDS.get(value)
    return [str(value), words] if words else [str(value)]


def render(survey: dict[str, Any]) -> dict[str, Any]:
    items = survey["items"]
    if len(items) not in COUNT_WORDS:
        raise ValueError(f"survey {survey.get('survey_id')!r} has {len(items)} questions; a call takes 1 to 3")
    return {
        "channel": "voice",
        "how_it_arrives": HOW_IT_ARRIVES,
        "opening": _opening(len(items)),
        "items": [_item(item) for item in items],
        "closing": CLOSING,
        "closing_if_follow_up": CLOSING_IF_FOLLOW_UP,
    }
