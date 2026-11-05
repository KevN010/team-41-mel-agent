"""Environment-driven settings (pydantic-settings style, plain pydantic, no extra dependency).

Every field reads the environment variable of the same name. Lists accept JSON
(``["en-IN","hi-IN"]``) or a comma list (``en-IN,hi-IN``). Import the shared instance:

    from mel.settings import settings
    settings.LANGUAGES

Tests that need other values build their own: ``Settings.from_env({"TIMING_PROFILE": "rules_v1"})``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

REPO_ROOT = Path(__file__).resolve().parent.parent
# Deployed packages (Lambda zip, agent container) hold mel/ and models/ but not pack/. The runtime
# subset of the pack (schemas, rules, crop calendar) is kept in mel/_pack; tests/test_runtime_pack.py
# checks it is byte-identical to pack/.
RUNTIME_PACK_DIR = Path(__file__).resolve().parent / "_pack"


def _default_pack_dir() -> Path:
    full = REPO_ROOT / "pack"
    return full if (full / "json" / "schemas").is_dir() else RUNTIME_PACK_DIR


# The deployed environment (infra/app.py, CLAUDE.md) uses MEL_* names. A plain name wins when both
# are set, so tests and local runs keep working.
ENV_ALIASES = {
    "MEL_REGION": "REGION",
    "MEL_TABLE": "LEDGER_TABLE",
    "MEL_FOLLOWUP_QUEUE_URL": "FOLLOW_UP_QUEUE_URL",
    "MEL_MODELS_FILE": "MODELS_FILE",
    "MEL_METRICS_NAMESPACE": "METRICS_NAMESPACE",
}

JEV_CHECKS = (
    "matches_advice",
    "gives_new_advice",
    "asks_personal_info",
    "inappropriate_content",
    "language_matches_tag",
)


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    REGION: str = "us-west-2"
    LANGUAGES: list[str] = Field(default_factory=lambda: ["en-IN"])
    TIMING_PROFILE: Literal["golden_v1", "rules_v1"] = "golden_v1"
    RATE_LIMIT_RPM: int = Field(60, ge=1)
    MODELS_FILE: Path = REPO_ROOT / "models" / "models.yaml"
    PACK_DIR: Path = Field(default_factory=_default_pack_dir)
    SEASON_END: date = date(2027, 3, 31)
    MAX_TOKENS: int = Field(600, ge=1)

    # Jev (TypeSafe System One). The key is read from JEV_API_KEY, which the deploy fills
    # from Secrets Manager. SecretStr keeps it out of repr() and logs.
    JEV_URL: str = "https://api.typesafe.ai/v1/systemone"
    JEV_TIMEOUT_S: float = Field(2.0, gt=0)
    JEV_API_KEY: SecretStr | None = None
    # Thresholds for the five Jev checks (see mel/judge.py for direction of each).
    JEV_THRESHOLD_MATCHES_ADVICE: float = Field(0.5, ge=0, le=1)
    JEV_THRESHOLD_GIVES_NEW_ADVICE: float = Field(0.5, ge=0, le=1)
    JEV_THRESHOLD_ASKS_PERSONAL_INFO: float = Field(0.5, ge=0, le=1)
    JEV_THRESHOLD_INAPPROPRIATE_CONTENT: float = Field(0.5, ge=0, le=1)
    JEV_THRESHOLD_LANGUAGE_MATCHES_TAG: float = Field(0.5, ge=0, le=1)

    # AWS resource names (CDK sets these on the Lambda environment).
    LEDGER_TABLE: str = "mel-ledger"
    FOLLOW_UP_QUEUE_URL: str | None = None
    METRICS_NAMESPACE: str = "MelAgent"
    METRICS_OFF: bool = False

    @field_validator("LANGUAGES", mode="before")
    @classmethod
    def _split_list(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("["):
                return json.loads(value)
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("MODELS_FILE", mode="after")
    @classmethod
    def _models_file_from_root(cls, value: Path) -> Path:
        # MEL_MODELS_FILE is "models/models.yaml" in the deployed env: relative to the package root.
        return value if value.is_absolute() else REPO_ROOT / value

    @field_validator("REGION")
    @classmethod
    def _region_fixed(cls, value: str) -> str:
        if value != "us-west-2":
            raise ValueError("REGION is fixed to us-west-2 (CLAUDE.md)")
        return value

    @property
    def jev_thresholds(self) -> dict[str, float]:
        return {check: getattr(self, f"JEV_THRESHOLD_{check.upper()}") for check in JEV_CHECKS}

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        values = {
            field: env[alias]
            for alias, field in ENV_ALIASES.items()
            if env.get(alias) and field in cls.model_fields
        }
        values |= {name: env[name] for name in cls.model_fields if name in env and env[name] != ""}
        return cls.model_validate(values)


settings = Settings.from_env()


def get_settings() -> Settings:
    return settings
