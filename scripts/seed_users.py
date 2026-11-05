#!/usr/bin/env python3
"""Idempotently provision the first five farmers; never print their password."""
import csv
import os
from pathlib import Path

import boto3


def main():
    password = os.environ.get("SEED_PASSWORD")
    if not password:
        raise SystemExit("SEED_PASSWORD must be set")
    session = boto3.Session(region_name="us-west-2")
    ssm = session.client("ssm")
    pool = ssm.get_parameter(Name="/mel/user_pool_id")["Parameter"]["Value"]
    client = ssm.get_parameter(Name="/mel/user_pool_client_id")["Parameter"]["Value"]
    cognito = session.client("cognito-idp")
    with (Path(__file__).resolve().parent.parent / "pack/data/farmers.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))[:5]
    if len(rows) != 5:
        raise SystemExit("farmers.csv must contain at least five farmers")
    for i, row in enumerate(rows, 1):
        username = f"farmer{i}"
        expected = {"custom:farmer_id": row["farmer_id"], "custom:org_id": "org.farmerchat"}
        try:
            cognito.admin_create_user(UserPoolId=pool, Username=username, MessageAction="SUPPRESS",
                UserAttributes=[{"Name": k, "Value": v} for k, v in expected.items()])
        except cognito.exceptions.UsernameExistsException:
            user = cognito.admin_get_user(UserPoolId=pool, Username=username)
            attributes = {a["Name"]: a["Value"] for a in user["UserAttributes"]}
            if any(attributes.get(k) != v for k, v in expected.items()):
                raise SystemExit(f"{username} exists with different immutable identity attributes")
        cognito.admin_set_user_password(UserPoolId=pool, Username=username, Password=password, Permanent=True)
        print(f"Seeded {username}: {row['farmer_id']}")
    # The CLI expands the caller's env var; documentation never includes the secret.
    print(f'aws cognito-idp initiate-auth --region us-west-2 --client-id {client} '
          '--auth-flow USER_PASSWORD_AUTH --auth-parameters "USERNAME=farmer1,PASSWORD=$SEED_PASSWORD" '
          '--query AuthenticationResult.TokenType --output text')


if __name__ == "__main__":
    main()
