"""Ledger contract tests, run against both backends (in-memory and DynamoDB under moto)."""

from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import boto3
import pytest
from moto import mock_aws

from mel.ledger_ddb import DynamoLedger
from mel.ledger_mem import InMemoryLedger, SurveyIdConflict
from mel.models import (
    Attempt,
    FollowUpItem,
    PutOutcome,
    ResponseRecord,
    ScheduleHandoff,
    Survey,
)
from mel.protocols import Ledger

TABLE = "mel-ledger"
ORG = "org-a"
OTHER_ORG = "org-b"
FARMER = "F-000123"
OTHER_FARMER = "F-000999"


# --------------------------------------------------------------------------- fixtures


def _create_table(region: str = "us-west-2") -> None:
    boto3.client("dynamodb", region_name=region).create_table(
        TableName=TABLE,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
            {"AttributeName": "gsi1pk", "AttributeType": "S"},
            {"AttributeName": "gsi1sk", "AttributeType": "S"},
        ],
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "GSI1",
                "KeySchema": [
                    {"AttributeName": "gsi1pk", "KeyType": "HASH"},
                    {"AttributeName": "gsi1sk", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    )


@pytest.fixture(params=["mem", "ddb"])
def ledger(request, monkeypatch):
    if request.param == "mem":
        yield InMemoryLedger()
        return
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    with mock_aws():
        _create_table()
        yield DynamoLedger(TABLE, "us-west-2")


@pytest.fixture(scope="module")
def scenario(scenarios):
    return scenarios[0]


@pytest.fixture
def survey(scenario) -> Survey:
    return Survey.model_validate(scenario["survey_by_lang"]["en-IN"])


@pytest.fixture
def handoff(scenario) -> ScheduleHandoff:
    return ScheduleHandoff.model_validate(scenario["handoff"])


@pytest.fixture
def response(scenario) -> ResponseRecord:
    return ResponseRecord.model_validate(scenario["responses"]["app"])


def make_attempt(survey: Survey, n: int = 1, farmer_id: str | None = None) -> Attempt:
    return Attempt(
        survey_id=survey.survey_id,
        farmer_id=farmer_id or survey.farmer_id,
        channel="app",
        delivery_attempt=n,
        response_key=f"rk-{survey.survey_id}-{n}",
        language=survey.language,
        source_insight_ids=survey.source_insight_ids,
        created_at=survey.send_window.not_before,
    )


def make_follow_up(survey: Survey, fid: str, created_at: datetime, farmer_id: str | None = None) -> FollowUpItem:
    return FollowUpItem(
        follow_up_id=fid,
        farmer_id=farmer_id or survey.farmer_id,
        survey_id=survey.survey_id,
        response_key=f"rk-{fid}",
        source_insight_ids=survey.source_insight_ids,
        reasons=["advice_did_not_work"],
        accepted_answers={"q1": "no"},
        created_at=created_at,
    )


# --------------------------------------------------------------------------- protocol and ids


def test_implements_protocol(ledger):
    assert isinstance(ledger, Ledger)


@pytest.mark.parametrize("bad", ["", "a#b", "ORG#x"])
def test_ids_that_could_forge_a_key_are_rejected(ledger, bad):
    with pytest.raises(ValueError):
        ledger.is_opted_out(bad, FARMER)
    with pytest.raises(ValueError):
        ledger.is_opted_out(ORG, bad)


# --------------------------------------------------------------------------- surveys


def test_survey_roundtrip_and_owner(ledger, survey, clock):
    ledger.put_survey(ORG, survey, clock.now() + timedelta(days=10))
    assert ledger.get_survey(ORG, survey.farmer_id, survey.survey_id) == survey
    assert ledger.find_survey_owner(ORG, survey.survey_id) == survey.farmer_id
    assert ledger.get_survey(ORG, OTHER_FARMER, survey.survey_id) is None
    assert ledger.find_survey_owner(ORG, "S-99999") is None


def test_survey_id_cannot_be_taken_by_another_farmer(ledger, survey, clock):
    ledger.put_survey(ORG, survey, clock.now() + timedelta(days=10))
    stolen = survey.model_copy(update={"farmer_id": OTHER_FARMER})
    with pytest.raises(SurveyIdConflict):
        ledger.put_survey(ORG, stolen, clock.now() + timedelta(days=10))
    assert ledger.find_survey_owner(ORG, survey.survey_id) == survey.farmer_id
    assert ledger.get_survey(ORG, OTHER_FARMER, survey.survey_id) is None
    ledger.put_survey(ORG, survey, clock.now() + timedelta(days=11))  # same farmer: idempotent


def test_next_survey_seq_counts_per_org_and_is_atomic(ledger):
    assert [ledger.next_survey_seq(ORG) for _ in range(3)] == [1, 2, 3]
    assert ledger.next_survey_seq(OTHER_ORG) == 1
    with ThreadPoolExecutor(8) as pool:
        got = list(pool.map(lambda _: ledger.next_survey_seq(ORG), range(16)))
    assert sorted(got) == list(range(4, 20))


def test_returned_records_are_copies(ledger, survey, clock):
    ledger.put_survey(ORG, survey, clock.now() + timedelta(days=10))
    first = ledger.get_survey(ORG, survey.farmer_id, survey.survey_id)
    first.rationale = "changed by caller"
    again = ledger.get_survey(ORG, survey.farmer_id, survey.survey_id)
    assert again.rationale == survey.rationale


# --------------------------------------------------------------------------- responses


def test_duplicate_response_rejected_and_first_kept(ledger, response):
    assert ledger.put_response(ORG, response) is PutOutcome.WRITTEN
    second = copy.deepcopy(response)
    second.answers = {"q1": "no"}
    second.status = "negative_outcome"
    assert ledger.put_response(ORG, second) is PutOutcome.DUPLICATE
    kept = ledger.get_response(ORG, response.farmer_id, response.response_key)
    assert kept == response
    assert kept.answers == response.answers


def test_same_response_key_in_another_org_is_not_a_duplicate(ledger, response):
    assert ledger.put_response(ORG, response) is PutOutcome.WRITTEN
    assert ledger.put_response(OTHER_ORG, response) is PutOutcome.WRITTEN


def test_concurrent_put_response_writes_once(ledger, response):
    with ThreadPoolExecutor(8) as pool:
        outcomes = list(pool.map(lambda _: ledger.put_response(ORG, response), range(8)))
    assert outcomes.count(PutOutcome.WRITTEN) == 1
    assert outcomes.count(PutOutcome.DUPLICATE) == 7


# --------------------------------------------------------------------------- frequency cap


def test_record_cap_counts_a_survey_once(ledger, clock):
    assert ledger.record_cap(ORG, FARMER, "S-00001", clock.now()) is True
    assert ledger.record_cap(ORG, FARMER, "S-00001", clock.now()) is False
    assert ledger.cap_count(ORG, FARMER, 7, clock.now()) == 1


def test_record_cap_counts_once_under_concurrent_calls(ledger, clock):
    at = clock.now()
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda _: ledger.record_cap(ORG, FARMER, "S-00001", at), range(8)))
    assert results.count(True) == 1
    assert results.count(False) == 7
    assert ledger.cap_count(ORG, FARMER, 7, at) == 1


def test_cap_window_is_open_at_the_start_and_closed_at_now(ledger, clock):
    now = clock.now()
    ledger.record_cap(ORG, FARMER, "S-00001", now - timedelta(days=7))  # exactly on the edge: out
    ledger.record_cap(ORG, FARMER, "S-00002", now - timedelta(days=7) + timedelta(seconds=1))
    ledger.record_cap(ORG, FARMER, "S-00003", now)  # at now: in
    ledger.record_cap(ORG, FARMER, "S-00004", now + timedelta(seconds=1))  # future: out
    assert ledger.cap_count(ORG, FARMER, 7, now) == 2
    assert ledger.cap_count(ORG, FARMER, 8, now) == 3


def test_cap_is_scoped_by_farmer_and_org(ledger, clock):
    ledger.record_cap(ORG, FARMER, "S-00001", clock.now())
    assert ledger.cap_count(ORG, OTHER_FARMER, 7, clock.now()) == 0
    assert ledger.cap_count(OTHER_ORG, FARMER, 7, clock.now()) == 0
    assert ledger.record_cap(OTHER_ORG, FARMER, "S-00001", clock.now()) is True


def test_naive_timestamp_is_rejected(ledger):
    with pytest.raises(ValueError):
        ledger.record_cap(ORG, FARMER, "S-00001", datetime(2026, 11, 5, 9, 0))


# --------------------------------------------------------------------------- opt-out


def test_opt_out_blocks_a_later_attempt(ledger, survey):
    assert ledger.put_attempt(ORG, make_attempt(survey, 1)) is PutOutcome.WRITTEN
    assert ledger.is_opted_out(ORG, survey.farmer_id) is False
    ledger.set_opt_out(ORG, survey.farmer_id, survey.send_window.not_before)
    assert ledger.is_opted_out(ORG, survey.farmer_id) is True
    assert ledger.put_attempt(ORG, make_attempt(survey, 2)) is PutOutcome.OPTED_OUT
    # Nothing was written for the blocked attempt.
    assert ledger.item_ttl(ORG, survey.farmer_id, f"ATTEMPT#{survey.survey_id}#2") is None
    assert ledger.item_ttl(ORG, survey.farmer_id, f"ATTEMPT#{survey.survey_id}#1") is not None


def test_opt_out_is_idempotent_and_scoped(ledger, survey):
    ledger.set_opt_out(ORG, FARMER, survey.send_window.not_before)
    ledger.set_opt_out(ORG, FARMER, survey.send_window.not_after)
    assert ledger.is_opted_out(ORG, FARMER) is True
    assert ledger.is_opted_out(ORG, OTHER_FARMER) is False
    assert ledger.is_opted_out(OTHER_ORG, FARMER) is False
    other = make_attempt(survey, 1, farmer_id=OTHER_FARMER)
    assert ledger.put_attempt(ORG, other) is PutOutcome.WRITTEN
    assert ledger.put_attempt(OTHER_ORG, make_attempt(survey, 1)) is PutOutcome.WRITTEN


# --------------------------------------------------------------------------- isolation


def test_cross_org_read_returns_nothing(ledger, survey, response, handoff, clock):
    ledger.put_survey(ORG, survey, clock.now() + timedelta(days=10))
    ledger.put_response(ORG, response)
    ledger.put_handoff(ORG, handoff)
    ledger.record_cap(ORG, survey.farmer_id, survey.survey_id, clock.now())
    ledger.set_opt_out(ORG, survey.farmer_id, clock.now())
    ledger.put_follow_up(ORG, make_follow_up(survey, "FU-1", clock.now()))

    assert ledger.get_survey(OTHER_ORG, survey.farmer_id, survey.survey_id) is None
    assert ledger.find_survey_owner(OTHER_ORG, survey.survey_id) is None
    assert ledger.get_response(OTHER_ORG, response.farmer_id, response.response_key) is None
    assert ledger.cap_count(OTHER_ORG, survey.farmer_id, 7, clock.now()) == 0
    assert ledger.is_opted_out(OTHER_ORG, survey.farmer_id) is False
    assert ledger.list_follow_ups(OTHER_ORG) == []
    assert ledger.item_ttl(OTHER_ORG, survey.farmer_id, f"SURVEY#{survey.survey_id}") is None


def test_cross_farmer_read_returns_nothing(ledger, survey, response, clock):
    ledger.put_survey(ORG, survey, clock.now() + timedelta(days=10))
    ledger.put_response(ORG, response)
    assert ledger.get_survey(ORG, OTHER_FARMER, survey.survey_id) is None
    assert ledger.get_response(ORG, OTHER_FARMER, response.response_key) is None


# --------------------------------------------------------------------------- ttl


def test_ttl_is_expiry_plus_seven_days(ledger, survey, handoff, clock):
    expires = clock.now() + timedelta(days=10)
    want = int((expires + timedelta(days=7)).timestamp())
    ledger.put_survey(ORG, survey, expires)
    ledger.put_attempt(ORG, make_attempt(survey, 1))
    assert ledger.item_ttl(ORG, survey.farmer_id, f"SURVEY#{survey.survey_id}") == want
    assert ledger.item_ttl(ORG, survey.farmer_id, f"ATTEMPT#{survey.survey_id}#1") == want

    ledger.put_handoff(ORG, handoff)
    handoff_want = int((handoff.expires_at + timedelta(days=7)).timestamp())
    assert ledger.item_ttl(ORG, handoff.survey.farmer_id, f"HANDOFF#{handoff.handoff_id}") == handoff_want


def test_attempt_without_a_stored_survey_still_gets_a_ttl(ledger, survey):
    ledger.put_attempt(ORG, make_attempt(survey, 1))
    assert ledger.item_ttl(ORG, survey.farmer_id, f"ATTEMPT#{survey.survey_id}#1") is not None


# --------------------------------------------------------------------------- follow-ups


def test_follow_ups_listed_oldest_first_per_org(ledger, survey, clock):
    t0 = clock.now()
    ledger.put_follow_up(ORG, make_follow_up(survey, "FU-b", t0 + timedelta(hours=2)))
    ledger.put_follow_up(ORG, make_follow_up(survey, "FU-a", t0, farmer_id=OTHER_FARMER))
    ledger.put_follow_up(OTHER_ORG, make_follow_up(survey, "FU-x", t0))
    got = ledger.list_follow_ups(ORG)
    assert [i.follow_up_id for i in got] == ["FU-a", "FU-b"]
    assert [i.follow_up_id for i in ledger.list_follow_ups(OTHER_ORG)] == ["FU-x"]


def test_follow_up_put_is_idempotent_on_id(ledger, survey, clock):
    item = make_follow_up(survey, "FU-1", clock.now())
    ledger.put_follow_up(ORG, item)
    ledger.put_follow_up(ORG, item)
    assert len(ledger.list_follow_ups(ORG)) == 1
