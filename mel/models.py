"""Pydantic v2 models for every record mel-agent reads or writes.

Field names and enum values are copied from pack/json/schemas/*.json. Models are a typed
view of the pack schemas; the schemas stay the judge (see mel.validate). Every model:

- forbids unknown fields (the schemas use additionalProperties: false);
- serialises with ``to_pack()`` to the exact JSON shape the pack uses: optional fields that
  are unset (None) are left out, required-but-nullable fields are written as null;
- stores timestamps as timezone-aware datetimes in India time (+05:30). Naive datetimes are
  rejected. Strings must carry the literal +05:30 offset, as the schemas require.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    StrictInt,
    StrictStr,
    model_serializer,
    model_validator,
)

# --------------------------------------------------------------------------- time

IST = timezone(timedelta(hours=5, minutes=30), "IST")

_IST_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+05:30$")
_INSIGHT_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?\+05:30$")


def to_ist(value: datetime) -> datetime:
    """Return an aware datetime in +05:30. Raises ValueError on a naive datetime."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("naive datetime: every timestamp must carry the +05:30 offset")
    return value.astimezone(IST)


def _ist_validator(pattern: re.Pattern[str], whole_seconds: bool):
    def check(value: Any) -> datetime:
        if isinstance(value, str):
            if not pattern.match(value):
                raise ValueError(f"timestamp must match {pattern.pattern}")
            dt = datetime.fromisoformat(value)
        elif isinstance(value, datetime):
            dt = value
        else:
            raise TypeError("timestamp must be an ISO 8601 string or a datetime")
        dt = to_ist(dt)
        return dt.replace(microsecond=0) if whole_seconds else dt

    return check


IstTime = Annotated[
    datetime,
    BeforeValidator(_ist_validator(_IST_TIME_RE, whole_seconds=True)),
    PlainSerializer(lambda d: d.isoformat(timespec="seconds"), return_type=str, when_used="json"),
]
"""survey.schema.json#/$defs/ist_time: whole seconds, +05:30."""

InsightTime = Annotated[
    datetime,
    BeforeValidator(_ist_validator(_INSIGHT_TIME_RE, whole_seconds=False)),
    PlainSerializer(lambda d: d.isoformat(), return_type=str, when_used="json"),
]
"""insight.created_at: like IstTime but fractional seconds are allowed."""

# --------------------------------------------------------------------------- enums

Channel = Literal["app", "web", "whatsapp", "telegram", "voice"]
QuestionType = Literal["survey-single-select", "survey-confirm", "survey-scale"]
FollowUpReason = Literal[
    "advice_did_not_work",
    "crop_or_animal_damaged",
    "could_not_get_input",
    "could_not_reach_expert",
]
AssetCategory = Literal["crop", "livestock"]
GrowthStage = Literal[
    "germination", "seedling", "vegetative", "tillering", "flowering",
    "fruiting", "maturity", "harvest", "post_harvest", "dormant",
]
Concern = Literal[
    "pest_disease", "weather_climate", "growth_issue", "nutrient_deficiency",
    "variety_selection", "soil_health", "water_stress", "storage_post_harvest",
    "livestock_nutrition", "livestock_health", "market_price", "weed_management",
    "breeding_reproduction", "yield_loss",
]
BehavioralIntent = Literal[
    "procedural_guidance", "information_seeking", "diagnosing", "planning",
    "profile_update", "exploring_options", "symptom_reporting", "confirming",
    "decision_making", "market_inquiry", "following_up", "comparing", "emergency",
]
DecisionEpisodeType = Literal["decision", "problem_resolution", "general_knowledge", "casual", "exploration"]
Severity = Literal["low", "medium", "high", "critical"]
ResolutionType = Literal[
    "direct_action", "generic_information", "plan_created", "needs_more_context",
    "do_not_act", "wait_and_monitor", "escalate_to_expert",
]
VerificationTiming = Literal[
    "none", "same_day", "next_day", "two_to_five_days", "three_to_ten_days",
    "seven_to_fourteen_days", "seasonal",
]
VerificationMethod = Literal["none", "push", "whatsapp", "ivr_callback", "repeat_photo", "agent_followup"]
QualityFlag = Literal["clean", "junk"]

ResponseStatus = Literal[
    "completed", "partial", "negative_outcome", "expired", "declined",
    "delivery_failed", "invalid_input", "stale", "duplicate", "identity_mismatch",
]
FailureCode = Literal[
    "window_expired", "farmer_declined", "farmer_opted_out", "push_token_invalid",
    "client_cannot_render", "wa_session_window_closed", "wa_undelivered", "tg_bot_blocked",
    "voice_no_answer", "voice_busy", "voice_call_dropped", "free_text_instead_of_choice",
    "keypad_out_of_range", "speech_not_understood", "survey_closed", "survey_replaced",
    "duplicate_answer", "identity_mismatch", "sheet_dismissed", "push_not_opened",
]
SheetOutcome = Literal["finished", "closed_partway", "interrupted", "dismissed", "never_opened"]
ItemResult = Literal["answered", "skipped", "invalid", "not_reached", "discarded"]
InputKind = Literal["sheet_tap", "button_reply", "list_reply", "callback_data", "keypad", "speech", "free_text"]
RetryDecision = Literal["none", "retry_same_channel", "fall_back_to_next_channel", "give_up"]
Priority = Literal["high", "normal", "low"]

# Our own (not in the pack): rule ids and the 7 golden no-survey reason codes.
RuleId = Literal["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]
ReasonCode = Literal[
    "junk_insight",
    "critical_needs_human_call",
    "nothing_to_verify",
    "waiting_for_details",
    "no_check_needed",
    "window_after_season",
    "crop_already_harvested",
]
NoSurveyReasonCode = Literal["generic_information", "needs_more_context"]
TimingProfile = Literal["golden_v1", "rules_v1"]

# --------------------------------------------------------------------------- shared types

Id64 = Annotated[str, Field(min_length=1, max_length=64)]
SurveyId = Annotated[str, Field(pattern=r"^S-[0-9]{5,10}$")]
ItemId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")]
OptionValue = Annotated[StrictStr, Field(pattern=r"^[a-z0-9][a-z0-9_]{0,63}$")]
ScaleValue = Annotated[StrictInt, Field(ge=0, le=100)]
LanguageTag = Annotated[str, Field(pattern=r"^[a-z]{2,3}-[A-Z]{2}$")]
AnswerValue = OptionValue | ScaleValue
"""A stored answer: the option value string, or the integer for a scale."""


class PackModel(BaseModel):
    """Base for every pack record. See module docstring for the serialisation rules."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @model_serializer(mode="wrap")
    def _omit_unset_optionals(self, handler):
        data = handler(self)
        if isinstance(data, dict):
            for name, field in type(self).model_fields.items():
                if not field.is_required() and getattr(self, name) is None:
                    data.pop(name, None)
                    if field.alias:
                        data.pop(field.alias, None)
        return data

    def to_pack(self) -> dict[str, Any]:
        """JSON-ready dict in the pack's exact shape. Feed this to mel.validate."""
        return self.model_dump(mode="json", by_alias=True)


# --------------------------------------------------------------------------- insight


class Location(PackModel):
    country: Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
    state: Annotated[str, Field(min_length=1, max_length=80)]
    district: Annotated[str, Field(min_length=1, max_length=80)]


class Asset(PackModel):
    """Every field is required by the schema but may be null."""

    name: Annotated[str, Field(min_length=1, max_length=60, pattern=r"^[a-z][a-z ()-]*$")] | None
    category: AssetCategory | None
    growth_stage: GrowthStage | None


class Verification(PackModel):
    needed: bool
    timing: VerificationTiming
    method: VerificationMethod


class Insight(PackModel):
    insight_id: Id64
    farmer_id: Id64
    conversation_id: Id64
    created_at: InsightTime
    conversation_language: LanguageTag
    location: Location
    asset: Asset
    concern: Concern | None
    behavioral_intent: BehavioralIntent
    decision_episode_type: DecisionEpisodeType | None
    severity: Severity | None
    query_summary: Annotated[str, Field(min_length=1, max_length=400)]
    advice_summary: Annotated[str, Field(min_length=1, max_length=600)]
    resolution_type: ResolutionType
    action_window_days: Annotated[StrictInt, Field(ge=0, le=180)] | None
    verification: Verification
    preferred_channel: Channel
    quality_flag: QualityFlag | None = None


# --------------------------------------------------------------------------- survey


class SendWindow(PackModel):
    not_before: IstTime
    not_after: IstTime


class Option(PackModel):
    value: OptionValue
    label: Annotated[str, Field(min_length=1, max_length=20)]
    follow_up: FollowUpReason | None = None


class SurveyItem(PackModel):
    item_id: ItemId
    type: QuestionType
    prompt: Annotated[str, Field(min_length=1, max_length=400)]
    options: Annotated[list[Option], Field(min_length=2, max_length=10)] | None = None
    scale_min: Annotated[StrictInt, Field(ge=0, le=100)] | None = None
    scale_max: Annotated[StrictInt, Field(ge=1, le=100)] | None = None
    follow_up_at_or_below: Annotated[StrictInt, Field(ge=0, le=100)] | None = None
    follow_up_reason: FollowUpReason | None = None

    @model_validator(mode="after")
    def _schema_allof(self) -> SurveyItem:
        # Mirrors the allOf block of survey.schema.json#/$defs/item.
        if self.type == "survey-scale":
            if self.scale_min is None or self.scale_max is None:
                raise ValueError("survey-scale needs scale_min and scale_max")
            if self.options is not None:
                raise ValueError("survey-scale must not have options")
        else:
            if self.options is None:
                raise ValueError(f"{self.type} needs options")
            if any(v is not None for v in (self.scale_min, self.scale_max, self.follow_up_at_or_below)):
                raise ValueError(f"{self.type} must not have scale_min, scale_max or follow_up_at_or_below")
        if self.type == "survey-confirm" and self.options is not None and len(self.options) > 2:
            raise ValueError("survey-confirm has at most 2 options")
        if self.follow_up_at_or_below is not None and self.follow_up_reason is None:
            raise ValueError("follow_up_at_or_below needs follow_up_reason")
        return self


class SelfEval(PackModel):
    """schema_valid is always computed by mel.validate, never copied from a model."""

    schema_valid: bool | None = None
    relevance_score: Annotated[float, Field(ge=0, le=1)] | None = None
    gives_new_advice: bool | None = None
    asks_personal_info: bool | None = None


class Survey(PackModel):
    survey_id: SurveyId
    farmer_id: Id64
    source_insight_ids: Annotated[list[Id64], Field(min_length=1, max_length=5)]
    language: LanguageTag
    send_window: SendWindow
    items: Annotated[list[SurveyItem], Field(min_length=1, max_length=3)]
    rationale: Annotated[str, Field(min_length=1, max_length=400)]
    self_eval: SelfEval | None = None

    @model_validator(mode="after")
    def _unique_ids(self) -> Survey:
        if len(set(self.source_insight_ids)) != len(self.source_insight_ids):
            raise ValueError("source_insight_ids must be unique")
        return self


class NoSurvey(PackModel):
    insight_id: Id64
    farmer_id: Id64
    decision: Literal["no_survey"] = "no_survey"
    reason_code: NoSurveyReasonCode
    reason: Annotated[str, Field(min_length=1, max_length=300)]


# --------------------------------------------------------------------------- hand-off

HHMM = Annotated[str, Field(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")]


class SendHours(PackModel):
    from_: HHMM = Field(alias="from")
    to: HHMM


class ChannelStep(PackModel):
    channel: Channel
    wait_hours: Annotated[StrictInt, Field(ge=1, le=168)] | None


class FrequencyCap(PackModel):
    key: Annotated[str, Field(pattern=r"^mel:farmer:.{1,64}$")]
    max_surveys: Annotated[StrictInt, Field(ge=1, le=7)]
    window_days: Annotated[StrictInt, Field(ge=1, le=90)]
    exempt: bool


class FarmerchatFlow(PackModel):
    org_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,64}$")]
    flow_key: ItemId
    version: Annotated[StrictInt, Field(ge=1)]
    campaign_id: Annotated[str, Field(pattern=r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")]
    flow_id: Annotated[str, Field(pattern=r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")]


class ScheduleHandoff(PackModel):
    handoff_id: Annotated[str, Field(pattern=r"^H-[0-9]{5,10}$")]
    created_at: IstTime
    survey: Survey
    send_window: SendWindow
    send_hours: SendHours
    channel_order: Annotated[list[ChannelStep], Field(min_length=1, max_length=5)]
    frequency_cap: FrequencyCap
    priority: Priority
    expires_at: IstTime
    farmerchat_flow: FarmerchatFlow


# --------------------------------------------------------------------------- response


class ResponseItem(PackModel):
    item_id: ItemId
    item_type: QuestionType
    result: ItemResult
    value: StrictStr | StrictInt | None
    raw_input: Annotated[str, Field(max_length=256)] | None
    input_kind: InputKind | None
    attempts: Annotated[StrictInt, Field(ge=0, le=5)]


class Timestamps(PackModel):
    """Null when the step did not happen or the channel cannot tell (Telegram: opened is null)."""

    sent: IstTime | None
    delivered: IstTime | None
    opened: IstTime | None
    answered: IstTime | None


class FarmerchatReply(PackModel):
    http_status: Literal[200, 201, 404, 422]
    outcome: Literal["accepted", "duplicate", "unknown_flow", "invalid_answer"]


class ResponseRecord(PackModel):
    response_key: Id64
    survey_id: SurveyId
    farmer_id: Id64
    source_insight_ids: Annotated[list[Id64], Field(min_length=1)]
    channel: Channel
    language: LanguageTag
    question_type: QuestionType | None = None
    status: ResponseStatus
    failure_code: FailureCode | None
    answers: Annotated[dict[ItemId, AnswerValue], Field(max_length=3)]
    items: Annotated[list[ResponseItem], Field(min_length=1, max_length=3)]
    complete: bool
    delivery_attempt: Annotated[StrictInt, Field(ge=1, le=5)]
    timestamps: Timestamps
    recorded_at: IstTime
    answered_by: Annotated[str, Field(max_length=64)] | None
    sheet_outcome: SheetOutcome | None
    raw_event: Annotated[str, Field(max_length=256)] | None
    retry_decision: RetryDecision
    retry_after_minutes: Annotated[StrictInt, Field(ge=0, le=10080)] | None
    counts_toward_cap: bool
    farmerchat_reply: FarmerchatReply | None
    needs_follow_up: bool
    follow_up_reasons: list[FollowUpReason]

    @model_validator(mode="after")
    def _unique_lists(self) -> ResponseRecord:
        if len(set(self.source_insight_ids)) != len(self.source_insight_ids):
            raise ValueError("source_insight_ids must be unique")
        if len(set(self.follow_up_reasons)) != len(self.follow_up_reasons):
            raise ValueError("follow_up_reasons must be unique")
        return self


# --------------------------------------------------------------------------- bottom sheet


class SheetPresentation(PackModel):
    type: Literal["bottom_sheet"]
    opens_when: Annotated[
        list[Literal["push_tapped", "next_app_open", "next_web_visit"]], Field(min_length=1)
    ]
    waits_for: Annotated[
        list[Literal["answer_finished_streaming", "no_typing_for_5_seconds", "no_call_in_progress"]],
        Field(min_length=1),
    ]
    one_question_per_step: Literal[True]
    steps_total: Annotated[StrictInt, Field(ge=1, le=3)]
    can_skip: Literal[True]
    can_close: Literal[True]
    swipe_down_closes: Literal[True]


class SheetOption(PackModel):
    label: Annotated[str, Field(min_length=1, max_length=20)]
    answer: AnswerValue


class SheetStep(PackModel):
    step: Annotated[StrictInt, Field(ge=1, le=3)]
    step_label: Annotated[str, Field(min_length=1, max_length=20)]
    item_id: ItemId
    question_type: QuestionType
    question: Annotated[str, Field(min_length=1, max_length=400)]
    options: Annotated[list[SheetOption], Field(min_length=2, max_length=10)]


class Sheet(PackModel):
    title: Annotated[str, Field(min_length=1, max_length=80)]
    skip_label: Annotated[str, Field(min_length=1, max_length=20)]
    close_label: Annotated[str, Field(min_length=1, max_length=20)]
    steps: Annotated[list[SheetStep], Field(min_length=1, max_length=3)]
    thank_you: Annotated[str, Field(min_length=1, max_length=200)]


class BottomSheet(PackModel):
    """The presentation + sheet part of an app/web render file.

    Render files (scenarios/*/render/*/app.json, web.json) also carry ``channel`` and
    ``how_it_arrives``, which bottom_sheet.schema.json does not allow. Strip them first:
    ``BottomSheet.from_render(render_dict)``.
    """

    presentation: SheetPresentation
    sheet: Sheet

    @classmethod
    def from_render(cls, render: dict[str, Any]) -> BottomSheet:
        return cls.model_validate({k: render[k] for k in ("presentation", "sheet")})


# --------------------------------------------------------------------------- our own records


class DecisionRecord(PackModel):
    """The decision engine's output for one insight (mel/rules.py). Not a pack record.

    reason_code is one of the 7 golden no-survey codes, or None when survey is True (R8).
    Mapping to the 2-code no_survey schema happens in mel/handoff.py.
    """

    insight_id: Id64
    farmer_id: Id64
    survey: bool
    rule_id: RuleId
    reason_code: ReasonCode | None
    timing_profile: TimingProfile
    send_window: SendWindow | None
    created_at: IstTime

    @model_validator(mode="after")
    def _consistent(self) -> DecisionRecord:
        if self.survey != (self.rule_id == "R8"):
            raise ValueError("survey is True exactly when rule_id is R8")
        if self.survey and self.reason_code is not None:
            raise ValueError("an R8 (survey) decision has reason_code None")
        if not self.survey and self.reason_code is None:
            raise ValueError("a no-survey decision needs a reason_code")
        if not self.survey and self.send_window is not None:
            raise ValueError("a no-survey decision has send_window None")
        return self


class Attempt(PackModel):
    """One delivery try of one survey on one channel. Input to mel.outcomes.apply_event.

    response_key is the sender's key for this try; a transport retry keeps the same
    response_key and delivery_attempt.
    """

    survey_id: SurveyId
    farmer_id: Id64
    channel: Channel
    delivery_attempt: Annotated[StrictInt, Field(ge=1, le=5)]
    response_key: Id64
    language: LanguageTag
    source_insight_ids: Annotated[list[Id64], Field(min_length=1)]
    created_at: IstTime


class FollowUpItem(PackModel):
    """What goes to FarmerChat's follow-up queue when a response has needs_follow_up."""

    follow_up_id: Id64
    farmer_id: Id64
    survey_id: SurveyId
    response_key: Id64
    source_insight_ids: Annotated[list[Id64], Field(min_length=1)]
    reasons: Annotated[list[FollowUpReason], Field(min_length=1)]
    accepted_answers: dict[ItemId, AnswerValue]
    created_at: IstTime


class Usage(PackModel):
    """Token and latency accounting for one model call. Never holds prompt or output text."""

    model_id: str
    input_tokens: Annotated[StrictInt, Field(ge=0)]
    output_tokens: Annotated[StrictInt, Field(ge=0)]
    latency_ms: Annotated[float, Field(ge=0)]
    cost_usd: Annotated[float, Field(ge=0)] | None = None


class JudgeVerdict(PackModel):
    """Jev's verdict on one survey. pending_review: Jev failed or returned bad data; never ok."""

    ok: bool
    scores: dict[str, float]
    reason: str | None = None
    pending_review: bool = False

    @model_validator(mode="after")
    def _pending_is_not_ok(self) -> JudgeVerdict:
        if self.pending_review and self.ok:
            raise ValueError("a pending_review verdict cannot be ok")
        return self


class PutOutcome(StrEnum):
    """Return value of conditional ledger writes."""

    WRITTEN = "written"
    DUPLICATE = "duplicate"
    OPTED_OUT = "opted_out"


__all__ = [name for name in dir() if not name.startswith("_")]
