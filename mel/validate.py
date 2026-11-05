"""Schema validation against the pack's JSON Schemas. Nothing else lives here.

    ok, errors = validate_against_pack(obj, "survey")

``obj`` is a dict or a mel.models PackModel (serialised with ``to_pack()``). ``schema_name``
is a pack schema name with or without the suffix: "survey", "survey.schema.json",
"schedule_handoff", "response", "insight", "no_survey", "bottom_sheet".

Cross-schema ``$ref`` (handoff and response point into survey.schema.json) resolve through a
``referencing`` registry built from every file in pack/json/schemas, keyed by each ``$id``.
Formats the stdlib can check (uuid) are checked; date-time is pinned by the schema patterns.
"""

from __future__ import annotations

import json
from functools import cache, lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mel.settings import settings

SCHEMA_NAMES = ("insight", "survey", "schedule_handoff", "response", "no_survey", "bottom_sheet")


def _schema_dir() -> Path:
    return Path(settings.PACK_DIR) / "json" / "schemas"


def _normalise(name: str) -> str:
    name = name.removesuffix(".json").removesuffix(".schema")
    if name not in SCHEMA_NAMES:
        raise KeyError(f"unknown pack schema {name!r}; expected one of {SCHEMA_NAMES}")
    return name


@lru_cache(maxsize=1)
def _load() -> tuple[dict[str, dict[str, Any]], Registry]:
    schemas: dict[str, dict[str, Any]] = {}
    registry: Registry = Registry()
    for name in SCHEMA_NAMES:
        schema = json.loads((_schema_dir() / f"{name}.schema.json").read_text(encoding="utf-8"))
        schemas[name] = schema
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema, DRAFT202012))
    return schemas, registry.crawl()


@cache
def _validator(name: str) -> Draft202012Validator:
    schemas, registry = _load()
    return Draft202012Validator(schemas[name], registry=registry, format_checker=FormatChecker())


def pack_schema(schema_name: str) -> dict[str, Any]:
    """The raw pack schema dict (read-only use: do not mutate)."""
    return _load()[0][_normalise(schema_name)]


def validate_against_pack(obj: Any, schema_name: str) -> tuple[bool, list[str]]:
    """Validate ``obj`` against a pack schema. Returns (ok, errors).

    Each error is "<json path>: <message>", sorted by path, so output is stable.
    """
    if hasattr(obj, "to_pack"):
        obj = obj.to_pack()
    validator = _validator(_normalise(schema_name))
    errors = sorted(validator.iter_errors(obj), key=lambda e: (list(map(str, e.absolute_path)), e.message))
    messages = [f"{e.json_path}: {e.message}" for e in errors]
    return (not messages), messages
