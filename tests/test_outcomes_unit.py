"""Unit tests for mel.outcomes.apply_event. Offline. Surveys are built here, not read from the pack."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from mel.fixtures import load_outcome_codes
from mel.models import IST, Attempt, Survey
from mel.outcomes import (
    InvalidAnswer,
    NonTerminalEvent,
    apply_event,
    update_timestamps,
)
from mel.validate import validate_against_pack

FARMER = "F-000001"
OTHER = "F-000002"
SURVEY_ID = "S-90001"
NOT_BEFORE = "2026-12-16T07:00:00+05:30"
NOT_AFTER = "2026-12-18T19:00:00+05:30"
T_ANSWER = "2026-12-16T07:25:00+05:30"


def make_survey() -> Survey:
    return Survey.model_validate(
        {
            "survey_id": SURVEY_ID,
            "farmer_id": FARMER,
            "source_insight_ids": ["I-1"],
            "language": "en-IN",
            "send_window": {"not_before": NOT_BEFORE, "not_after": NOT_AFTER},
            "items": [
                {
                    "item_id": "q1",
                    "type": "survey-confirm",
                    "prompt": "Did you spray?",
                    "options": [{"value": "yes", "label": "Yes"}, {"value": "no", "label": "No"}],
                },
                {
                    "item_id": "q2",
                    "type": "survey-single-select",
                    "prompt": "How was it?",
                    "options": [
                        {"value": "easy", "label": "Easy"},
                        {"value": "hard", "label": "Hard"},
                        {"value": "same", "label": "No change", "follow_up": "advice_did_not_work"},
                    ],
                },
                {
                    "item_id": "q3",
                    "type": "survey-scale",
                    "prompt": "How many aphids are left?",
                    "scale_min": 1,
                    "scale_max": 5,
                    "follow_up_at_or_below": 1,
                    "follow_up_reason": "crop_or_animal_damaged",
                },
            ],
            "rationale": "Check the spray worked.",
        }
    )


def make_attempt(channel: str = "app", delivery_attempt: int = 1, **extra: Any) -> dict[str, Any]:
    base = {
        "survey_id": SURVEY_ID,
        "farmer_id": FARMER,
        "channel": channel,
        "delivery_attempt": delivery_attempt,
        "response_key": f"rk-{SURVEY_ID}-{channel}-{delivery_attempt}",
        "language": "en-IN",
        "source_insight_ids": ["I-1"],
        "created_at": NOT_BEFORE,
    }
    return base | extra


def ev(kind: str = "answer", channel: str = "app", **kw: Any) -> dict[str, Any]:
    return {"kind": kind, "channel": channel, "farmer_id": FARMER, "at": T_ANSWER} | kw


def run(clock, codes, event, *, channel="app", survey=None, attempt=None):
    record = apply_event(
        survey or make_survey(),
        attempt if attempt is not None else make_attempt(channel),
        event,
        clock,
        codes,
    )
    ok, errors = validate_against_pack(record.to_pack(), "response")
    assert ok, f"record fails the pack schema: {errors}"
    return record


ALL3 = {"q1": "yes", "q2": "easy", "q3": 4}


# --------------------------------------------------------------------------- success paths


def test_all_answered_is_completed(clock, outcome_codes):
    r = run(clock, outcome_codes, ev(answers=ALL3))
    assert (r.status, r.failure_code, r.complete) == ("completed", None, True)
    assert r.answers == ALL3
    assert [i.result for i in r.items] == ["answered"] * 3
    assert (r.retry_decision, r.retry_after_minutes, r.counts_toward_cap) == ("none", None, True)
    assert (r.needs_follow_up, r.follow_up_reasons) == (False, [])
    assert r.sheet_outcome == "finished"
    assert r.farmerchat_reply.model_dump() == {"http_status": 201, "outcome": "accepted"}
    assert r.answered_by == FARMER


def test_some_answered_is_partial_with_skipped_rest(clock, outcome_codes):
    r = run(clock, outcome_codes, ev(answers={"q1": "yes"}))
    assert (r.status, r.complete) == ("partial", False)
    assert r.answers == {"q1": "yes"}
    assert [i.result for i in r.items] == ["answered", "skipped", "skipped"]
    assert r.sheet_outcome == "closed_partway"
    assert r.counts_toward_cap is True and r.retry_decision == "none"


def test_sheet_outcome_interrupted_when_event_says_so(clock, outcome_codes):
    r = run(clock, outcome_codes, ev(answers={"q1": "yes"}, sheet_outcome="interrupted"))
    assert r.sheet_outcome == "interrupted"
    # The value is only honoured for a partial; a finished sheet stays finished.
    r = run(clock, outcome_codes, ev(answers=ALL3, sheet_outcome="interrupted"))
    assert r.sheet_outcome == "finished"


@pytest.mark.parametrize("channel", ["whatsapp", "telegram", "voice"])
def test_sheet_outcome_is_null_off_the_sheet_channels(clock, outcome_codes, channel):
    r = run(clock, outcome_codes, ev(channel=channel, answers={"q1": "yes"}), channel=channel)
    assert r.sheet_outcome is None


def test_negative_option_makes_negative_outcome(clock, outcome_codes):
    r = run(clock, outcome_codes, ev(answers={"q1": "yes", "q2": "same", "q3": 4}))
    assert r.status == "negative_outcome"
    assert r.complete is True
    assert r.needs_follow_up is True
    assert r.follow_up_reasons == ["advice_did_not_work"]
    assert r.counts_toward_cap is True and r.retry_decision == "none"


@pytest.mark.parametrize("value,negative", [(1, True), (2, False), (5, False)])
def test_scale_follow_up_threshold_is_inclusive(clock, outcome_codes, value, negative):
    r = run(clock, outcome_codes, ev(answers={"q1": "yes", "q2": "easy", "q3": value}))
    assert r.needs_follow_up is negative
    assert r.status == ("negative_outcome" if negative else "completed")
    assert r.follow_up_reasons == (["crop_or_animal_damaged"] if negative else [])


def test_follow_up_reasons_are_unique_and_ordered(clock, outcome_codes):
    r = run(clock, outcome_codes, ev(answers={"q2": "same", "q3": 1}))
    assert r.follow_up_reasons == ["advice_did_not_work", "crop_or_animal_damaged"]
    assert r.status == "negative_outcome" and r.complete is False


def test_partial_with_a_negative_answer_still_goes_to_follow_up(clock, outcome_codes):
    r = run(clock, outcome_codes, ev(answers={"q2": "same"}))
    assert (r.status, r.complete, r.needs_follow_up) == ("negative_outcome", False, True)


# --------------------------------------------------------------------------- accept only valid values


@pytest.mark.parametrize(
    "answers",
    [
        {"q1": "maybe"},  # not an option
        {"q1": "YES"},  # case matters
        {"q1": 1},  # int for a choice item
        {"q2": None},
        {"q3": 6},  # above scale_max
        {"q3": 0},  # below scale_min
        {"q3": True},  # bool is not a scale value
        {"q3": "4"},  # numeric string is not an integer
        {"q3": 4.0},  # float is not an integer
    ],
)
def test_app_rejects_values_the_sheet_cannot_produce(clock, outcome_codes, answers):
    with pytest.raises(InvalidAnswer):
        apply_event(make_survey(), make_attempt("app"), ev(answers=answers), clock, outcome_codes)


def test_unknown_item_id_is_rejected(clock, outcome_codes):
    with pytest.raises(InvalidAnswer):
        apply_event(make_survey(), make_attempt("app"), ev(answers={"q9": "yes"}), clock, outcome_codes)


def test_event_with_no_values_is_rejected(clock, outcome_codes):
    with pytest.raises(ValueError):
        apply_event(make_survey(), make_attempt("app"), ev(answers={}), clock, outcome_codes)


@pytest.mark.parametrize(
    "channel,input_kind,code,attempts",
    [
        ("whatsapp", "free_text", "free_text_instead_of_choice", 1),
        ("telegram", "free_text", "free_text_instead_of_choice", 1),
        ("voice", "keypad", "keypad_out_of_range", 2),
        ("voice", "speech", "speech_not_understood", 2),
    ],
)
def test_bad_value_on_chat_and_voice_is_invalid_input_and_never_accepted(
    clock, outcome_codes, channel, input_kind, code, attempts
):
    event = ev(channel=channel, answers={"q1": "yes", "q2": "not an option"}, input_kind=input_kind)
    r = run(clock, outcome_codes, event, channel=channel)
    assert (r.status, r.failure_code) == ("invalid_input", code)
    assert r.answers == {"q1": "yes"}  # the good answer is kept, the bad one is not
    assert [i.result for i in r.items] == ["answered", "invalid", "not_reached"]
    assert r.items[1].value is None and r.items[1].attempts == attempts
    assert r.complete is False


def test_invalid_input_keeps_follow_up_from_accepted_answers(clock, outcome_codes):
    event = ev(channel="whatsapp", answers={"q2": "same", "q3": 99}, input_kind="free_text")
    r = run(clock, outcome_codes, event, channel="whatsapp")
    assert r.status == "invalid_input"
    assert r.needs_follow_up and r.follow_up_reasons == ["advice_did_not_work"]


# --------------------------------------------------------------------------- identity


def test_identity_mismatch_never_accepts_answers(clock, outcome_codes):
    r = run(clock, outcome_codes, ev(farmer_id=OTHER, answers={"q2": "same"}))
    assert (r.status, r.failure_code) == ("identity_mismatch", "identity_mismatch")
    assert r.answers == {}
    assert all(i.result in ("discarded", "not_reached") for i in r.items)
    assert r.items[1].result == "discarded"
    assert (r.needs_follow_up, r.follow_up_reasons, r.complete) == (False, [], False)
    assert (r.retry_decision, r.counts_toward_cap) == ("give_up", False)
    assert r.answered_by == OTHER
    assert r.farmer_id == FARMER  # the record stays with the surveyed farmer


@pytest.mark.parametrize(
    "event",
    [
        ev("opt_out", farmer_id=OTHER, raw="STOP"),
        ev("decline", farmer_id=OTHER),
        ev("failure", farmer_id=OTHER, failure_code="window_expired"),
        ev(farmer_id=OTHER, answers=ALL3, failure_code="duplicate_answer"),
    ],
)
def test_identity_beats_every_other_outcome(clock, outcome_codes, event):
    channel = "whatsapp"
    r = run(clock, outcome_codes, event | {"channel": channel}, channel=channel)
    assert r.status == "identity_mismatch" and r.answers == {}


def test_missing_event_farmer_is_taken_as_the_surveyed_farmer(clock, outcome_codes):
    event = ev(answers=ALL3)
    del event["farmer_id"]
    assert run(clock, outcome_codes, event).status == "completed"


# --------------------------------------------------------------------------- duplicate, closed, replaced


def test_duplicate_record_is_built_only_when_the_caller_says_so(clock, outcome_codes):
    # The ledger decides duplicates (put_response returns DUPLICATE). apply_event only shapes the record.
    event = ev(answers={"q1": "no"}, at="2026-12-16T07:27:00+05:30", failure_code="duplicate_answer")
    r = run(clock, outcome_codes, event)
    assert (r.status, r.failure_code) == ("duplicate", "duplicate_answer")
    assert r.answers == {}
    assert r.items[0].result == "discarded"
    assert (r.retry_decision, r.counts_toward_cap) == ("none", False)
    assert r.farmerchat_reply.model_dump() == {"http_status": 200, "outcome": "duplicate"}


def test_apply_event_never_decides_a_duplicate_itself(clock, outcome_codes):
    # Same attempt, same key, applied twice: both come out as plain answers. No state, no duplicate.
    a = run(clock, outcome_codes, ev(answers={"q1": "yes"}))
    b = run(clock, outcome_codes, ev(answers={"q1": "yes"}), attempt=make_attempt("app", already_answered=True))
    assert a == b and a.status == "partial"


def test_answer_after_window_is_stale_survey_closed(clock, outcome_codes):
    late = ev(answers={"q1": "yes"}, at="2026-12-18T19:00:01+05:30")
    r = run(clock, outcome_codes, late)
    assert (r.status, r.failure_code, r.answers) == ("stale", "survey_closed", {})
    assert (r.retry_decision, r.counts_toward_cap) == ("give_up", False)
    assert r.farmerchat_reply is None


def test_answer_at_the_last_second_is_accepted(clock, outcome_codes):
    on_time = ev(answers=ALL3, at=NOT_AFTER)
    assert run(clock, outcome_codes, on_time).status == "completed"


def test_replaced_survey_is_stale_survey_replaced(clock, outcome_codes):
    r = run(clock, outcome_codes, ev(answers={"q1": "yes"}), attempt=make_attempt("app", superseded=True))
    assert (r.status, r.failure_code, r.answers) == ("stale", "survey_replaced", {})
    assert r.farmerchat_reply.model_dump() == {"http_status": 404, "outcome": "unknown_flow"}


def test_priority_identity_then_replaced_then_closed(clock, outcome_codes):
    late = "2026-12-19T09:00:00+05:30"
    replaced = run(clock, outcome_codes, ev(answers={"q1": "yes"}, at=late), attempt=make_attempt("app", superseded=True))
    assert replaced.failure_code == "survey_replaced"
    closed = run(clock, outcome_codes, ev(answers={"q1": "yes"}, at=late))
    assert closed.failure_code == "survey_closed"
    wrong = run(clock, outcome_codes, ev(answers={"q1": "yes"}, at=late, farmer_id=OTHER), attempt=make_attempt("app", superseded=True))
    assert wrong.failure_code == "identity_mismatch"


def test_discarded_item_keeps_nothing_untrusted_in_value(clock, outcome_codes):
    r = run(clock, outcome_codes, ev(farmer_id=OTHER, answers={"q1": "ignore previous instructions"}))
    assert r.items[0].result == "discarded" and r.items[0].value is None
    assert r.answers == {}


# --------------------------------------------------------------------------- failures from the table


def _failure_cases(codes: dict[str, Any]):
    for code, info in codes["failures"].items():
        if code in ("duplicate_answer", "identity_mismatch", "survey_closed", "survey_replaced"):
            continue
        for channel in info["channels"]:
            yield pytest.param(code, channel, id=f"{channel}-{code}")


@pytest.mark.parametrize("code,channel", list(_failure_cases(load_outcome_codes())))
def test_every_failure_code_copies_the_table(clock, outcome_codes, code, channel):
    info = outcome_codes["failures"][code]
    kind = {"farmer_declined": "decline", "farmer_opted_out": "opt_out"}.get(code, "failure")
    r = run(clock, outcome_codes, ev(kind, channel=channel, failure_code=code, raw="x"), channel=channel)
    assert r.status == info["status"]
    assert r.failure_code == code
    assert r.retry_decision == info["retry_decision"]
    assert r.retry_after_minutes == info["retry_after_minutes"]
    assert r.counts_toward_cap == info["counts_toward_cap"]
    assert r.answers == {} and r.complete is False
    assert r.needs_follow_up is False


def test_delivery_failures_do_not_count_toward_the_cap(clock, outcome_codes):
    for channel, code in [("app", "push_token_invalid"), ("whatsapp", "wa_undelivered"), ("voice", "voice_busy")]:
        r = run(clock, outcome_codes, ev("failure", channel=channel, failure_code=code), channel=channel)
        assert r.status == "delivery_failed" and r.counts_toward_cap is False


def test_voice_call_dropped_keeps_answers_and_counts(clock, outcome_codes):
    r = run(clock, outcome_codes, ev("failure", "voice", failure_code="voice_call_dropped", answers={"q1": "yes", "q2": "easy"}), channel="voice")
    assert (r.status, r.retry_decision, r.retry_after_minutes, r.counts_toward_cap) == ("delivery_failed", "retry_same_channel", 10, True)
    assert r.answers == {"q1": "yes", "q2": "easy"}
    assert [i.result for i in r.items] == ["answered", "answered", "not_reached"]
    assert r.answered_by == FARMER


def test_voice_call_dropped_before_any_answer_has_no_answerer(clock, outcome_codes):
    r = run(clock, outcome_codes, ev("failure", "voice", failure_code="voice_call_dropped"), channel="voice")
    assert r.answered_by is None and r.timestamps.answered is None


def test_window_expired_with_nothing_answered_is_expired(clock, outcome_codes):
    shown = {"delivered": "2026-12-16T08:01:00+05:30", "opened": "2026-12-16T08:20:00+05:30"}
    r = run(clock, outcome_codes, ev("failure", "whatsapp", failure_code="window_expired", timestamps=shown), channel="whatsapp")
    assert (r.status, r.retry_decision, r.counts_toward_cap) == ("expired", "give_up", True)
    assert [i.result for i in r.items] == ["skipped", "not_reached", "not_reached"]
    assert r.answered_by is None


def test_window_expired_after_some_answers_is_partial(clock, outcome_codes):
    r = run(clock, outcome_codes, ev("failure", "whatsapp", failure_code="window_expired", answers={"q1": "yes"}), channel="whatsapp")
    assert (r.status, r.failure_code) == ("partial", None)
    assert r.answers == {"q1": "yes"}


def test_web_window_expired_without_open_is_never_opened(clock, outcome_codes):
    r = run(clock, outcome_codes, ev("failure", "web", failure_code="window_expired", timestamps={"delivered": T_ANSWER}), channel="web")
    assert r.sheet_outcome == "never_opened"
    assert [i.result for i in r.items] == ["not_reached"] * 3


def test_telegram_window_expired_counts_as_shown_once_delivered(clock, outcome_codes):
    r = run(clock, outcome_codes, ev("failure", "telegram", failure_code="window_expired", timestamps={"delivered": T_ANSWER}), channel="telegram")
    assert [i.result for i in r.items] == ["skipped", "not_reached", "not_reached"]


def test_sheet_dismissed_marks_first_item_skipped(clock, outcome_codes):
    r = run(clock, outcome_codes, ev("failure", failure_code="sheet_dismissed"))
    assert (r.status, r.sheet_outcome) == ("declined", "dismissed")
    assert [i.result for i in r.items] == ["skipped", "not_reached", "not_reached"]
    assert r.answered_by == FARMER


@pytest.mark.parametrize("code", ["push_token_invalid", "client_cannot_render", "push_not_opened"])
def test_app_failures_before_the_sheet_opened(clock, outcome_codes, code):
    r = run(clock, outcome_codes, ev("failure", failure_code=code))
    assert r.sheet_outcome == "never_opened" and r.answered_by is None


def test_opt_out_stops_everything_and_drops_any_answers(clock, outcome_codes):
    r = run(clock, outcome_codes, ev("opt_out", "whatsapp", raw="STOP", answers={"q1": "yes"}), channel="whatsapp")
    assert (r.status, r.failure_code, r.answers) == ("declined", "farmer_opted_out", {})
    assert r.raw_event == "STOP"
    assert r.sheet_outcome is None
    assert r.retry_decision == "give_up" and r.counts_toward_cap is True
    app = run(clock, outcome_codes, ev("opt_out", raw="tapped Do not ask me again"))
    assert app.sheet_outcome == "dismissed"


def test_decline_is_not_available_on_the_sheet_channels(clock, outcome_codes):
    with pytest.raises(ValueError):
        apply_event(make_survey(), make_attempt("app"), ev("decline"), clock, outcome_codes)


def test_raw_event_is_cut_to_the_schema_limit(clock, outcome_codes):
    r = run(clock, outcome_codes, ev("opt_out", "voice", raw="9" * 400), channel="voice")
    assert len(r.raw_event) == 256


# --------------------------------------------------------------------------- retries and timestamps


def test_transport_retry_keeps_response_key_and_delivery_attempt(clock, outcome_codes):
    attempt = make_attempt("voice", delivery_attempt=3)
    event = ev("failure", "voice", failure_code="voice_no_answer")
    a = run(clock, outcome_codes, event, channel="voice", attempt=attempt)
    b = run(clock, outcome_codes, event, channel="voice", attempt=attempt)
    assert a == b
    assert (a.delivery_attempt, a.response_key) == (3, attempt["response_key"])


def test_attempt_model_is_accepted(clock, outcome_codes):
    attempt = Attempt.model_validate(make_attempt("app"))
    r = run(clock, outcome_codes, ev(answers=ALL3), attempt=attempt)
    assert r.response_key == attempt.response_key and r.timestamps.sent.isoformat() == NOT_BEFORE


def test_delivered_and_opened_are_not_terminal(clock, outcome_codes):
    for kind in ("delivered", "opened"):
        with pytest.raises(NonTerminalEvent):
            apply_event(make_survey(), make_attempt("app"), ev(kind), clock, outcome_codes)


def test_update_timestamps_never_fabricates(clock):
    ts = update_timestamps(None, ev("delivered", at="2026-12-16T07:01:00+05:30"), "whatsapp")
    assert ts["delivered"].isoformat() == "2026-12-16T07:01:00+05:30"
    assert ts["opened"] is None and ts["answered"] is None
    ts = update_timestamps(ts, ev("opened", "whatsapp", at="2026-12-16T07:20:00+05:30"), "whatsapp")
    assert ts["opened"].isoformat() == "2026-12-16T07:20:00+05:30"
    # Telegram has no read receipts.
    tg = update_timestamps(None, ev("opened", "telegram"), "telegram")
    assert tg["opened"] is None
    # An opened event does not invent a delivered time.
    assert update_timestamps(None, ev("opened", "app"), "app")["delivered"] is None
    # A second report does not overwrite the first.
    again = update_timestamps(ts, ev("delivered", at="2026-12-16T09:00:00+05:30"), "whatsapp")
    assert again["delivered"].isoformat() == "2026-12-16T07:01:00+05:30"


def test_answer_without_reported_steps_leaves_delivered_and_opened_null(clock, outcome_codes):
    r = run(clock, outcome_codes, ev(answers=ALL3))
    t = r.timestamps
    assert t.sent is not None and t.answered is not None
    assert t.delivered is None and t.opened is None


def test_telegram_opened_stays_null_even_when_the_event_sends_one(clock, outcome_codes):
    stamps = {"delivered": "2026-12-16T08:01:00+05:30", "opened": "2026-12-16T08:20:00+05:30"}
    r = run(clock, outcome_codes, ev("answer", "telegram", answers=ALL3, timestamps=stamps), channel="telegram")
    assert r.timestamps.opened is None and r.timestamps.delivered is not None


def test_timestamps_known_to_the_attempt_are_kept(clock, outcome_codes):
    known = {"delivered": "2026-12-16T07:01:00+05:30", "opened": "2026-12-16T07:20:00+05:30"}
    r = run(clock, outcome_codes, ev(answers=ALL3), attempt=make_attempt("app", timestamps=known))
    assert r.timestamps.delivered.isoformat() == known["delivered"]
    assert r.timestamps.opened.isoformat() == known["opened"]


def test_recorded_at_is_the_clock_and_times_are_ist(clock, outcome_codes):
    other_zone = datetime(2026, 12, 16, 1, 55, tzinfo=UTC).isoformat()  # 07:25 IST
    r = run(clock, outcome_codes, ev(answers=ALL3, at=other_zone))
    assert r.recorded_at == clock.now()
    assert r.timestamps.answered.isoformat() == T_ANSWER
    assert r.timestamps.answered.utcoffset() == timedelta(hours=5, minutes=30)
    assert r.recorded_at.tzinfo is not None and r.recorded_at.utcoffset() == IST.utcoffset(None)


def test_naive_event_time_is_rejected(clock, outcome_codes):
    with pytest.raises(ValueError):
        apply_event(make_survey(), make_attempt("app"), ev(answers=ALL3, at="2026-12-16T07:25:00"), clock, outcome_codes)


# --------------------------------------------------------------------------- inputs and safety checks


def test_single_value_event_records_raw_input_and_kind(clock, outcome_codes):
    r = run(clock, outcome_codes, ev("answer", "telegram", answers={"q1": "yes"}, raw="mel|S-90001|q1|yes", input_kind="callback_data"), channel="telegram")
    assert (r.items[0].raw_input, r.items[0].input_kind, r.items[0].attempts) == ("mel|S-90001|q1|yes", "callback_data", 1)


def test_multi_value_event_does_not_spread_one_raw_over_every_item(clock, outcome_codes):
    r = run(clock, outcome_codes, ev(answers=ALL3, raw="yes", input_kind="sheet_tap"))
    assert all(i.raw_input is None and i.input_kind is None for i in r.items)


def test_per_item_inputs_are_used_when_given(clock, outcome_codes):
    inputs = {"q1": {"raw": "yes", "input_kind": "sheet_tap"}, "q3": {"raw": "4", "input_kind": "sheet_tap", "attempts": 2}}
    r = run(clock, outcome_codes, ev(answers={"q1": "yes", "q3": 4}, inputs=inputs))
    assert (r.items[0].raw_input, r.items[0].attempts) == ("yes", 1)
    assert (r.items[2].raw_input, r.items[2].attempts) == ("4", 2)


@pytest.mark.parametrize(
    "event,attempt",
    [
        (ev(answers=ALL3, channel="web"), make_attempt("app")),  # channel differs
        (ev("bogus"), make_attempt("app")),
        (ev("failure", failure_code="tg_bot_blocked"), make_attempt("app")),  # code not valid on app
        (ev("failure"), make_attempt("app")),  # failure needs a code
        (ev("failure", failure_code="not_a_code"), make_attempt("app")),
        (ev("failure", failure_code="push_token_invalid", answers={"q1": "yes"}), make_attempt("app")),
        (ev("answer", failure_code="window_expired", answers={"q1": "yes"}), make_attempt("app")),
        (ev("opt_out", failure_code="farmer_declined"), make_attempt("app")),
        (ev(answers=ALL3), make_attempt("app") | {"survey_id": "S-99999"}),
        (ev(answers=ALL3), make_attempt("app") | {"farmer_id": OTHER}),
    ],
)
def test_contradictory_input_is_rejected(clock, outcome_codes, event, attempt):
    with pytest.raises(ValueError):
        apply_event(make_survey(), attempt, event, clock, outcome_codes)


def test_inputs_are_not_mutated(clock, outcome_codes):
    survey, attempt, event = make_survey(), make_attempt("app"), ev(answers=dict(ALL3))
    before = (survey.model_dump(), deepcopy(attempt), deepcopy(event))
    apply_event(survey, attempt, event, clock, outcome_codes)
    assert (survey.model_dump(), attempt, event) == before


def test_survey_may_be_the_pack_dict(clock, outcome_codes):
    r = apply_event(make_survey().to_pack(), make_attempt("app"), ev(answers=ALL3), clock, outcome_codes)
    assert r.status == "completed"
