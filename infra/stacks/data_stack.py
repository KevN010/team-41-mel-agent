from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    CfnOutput,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_sqs as sqs,
)
from cdk_nag import NagSuppressions
from constructs import Construct


class DataStack(Stack):
    """Ledger table, artifact/evidence bucket, simulator bucket + CloudFront, follow-up queue."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- DynamoDB single-table ledger -------------------------------------------------
        self.table = dynamodb.Table(
            self,
            "LedgerTable",
            table_name="mel-ledger",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="sk", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
            time_to_live_attribute="ttl",
            removal_policy=RemovalPolicy.RETAIN,
        )

        # --- S3 -----------------------------------------------------------------------------
        # Access-log bucket. Receives S3 server access logs and CloudFront standard logs.
        # CloudFront standard logging needs ACLs, hence BUCKET_OWNER_PREFERRED on this bucket only.
        self.logs_bucket = s3.Bucket(
            self,
            "AccessLogsBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_PREFERRED,
            lifecycle_rules=[s3.LifecycleRule(expiration=Duration.days(90))],
            removal_policy=RemovalPolicy.RETAIN,
        )
        NagSuppressions.add_resource_suppressions(
            self.logs_bucket,
            [
                {
                    "id": "AwsSolutions-S1",
                    "reason": "This is the access-log sink bucket; logging it to itself or a further bucket adds no value.",
                }
            ],
        )

        self.artifacts_bucket = s3.Bucket(
            self,
            "ArtifactsBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            versioned=True,
            server_access_logs_bucket=self.logs_bucket,
            server_access_logs_prefix="artifacts/",
            removal_policy=RemovalPolicy.RETAIN,
        )

        self.sim_bucket = s3.Bucket(
            self,
            "SimBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            server_access_logs_bucket=self.logs_bucket,
            server_access_logs_prefix="sim/",
            removal_policy=RemovalPolicy.RETAIN,
        )

        security_headers = cloudfront.ResponseHeadersPolicy(
            self,
            "SimSecurityHeaders",
            security_headers_behavior=cloudfront.ResponseSecurityHeadersBehavior(
                strict_transport_security=cloudfront.ResponseHeadersStrictTransportSecurity(
                    access_control_max_age=Duration.days(365),
                    include_subdomains=True,
                    override=True,
                ),
                content_type_options=cloudfront.ResponseHeadersContentTypeOptions(override=True),
                frame_options=cloudfront.ResponseHeadersFrameOptions(
                    frame_option=cloudfront.HeadersFrameOption.DENY, override=True
                ),
                referrer_policy=cloudfront.ResponseHeadersReferrerPolicy(
                    referrer_policy=cloudfront.HeadersReferrerPolicy.NO_REFERRER, override=True
                ),
            ),
        )

        # S3BucketOrigin.with_origin_access_control creates an OAC and a bucket policy that only
        # allows cloudfront.amazonaws.com for this distribution. The bucket stays private.
        self.distribution = cloudfront.Distribution(
            self,
            "SimDistribution",
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(self.sim_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                response_headers_policy=security_headers,
            ),
            enable_logging=True,
            log_bucket=self.logs_bucket,
            log_file_prefix="cloudfront/",
        )
        NagSuppressions.add_resource_suppressions(
            self.distribution,
            [
                {
                    "id": "AwsSolutions-CFR1",
                    "reason": "Geo restriction not required: synthetic demo content, no regional licensing constraint.",
                },
                {
                    "id": "AwsSolutions-CFR2",
                    "reason": "WAF not attached: static simulator page with no data; WAF adds fixed monthly cost for a 5-hour hackathon.",
                },
                {
                    "id": "AwsSolutions-CFR4",
                    "reason": "Default *.cloudfront.net certificate cannot enforce TLS 1.2 minimum; needs a custom domain and ACM cert which is out of scope.",
                },
            ],
        )

        # --- SQS follow-up queue + DLQ --------------------------------------------------------
        self.followup_dlq = sqs.Queue(
            self,
            "FollowUpDlq",
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            enforce_ssl=True,
            retention_period=Duration.days(14),
        )
        self.followup_queue = sqs.Queue(
            self,
            "FollowUpQueue",
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            enforce_ssl=True,
            visibility_timeout=Duration.seconds(60),
            dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=3, queue=self.followup_dlq),
        )

        CfnOutput(self, "LedgerTableName", value=self.table.table_name)
        CfnOutput(self, "ArtifactsBucketName", value=self.artifacts_bucket.bucket_name)
        CfnOutput(self, "SimBucketName", value=self.sim_bucket.bucket_name)
        CfnOutput(self, "SimUrl", value=f"https://{self.distribution.distribution_domain_name}")
        CfnOutput(self, "FollowUpQueueUrl", value=self.followup_queue.queue_url)
