from aws_cdk import (
    CfnOutput,
    RemovalPolicy,
    SecretValue,
    Stack,
    aws_secretsmanager as secretsmanager,
)
from cdk_nag import NagSuppressions
from constructs import Construct


class SecretsStack(Stack):
    """Secret for the Jev (TypeSafe) API key. The read grant to the agent role is made in
    AgentStack (secret.grant_read), because the role is created after this stack."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.jev_secret = secretsmanager.Secret(
            self,
            "JevApiKey",
            secret_name="mel/jev-api-key",
            description="TypeSafe Jev API key. Replace the placeholder with: aws secretsmanager put-secret-value",
            secret_string_value=SecretValue.unsafe_plain_text("PLACEHOLDER-replace-with-put-secret-value"),
            removal_policy=RemovalPolicy.DESTROY,
        )
        NagSuppressions.add_resource_suppressions(
            self.jev_secret,
            [
                {
                    "id": "AwsSolutions-SMG4",
                    "reason": "Third-party API key issued by TypeSafe; Secrets Manager cannot rotate it automatically.",
                }
            ],
        )

        CfnOutput(self, "JevSecretArn", value=self.jev_secret.secret_arn)
