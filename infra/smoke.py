#!/usr/bin/env python3
"""Live infrastructure proof; no passwords, JWTs, or API keys in output."""
import base64
import json
import os
import urllib.error
import urllib.request

import boto3

EXPECTED = {"table_name", "artifacts_bucket", "sim_bucket", "sim_url", "followup_queue_url", "followup_dlq_url", "user_pool_id", "user_pool_client_id", "api_url", "jev_secret_arn", "agent_role_arn", "ecr_repo_uri", "agent_runtime_arn", "dashboard_name"}


def main():
    session = boto3.Session(region_name="us-west-2")
    params = {}
    for page in session.client("ssm").get_paginator("get_parameters_by_path").paginate(Path="/mel"):
        params.update({p["Name"].removeprefix("/mel/"): p["Value"] for p in page["Parameters"]})
    assert EXPECTED.issubset(params), f"Missing parameters: {EXPECTED - params.keys()}"
    assert all(params[name] for name in EXPECTED)
    print(f"SSM: all {len(EXPECTED)} interface parameters resolve (runtime={params['agent_runtime_arn']})")
    def request(token=None):
        req = urllib.request.Request(params["api_url"] + "/follow-ups")
        if token:
            req.add_header("Authorization", "Bearer " + token)
        try:
            with urllib.request.urlopen(req, timeout=35) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()
    code, body = request()
    print(f"Unauthenticated GET /follow-ups: {code} {body}")
    assert code == 401
    auth = session.client("cognito-idp").initiate_auth(ClientId=params["user_pool_client_id"],
        AuthFlow="USER_PASSWORD_AUTH", AuthParameters={"USERNAME": "farmer1", "PASSWORD": os.environ["SEED_PASSWORD"]})
    token = auth["AuthenticationResult"]["IdToken"]
    claims_segment = token.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(claims_segment + "=" * (-len(claims_segment) % 4)))
    assert claims["sub"] and claims["custom:farmer_id"] == "F-000001"
    assert claims["custom:org_id"] == "org.farmerchat"
    print("JWT identity claims: sub, custom:farmer_id, custom:org_id verified")
    code, body = request(token)
    print(f"Authenticated GET /follow-ups (farmer1): {code} {body}")
    assert code == 501 and json.loads(body) == {"error": "not implemented"}
    db = session.client("dynamodb")
    table = db.describe_table(TableName=params["table_name"])["Table"]
    recovery = db.describe_continuous_backups(TableName=params["table_name"])["ContinuousBackupsDescription"]["PointInTimeRecoveryDescription"]
    assert table["SSEDescription"]["Status"] == "ENABLED"
    assert recovery["PointInTimeRecoveryStatus"] == "ENABLED"
    print("aws dynamodb describe-table:", json.dumps({"TableName": table["TableName"], "SSEDescription": table["SSEDescription"]}, default=str))
    print("aws dynamodb describe-continuous-backups:", json.dumps(recovery, default=str))
    print("PASS: live infrastructure smoke checks")


if __name__ == "__main__":
    main()
