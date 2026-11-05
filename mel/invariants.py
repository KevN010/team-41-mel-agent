"""Survey invariants: checks the pack schema cannot express, run after mel.validate.

    violations = check_survey(survey_dict, language="en-IN", window=send_window)

Pure functions, no I/O. Input is untrusted (a model draft merged by mel.generate), so every
check is defensive: wrong types give a violation, never an exception.

Each violation is "<json path>: <what is wrong>". Messages never echo the offending value,
so they are safe to log and safe to send back to the model as repair errors.

The invariant list (ids are used in tests and in the report):

    INV-ITEMS        1..3 items
    INV-ITEM-ID      item_id unique across the survey
    INV-OPTIONS      option items have 2..10 options; survey-confirm has exactly 2
    INV-OPTION-VALUE option values unique inside one item
    INV-LABEL        every label is a non-empty string of at most 20 Unicode code points
    INV-SCALE        scale_min < scale_max and at most 10 steps (scale_max - scale_min + 1)
    INV-FOLLOW-UP-AT follow_up_at_or_below in [scale_min, scale_max) and has a follow_up_reason
    INV-FOLLOW-UP    at least one answer routes to follow-up (an option follow_up or a scale threshold)
    INV-LANGUAGE     survey.language is the requested language, and every prompt and label is
                     in that language's script (en-IN: no Indic letters; hi-IN: Devanagari, no Latin)
    INV-RATIONALE    rationale is a non-empty string of at most 400 code points
    INV-WINDOW       send_window equals the window computed by mel.timing, not_before < not_after
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from mel.models import SendWindow

MAX_ITEMS = 3
MIN_OPTIONS = 2
MAX_OPTIONS = 10
CONFIRM_OPTIONS = 2
MAX_LABEL_CODE_POINTS = 20
MAX_SCALE_STEPS = 10
MAX_RATIONALE_CODE_POINTS = 400

OPTION_TYPES = ("survey-single-select", "survey-confirm")
SCALE_TYPE = "survey-scale"

INVARIANT_IDS = (
    "INV-ITEMS",
    "INV-ITEM-ID",
    "INV-OPTIONS",
    "INV-OPTION-VALUE",
    "INV-LABEL",
    "INV-SCALE",
    "INV-FOLLOW-UP-AT",
    "INV-FOLLOW-UP",
    "INV-LANGUAGE",
    "INV-RATIONALE",
    "INV-WINDOW",
)

# Letters of the Indic scripts (Devanagari .. Malayalam, U+0900..U+0D7F). Digits, spaces and
# punctuation are script-neutral and are allowed in every language.
_INDIC_LETTER = re.compile(r"[ऀ-ൿ]")
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_LATIN_LETTER = re.compile(r"[A-Za-zÀ-ɏ]")


def _en_in(text: str) -> bool:
    return _INDIC_LETTER.search(text) is None


def _hi_in(text: str) -> bool:
    return _DEVANAGARI.search(text) is not None and _LATIN_LETTER.search(text) is None


SCRIPT_RULES = {"en-IN": _en_in, "hi-IN": _hi_in}
"""Per language: True when one piece of farmer-facing text is written in that language's script."""


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _window_dict(window: SendWindow | dict[str, Any]) -> dict[str, Any]:
    if isinstance(window, SendWindow):
        return window.to_pack()
    return dict(window)


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else None


def check_items(items: Any) -> list[str]:
    """INV-ITEMS .. INV-FOLLOW-UP over the items list."""
    if not isinstance(items, list):
        return ["$.items: must be a list (INV-ITEMS)"]
    out: list[str] = []
    if not 1 <= len(items) <= MAX_ITEMS:
        out.append(f"$.items: must have 1 to {MAX_ITEMS} items (INV-ITEMS)")

    seen_ids: set[str] = set()
    has_follow_up = False
    for i, item in enumerate(items):
        path = f"$.items[{i}]"
        if not isinstance(item, dict):
            out.append(f"{path}: must be an object (INV-ITEMS)")
            continue
        item_id = item.get("item_id")
        if isinstance(item_id, str):
            if item_id in seen_ids:
                out.append(f"{path}.item_id: duplicate item_id (INV-ITEM-ID)")
            seen_ids.add(item_id)

        kind = item.get("type")
        if kind in OPTION_TYPES:
            errs, follow = _check_options(path, kind, item.get("options"))
            out.extend(errs)
            has_follow_up = has_follow_up or follow
        elif kind == SCALE_TYPE:
            errs, follow = _check_scale(path, item)
            out.extend(errs)
            has_follow_up = has_follow_up or follow
        # Any other type is a schema error; mel.validate reports it.

    if items and not has_follow_up:
        out.append(
            "$.items: no answer routes to follow-up; mark the bad-outcome answers with a "
            "follow_up reason (INV-FOLLOW-UP)"
        )
    return out


def _check_options(path: str, kind: str, options: Any) -> tuple[list[str], bool]:
    if not isinstance(options, list):
        return [f"{path}.options: {kind} needs a list of options (INV-OPTIONS)"], False
    out: list[str] = []
    if kind == "survey-confirm" and len(options) != CONFIRM_OPTIONS:
        out.append(f"{path}.options: survey-confirm needs exactly {CONFIRM_OPTIONS} options (INV-OPTIONS)")
    elif not MIN_OPTIONS <= len(options) <= MAX_OPTIONS:
        out.append(f"{path}.options: needs {MIN_OPTIONS} to {MAX_OPTIONS} options (INV-OPTIONS)")

    seen_values: set[str] = set()
    follow = False
    for j, opt in enumerate(options):
        opath = f"{path}.options[{j}]"
        if not isinstance(opt, dict):
            out.append(f"{opath}: must be an object (INV-OPTIONS)")
            continue
        value = opt.get("value")
        if isinstance(value, str):
            if value in seen_values:
                out.append(f"{opath}.value: duplicate option value in this item (INV-OPTION-VALUE)")
            seen_values.add(value)
        label = opt.get("label")
        if not isinstance(label, str) or not label.strip():
            out.append(f"{opath}.label: must be a non-empty string (INV-LABEL)")
        elif len(label) > MAX_LABEL_CODE_POINTS:
            out.append(
                f"{opath}.label: {len(label)} code points, at most {MAX_LABEL_CODE_POINTS} allowed (INV-LABEL)"
            )
        if opt.get("follow_up") is not None:
            follow = True
    return out, follow


def _check_scale(path: str, item: dict[str, Any]) -> tuple[list[str], bool]:
    lo, hi = item.get("scale_min"), item.get("scale_max")
    if not (_is_int(lo) and _is_int(hi)):
        return [f"{path}: survey-scale needs integer scale_min and scale_max (INV-SCALE)"], False
    out: list[str] = []
    if lo >= hi:
        out.append(f"{path}: scale_min must be less than scale_max (INV-SCALE)")
    elif hi - lo + 1 > MAX_SCALE_STEPS:
        out.append(f"{path}: scale has {hi - lo + 1} steps, at most {MAX_SCALE_STEPS} allowed (INV-SCALE)")

    at = item.get("follow_up_at_or_below")
    if at is None:
        return out, False
    if not _is_int(at) or not lo <= at < hi:
        out.append(
            f"{path}.follow_up_at_or_below: must be an integer from scale_min to scale_max - 1 "
            "(INV-FOLLOW-UP-AT)"
        )
        return out, False
    if item.get("follow_up_reason") is None:
        out.append(f"{path}.follow_up_reason: needed when follow_up_at_or_below is set (INV-FOLLOW-UP-AT)")
        return out, False
    return out, True


def check_language(survey: dict[str, Any], language: str) -> list[str]:
    """INV-LANGUAGE: the survey is in exactly the requested language (rationale excluded: English)."""
    rule = SCRIPT_RULES.get(language)
    if rule is None:
        return [f"$.language: no script rule for this language tag; known: {sorted(SCRIPT_RULES)} (INV-LANGUAGE)"]
    out: list[str] = []
    if survey.get("language") != language:
        out.append("$.language: must equal the requested language (INV-LANGUAGE)")
    items = survey.get("items")
    if not isinstance(items, list):
        return out
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        texts: list[tuple[str, Any]] = [(f"$.items[{i}].prompt", item.get("prompt"))]
        options = item.get("options")
        if isinstance(options, list):
            texts += [
                (f"$.items[{i}].options[{j}].label", o.get("label"))
                for j, o in enumerate(options)
                if isinstance(o, dict)
            ]
        for path, text in texts:
            if isinstance(text, str) and text and not rule(text):
                out.append(f"{path}: not written in the {language} script (INV-LANGUAGE)")
    return out


def check_rationale(rationale: Any) -> list[str]:
    """INV-RATIONALE."""
    if not isinstance(rationale, str) or not rationale.strip():
        return ["$.rationale: must be a non-empty string (INV-RATIONALE)"]
    if len(rationale) > MAX_RATIONALE_CODE_POINTS:
        n = len(rationale)
        return [f"$.rationale: {n} code points, at most {MAX_RATIONALE_CODE_POINTS} allowed (INV-RATIONALE)"]
    return []


def check_window(actual: Any, expected: SendWindow | dict[str, Any]) -> list[str]:
    """INV-WINDOW: the survey's send_window is the timing window, unchanged, and not empty."""
    expected_d = _window_dict(expected)
    out: list[str] = []
    if actual != expected_d:
        out.append("$.send_window: must equal the window from mel.timing (INV-WINDOW)")
    start = _parse_time(expected_d.get("not_before"))
    end = _parse_time(expected_d.get("not_after"))
    if start is None or end is None or not start < end:
        out.append("$.send_window: not_before must be earlier than not_after (INV-WINDOW)")
    return out


def check_survey(survey: Any, *, language: str, window: SendWindow | dict[str, Any]) -> list[str]:
    """Every invariant. Empty list means the survey passes."""
    if not isinstance(survey, dict):
        return ["$: survey must be an object"]
    return [
        *check_items(survey.get("items")),
        *check_language(survey, language),
        *check_rationale(survey.get("rationale")),
        *check_window(survey.get("send_window"), window),
    ]


__all__ = [
    "INVARIANT_IDS",
    "SCRIPT_RULES",
    "check_items",
    "check_language",
    "check_rationale",
    "check_survey",
    "check_window",
]
