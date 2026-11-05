#!/usr/bin/env python3
"""Independent MelAgent stacks; resource values cross boundaries only through SSM."""
import os
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import (
    aws_apigatewayv2 as apigw,
    aws_budgets as budgets,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_cloudwatch as cw,
    aws_cognito as cognito,
    aws_dynamodb as dynamodb,
    aws_ecr as ecr,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_s3 as s3,
    aws_secretsmanager as secrets,
    aws_sqs as sqs,
    aws_ssm as ssm,
)
from cdk_nag import AwsSolutionsChecks, NagSuppressions

ROOT = Path(__file__).resolve().parent.parent
REGION = "us-west-2"
NAG_REASONS = {
    "AwsSolutions-S1": "The dedicated access-log sink does not log to itself, avoiding recursive logging.",
    "AwsSolutions-CFR1": "This hackathon simulator is intentionally accessible from every country.",
    "AwsSolutions-CFR2": "CloudFront serves static files only; a paid WAF is outside the fixed demo scope.",
    "AwsSolutions-CFR4": "The AWS default CloudFront certificate is required for the distribution domain; HTTPS-only redirects are enforced.",
    "AwsSolutions-COG1": "The requested Cognito default password policy is retained for the demo.",
    "AwsSolutions-COG2": "MFA is explicitly disabled by the fixed demo requirements.",
    "AwsSolutions-COG8": "The paid Cognito Plus plan is outside the fixed hackathon demo scope.",
    "AwsSolutions-SMG4": "This third-party Jev key is rotated by its human owner; no provider rotation API is available.",
    "AwsSolutions-COG3": "Cognito advanced threat protection is outside the fixed demo scope.",
    "AwsSolutions-IAM5": "Resource wildcards cover only specified model families, table indexes, log streams, artifacts objects, ECR authentication, metrics, and /mel parameters; actions are explicit.",
    "AwsSolutions-L1": "Python 3.12 is explicitly required by the Lambda interface contract.",
}


def publish(stack, name, value):
    ssm.StringParameter(stack, "Param" + name.title().replace("_", ""),
                        parameter_name="/mel/" + name, string_value=value)


def read(stack, name):
    return ssm.StringParameter.value_for_string_parameter(stack, "/mel/" + name)


def environment(stack):
    return {
        "MEL_REGION": REGION,
        "MEL_TABLE": read(stack, "table_name"),
        "MEL_ARTIFACTS_BUCKET": read(stack, "artifacts_bucket"),
        "MEL_FOLLOWUP_QUEUE_URL": read(stack, "followup_queue_url"),
        "MEL_JEV_SECRET_ARN": read(stack, "jev_secret_arn"),
        "MEL_USER_POOL_ID": read(stack, "user_pool_id"),
        "MEL_USER_POOL_CLIENT_ID": read(stack, "user_pool_client_id"),
        "MEL_MODELS_FILE": "models/models.yaml",
        "MEL_METRICS_NAMESPACE": "MelAgent",
    }


class Data(cdk.Stack):
    def __init__(self, scope, id, **kwargs):
        super().__init__(scope, id, **kwargs)
        table = dynamodb.Table(self, "Ledger", table_name="mel-ledger",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="sk", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(point_in_time_recovery_enabled=True),
            time_to_live_attribute="ttl", deletion_protection=True,
            removal_policy=cdk.RemovalPolicy.RETAIN)
        table.add_global_secondary_index(index_name="GSI1",
            partition_key=dynamodb.Attribute(name="gsi1pk", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="gsi1sk", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.ALL)
        access = s3.Bucket(self, "AccessLogs", encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL, enforce_ssl=True,
            object_ownership=s3.ObjectOwnership.OBJECT_WRITER,
            removal_policy=cdk.RemovalPolicy.RETAIN)
        NagSuppressions.add_resource_suppressions(access,
            [{"id": "AwsSolutions-S1", "reason": NAG_REASONS["AwsSolutions-S1"]}])
        artifacts = s3.Bucket(self, "Artifacts", encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL, enforce_ssl=True, versioned=True,
            server_access_logs_bucket=access, server_access_logs_prefix="artifacts/",
            removal_policy=cdk.RemovalPolicy.RETAIN)
        simulator = s3.Bucket(self, "Simulator", encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL, enforce_ssl=True,
            server_access_logs_bucket=access, server_access_logs_prefix="sim/",
            removal_policy=cdk.RemovalPolicy.RETAIN)
        distribution = cloudfront.Distribution(self, "SimulatorCdn",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(simulator),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS),
            default_root_object="index.html", minimum_protocol_version=cloudfront.SecurityPolicyProtocol.TLS_V1_2_2021,
            enable_logging=True, log_bucket=access, log_file_prefix="cloudfront/",
            price_class=cloudfront.PriceClass.PRICE_CLASS_100)
        NagSuppressions.add_resource_suppressions(distribution, [
            {"id": key, "reason": NAG_REASONS[key]} for key in
            ["AwsSolutions-CFR1", "AwsSolutions-CFR2", "AwsSolutions-CFR4"]])
        dlq = sqs.Queue(self, "FollowupDlq", queue_name="mel-followups-dlq",
            encryption=sqs.QueueEncryption.SQS_MANAGED, enforce_ssl=True,
            retention_period=cdk.Duration.days(14))
        queue = sqs.Queue(self, "Followups", queue_name="mel-followups",
            encryption=sqs.QueueEncryption.SQS_MANAGED, enforce_ssl=True,
            dead_letter_queue=sqs.DeadLetterQueue(queue=dlq, max_receive_count=3))
        for name, value in {
            "table_name": table.table_name, "artifacts_bucket": artifacts.bucket_name,
            "sim_bucket": simulator.bucket_name, "sim_url": "https://" + distribution.distribution_domain_name,
            "followup_queue_url": queue.queue_url, "followup_dlq_url": dlq.queue_url,
        }.items():
            publish(self, name, value)


class Secrets(cdk.Stack):
    def __init__(self, scope, id, **kwargs):
        super().__init__(scope, id, **kwargs)
        secret = secrets.Secret(self, "JevApiKey", secret_name="mel/jev-api-key",
            secret_string_value=cdk.SecretValue.unsafe_plain_text("REPLACE_ME"))
        NagSuppressions.add_resource_suppressions(secret, [{"id": "AwsSolutions-SMG4", "reason": NAG_REASONS["AwsSolutions-SMG4"]}])
        publish(self, "jev_secret_arn", secret.secret_arn)


class Auth(cdk.Stack):
    def __init__(self, scope, id, **kwargs):
        super().__init__(scope, id, **kwargs)
        pool = cognito.UserPool(self, "Users", user_pool_name="mel-agent-users",
            self_sign_up_enabled=False, mfa=cognito.Mfa.OFF,
            custom_attributes={"farmer_id": cognito.StringAttribute(mutable=False),
                               "org_id": cognito.StringAttribute(mutable=False)},
            removal_policy=cdk.RemovalPolicy.RETAIN)
        client = pool.add_client("Application", user_pool_client_name="mel-agent-app",
            generate_secret=False, auth_flows=cognito.AuthFlow(user_password=True),
            prevent_user_existence_errors=True,
            read_attributes=cognito.ClientAttributes().with_custom_attributes("farmer_id", "org_id"),
            write_attributes=cognito.ClientAttributes().with_standard_attributes(email=True))
        NagSuppressions.add_resource_suppressions(pool, [
            {"id": key, "reason": NAG_REASONS[key]} for key in
            ["AwsSolutions-COG1", "AwsSolutions-COG2", "AwsSolutions-COG3", "AwsSolutions-COG8"]], True)
        publish(self, "user_pool_id", pool.user_pool_id)
        publish(self, "user_pool_client_id", client.user_pool_client_id)


class Agent(cdk.Stack):
    def __init__(self, scope, id, **kwargs):
        super().__init__(scope, id, **kwargs)
        table_arn = self.format_arn(service="dynamodb", resource="table", resource_name=read(self, "table_name"))
        queue_name = cdk.Fn.select(4, cdk.Fn.split("/", read(self, "followup_queue_url")))
        queue_arn = self.format_arn(service="sqs", resource=queue_name, arn_format=cdk.ArnFormat.NO_RESOURCE_NAME)
        bucket_arn = "arn:aws:s3:::" + read(self, "artifacts_bucket")
        role = iam.Role(self, "ExecutionRole", role_name="mel-agent-role",
            assumed_by=iam.CompositePrincipal(iam.ServicePrincipal("lambda.amazonaws.com"),
                iam.ServicePrincipal("bedrock-agentcore.amazonaws.com", conditions={"StringEquals": {"aws:SourceAccount": self.account}, "ArnLike": {"aws:SourceArn": self.format_arn(service="bedrock-agentcore", resource="*")}})))
        repo = ecr.Repository(self, "Container", repository_name="mel-agent",
            image_scan_on_push=True, image_tag_mutability=ecr.TagMutability.IMMUTABLE,
            lifecycle_rules=[ecr.LifecycleRule(max_image_count=10)], removal_policy=cdk.RemovalPolicy.RETAIN)
        policy = iam.Policy(self, "RuntimePolicy", statements=[
            iam.PolicyStatement(actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"], resources=[
                "arn:aws:bedrock:*::foundation-model/openai.*", "arn:aws:bedrock:*::foundation-model/anthropic.*",
                self.format_arn(service="bedrock", resource="inference-profile", resource_name="*"),
                self.format_arn(service="bedrock", resource="project", resource_name="default")]),
            iam.PolicyStatement(actions=["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem",
                "dynamodb:BatchGetItem", "dynamodb:BatchWriteItem", "dynamodb:Query", "dynamodb:Scan", "dynamodb:DescribeTable",
                "dynamodb:ConditionCheckItem"], resources=[table_arn, table_arn + "/index/GSI1"]),
            iam.PolicyStatement(actions=["sqs:SendMessage"], resources=[queue_arn]),
            iam.PolicyStatement(actions=["s3:PutObject", "s3:GetObject"], resources=[bucket_arn + "/*"]),
            iam.PolicyStatement(actions=["secretsmanager:GetSecretValue"], resources=[read(self, "jev_secret_arn")]),
            iam.PolicyStatement(actions=["cloudwatch:PutMetricData"], resources=["*"],
                                conditions={"StringEquals": {"cloudwatch:namespace": "MelAgent"}}),
            iam.PolicyStatement(actions=["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"], resources=[
                self.format_arn(service="logs", resource="log-group", resource_name="/aws/lambda/mel-api:*", arn_format=cdk.ArnFormat.COLON_RESOURCE_NAME),
                self.format_arn(service="logs", resource="log-group", resource_name="/aws/bedrock-agentcore/runtimes/*", arn_format=cdk.ArnFormat.COLON_RESOURCE_NAME)]),
            iam.PolicyStatement(actions=["ssm:GetParameter"], resources=[self.format_arn(service="ssm", resource="parameter", resource_name="mel/*")]),
            iam.PolicyStatement(actions=["ecr:GetAuthorizationToken"], resources=["*"]),
            iam.PolicyStatement(actions=["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"], resources=[repo.repository_arn]),
        ])
        role.attach_inline_policy(policy)
        NagSuppressions.add_resource_suppressions(policy, [{"id": "AwsSolutions-IAM5", "reason": NAG_REASONS["AwsSolutions-IAM5"]}], True)
        publish(self, "agent_role_arn", role.role_arn)
        publish(self, "ecr_repo_uri", repo.repository_uri)
        publish(self, "agent_runtime_arn", "pending")


class Api(cdk.Stack):
    def __init__(self, scope, id, **kwargs):
        super().__init__(scope, id, **kwargs)
        log = logs.LogGroup(self, "LambdaLog", log_group_name="/aws/lambda/mel-api",
                            retention=logs.RetentionDays.TWO_WEEKS, removal_policy=cdk.RemovalPolicy.RETAIN)
        fn = lambda_.Function(self, "Handler", function_name="mel-api", runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64, memory_size=512, timeout=cdk.Duration.seconds(30),
            handler="mel.api.handler.lambda_handler", role=iam.Role.from_role_arn(self, "RuntimeRole", read(self, "agent_role_arn"), mutable=False),
            environment=environment(self), code=lambda_.Code.from_asset(str(ROOT / "build/lambda")), log_group=log)
        NagSuppressions.add_resource_suppressions(fn, [{"id": "AwsSolutions-L1", "reason": NAG_REASONS["AwsSolutions-L1"]}])
        api = apigw.CfnApi(self, "HttpApi", name="mel-api", protocol_type="HTTP",
            cors_configuration=apigw.CfnApi.CorsProperty(allow_origins=[read(self, "sim_url")],
                allow_headers=["authorization", "content-type"], allow_methods=["GET", "POST", "OPTIONS"]))
        authorizer = apigw.CfnAuthorizer(self, "Jwt", api_id=api.ref, name="mel-cognito", authorizer_type="JWT",
            identity_source=["$request.header.Authorization"],
            jwt_configuration=apigw.CfnAuthorizer.JWTConfigurationProperty(
                issuer=f"https://cognito-idp.{REGION}.amazonaws.com/" + read(self, "user_pool_id"),
                audience=[read(self, "user_pool_client_id")]))
        integration = apigw.CfnIntegration(self, "Integration", api_id=api.ref,
            integration_type="AWS_PROXY", integration_uri=fn.function_arn, payload_format_version="2.0", timeout_in_millis=30000)
        for i, route in enumerate(["POST /surveys/decide", "GET /surveys/{id}", "POST /surveys/{id}/responses", "GET /follow-ups", "POST /farmers/me/opt-out"]):
            apigw.CfnRoute(self, "Route" + str(i), api_id=api.ref, route_key=route,
                          target="integrations/" + integration.ref, authorization_type="JWT", authorizer_id=authorizer.ref)
        access = logs.LogGroup(self, "AccessLog", log_group_name="/aws/apigateway/mel-api",
                              retention=logs.RetentionDays.TWO_WEEKS, removal_policy=cdk.RemovalPolicy.RETAIN)
        apigw.CfnStage(self, "DefaultStage", api_id=api.ref, stage_name="$default", auto_deploy=True,
            default_route_settings=apigw.CfnStage.RouteSettingsProperty(throttling_rate_limit=1, throttling_burst_limit=10, detailed_metrics_enabled=True),
            access_log_settings=apigw.CfnStage.AccessLogSettingsProperty(destination_arn=access.log_group_arn,
                format='{"requestId":"$context.requestId","routeKey":"$context.routeKey","status":"$context.status","responseLength":"$context.responseLength"}'))
        fn.add_permission("GatewayInvoke", principal=iam.ServicePrincipal("apigateway.amazonaws.com"),
            source_arn=self.format_arn(service="execute-api", resource=api.ref, resource_name="*/*", arn_format=cdk.ArnFormat.SLASH_RESOURCE_NAME), source_account=self.account)
        publish(self, "api_url", api.attr_api_endpoint)


class Observability(cdk.Stack):
    def __init__(self, scope, id, **kwargs):
        super().__init__(scope, id, **kwargs)
        dashboard = cw.Dashboard(self, "Dashboard", dashboard_name="mel-agent")
        for name in ["DecisionsByRule", "ModelCalls", "ModelTokens", "JudgeVerdicts", "LatencyMs", "CostUsd"]:
            metrics = [cw.Metric(namespace="MelAgent", metric_name=name, statistic="Sum", period=cdk.Duration.minutes(1))]
            if name == "LatencyMs":
                metrics.extend(cw.Metric(namespace="MelAgent", metric_name=name, statistic=p, period=cdk.Duration.minutes(1)) for p in ["p50", "p95"])
            dashboard.add_widgets(cw.GraphWidget(title=name, left=metrics))
        api_id = cdk.Fn.select(0, cdk.Fn.split(".", cdk.Fn.select(1, cdk.Fn.split("https://", read(self, "api_url")))))
        def metric(namespace, name, dimensions, statistic="Sum"):
            return cw.Metric(namespace=namespace, metric_name=name, dimensions_map=dimensions, statistic=statistic, period=cdk.Duration.minutes(1))
        dlq_name = cdk.Fn.select(4, cdk.Fn.split("/", read(self, "followup_dlq_url")))
        dlq_depth = metric("AWS/SQS", "ApproximateNumberOfMessagesVisible", {"QueueName": dlq_name}, "Maximum")
        dashboard.add_widgets(
            cw.GraphWidget(title="Lambda errors and duration", left=[metric("AWS/Lambda", "Errors", {"FunctionName": "mel-api"})],
                right=[metric("AWS/Lambda", "Duration", {"FunctionName": "mel-api"}, "p95")]),
            cw.GraphWidget(title="HTTP API errors", left=[metric("AWS/ApiGateway", n, {"ApiId": api_id}) for n in ["4xx", "5xx"]]),
            cw.GraphWidget(title="DynamoDB throttles", left=[metric("AWS/DynamoDB", n, {"TableName": read(self, "table_name")}) for n in ["ReadThrottleEvents", "WriteThrottleEvents"]]),
            cw.GraphWidget(title="Followup DLQ depth", left=[dlq_depth]))
        cw.Alarm(self, "ModelCallLimit", alarm_name="mel-model-calls-over-60",
            metric=metric("MelAgent", "ModelCalls", {}), threshold=60, evaluation_periods=1,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD, treat_missing_data=cw.TreatMissingData.NOT_BREACHING)
        cw.Alarm(self, "DlqNonEmpty", alarm_name="mel-followup-dlq-nonempty", metric=dlq_depth, threshold=1,
            evaluation_periods=1, comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING)
        if os.environ.get("BUDGET_EMAIL"):
            budgets.CfnBudget(self, "Budget", budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name="mel-agent-monthly", budget_type="COST", time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(amount=50, unit="USD"),
                cost_filters={"TagKeyValue": ["user:Project$MelAgent"]}),
                notifications_with_subscribers=[budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(comparison_operator="GREATER_THAN", notification_type="ACTUAL", threshold=80, threshold_type="PERCENTAGE"),
                    subscribers=[budgets.CfnBudget.SubscriberProperty(address=os.environ["BUDGET_EMAIL"], subscription_type="EMAIL")])])
        publish(self, "dashboard_name", dashboard.dashboard_name)


app = cdk.App()
env = cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region=REGION)
data = Data(app, "MelAgent-Data", env=env)
secrets_stack = Secrets(app, "MelAgent-Secrets", env=env)
auth = Auth(app, "MelAgent-Auth", env=env)
agent = Agent(app, "MelAgent-Agent", env=env)
api = Api(app, "MelAgent-Api", env=env)
obs = Observability(app, "MelAgent-Obs", env=env)
for dependency in [data, secrets_stack]:
    agent.add_dependency(dependency)
for dependency in [data, secrets_stack, auth, agent]:
    api.add_dependency(dependency)
for dependency in [data, api]:
    obs.add_dependency(dependency)
cdk.Tags.of(app).add("Project", "MelAgent")
for stack in [data, secrets_stack, auth, agent, api, obs]:
    cdk.Aspects.of(stack).add(AwsSolutionsChecks(verbose=True))
app.synth()
