#!/usr/bin/env python3
"""Write inspectable deployment evidence without querying secret values."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, timezone

import boto3

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "infra/evidence"
STACKS = ["CDKToolkit", "MelAgent-Data", "MelAgent-Secrets", "MelAgent-Auth", "MelAgent-Agent", "MelAgent-Api", "MelAgent-Obs"]


def main():
    session = boto3.Session(region_name="us-west-2")
    account = session.client("sts").get_caller_identity()["Account"]
    cf = session.client("cloudformation")
    params = {}
    response = subprocess.run(["aws", "ssm", "get-parameters-by-path", "--path", "/mel", "--region", "us-west-2", "--output", "json"], capture_output=True, text=True)
    ssm_output = response.stdout if response.returncode == 0 else response.stderr
    if response.returncode == 0:
        params = {p["Name"].removeprefix("/mel/"): p["Value"] for p in json.loads(response.stdout)["Parameters"]}
    inventory = []
    for stack in STACKS:
        try:
            resources = cf.list_stack_resources(StackName=stack)["StackResourceSummaries"]
        except cf.exceptions.ClientError as exc:
            inventory.append(f"| {stack} | unavailable | {exc.response['Error']['Code']} | — |")
            continue
        for r in resources:
            physical = r.get("PhysicalResourceId", "not created")
            t = r["ResourceType"]
            arn = arn_for(t, physical, account, params)
            inventory.append(f"| {stack} / {r['LogicalResourceId']} | {t} | `{physical}` | `{arn}` |")
    live_path = EVIDENCE / "runtime-live.json"
    if live_path.exists():
        live = json.loads(live_path.read_text())
        runtime = live["runtime"]
        endpoint = live["endpoint"]
        identity = runtime.get("workloadIdentityDetails", {}).get("workloadIdentityArn")
        inventory.append(f"| AgentCore | Runtime | `{runtime['agentRuntimeName']}` | `{runtime['agentRuntimeArn']}` |")
        inventory.append(f"| AgentCore | Default endpoint | `DEFAULT` | `{endpoint['agentRuntimeEndpointArn']}` |")
        if identity:
            inventory.append(f"| AgentCore | Workload identity | `{identity.rsplit('/', 1)[-1]}` | `{identity}` |")
        log_name = "/aws/bedrock-agentcore/runtimes/" + runtime["agentRuntimeId"] + "-DEFAULT"
        inventory.append(f"| AgentCore | Runtime log group | `{log_name}` | `arn:aws:logs:us-west-2:{account}:log-group:{log_name}` |")
    def evidence(name):
        path = EVIDENCE / name
        return path.read_text() if path.exists() else "Not run."
    runtime_path = EVIDENCE / "runtime.json"
    runtime = json.loads(runtime_path.read_text()) if runtime_path.exists() else {"status": "not launched", "error": "CDK deployment did not finish."}
    report = ["# MelAgent infrastructure", "", f"Recorded {datetime.now(timezone.utc).isoformat()}; account {account}; region us-west-2.", "",
        "Deployment status: " + ("incomplete" if "--incomplete" in sys.argv else "CDK stacks deployed; see live smoke evidence below."), "",
        "## Interface and limitations", "",
        "- All cross-stack values use deploy-time SSM String parameters; stack dependencies determine deployment order.",
        "- HTTP API native request validation is unavailable in AWS. The user approved retaining HTTP API with application payload validation. Reference: https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-open-api.html",
        "- Project=MelAgent tags are applied to all taggable resources. AWS child resources without tagging support inherit ownership through their parent/stack.",
        "- Jev is initialized to REPLACE_ME; a human must set its value. No secret value is queried for this report.",
        ("- Budget created with the BUDGET_EMAIL notification recipient." if os.environ.get("BUDGET_EMAIL") else "- BUDGET_EMAIL was unset; the optional budget was skipped."),
        "- CloudWatch alarms are visible in the console; no notification destination was requested for them.",
        "- Lambda and container packages select application code when the matching handler/agent exists, otherwise isolated build stubs. Runtime dependencies live in infra/lambda-requirements.txt.",
        "- DynamoDB describe-table reports SSE; PITR is reported by describe-continuous-backups, not describe-table.", "",
        "## Endpoints", "", f"API: {params.get('api_url', 'not deployed')}", "", f"Simulator: {params.get('sim_url', 'not deployed')}", "",
        "The simulator bucket is private and ready for static files; simulator content is owned by the application team.", "",
        "## CDK deployment summary", "", "```text", strip_ansi(evidence("deploy.log")), "```", "",
        "## SSM parameters", "", "`aws ssm get-parameters-by-path --path /mel --region us-west-2`", "", "```json", ssm_output.strip(), "```", "",
        "## Resource inventory", "", "Includes the CDK bootstrap stack and six application stacks. AWS resources without a standalone ARN are identified by their physical ID and parent ARN where applicable. CloudFront ARN formats follow https://docs.aws.amazon.com/service-authorization/latest/reference/list_cloudfront.html.", "",
        "| Stack / logical ID | Type | Physical name / ID | ARN / parent |", "|---|---|---|---|", *inventory, "",
        "## Operational commands", "", "Run from the repository root with AWS credentials exported and the CDK CLI on PATH. Initialize infra/.venv with Python and pip install -r infra/requirements.txt. Commands run with an explicit working directory; the parent shell never changes directory.", "",
        "```bash", 'export AWS_DEFAULT_REGION=us-west-2', 'export PATH="$PWD/infra/.venv/bin:$PATH"',
        '# Retrieve the locally generated seed password without printing it:', 'export SEED_PASSWORD="$(cat /private/tmp/mel-seed-password)"',
        'python scripts/seed_users.py',
        f'aws cognito-idp initiate-auth --region us-west-2 --client-id {params.get("user_pool_client_id", "<SSM_CLIENT_ID>")} --auth-flow USER_PASSWORD_AUTH --auth-parameters "USERNAME=farmer1,PASSWORD=$SEED_PASSWORD" --query AuthenticationResult.TokenType --output text',
        '# Human-only Jev update; /secure/path/jev-key.txt must contain the key:',
        'aws secretsmanager put-secret-value --region us-west-2 --secret-id mel/jev-api-key --secret-string file:///secure/path/jev-key.txt',
        '# Lambda redeploy:', 'bash scripts/package_lambda.sh', 'bash scripts/deploy.sh --lambda-only',
        '# Container redeploy (arm64 build, ECR push, agentcore configure then launch):', 'python infra/runtime.py',
        '# Complete deployment:', 'bash scripts/deploy.sh', '```', "",
        "Generated seed credentials remain only in the local mode-0600 file; neither the password nor JWT tokens are included here.", "",
        "## AgentCore Runtime: " + runtime["status"], "", "```json", json.dumps({k: v for k, v in runtime.items() if k != "error"}, indent=2), "```", "",
        *( ["Exact failure output:", "", "```text", strip_ansi(runtime["error"]), "```", ""] if "error" in runtime else [] ),
        "## Smoke test output", "", "```text", strip_ansi(evidence("seed.log") + "\n" + evidence("smoke.log") + "\n" + evidence("runtime-smoke.log")), "```", "",
        "## Offline verification", "", "```text", strip_ansi(evidence("contracts.log")), "```", "",
        "cdk-nag details and one-line suppression reasons: [NAG.md](NAG.md). Independent test and security review results are recorded in [REVIEW.md](REVIEW.md).", ""]
    (ROOT / "infra/INFRA.md").write_text("\n".join(report))


def strip_ansi(value):
    return re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", value)


def arn_for(t, name, account, params):
    if name.startswith("arn:"):
        return name
    prefix = f"arn:aws:{{service}}:us-west-2:{account}:"
    if t == "AWS::S3::Bucket": return "arn:aws:s3:::" + name
    if t == "AWS::S3::BucketPolicy": return "arn:aws:s3:::" + name + " (bucket policy)"
    if t == "AWS::DynamoDB::Table": return prefix.format(service="dynamodb") + "table/" + name
    if t == "AWS::SSM::Parameter": return prefix.format(service="ssm") + "parameter" + name
    if t == "AWS::SQS::Queue": return prefix.format(service="sqs") + name.rsplit("/", 1)[-1]
    if t == "AWS::IAM::Role": return f"arn:aws:iam::{account}:role/" + name
    if t == "AWS::IAM::Policy": return params.get("agent_role_arn", "mel-agent-role") + " (inline policy " + name + ")"
    if t == "AWS::Lambda::Function": return prefix.format(service="lambda") + "function:" + name
    if t == "AWS::Logs::LogGroup": return prefix.format(service="logs") + "log-group:" + name
    if t == "AWS::ECR::Repository": return prefix.format(service="ecr") + "repository/" + name
    if t == "AWS::CloudFront::Distribution": return f"arn:aws:cloudfront::{account}:distribution/" + name
    if t == "AWS::Cognito::UserPool": return prefix.format(service="cognito-idp") + "userpool/" + name
    if t == "AWS::CloudWatch::Dashboard": return f"arn:aws:cloudwatch::{account}:dashboard/" + name
    if t == "AWS::CloudWatch::Alarm": return prefix.format(service="cloudwatch") + "alarm:" + name
    if t == "AWS::CloudFront::OriginAccessControl": return f"arn:aws:cloudfront::{account}:origin-access-control/" + name
    if t == "AWS::Cognito::UserPoolClient": return prefix.format(service="cognito-idp") + "userpool/" + params.get("user_pool_id", "unknown") + " (client has no standalone ARN)"
    if t == "AWS::SQS::QueuePolicy": return "Policy attached to queue ARNs above; no standalone ARN"
    if t == "AWS::Lambda::Permission": return prefix.format(service="lambda") + "function:mel-api (resource policy statement)"
    if t == "AWS::ApiGatewayV2::Api": return "arn:aws:apigateway:us-west-2::/apis/" + name
    if t.startswith("AWS::ApiGatewayV2::"):
        api_id = params.get("api_url", "").replace("https://", "").split(".")[0]
        kind = {"AWS::ApiGatewayV2::Authorizer": "authorizers", "AWS::ApiGatewayV2::Integration": "integrations", "AWS::ApiGatewayV2::Route": "routes", "AWS::ApiGatewayV2::Stage": "stages"}.get(t)
        if kind: return "arn:aws:apigateway:us-west-2::/apis/" + api_id + "/" + kind + "/" + name
    return "No standalone ARN; see parent resource and physical ID"


if __name__ == "__main__":
    main()
