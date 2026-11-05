"""Hand-off and no-survey records. Pure code: no model calls, no I/O, no logging.

    build_handoff(survey, insight, decision, clock, rules) -> ScheduleHandoff
    build_no_survey(decision) -> (NoSurvey | None, DecisionRecord)

Every constant comes from pack/json/rules/rules.json (passed in as ``rules``, the dict that
``mel.fixtures.load_rules()`` returns). Errors raised here name fields, never values: insight
text must not reach a log line.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from mel.fixtures import load_rules
from mel.models import (
    Channel,
    ChannelStep,
    DecisionRecord,
    FarmerchatFlow,
    FrequencyCap,
    Insight,
    NoSurvey,
    Priority,
    ReasonCode,
    RuleId,
    ScheduleHandoff,
    SendHours,
    Survey,
    to_ist,
)
from mel.protocols import Clock

# The pack derives its FarmerChat ids with uuid5 (checked against all five scenario hand-offs):
#   namespace   = uuid5(NAMESPACE_URL, "https://farmerchat.digitalgreen.org/mel")
#   campaign_id = uuid5(namespace, rules.farmerchat_flow.campaign_name)
#   flow_id     = uuid5(namespace, survey_id)
# rules.json carries only the campaign name, not the ids, so the derivation lives here.
_ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://farmerchat.digitalgreen.org/mel")

# Golden reason code per no-survey rule. R3 and R4 also map to the 2-code no_survey schema.
RULE_REASON: dict[str, ReasonCode] = {
    "R1": "junk_insight",
    "R2": "critical_needs_human_call",
    "R3": "nothing_to_verify",
    "R4": "waiting_for_details",
    "R5": "no_check_needed",
    "R6": "window_after_season",
    "R7": "crop_already_harvested",
}

# Fixed, farmer-neutral reasons. They never quote the insight (it is untrusted data).
_NO_SURVEY: dict[str, tuple[str, str]] = {
    "R3": (
        "generic_information",
        "No action was advised, so there is no advice to check on.",
    ),
    "R4": (
        "needs_more_context",
        "No advice was given yet; the conversation is still open.",
    ),
}


class HandoffError(ValueError):
    """The inputs do not describe one surveyable insight. The message names fields only."""


# --------------------------------------------------------------------------- pieces


def priority_for(insight: Insight, rules: dict[str, Any]) -> Priority:
    """high wins over low; otherwise normal. Conditions come from rules.json ``priority``."""
    cfg = rules["priority"]
    if (
        insight.resolution_type in cfg["high_if_resolution"]
        or (insight.severity is not None and insight.severity in cfg["high_if_severity"])
        or insight.behavioral_intent in cfg["high_if_behavioral_intent"]
    ):
        return "high"
    if insight.resolution_type in cfg["low_if_resolution"]:
        return "low"
    return "normal"


def channel_order_for(insight: Insight, priority: Priority, rules: dict[str, Any]) -> list[ChannelStep]:
    """preferred channel, the verification method's channel, WhatsApp, then voice (high only).

    Each channel appears once. Every step but the last waits ``wait_hours_by_priority``.
    """
    order: list[Channel] = [insight.preferred_channel]
    by_method = rules["channel_by_method"].get(insight.verification.method)
    if by_method is not None and by_method not in order:
        order.append(by_method)
    if "whatsapp" not in order:
        order.append("whatsapp")
    if priority == "high" and "voice" not in order:
        order.append("voice")
    wait = rules["wait_hours_by_priority"][priority]
    last = len(order) - 1
    return [ChannelStep(channel=ch, wait_hours=None if i == last else wait) for i, ch in enumerate(order)]


def survey_id_lower(survey_id: str) -> str:
    return survey_id.lower().replace("-", "_")


def campaign_id(rules: dict[str, Any]) -> str:
    return str(uuid.uuid5(_ID_NAMESPACE, rules["farmerchat_flow"]["campaign_name"]))


def flow_id(survey_id: str) -> str:
    return str(uuid.uuid5(_ID_NAMESPACE, survey_id))


def handoff_id_for(survey_id: str) -> str:
    """H-<digits of the survey id>. The pack's five hand-offs follow this (S-21310 -> H-21310)."""
    return "H-" + survey_id.removeprefix("S-")


# --------------------------------------------------------------------------- builders


def build_handoff(
    survey: Survey,
    insight: Insight,
    decision: DecisionRecord,
    clock: Clock,
    rules: dict[str, Any] | None = None,
) -> ScheduleHandoff:
    """Build the scheduler hand-off for one surveyed insight (decision rule R8).

    created_at is ``clock.now()``. The send window is the survey's. Raises HandoffError when
    the decision is not a survey decision or the three inputs are about different insights or
    farmers.
    """
    rules = rules if rules is not None else load_rules()

    if not decision.survey:
        raise HandoffError("decision is not a survey decision (rule_id is not R8)")
    if decision.insight_id != insight.insight_id:
        raise HandoffError("decision.insight_id does not match insight.insight_id")
    if not (decision.farmer_id == insight.farmer_id == survey.farmer_id):
        raise HandoffError("farmer_id differs between decision, insight and survey")
    if insight.insight_id not in survey.source_insight_ids:
        raise HandoffError("survey.source_insight_ids does not include the insight")
    if decision.send_window is not None and decision.send_window != survey.send_window:
        raise HandoffError("decision.send_window differs from survey.send_window")

    priority = priority_for(insight, rules)
    window = survey.send_window
    cap = rules["frequency_cap"]
    flow = rules["farmerchat_flow"]

    return ScheduleHandoff(
        handoff_id=handoff_id_for(survey.survey_id),
        created_at=to_ist(clock.now()),
        survey=survey,
        send_window=window,
        send_hours=SendHours(**{"from": rules["send_hours"]["from"], "to": rules["send_hours"]["to"]}),
        channel_order=channel_order_for(insight, priority, rules),
        frequency_cap=FrequencyCap(
            key=cap["key"].format(farmer_id=insight.farmer_id),
            max_surveys=cap["max_surveys"],
            window_days=cap["window_days"],
            exempt=priority in cap["exempt_priority"],
        ),
        priority=priority,
        expires_at=window.not_after + timedelta(days=rules["expiry_days_after_window"]),
        farmerchat_flow=FarmerchatFlow(
            org_id=flow["org_id"],
            flow_key=flow["flow_key"].format(survey_id_lower=survey_id_lower(survey.survey_id)),
            version=flow["version"],
            campaign_id=campaign_id(rules),
            flow_id=flow_id(survey.survey_id),
        ),
    )


def build_no_survey(decision: DecisionRecord) -> tuple[NoSurvey | None, DecisionRecord]:
    """The no-survey output for a non-R8 decision.

    Returns ``(NoSurvey, record)`` for R3 (generic_information) and R4 (needs_more_context),
    the only two cases the pack's no_survey schema covers. For R1, R2, R5, R6 and R7 nothing
    goes out and the first item is None. The returned DecisionRecord always carries the
    golden reason code for its rule. Raises HandoffError for a survey (R8) decision.
    """
    if decision.survey:
        raise HandoffError("decision is a survey decision; use build_handoff")

    rule: RuleId = decision.rule_id
    golden = RULE_REASON[rule]
    if decision.reason_code != golden:
        record = DecisionRecord.model_validate({**decision.model_dump(), "reason_code": golden})
    else:
        record = decision

    entry = _NO_SURVEY.get(rule)
    if entry is None:
        return None, record
    code, reason = entry
    notice = NoSurvey(
        insight_id=decision.insight_id,
        farmer_id=decision.farmer_id,
        reason_code=code,  # type: ignore[arg-type]
        reason=reason,
    )
    return notice, record
