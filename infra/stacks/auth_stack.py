from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_cognito as cognito,
)
from cdk_nag import NagSuppressions
from constructs import Construct


class AuthStack(Stack):
    """Cognito user pool. farmer_id and org_id are immutable custom attributes and reach the API
    as the `custom:farmer_id` / `custom:org_id` claims of the ID token (access tokens do not carry
    custom attributes)."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.user_pool = cognito.UserPool(
            self,
            "UserPool",
            user_pool_name="mel-agent-users",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(username=True),
            account_recovery=cognito.AccountRecovery.NONE,
            mfa=cognito.Mfa.OPTIONAL,
            mfa_second_factor=cognito.MfaSecondFactor(sms=False, otp=True),
            password_policy=cognito.PasswordPolicy(
                min_length=12,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=True,
                temp_password_validity=Duration.days(1),
            ),
            custom_attributes={
                "farmer_id": cognito.StringAttribute(min_len=1, max_len=64, mutable=False),
                "org_id": cognito.StringAttribute(min_len=1, max_len=64, mutable=False),
            },
            removal_policy=RemovalPolicy.DESTROY,
        )
        NagSuppressions.add_resource_suppressions(
            self.user_pool,
            [
                {
                    "id": rule_id,
                    "reason": "Advanced security / Cognito Plus feature plan is a paid tier; the pool holds only synthetic users for the hackathon.",
                }
                for rule_id in ("AwsSolutions-COG3", "AwsSolutions-COG8")
            ],
        )

        # No hosted UI / domain is created on purpose. Clients use InitiateAuth with USER_PASSWORD_AUTH.
        # Clients may read the identity attributes but may not write any attribute.
        self.client = self.user_pool.add_client(
            "AppClient",
            user_pool_client_name="mel-agent-app",
            generate_secret=False,
            auth_flows=cognito.AuthFlow(user_password=True),
            prevent_user_existence_errors=True,
            access_token_validity=Duration.hours(1),
            id_token_validity=Duration.hours(1),
            refresh_token_validity=Duration.days(1),
            read_attributes=cognito.ClientAttributes().with_custom_attributes("farmer_id", "org_id"),
            write_attributes=cognito.ClientAttributes(),
        )

        CfnOutput(self, "UserPoolId", value=self.user_pool.user_pool_id)
        CfnOutput(self, "UserPoolClientId", value=self.client.user_pool_client_id)
        CfnOutput(self, "JwtIssuer", value=self.user_pool.user_pool_provider_url)
