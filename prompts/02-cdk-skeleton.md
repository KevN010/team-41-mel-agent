Model: Sonnet. Branch: cdk. Runs in parallel with Wave 0.

Goal: a CDK (Python) app that synthesizes clean and deploys the platform pieces, with security defaults on.

Read first: CLAUDE.md (security section), infra/README.md if present.

You own: infra/** (app.py, cdk.json, stacks/*.py), scripts/deploy.sh, NOTES-K.md.

Stacks, all in us-west-2, prefix MelAgent:
1. DataStack: DynamoDB table mel-ledger (PK pk, SK sk, on-demand, SSE, PITR on, TTL attribute `ttl`),
   S3 bucket for artifacts and evidence (block public, SSE-S3, versioning), S3 bucket for the simulator
   page behind CloudFront (OAC, no public bucket), SQS follow-up queue + DLQ (maxReceiveCount 3, SSE).
2. AuthStack: Cognito user pool (no hosted UI), app client with USER_PASSWORD_AUTH, custom attributes
   farmer_id and org_id (immutable). Script to create 5 synthetic users from pack/data/farmers.csv rows 1..5.
3. ApiStack: API Gateway HTTP API, JWT authorizer against the user pool, routes:
   POST /surveys/decide, POST /surveys/{id}/responses, GET /surveys/{id}, GET /follow-ups, POST /farmers/me/opt-out.
   Stage throttle rate 1 burst 10. Access logs to CloudWatch. Integration target: a Lambda proxy named
   mel-api (placeholder handler returning 501) that the integration agent will replace or point at
   AgentCore Runtime.
4. SecretsStack: Secrets Manager secret mel/jev-api-key (value placeholder), read grant to the agent role.
5. AgentStack: IAM role for AgentCore Runtime with bedrock:InvokeModel on the inference profiles listed in
   CLAUDE.md and on arn:aws:bedrock:us-west-2:<acct>:project/default, DynamoDB rw on the table,
   SQS send, S3 put on artifacts, secret read. ECR repo mel-agent. Nothing else.
6. ObsStack: CloudWatch dashboard with widgets for custom metrics namespace MelAgent: DecisionsByRule,
   ModelCalls, ModelTokens, JudgeVerdicts, LatencyMs p50/p95, CostUsd. Alarm: ModelCalls > 60 per minute.
   AWS Budgets monthly $50 with 80% alert.

scripts/deploy.sh: cdk bootstrap if needed, cdk deploy --all --require-approval never, print outputs.

Done when: `cd infra && cdk synth` succeeds with zero errors and cdk-nag AwsSolutions pack reports no
errors (warnings allowed, list them in NOTES-K.md). Do not deploy. Report: stack list, nag warnings.
