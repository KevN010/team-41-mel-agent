"""Loaders for the participant pack. All paths are relative to settings.PACK_DIR (pack/).

Loaders return raw dicts (the pack's JSON as is). Parse with mel.models when you need types;
junk insights may not parse, so load_insights() never parses.
"""

from __future__ import annotations

import csv
import json
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from mel.settings import settings

CHANNELS = ("app", "web", "whatsapp", "telegram", "voice")


def pack_path(*parts: str) -> Path:
    return Path(settings.PACK_DIR).joinpath(*parts)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_insights() -> list[dict[str, Any]]:
    """data/insights.jsonl: 6,999 raw insight dicts, junk rows included."""
    return _read_jsonl(pack_path("data", "insights.jsonl"))


def load_golden() -> list[dict[str, Any]]:
    """data/golden_set.jsonl: 150 rows {golden_id, insight_id, insight, expected}."""
    return _read_jsonl(pack_path("data", "golden_set.jsonl"))


def load_crop_calendar() -> dict[str, date]:
    """{crop name: latest end_date over all its stages} from data/crop_calendar_bihar_rabi.csv."""
    last: dict[str, date] = {}
    with pack_path("data", "crop_calendar_bihar_rabi.csv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            end = date.fromisoformat(row["end_date"])
            crop = row["crop"].strip()
            if crop not in last or end > last[crop]:
                last[crop] = end
    return last


def load_rules() -> dict[str, Any]:
    """json/rules/rules.json."""
    return _read_json(pack_path("json", "rules", "rules.json"))


def load_outcome_codes() -> dict[str, Any]:
    """json/rules/outcome_codes.json."""
    return _read_json(pack_path("json", "rules", "outcome_codes.json"))


def load_scenarios() -> list[dict[str, Any]]:
    """The six worked examples, sorted by directory name. Each is::

        {
          "name": "3-potato-blight-wait",
          "insight": {...},
          "survey_by_lang": {"en-IN": {...}, "hi-IN": {...}},      # {} for no-survey scenarios
          "handoff": {...} | None,
          "render": {"en-IN": {"app": {...}, ...}, "hi-IN": {...}}, # {} for no-survey scenarios
          "responses": {"app": {...}, ...},                        # {} for no-survey scenarios
          "no_survey": {...} | None,
        }
    """
    root = pack_path("json", "scenarios")
    scenarios = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        handoff = d / "schedule_handoff.json"
        no_survey = d / "no_survey.json"
        render: dict[str, dict[str, Any]] = {}
        if (d / "render").is_dir():
            for lang_dir in sorted(p for p in (d / "render").iterdir() if p.is_dir()):
                render[lang_dir.name] = {f.stem: _read_json(f) for f in sorted(lang_dir.glob("*.json"))}
        responses = {}
        if (d / "responses").is_dir():
            responses = {f.stem: _read_json(f) for f in sorted((d / "responses").glob("*.json"))}
        scenarios.append(
            {
                "name": d.name,
                "insight": _read_json(d / "insight.json"),
                "survey_by_lang": {
                    f.name.removeprefix("survey.").removesuffix(".json"): _read_json(f)
                    for f in sorted(d.glob("survey.*.json"))
                },
                "handoff": _read_json(handoff) if handoff.exists() else None,
                "render": render,
                "responses": responses,
                "no_survey": _read_json(no_survey) if no_survey.exists() else None,
            }
        )
    return scenarios


def load_outcomes() -> list[tuple[str, dict[str, Any]]]:
    """json/outcomes/<channel>/<question_type>/<case>.json as (path relative to pack/, record), sorted."""
    base = Path(settings.PACK_DIR)
    files = sorted(pack_path("json", "outcomes").rglob("*.json"))
    return [(f.relative_to(base).as_posix(), _read_json(f)) for f in files]


@lru_cache(maxsize=1)
def scenario_surveys_by_id() -> dict[str, dict[str, dict[str, Any]]]:
    """{survey_id: {language: survey dict}} across all scenarios. Handy for outcome fixtures."""
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for sc in load_scenarios():
        for lang, survey in sc["survey_by_lang"].items():
            out.setdefault(survey["survey_id"], {})[lang] = survey
    return out
