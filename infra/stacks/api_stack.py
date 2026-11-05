from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_apigatewayv2 as apigw,
    aws_apigatewayv2_authorizers as authorizers,
    aws_apigatewayv2_integrations as integrations,
    aws_cognito as cognito,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_logs as logs,
)
from cdk_nag import NagSuppressions
from constructs import Construct

PLACEHOLDER_CODE = '''\
import json


def handler(event, context):
    # Placeholder. The integration agent replaces this or points the routes at AgentCore Runtime.
    return {
        "statusCode": 501,
        "headers": {"content-type": "application/json"},
        "body": json.dumps({"error": "not_implemented"}),
    }
'''

ROUTES = [
    (apigw.HttpMethod.POST, "/surveys/decide"),
    (apigw.HttpMethod.POST, "/surveys/{id}/responses"),
    (apigw.HttpMethod.GET, "/surveys/{id}"),
    (apigw.HttpMethod.GET, "/follow-ups"),
    (apigw.HttpMethod.POST, "/farmers/me/opt-out"),
]


class ApiStack(Stack):
    """HTTP API with a Cognito JWT authorizer in front of the mel-api Lambda proxy."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        user_pool: cognito.IUserPool,
        user_pool_client: cognito.IUserPoolClient,
        sim_origin: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- mel-api Lambda: its own role, logs only. The integration agent widens it as needed.
        log_group = logs.LogGroup(
            self,
            "ApiFnLogs",
            log_group_name="/aws/lambda/mel-api",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )
        fn_role = iam.Role(
            self,
            "ApiFnRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            description="mel-api Lambda execution role (logs only)",
        )
        log_group.grant_write(fn_role)

        self.api_fn = _lambda.Function(
            self,
            "ApiFn",
            function_name="mel-api",
            runtime=_lambda.Runtime.PYTHON_3_14,
            handler="index.handler",
            code=_lambda.Code.from_inline(PLACEHOLDER_CODE),
            role=fn_role,
            log_group=log_group,
            timeout=Duration.seconds(30),
            memory_size=256,
        )

        # --- HTTP API --------------------------------------------------------------------------
        self.api = apigw.HttpApi(
            self,
            "HttpApi",
            api_name="mel-agent-api",
            create_default_stage=False,
            cors_preflight=apigw.CorsPreflightOptions(
                allow_origins=[sim_origin],
                allow_methods=[apigw.CorsHttpMethod.GET, apigw.CorsHttpMethod.POST],
                allow_headers=["authorization", "content-type"],
                max_age=Duration.hours(1),
            ),
        )

        authorizer = authorizers.HttpJwtAuthorizer(
            "CognitoJwt",
            jwt_issuer=user_pool.user_pool_provider_url,
            jwt_audience=[user_pool_client.user_pool_client_id],
        )
        integration = integrations.HttpLambdaIntegration("MelApiIntegration", self.api_fn)
        for method, path in ROUTES:
            self.api.add_routes(path=path, methods=[method], integration=integration, authorizer=authorizer)

        access_logs = logs.LogGroup(
            self,
            "ApiAccessLogs",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )
        # No request or response bodies are logged, only request metadata. Never log insight text.
        stage = apigw.HttpStage(
            self,
            "DefaultStage",
            http_api=self.api,
            stage_name="$default",
            auto_deploy=True,
            throttle=apigw.ThrottleSettings(rate_limit=1, burst_limit=10),
        )
        # Access logs via the L1 escape hatch: the L2 access-log API differs between aws-cdk-lib versions.
        access_log_format = (
            '{"requestId":"$context.requestId","ip":"$context.identity.sourceIp",'
            '"requestTime":"$context.requestTime","httpMethod":"$context.httpMethod",'
            '"routeKey":"$context.routeKey","status":"$context.status",'
            '"protocol":"$context.protocol","responseLength":"$context.responseLength",'
            '"integrationLatency":"$context.integrationLatency",'
            '"authorizerError":"$context.authorizer.error"}'
        )
        stage.node.default_child.access_log_settings = apigw.CfnStage.AccessLogSettingsProperty(
            destination_arn=access_logs.log_group_arn, format=access_log_format
        )
        self.stage = stage

        NagSuppressions.add_resource_suppressions(
            fn_role,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "Log-stream wildcard under the single mel-api log group created by CDK grant_write.",
                    "applies_to": [{"regex": "/^Resource::<ApiFnLogs.*\\.Arn>:\\*$/"}],
                }
            ],
            apply_to_children=True,
        )

        CfnOutput(self, "ApiUrl", value=self.api.api_endpoint)
        CfnOutput(self, "ApiFunctionName", value=self.api_fn.function_name)
