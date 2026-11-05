from aws_cdk import (
    CfnOutput,
    RemovalPolicy,
    Stack,
    aws_dynamodb as dynamodb,
    aws_ecr as ecr,
    aws_iam as iam,
    aws_s3 as s3,
    aws_secretsmanager as secretsmanager,
    aws_sqs as sqs,
)
from cdk_nag import NagSuppressions
from constructs import Construct

# Inference profiles from CLAUDE.md. The Haiku profile id comes from models/candidates.txt and is
# supplied through the CDK context key `haiku_profile_id`. gpt-6.1-luna is only added through
# `extra_inference_profiles` (CLAUDE.md: use only if it appears in models/candidates.txt).
DEFAULT_PROFILES = ["global.openai.gpt-6-luna", "global.openai.gpt-6.1-terra"]


class AgentStack(Stack):
    """IAM role for AgentCore Runtime plus the ECR repo. Least privilege, nothing else."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        table: dynamodb.ITable,
        followup_queue: sqs.IQueue,
        artifacts_bucket: s3.IBucket,
        jev_secret: secretsmanager.ISecret,
        inference_profiles: list[str],
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.repo = ecr.Repository(
            self,
            "AgentRepo",
            repository_name="mel-agent",
            image_scan_on_push=True,
            lifecycle_rules=[ecr.LifecycleRule(max_image_count=10)],
            removal_policy=RemovalPolicy.DESTROY,
            empty_on_delete=False,
        )

        self.role = iam.Role(
            self,
            "AgentRuntimeRole",
            description="Execution role for the mel-agent AgentCore Runtime",
            assumed_by=iam.ServicePrincipal(
                "bedrock-agentcore.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": self.account},
                    "ArnLike": {"aws:SourceArn": f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:*"},
                },
            ),
        )

        # --- Bedrock: Converse needs bedrock:InvokeModel on the profile and on the model behind it.
        profile_arns = [f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/{p}" for p in inference_profiles]
        model_ids = [p.split(".", 1)[1] if p.split(".", 1)[0] in ("global", "us", "eu", "apac") else p for p in inference_profiles]
        foundation_model_arns = []
        for m in model_ids:
            foundation_model_arns += [f"arn:aws:bedrock:::foundation-model/{m}", f"arn:aws:bedrock:*::foundation-model/{m}"]
        self.role.add_to_policy(
            iam.PolicyStatement(
                sid="InvokeInferenceProfiles",
                actions=["bedrock:InvokeModel"],
                resources=profile_arns + [f"arn:aws:bedrock:{self.region}:{self.account}:project/default"],
            )
        )
        self.role.add_to_policy(
            iam.PolicyStatement(
                sid="InvokeFoundationModelsViaProfilesOnly",
                actions=["bedrock:InvokeModel"],
                resources=foundation_model_arns,
                conditions={"ArnLike": {"bedrock:InferenceProfileArn": profile_arns}},
            )
        )

        # --- DynamoDB read/write on the ledger table. No Scan, no table admin actions.
        self.role.add_to_policy(
            iam.PolicyStatement(
                sid="LedgerReadWrite",
                actions=[
                    "dynamodb:GetItem",
                    "dynamodb:BatchGetItem",
                    "dynamodb:Query",
                    "dynamodb:PutItem",
                    "dynamodb:UpdateItem",
                    "dynamodb:DeleteItem",
                    "dynamodb:BatchWriteItem",
                    "dynamodb:ConditionCheckItem",
                ],
                resources=[table.table_arn, f"{table.table_arn}/index/*"],
            )
        )

        # --- SQS send, S3 put, secret read.
        followup_queue.grant_send_messages(self.role)
        self.role.add_to_policy(
            iam.PolicyStatement(
                sid="ArtifactsPut",
                actions=["s3:PutObject"],
                resources=[artifacts_bucket.arn_for_objects("*")],
            )
        )
        jev_secret.grant_read(self.role)

        # --- Minimum extras AgentCore Runtime needs to start and report (see NOTES-K.md).
        self.repo.grant_pull(self.role)  # includes ecr:GetAuthorizationToken
        self.role.add_to_policy(
            iam.PolicyStatement(
                sid="RuntimeLogs",
                actions=["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"],
                resources=[f"arn:aws:logs:{self.region}:{self.account}:log-group:/aws/bedrock-agentcore/runtimes/*"],
            )
        )
        self.role.add_to_policy(
            iam.PolicyStatement(
                sid="CustomMetricsMelAgentOnly",
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],
                conditions={"StringEquals": {"cloudwatch:namespace": "MelAgent"}},
            )
        )

        NagSuppressions.add_resource_suppressions(
            self.role,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "Scoped wildcards: ledger table indexes, artifact objects, foundation models reached only "
                        "through the listed inference profiles (region wildcard needed for global profiles), "
                        "AgentCore runtime log groups, ECR GetAuthorizationToken and PutMetricData "
                        "(resource * required, restricted to namespace MelAgent)."
                    ),
                    "applies_to": [
                        {"regex": "/^Resource::.*\\/index\\/\\*$/"},
                        {"regex": "/^Resource::.*\\/\\*$/"},
                        {"regex": "/^Resource::\\*$/"},
                        {"regex": "/^Resource::arn:aws:bedrock:\\*::foundation-model\\/.*$/"},
                    ],
                }
            ],
            apply_to_children=True,
        )

        CfnOutput(self, "AgentRuntimeRoleArn", value=self.role.role_arn)
        CfnOutput(self, "AgentRepoUri", value=self.repo.repository_uri)
