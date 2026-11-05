# Independent verification

The test and security agents reviewed only infrastructure and the owned scripts.

- Independent CDK synthesis: six stacks, exit 0.
- Contract suite: twenty-one tests passed without skips, including 14 SSM parameters, DynamoDB keys/GSI/SSE/PITR/TTL, private encrypted buckets and OAC, JWT routes, Lambda interface, independent stacks, explicit IAM actions, queues, and packaged stub response.
- Both shell scripts passed `bash -n`; all infrastructure Python sources passed compilation.
- Mocked seed operation: five expected farmer usernames/IDs, immutable org identity, permanent passwords, and no password literal in output.
- cdk-nag AwsSolutions: zero unsuppressed errors. Actual suppressions and reasons appear in NAG.md.
- Trivy offline secret and misconfiguration scan: zero findings in infra; scripts secret scan: zero findings.
- Checkov template scan: 55 resources parsed, 65 checks passed, 16 failed, zero parsing errors. Failed baseline checks require customer-managed KMS keys, a Lambda VPC/DLQ/reserved concurrency, more bucket versioning, or CloudFront WAF/custom certificate, beyond the fixed demo contract. Its SQS encryption check is a false positive against explicit SqsManagedSseEnabled=true. These results are not represented as a clean Checkov scan.
- AgentCore trust was tightened with SourceAccount and SourceArn conditions. Container uses a nonroot UID and a /ping healthcheck. Passwords/ECR credentials are passed without printing them. Temporary session credentials never enter repository files or Docker context.
- Corrected DynamoDB transaction IAM grants to use item actions and ConditionCheckItem, as AWS transaction APIs are not standalone IAM actions.
- Docker endpoint and plugin discovery survive isolated ECR login; regression tests verify explicit-host handling, directory/file permissions, and cleanup.
- Optional runtime failures are recorded and do not prevent infrastructure evidence/smoke checks.

HTTP API native request validation is unsupported by AWS; the user approved retaining HTTP API and documenting validation in application code. No application files were changed.

Final independent live runtime verification: READY, exact Lambda environment/role parity, linux/arm64 image, `python -m mel.agent`, and one invocation returning `{"status":"stub"}`. Runtime, endpoint, workload identity, and runtime log group have Project=MelAgent; runtime log retention is 14 days. Final independent Trivy re-scan: zero findings.
