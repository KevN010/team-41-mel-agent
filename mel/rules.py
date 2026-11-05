"""Decision engine: one insight in, one DecisionRecord out. Pure code, no model calls, no I/O
beyond reading mel/rules.yaml once.

    decision = decide(insight, clock, calendar, rules)

``insight`` is an Insight or a raw dict (junk rows may not parse). ``calendar`` is
``{crop: last end_date}`` (mel.fixtures.load_crop_calendar). ``rules`` is pack rules.json
(mel.fixtures.load_rules). The ordered rule table lives in mel/rules.yaml; each row names a
condition in CONDITIONS. The first row whose condition is true wins. R8 always matches.

R1 also fires when a raw dict fails the pack insight schema (mel.validate).

Insight text is untrusted and is never logged here; nothing here logs at all.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from mel.models import DecisionRecord, Insight, SendWindow, TimingProfile, to_ist
from mel.protocols import Clock
from mel.settings import settings
from mel.validate import validate_against_pack

RULES_FILE = Path(__file__).with_name("rules.yaml")

WindowFn = Callable[[Insight, TimingProfile, Clock, Mapping[str, Any]], SendWindow | None]


@dataclass(frozen=True)
class Context:
    """What a condition may look at. ``insight`` is None when the input failed validation."""

    insight: Insight | None
    calendar: Mapping[str, date]
    rules: Mapping[str, Any]


# --------------------------------------------------------------------------- conditions


def _season_end(ctx: Context) -> date:
    raw = ctx.rules.get("window_rules", {}).get("season_end")
    return date.fromisoformat(raw) if raw else settings.SEASON_END


def window_start_date(insight: Insight, rules: Mapping[str, Any]) -> date:
    """Earliest date a survey could be sent: created date + lo days of its timing bucket.

    Timing ``none`` has no lo/hi pair; its start is action_window_days (default 2 when null)
    plus ``none_start_after_action_window_days``.
    """
    created = to_ist(insight.created_at).date()
    spec = rules["send_window_days"][insight.verification.timing]
    if isinstance(spec, str):  # "from_action_window"
        wr = rules["window_rules"]
        aw = insight.action_window_days
        if aw is None:
            aw = wr["action_window_days_if_null"]
        return created + timedelta(days=aw + wr["none_start_after_action_window_days"])
    return created + timedelta(days=spec[0])


def junk_or_invalid(ctx: Context) -> bool:
    # Schema failures arrive as insight None. A parsed junk row has quality_flag junk.
    return ctx.insight is None or ctx.insight.quality_flag == "junk"


def severity_critical(ctx: Context) -> bool:
    return ctx.insight is not None and ctx.insight.severity == "critical"


def resolution_generic_information(ctx: Context) -> bool:
    return ctx.insight is not None and ctx.insight.resolution_type == "generic_information"


def resolution_needs_more_context(ctx: Context) -> bool:
    return ctx.insight is not None and ctx.insight.resolution_type == "needs_more_context"


def verification_not_needed(ctx: Context) -> bool:
    return ctx.insight is not None and ctx.insight.verification.needed is False


def window_starts_after_season(ctx: Context) -> bool:
    return ctx.insight is not None and window_start_date(ctx.insight, ctx.rules) > _season_end(ctx)


def crop_already_harvested(ctx: Context) -> bool:
    """Created on or after the crop's last calendar end date. Crops not in the calendar pass."""
    if ctx.insight is None:
        return False
    asset = ctx.insight.asset
    if asset is None or asset.category != "crop" or asset.name is None:
        return False
    last_end = ctx.calendar.get(asset.name)
    return last_end is not None and to_ist(ctx.insight.created_at).date() >= last_end


def otherwise(ctx: Context) -> bool:
    return True


CONDITIONS: dict[str, Callable[[Context], bool]] = {
    f.__name__: f
    for f in (
        junk_or_invalid,
        severity_critical,
        resolution_generic_information,
        resolution_needs_more_context,
        verification_not_needed,
        window_starts_after_season,
        crop_already_harvested,
        otherwise,
    )
}


# --------------------------------------------------------------------------- rule table


@dataclass(frozen=True)
class Rule:
    id: str
    condition: str
    reason_code: str | None


@lru_cache(maxsize=1)
def load_rule_table() -> tuple[Rule, ...]:
    raw = yaml.safe_load(RULES_FILE.read_text(encoding="utf-8"))
    table = tuple(Rule(r["id"], r["condition"], r.get("reason_code")) for r in raw["rules"])
    unknown = [r.condition for r in table if r.condition not in CONDITIONS]
    if unknown:
        raise ValueError(f"rules.yaml names unknown conditions: {unknown}")
    if not table or table[-1].condition != "otherwise":
        raise ValueError("rules.yaml must end with the 'otherwise' rule")
    return table


# --------------------------------------------------------------------------- decide


def _parse(insight: Insight | Mapping[str, Any]) -> Insight | None:
    """Return a typed Insight, or None if the input is not a valid insight (-> R1)."""
    if isinstance(insight, Insight):
        return insight
    ok, _errors = validate_against_pack(dict(insight), "insight")  # errors may echo values: unused
    if not ok:
        return None
    try:
        return Insight.model_validate(dict(insight))
    except ValidationError:
        return None


def _ident(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    return value if isinstance(value, str) and 0 < len(value) <= 64 else "unknown"


def _default_window_fn(
    insight: Insight, profile: TimingProfile, clock: Clock, rules: Mapping[str, Any]
) -> SendWindow | None:
    """mel.timing.send_window if wave 1 B has landed, else no window (None)."""
    try:
        from mel.timing import send_window
    except ImportError:
        return None
    result = send_window(insight, profile, clock, rules)
    return result if isinstance(result, SendWindow) else None


def decide(
    insight: Insight | Mapping[str, Any],
    clock: Clock,
    calendar: Mapping[str, date],
    rules: Mapping[str, Any],
    *,
    profile: TimingProfile | None = None,
    window_fn: WindowFn | None = None,
) -> DecisionRecord:
    """Apply rules R1..R8 in order and return the DecisionRecord.

    ``profile`` defaults to settings.TIMING_PROFILE. For R8 the send window comes from
    ``window_fn`` (default: mel.timing.send_window when that module exists, else None).
    ``created_at`` on the record is the decision time, ``clock.now()``.
    """
    profile = profile or settings.TIMING_PROFILE
    parsed = _parse(insight)
    ctx = Context(parsed, calendar, rules)

    rule = next(r for r in load_rule_table() if CONDITIONS[r.condition](ctx))

    raw: Mapping[str, Any] = (
        parsed.model_dump(mode="json") if parsed is not None else (insight if isinstance(insight, Mapping) else {})
    )
    window = None
    if rule.id == "R8":
        assert parsed is not None  # R1 catches None
        window = (window_fn or _default_window_fn)(parsed, profile, clock, rules)

    return DecisionRecord(
        insight_id=_ident(raw, "insight_id"),
        farmer_id=_ident(raw, "farmer_id"),
        survey=rule.id == "R8",
        rule_id=rule.id,  # type: ignore[arg-type]
        reason_code=rule.reason_code,  # type: ignore[arg-type]
        timing_profile=profile,
        send_window=window,
        created_at=clock.now(),
    )
