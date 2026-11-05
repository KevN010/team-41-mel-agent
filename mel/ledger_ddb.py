"""DynamoDB Ledger. Single table (name from MEL_TABLE, else settings.LEDGER_TABLE, default mel-ledger).

Key design (same as mel/ledger_mem.py):

    pk = ORG#<org_id>#FARMER#<farmer_id>
         sk = SURVEY#<id> | HANDOFF#<id> | ATTEMPT#<survey_id>#<n> | RESPONSE#<response_key>
              | CAP#<survey_id> | OPTOUT | FOLLOWUP#<id>
    pk = ORG#<org_id>
         sk = COUNTER#SURVEY (atomic ADD)  |  SURVEYOWNER#<survey_id> (farmer_id, for identity_mismatch)
    GSI1: gsi1pk = ORG#<org_id>, gsi1sk = FOLLOWUP#<created_at>#<id>   (list_follow_ups)
    ttl (epoch seconds) = expires_at + 7 days on SURVEY, HANDOFF and ATTEMPT items.

Every key starts with ORG#<org_id>, and org_id/farmer_id may not contain '#', so no call can read or
write another org's items. Records are stored as one JSON string attribute ``data`` (to_pack()), which
avoids DynamoDB's float/Decimal rules and round-trips exactly.

Conditional writes: put_response and record_cap use attribute_not_exists(sk); put_attempt is a
transact_write with a ConditionCheck on the farmer's OPTOUT item, so an opt-out cannot slip between
the check and the write. Nothing here logs record content.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

import boto3
from botocore.exceptions import ClientError

from mel.ledger_mem import (
    ATTEMPT_FALLBACK_TTL,
    SurveyIdConflict,
    attempt_sk,
    dump,
    farmer_pk,
    followup_gsi_sk,
    org_pk,
    to_micros,
    to_ttl,
)
from mel.models import (
    Attempt,
    FollowUpItem,
    PutOutcome,
    ResponseRecord,
    ScheduleHandoff,
    Survey,
    to_ist,
)
from mel.settings import settings

_COND_FAILED = "ConditionalCheckFailedException"
_TX_CANCELED = "TransactionCanceledException"
_REASON_COND_FAILED = "ConditionalCheckFailed"  # CancellationReasons use the short code


def _first_condition_failed(exc: ClientError) -> bool:
    """True when a transact_write was cancelled because its first item's condition failed."""
    if exc.response.get("Error", {}).get("Code") != _TX_CANCELED:
        return False
    reasons = exc.response.get("CancellationReasons") or []
    return bool(reasons) and reasons[0].get("Code") == _REASON_COND_FAILED


def _is_condition_failure(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") == _COND_FAILED


class DynamoLedger:
    """Ledger on one DynamoDB table. Pass ``client`` (a boto3 *resource* client) in tests."""

    def __init__(self, table_name: str | None = None, region: str | None = None, *, client: Any = None) -> None:
        self._table = table_name or os.environ.get("MEL_TABLE") or settings.LEDGER_TABLE
        if client is None:
            client = boto3.resource("dynamodb", region_name=region or settings.REGION).meta.client
        self._ddb = client  # resource-level client: takes and returns plain Python types

    # -- counters and surveys

    def next_survey_seq(self, org_id: str) -> int:
        resp = self._ddb.update_item(
            TableName=self._table,
            Key={"pk": org_pk(org_id), "sk": "COUNTER#SURVEY"},
            UpdateExpression="ADD #s :one",
            ExpressionAttributeNames={"#s": "seq"},
            ExpressionAttributeValues={":one": 1},
            ReturnValues="UPDATED_NEW",
        )
        return int(resp["Attributes"]["seq"])

    def put_survey(self, org_id: str, survey: Survey, expires_at: datetime) -> None:
        try:
            self._ddb.transact_write_items(
                TransactItems=[
                    {
                        "Put": {
                            "TableName": self._table,
                            "Item": {
                                "pk": org_pk(org_id),
                                "sk": f"SURVEYOWNER#{survey.survey_id}",
                                "farmer_id": survey.farmer_id,
                            },
                            # Same survey_id may be re-put by its own farmer, never by another.
                            "ConditionExpression": "attribute_not_exists(sk) OR farmer_id = :f",
                            "ExpressionAttributeValues": {":f": survey.farmer_id},
                        }
                    },
                    {
                        "Put": {
                            "TableName": self._table,
                            "Item": {
                                "pk": farmer_pk(org_id, survey.farmer_id),
                                "sk": f"SURVEY#{survey.survey_id}",
                                "data": dump(survey),
                                "ttl": to_ttl(expires_at),
                            },
                        }
                    },
                ]
            )
        except ClientError as exc:
            if _first_condition_failed(exc):
                raise SurveyIdConflict(survey.survey_id) from None
            raise

    def get_survey(self, org_id: str, farmer_id: str, survey_id: str) -> Survey | None:
        item = self._get(farmer_pk(org_id, farmer_id), f"SURVEY#{survey_id}")
        return None if item is None else Survey.model_validate_json(item["data"])

    def find_survey_owner(self, org_id: str, survey_id: str) -> str | None:
        item = self._get(org_pk(org_id), f"SURVEYOWNER#{survey_id}")
        return None if item is None else item["farmer_id"]

    # -- hand-off and attempts

    def put_handoff(self, org_id: str, handoff: ScheduleHandoff) -> None:
        self._ddb.put_item(
            TableName=self._table,
            Item={
                "pk": farmer_pk(org_id, handoff.survey.farmer_id),
                "sk": f"HANDOFF#{handoff.handoff_id}",
                "data": dump(handoff),
                "ttl": to_ttl(handoff.expires_at),
            },
        )

    def put_attempt(self, org_id: str, attempt: Attempt) -> PutOutcome:
        pk = farmer_pk(org_id, attempt.farmer_id)
        survey = self._get(pk, f"SURVEY#{attempt.survey_id}", projection="ttl")
        ttl = survey["ttl"] if survey else int((attempt.created_at + ATTEMPT_FALLBACK_TTL).timestamp())
        try:
            self._ddb.transact_write_items(
                TransactItems=[
                    {
                        "ConditionCheck": {
                            "TableName": self._table,
                            "Key": {"pk": pk, "sk": "OPTOUT"},
                            "ConditionExpression": "attribute_not_exists(sk)",
                        }
                    },
                    {
                        "Put": {
                            "TableName": self._table,
                            "Item": {"pk": pk, "sk": attempt_sk(attempt), "data": dump(attempt), "ttl": ttl},
                        }
                    },
                ]
            )
        except ClientError as exc:
            if _first_condition_failed(exc):
                return PutOutcome.OPTED_OUT
            raise
        return PutOutcome.WRITTEN

    # -- responses

    def put_response(self, org_id: str, record: ResponseRecord) -> PutOutcome:
        try:
            self._ddb.put_item(
                TableName=self._table,
                Item={
                    "pk": farmer_pk(org_id, record.farmer_id),
                    "sk": f"RESPONSE#{record.response_key}",
                    "data": dump(record),
                },
                ConditionExpression="attribute_not_exists(sk)",
            )
        except ClientError as exc:
            if _is_condition_failure(exc):
                return PutOutcome.DUPLICATE
            raise
        return PutOutcome.WRITTEN

    def get_response(self, org_id: str, farmer_id: str, response_key: str) -> ResponseRecord | None:
        item = self._get(farmer_pk(org_id, farmer_id), f"RESPONSE#{response_key}")
        return None if item is None else ResponseRecord.model_validate_json(item["data"])

    # -- frequency cap

    def cap_count(self, org_id: str, farmer_id: str, window_days: int, now: datetime) -> int:
        upper = to_micros(now)
        lower = upper - int(timedelta(days=window_days) / timedelta(microseconds=1))
        total = 0
        kwargs: dict[str, Any] = {
            "TableName": self._table,
            "KeyConditionExpression": "pk = :pk AND begins_with(sk, :p)",
            "FilterExpression": "at_us > :lo AND at_us <= :hi",
            "ExpressionAttributeValues": {":pk": farmer_pk(org_id, farmer_id), ":p": "CAP#", ":lo": lower, ":hi": upper},
            "ConsistentRead": True,
            "Select": "COUNT",
        }
        while True:
            resp = self._ddb.query(**kwargs)
            total += resp["Count"]
            if "LastEvaluatedKey" not in resp:
                return total
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    def record_cap(self, org_id: str, farmer_id: str, survey_id: str, at: datetime) -> bool:
        try:
            self._ddb.put_item(
                TableName=self._table,
                Item={"pk": farmer_pk(org_id, farmer_id), "sk": f"CAP#{survey_id}", "at_us": to_micros(at)},
                ConditionExpression="attribute_not_exists(sk)",
            )
        except ClientError as exc:
            if _is_condition_failure(exc):
                return False
            raise
        return True

    # -- opt-out

    def set_opt_out(self, org_id: str, farmer_id: str, at: datetime) -> None:
        try:
            self._ddb.put_item(
                TableName=self._table,
                Item={
                    "pk": farmer_pk(org_id, farmer_id),
                    "sk": "OPTOUT",
                    "at": to_ist(at).isoformat(timespec="seconds"),
                },
                ConditionExpression="attribute_not_exists(sk)",  # keep the first opt-out time
            )
        except ClientError as exc:
            if not _is_condition_failure(exc):
                raise

    def is_opted_out(self, org_id: str, farmer_id: str) -> bool:
        return self._get(farmer_pk(org_id, farmer_id), "OPTOUT") is not None

    # -- follow-ups

    def put_follow_up(self, org_id: str, item: FollowUpItem) -> None:
        self._ddb.put_item(
            TableName=self._table,
            Item={
                "pk": farmer_pk(org_id, item.farmer_id),
                "sk": f"FOLLOWUP#{item.follow_up_id}",
                "data": dump(item),
                "gsi1pk": org_pk(org_id),
                "gsi1sk": followup_gsi_sk(item),
            },
        )

    def list_follow_ups(self, org_id: str) -> list[FollowUpItem]:
        """Oldest first. GSI reads are eventually consistent: a just-written item may lag briefly."""
        out: list[FollowUpItem] = []
        kwargs: dict[str, Any] = {
            "TableName": self._table,
            "IndexName": "GSI1",
            "KeyConditionExpression": "gsi1pk = :pk AND begins_with(gsi1sk, :p)",
            "ExpressionAttributeValues": {":pk": org_pk(org_id), ":p": "FOLLOWUP#"},
        }
        while True:
            resp = self._ddb.query(**kwargs)
            out.extend(FollowUpItem.model_validate_json(row["data"]) for row in resp["Items"])
            if "LastEvaluatedKey" not in resp:
                return out
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    # -- inspection (tests only; not part of the Ledger protocol)

    def item_ttl(self, org_id: str, farmer_id: str, sk: str) -> int | None:
        """The ``ttl`` attribute of one item, or None if the item or attribute is missing."""
        item = self._get(farmer_pk(org_id, farmer_id), sk, projection="ttl")
        return None if item is None else item.get("ttl")

    # -- internals

    def _get(self, pk: str, sk: str, projection: str | None = None) -> dict[str, Any] | None:
        kwargs: dict[str, Any] = {"TableName": self._table, "Key": {"pk": pk, "sk": sk}, "ConsistentRead": True}
        if projection:  # attribute names go through a placeholder: "ttl" is a DynamoDB reserved word
            kwargs["ProjectionExpression"] = "#p"
            kwargs["ExpressionAttributeNames"] = {"#p": projection}
        return self._ddb.get_item(**kwargs).get("Item")
