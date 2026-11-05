Model: Opus. Branch: wave2-integration. You are the only agent allowed to edit across directories.
Goal: wire everything, deploy to us-west-2, produce one real AWS trace of the full flow.
Read first: CLAUDE.md, CONTRACTS.md, every NOTES-*.md, mel/**, infra/**, models/models.yaml, sim/README.md.
Deliver:
1. mel/agent.py: AgentCore Runtime entrypoint (BedrockAgentCoreApp, @app.entrypoint) that accepts
   {action: decide|respond|follow_ups, identity, payload} and calls mel.api. Also mel/api/handler.py
   for the Lambda path. Both share the same functions. No business logic here.
2. Resolve every NOTES-*.md item: fix or record in KNOWN-ISSUES.md.
3. `make test` green. ruff clean.
4. scripts/deploy.sh end to end: cdk deploy, ECR push, agentcore launch, seed users, upload sim/.
   Put the Jev key into the secret by hand (do not commit it).
5. Run the demo path against the deployed stack for scenario 3 (potato) and 6 (no survey):
   decide -> survey -> handoff -> advance clock -> respond "spreading" -> follow-up item.
   Save: the CloudWatch log lines with rule id, model id, tokens, cost; the DynamoDB items; the SQS
   message; the X-Ray or AgentCore Observability trace id. Write them to evidence/e2e-run-1.md.
6. Restart the Runtime (new deployment) and show the same survey is still readable: evidence/restart.md.
Done when: evidence/e2e-run-1.md exists with real identifiers. Report: what is deployed, what is not,
and every KNOWN-ISSUES entry.
