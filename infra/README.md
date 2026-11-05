# infra

CDK (Python) app in us-west-2 with six stacks, all prefixed `MelAgent`: `MelAgentDataStack` (DynamoDB table `mel-ledger`, artifact/evidence and simulator S3 buckets, SQS follow-up queue with DLQ), `MelAgentAuthStack` (Cognito user pool with immutable `custom:farmer_id` and `custom:org_id`), `MelAgentApiStack` (HTTP API with JWT authorizer and Lambda `mel-api`), `MelAgentSecretsStack` (secret `mel/jev-api-key`), `MelAgentAgentStack` (AgentCore Runtime role and ECR repo `mel-agent`) and `MelAgentObsStack` (CloudWatch dashboard and alarms for namespace `MelAgent`, monthly budget).
