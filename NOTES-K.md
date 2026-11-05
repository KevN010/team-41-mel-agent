# NOTES-K: CDK skeleton (branch work for prompt 02)

Result: `cd infra && cdk synth` succeeds. cdk-nag AwsSolutions: 0 errors, 1 warning. Not deployed.

## Stacks (all us-west-2)
MelAgentDataStack, MelAgentAuthStack, MelAgentSecretsStack, MelAgentApiStack, MelAgentAgentStack, MelAgentObsStack.

## cdk-nag warnings
- AwsSolutions-COG2 on the user pool: MFA is OPTIONAL (TOTP), not required. Pool holds only synthetic users.

## cdk-nag suppressions (each has a reason in code)
- S1 on the access-log bucket (it is the log sink).
- CFR1 geo restriction, CFR2 WAF, CFR4 TLS 1.2 minimum (default CloudFront cert cannot enforce it).
- COG3 and COG8: Cognito Plus plan is a paid tier.
- SMG4: third-party Jev key cannot auto-rotate.
- IAM5 on the agent role and the mel-api role: scoped wildcards only (table indexes, artifact objects, runtime log group, foundation models behind the listed profiles, `*` for GetAuthorizationToken and PutMetricData).

## Disagreements with the prompt or CLAUDE.md
- CLAUDE.md asks for API Gateway "request validation". HTTP APIs do not support request validators (REST APIs only). Validate bodies in the handler with pydantic. Not fixable without switching to a REST API.
- Prompt says SecretsStack has the read grant to the agent role. The grant is made in AgentStack (`secret.grant_read`) because the role is created after the secret. Same effect.
- Agent role has extras beyond the listed permissions, needed for AgentCore Runtime to start and report: ECR pull on `mel-agent`, `ecr:GetAuthorizationToken`, CloudWatch Logs on `/aws/bedrock-agentcore/runtimes/*`, `cloudwatch:PutMetricData` limited to namespace `MelAgent`. No `GetWorkloadAccessToken*` yet; add if AgentCore Identity is used.
- Agent role also has DynamoDB access on `table/mel-ledger/index/*` so a GSI can be added later without an IAM change. No Scan.
- Bedrock IAM for global profiles is written from the AWS docs pattern and untested (`InvokeModel` on the inference-profile ARN, plus the foundation-model ARN conditioned on `bedrock:InferenceProfileArn`). Run `make day0` on a real account before trusting it. Haiku profile: pass `-c haiku_profile_id=<id from models/candidates.txt>` (deploy.sh reads `HAIKU_PROFILE_ID`). `gpt-6.1-luna`: `-c extra_inference_profiles='["global.openai.gpt-6.1-luna"]'`.
- `cdk-nag` is pinned `<3`. Version 3.x removed `NagSuppressions`.
- Lambda `mel-api` placeholder uses Python 3.14; AwsSolutions-L1 fails on older runtimes. CLAUDE.md says 3.12. The integration agent decides.
- Branch: the harness assigned `claude/project-thread-owkhls`, not `cdk`.
- `infra/requirements.txt` was added because the root `requirements.txt` is not mine.

## Things the next agents must know
- The API authorizer checks the ID token (audience = app client id). `custom:farmer_id` and `custom:org_id` exist only in the ID token. Access tokens do not carry custom attributes, so clients must send the ID token.
- Obs contract: alarm uses the dimensionless metric `MelAgent/ModelCalls` (Sum, 1 min). Emitters must publish that aggregate, with or without extra dimensioned copies. Other widgets use `SEARCH('MelAgent <Metric>')` and accept any dimensions. `LatencyMs` p50/p95 widgets use the dimensionless metric too.
- Budget needs an email: set `ALERT_EMAIL` for deploy.sh. Default for synth is `alerts@example.com`; do not deploy with it.
- The follow-up queue has no consumer yet. The DLQ has retention 14 days and maxReceiveCount 3.
- Simulator: bucket and CloudFront exist but nothing uploads `sim/`. After deploy: `aws s3 sync sim/ s3://<SimBucketName>/`. Output `SimUrl` has the URL. CORS on the API allows only that origin.
- Stateful resources (table, three buckets) have RemovalPolicy.RETAIN. The table name is fixed (`mel-ledger`), so destroy then redeploy needs a manual delete of the table first.
- API stage throttle is rate 1, burst 10 on the `$default` stage, as asked. Access logs go to a CloudWatch log group (no bodies, no claims).
- Synthetic users: `python infra/scripts/create_synthetic_users.py [--org-id org-demo]` after deploy. Creates farmers.csv rows 1..5 (F-000001..F-000005), org default `org-demo` (farmers.csv has no org column). Passwords are random and written only to `infra/.synthetic-users.json` (0600, git-ignored). Tested against moto, not real Cognito.
- Setup: `python -m venv .venv && .venv/bin/pip install -r infra/requirements.txt && npm i -g aws-cdk`, then `PATH=.venv/bin:$PATH cdk synth` in `infra/`.
