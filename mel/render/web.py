"""Web chat bottom sheet: the same sheet as the app, opened on the next web visit."""

from __future__ import annotations

from typing import Any

from mel.render.app import bottom_sheet

HOW_IT_ARRIVES = (
    "Web chat has no notifications. The sheet opens the next time the farmer visits inside the send "
    "window, once the answer on screen has finished arriving."
)
OPENS_WHEN = ["next_web_visit"]


def render(survey: dict[str, Any]) -> dict[str, Any]:
    return bottom_sheet(survey, channel="web", opens_when=OPENS_WHEN, how_it_arrives=HOW_IT_ARRIVES)
