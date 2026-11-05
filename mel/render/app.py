"""App bottom sheet: the survey shown one question per step.

The app shows the sheet after a push tap or on the next app open inside the send window. The
shared sheet builder also serves the web chat (see ``mel.render.web``).
"""

from __future__ import annotations

from typing import Any

from mel.render import choices

TITLE = "A quick question about the advice you got"
SKIP_LABEL = "Skip"
CLOSE_LABEL = "Close"
THANK_YOU = "Thank you. Your answers help us give better advice."
WAITS_FOR = ["answer_finished_streaming", "no_typing_for_5_seconds", "no_call_in_progress"]
OPENS_WHEN = ["push_tapped", "next_app_open"]
HOW_IT_ARRIVES = (
    "A notification tells the farmer there is a short question. Tapping it opens the app with the "
    "sheet. If they open the app another way inside the send window, the sheet opens then. It never "
    "covers an answer that is still arriving, a message being typed, or a call."
)
MAX_STEPS = 3


def bottom_sheet(
    survey: dict[str, Any], *, channel: str, opens_when: list[str], how_it_arrives: str
) -> dict[str, Any]:
    """The bottom-sheet payload for one channel: presentation block plus the sheet itself."""
    items = survey["items"]
    total = len(items)
    if not 1 <= total <= MAX_STEPS:
        raise ValueError(f"survey {survey.get('survey_id')!r} has {total} questions; a sheet takes 1 to 3")
    steps = []
    for number, item in enumerate(items, start=1):
        steps.append(
            {
                "step": number,
                "step_label": f"{number} of {total}",
                "item_id": item["item_id"],
                "question_type": item["type"],
                "question": item["prompt"],
                "options": [{"label": c["label"], "answer": c["value"]} for c in choices(item)],
            }
        )
    return {
        "channel": channel,
        "how_it_arrives": how_it_arrives,
        "presentation": {
            "type": "bottom_sheet",
            "opens_when": list(opens_when),
            "waits_for": list(WAITS_FOR),
            "one_question_per_step": True,
            "steps_total": total,
            "can_skip": True,
            "can_close": True,
            "swipe_down_closes": True,
        },
        "sheet": {
            "title": TITLE,
            "skip_label": SKIP_LABEL,
            "close_label": CLOSE_LABEL,
            "thank_you": THANK_YOU,
            "steps": steps,
        },
    }


def render(survey: dict[str, Any]) -> dict[str, Any]:
    return bottom_sheet(survey, channel="app", opens_when=OPENS_WHEN, how_it_arrives=HOW_IT_ARRIVES)
