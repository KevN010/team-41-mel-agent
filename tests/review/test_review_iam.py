"""Review item 10: IAM wildcard actions or resources, and least privilege.

No wildcard actions. Required "*" resources (ecr:GetAuthorizationToken, cloudwatch:PutMetricData
with a namespace condition) are fine. Open findings in infra/app.py Agent stack:
  * one role (mel-agent-role) is shared by the Lambda and the AgentCore runtime (CompositePrincipal);
    CLAUDE.md asks for one role per component.
  * DynamoDB actions the code never uses: Scan, DeleteItem, BatchGetItem, BatchWriteItem. Scan on a
    multi-tenant table reads every org.
  * bedrock:InvokeModel on inference-profile/* and foundation-model/anthropic.*; models.yaml uses
    only global.openai.gpt-6-luna.
These are static checks on the CDK source (synth needs node and AWS context; tests stay offline).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = (ROOT / "infra" / "app.py").read_text(encoding="utf-8")
MEL_SOURCE = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "mel").rglob("*.py"))


@pytest.mark.xfail(strict=True, reason="REVIEW item 10: Lambda and AgentCore share one role")
def test_one_role_per_component():
    assert "CompositePrincipal" not in APP


@pytest.mark.xfail(strict=True, reason="REVIEW item 10: DynamoDB actions granted that no code uses")
def test_no_unused_dynamodb_actions():
    used = {"GetItem": "get_item", "PutItem": "put_item", "UpdateItem": "update_item", "Query": "query(",
            "Scan": ".scan(", "DeleteItem": "delete_item", "BatchGetItem": "batch_get_item",
            "BatchWriteItem": "batch_write_item"}
    granted = set(re.findall(r'"dynamodb:(\w+)"', APP))
    unused = sorted(a for a in granted if a in used and used[a] not in MEL_SOURCE)
    assert unused == []


@pytest.mark.xfail(strict=True, reason="REVIEW item 10: Bedrock resources wider than models.yaml")
def test_bedrock_resources_name_the_chosen_profile():
    assert 'resource="inference-profile", resource_name="*"' not in APP
    assert "foundation-model/anthropic.*" not in APP
