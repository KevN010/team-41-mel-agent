Model: Sonnet. Branch: w1-K. Continues the cdk branch from prompt 02.
Goal: finish infra so the integration agent can deploy with one command.
Read first: infra/**, NOTES-K.md, CLAUDE.md, mel/api/* if merged.
You own: infra/**, scripts/deploy.sh, scripts/seed_users.py, NOTES-K.md.
Deliver: Lambda mel-api (Python 3.12, arm64) packaged from mel/ with handler mel.api.handler.lambda_handler
that routes the five API paths to mel.api functions; env vars from settings; role from AgentStack.
AgentCore Runtime definition: Dockerfile.agent (arm64) with entrypoint mel/agent.py, ECR push in
deploy.sh, and the `agentcore configure`/`agentcore launch` steps written out (starter toolkit), with a
fallback note if the toolkit is unavailable. CloudFront + S3 deploy of sim/ via BucketDeployment.
scripts/seed_users.py creates 5 Cognito users with custom:farmer_id and custom:org_id = org.farmerchat
and prints a working token command. cdk-nag errors: zero.
Done when: cdk synth clean, nag errors zero. Do not deploy. Report: outputs the integrator needs.
