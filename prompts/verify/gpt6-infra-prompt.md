# GPT-6 prompt: build and deploy the AWS infrastructure for mel-agent now

Run this in Codex (or ChatGPT Work on Bedrock) with the team-41-mel-agent repo checked out and AWS credentials
for us-west-2 in the environment. Paste everything below the line.

Before you paste: append the "CLAUDE.md addendum" at the bottom of this file to mel-agent/CLAUDE.md and delete
prompts/02-cdk-skeleton.md and prompts/wave1/K-cdk-finish.md. Claude threads then read infra/INFRA.md and never
touch infra/.

---

You own the AWS infrastructure for mel-agent, a small Python service for an AWS hackathon. Another team of agents
writes the application code in mel/ at the same time. You do not touch mel/, tests/, sim/ or prompts/. You own
infra/**, scripts/package_lambda.sh, scripts/deploy.sh, scripts/seed_users.py and infra/INFRA.md.

Goal: everything below deployed to us-west-2 within 60 minutes, with the interface contract honored exactly, so
the application can be dropped in later without infrastructure changes.

## Fixed decisions
- Region us-west-2. CDK v2 in Python (aws-cdk-lib, constructs). Stack prefix MelAgent. Tag every resource Project=MelAgent.
- Cross-stack wiring goes through SSM parameters, never through Python object references, so stacks deploy
  independently. Producers write parameters; consumers read them with
  ssm.StringParameter.value_for_string_parameter at deploy time.
- Security defaults on everywhere. cdk-nag AwsSolutions checks must report zero errors; list suppressions with a
  one-line reason each in infra/NAG.md.
- Deploy in dependency order with concurrency: `cdk deploy --all --concurrency 6 --require-approval never`.
- No secrets in code or outputs. The Jev API key is set by a human with `aws secretsmanager put-secret-value`.

## Interface contract (the application reads exactly these; do not rename)
SSM parameters, all String type:
  /mel/table_name            DynamoDB table name
  /mel/artifacts_bucket      S3 bucket for artifacts and evidence
  /mel/sim_bucket            S3 bucket behind CloudFront for the static simulator
  /mel/sim_url               CloudFront https URL
  /mel/followup_queue_url    SQS queue URL
  /mel/followup_dlq_url      SQS DLQ URL
  /mel/user_pool_id          Cognito user pool id
  /mel/user_pool_client_id   Cognito app client id
  /mel/api_url               API Gateway invoke URL (no trailing slash)
  /mel/jev_secret_arn        Secrets Manager secret ARN
  /mel/agent_role_arn        IAM role ARN for the agent and the Lambda
  /mel/ecr_repo_uri          ECR repository URI for the AgentCore container
  /mel/agent_runtime_arn     AgentCore Runtime ARN, written by scripts/deploy.sh after launch, placeholder "pending" until then
  /mel/dashboard_name        CloudWatch dashboard name
Lambda and container environment variables (same values):
  MEL_REGION=us-west-2, MEL_TABLE, MEL_ARTIFACTS_BUCKET, MEL_FOLLOWUP_QUEUE_URL, MEL_JEV_SECRET_ARN,
  MEL_USER_POOL_ID, MEL_USER_POOL_CLIENT_ID, MEL_MODELS_FILE=models/models.yaml, MEL_METRICS_NAMESPACE=MelAgent
Lambda handler string: mel.api.handler.lambda_handler  (the module arrives later; ship a stub with the same path)
Container entrypoint: python -m mel.agent                (same; ship a stub)
API routes (HTTP API, all behind the JWT authorizer):
  POST /surveys/decide
  GET  /surveys/{id}
  POST /surveys/{id}/responses
  GET  /follow-ups
  POST /farmers/me/opt-out
JWT claims the app relies on: sub, custom:farmer_id, custom:org_id
DynamoDB table: name mel-ledger, partition key pk (S), sort key sk (S), GSI1 with pk gsi1pk (S) and sk gsi1sk (S),
  on-demand, SSE with AWS managed key, point-in-time recovery on, TTL attribute ttl.
CloudWatch custom metrics namespace MelAgent with metric names DecisionsByRule, ModelCalls, ModelTokens,
  JudgeVerdicts, LatencyMs, CostUsd.

## Stacks
1. MelAgent-Data: the table above; artifacts bucket (block public, SSE-S3, versioning, enforce SSL); sim bucket
   (block public, SSE-S3) with a CloudFront distribution using origin access control and HTTPS only; SQS queue
   mel-followups with SSE and a DLQ mel-followups-dlq (maxReceiveCount 3, retention 14 days). Write the SSM params.
2. MelAgent-Secrets: Secrets Manager secret mel/jev-api-key with placeholder value "REPLACE_ME". Write the param.
3. MelAgent-Auth: Cognito user pool (self sign-up off, no hosted UI, MFA off for the demo, password policy default),
   custom attributes farmer_id and org_id (string, mutable false), app client with USER_PASSWORD_AUTH and
   no client secret. Write the params.
4. MelAgent-Agent: one IAM role mel-agent-role assumable by lambda.amazonaws.com and bedrock-agentcore.amazonaws.com
   with: bedrock:InvokeModel and bedrock:InvokeModelWithResponseStream on
   arn:aws:bedrock:*::foundation-model/openai.* , arn:aws:bedrock:*::foundation-model/anthropic.* ,
   arn:aws:bedrock:us-west-2:<account>:inference-profile/* , arn:aws:bedrock:us-west-2:<account>:project/default;
   dynamodb read/write on the table and its GSI only; sqs:SendMessage on the queue; s3 put/get on the artifacts
   bucket; secretsmanager:GetSecretValue on the Jev secret; cloudwatch:PutMetricData conditioned on namespace
   MelAgent; logs create/put; ssm:GetParameter on /mel/*. No wildcard actions. ECR repository mel-agent with
   scan on push and a lifecycle rule keeping 10 images. Write the params.
5. MelAgent-Api: Lambda mel-api (Python 3.12, arm64, 512 MB, 30 s timeout, role from above, env vars above,
   code from build/lambda produced by scripts/package_lambda.sh, which for now packages a stub module
   mel/api/handler.py returning HTTP 501 {"error":"not implemented"}; do not create mel/ in the repo, build the
   stub inside build/). HTTP API with JWT authorizer (issuer and audience from the user pool and client), the five
   routes, request validation on, access logging to a log group with 14-day retention, default stage throttle
   rate 1 burst 10, CORS allowing the CloudFront URL only. Write the api_url param.
6. MelAgent-Obs: CloudWatch dashboard mel-agent with widgets for the six custom metrics (sum per minute, and p50
   and p95 for LatencyMs), Lambda errors and duration, API 4xx and 5xx, DynamoDB throttles, SQS DLQ depth.
   Alarm when ModelCalls sum over 1 minute exceeds 60. Alarm when DLQ depth is at least 1. AWS Budgets monthly
   USD 50 with notification at 80 percent to an email you take from the environment variable BUDGET_EMAIL
   (skip the budget if unset). Write the dashboard param.
7. AgentCore Runtime: build an arm64 container from infra/Dockerfile.agent containing a stub mel/agent.py that
   uses the bedrock-agentcore SDK (BedrockAgentCoreApp with one @app.entrypoint returning {"status":"stub"}),
   push to the ECR repo, and launch it with the bedrock-agentcore-starter-toolkit
   (`agentcore configure` then `agentcore launch`) using the mel-agent-role. If the toolkit is unavailable or
   fails, write the exact failing command and error into infra/INFRA.md under "AgentCore Runtime: not launched"
   and continue; do not block the rest. On success write the runtime ARN into /mel/agent_runtime_arn.

## Scripts
- scripts/package_lambda.sh: builds build/lambda from the repo's mel/ if it exists, else from the stub; installs
  requirements for arm64 manylinux; prints the zip size.
- scripts/deploy.sh: cdk bootstrap if needed; cdk deploy --all --concurrency 6 --require-approval never;
  then the AgentCore steps; then writes infra/INFRA.md.
- scripts/seed_users.py: creates 5 Cognito users from pack/data/farmers.csv rows 1 to 5 with usernames
  farmer1..farmer5, custom:farmer_id = the farmer_id column, custom:org_id = org.farmerchat, a permanent
  password read from env SEED_PASSWORD, and prints one working `aws cognito-idp initiate-auth` command.

## Deliverables, in this order
1. infra/** synthesizes clean: `cd infra && cdk synth` and cdk-nag zero errors.
2. Deployed. Paste the `cdk deploy` summary and `aws ssm get-parameters-by-path --path /mel --region us-west-2`
   output into infra/INFRA.md, together with: every resource name and ARN, the API URL, the CloudFront URL,
   the seed-user command, the command to set the Jev secret, the redeploy command for the Lambda and the
   container, and the AgentCore Runtime status.
3. infra/NAG.md with suppressions and reasons.
4. A smoke test you ran and its output: unauthenticated GET /follow-ups returns 401; an authenticated call with
   a seeded user returns 501 from the stub; the SSM parameters all resolve; `aws dynamodb describe-table` shows
   SSE and PITR on.
Report: the four items above and nothing else. Do not fix application code. Do not open a PR against mel/.
If a step needs something you do not have (credentials, bootstrap permission, a quota), stop and say exactly what.

====================================================================
CLAUDE.md addendum (append to mel-agent/CLAUDE.md before launching Claude threads)
====================================================================

## Infrastructure (owned by GPT, not by Claude threads)
Infrastructure is built and deployed separately. Never edit infra/, scripts/deploy.sh, scripts/package_lambda.sh
or scripts/seed_users.py. Read infra/INFRA.md for resource names, URLs and commands.
The application reads configuration only from these environment variables, with SSM parameters under /mel/ as
the fallback when an env var is unset: MEL_REGION, MEL_TABLE, MEL_ARTIFACTS_BUCKET, MEL_FOLLOWUP_QUEUE_URL,
MEL_JEV_SECRET_ARN, MEL_USER_POOL_ID, MEL_USER_POOL_CLIENT_ID, MEL_MODELS_FILE, MEL_METRICS_NAMESPACE.
Lambda handler must be mel.api.handler.lambda_handler. Container entrypoint must be `python -m mel.agent`.
DynamoDB keys: pk, sk, GSI1 (gsi1pk, gsi1sk), TTL attribute ttl. Table name comes from MEL_TABLE.
Custom metrics namespace MelAgent; metric names DecisionsByRule, ModelCalls, ModelTokens, JudgeVerdicts,
LatencyMs, CostUsd. JWT claims: sub, custom:farmer_id, custom:org_id.
To redeploy application code: `bash scripts/package_lambda.sh && cd infra && cdk deploy MelAgent-Api`
and for the agent container the commands in infra/INFRA.md. Only the integration thread runs these.
