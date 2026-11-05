#!/usr/bin/env python3
"""Create 5 synthetic Cognito users from pack/data/farmers.csv data rows 1..5.

farmer_id and org_id are stored as the immutable custom attributes custom:farmer_id / custom:org_id,
which the API reads from the ID token. Passwords are random, permanent, and written only to
infra/.synthetic-users.json (mode 0600, git-ignored). They are never printed.

Usage: python infra/scripts/create_synthetic_users.py [--org-id org-demo] [--user-pool-id ID] [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import secrets
import string
from pathlib import Path

import boto3

REGION = "us-west-2"
ROOT = Path(__file__).resolve().parents[2]
FARMERS_CSV = ROOT / "pack" / "data" / "farmers.csv"
OUT_FILE = ROOT / "infra" / ".synthetic-users.json"
STACK = "MelAgentAuthStack"
COUNT = 5


def make_password() -> str:
    # 20 chars with all four classes, satisfying the pool policy (min 12, upper, lower, digit, symbol).
    alphabet = string.ascii_letters + string.digits
    core = "".join(secrets.choice(alphabet) for _ in range(16))
    return core + secrets.choice(string.ascii_uppercase) + secrets.choice(string.ascii_lowercase) + secrets.choice(string.digits) + secrets.choice("!#$%^*-_")


def read_farmer_ids(path: Path = FARMERS_CSV, count: int = COUNT) -> list[str]:
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    return [r["farmer_id"] for r in rows[:count]]


def lookup_pool_id(cfn) -> str:
    stack = cfn.describe_stacks(StackName=STACK)["Stacks"][0]
    outputs = {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}
    return outputs["UserPoolId"]


def create_users(idp, pool_id: str, farmer_ids: list[str], org_id: str) -> dict[str, str]:
    creds: dict[str, str] = {}
    for farmer_id in farmer_ids:
        password = make_password()
        try:
            idp.admin_create_user(
                UserPoolId=pool_id,
                Username=farmer_id,
                UserAttributes=[
                    {"Name": "custom:farmer_id", "Value": farmer_id},
                    {"Name": "custom:org_id", "Value": org_id},
                ],
                MessageAction="SUPPRESS",
            )
        except idp.exceptions.UsernameExistsException:
            print(f"exists, password reset: {farmer_id}")
        idp.admin_set_user_password(UserPoolId=pool_id, Username=farmer_id, Password=password, Permanent=True)
        creds[farmer_id] = password
        print(f"ready: {farmer_id} org={org_id}")
    return creds


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--org-id", default="org-demo")
    ap.add_argument("--user-pool-id")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    farmer_ids = read_farmer_ids()
    if args.dry_run:
        for fid in farmer_ids:
            print(f"would create: {fid} org={args.org_id}")
        return

    pool_id = args.user_pool_id or lookup_pool_id(boto3.client("cloudformation", region_name=REGION))
    idp = boto3.client("cognito-idp", region_name=REGION)
    creds = create_users(idp, pool_id, farmer_ids, args.org_id)

    fd = os.open(OUT_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"user_pool_id": pool_id, "org_id": args.org_id, "users": creds}, f, indent=2)
    print(f"credentials written to {OUT_FILE.relative_to(ROOT)} (0600, git-ignored)")


if __name__ == "__main__":
    main()
