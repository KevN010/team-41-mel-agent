# MelAgent infrastructure

Recorded 2026-11-05T11:54:31.340588+00:00; account 423964648384; region us-west-2.

Deployment status: CDK stacks deployed; see live smoke evidence below.

## Interface and limitations

- All cross-stack values use deploy-time SSM String parameters; stack dependencies determine deployment order.
- HTTP API native request validation is unavailable in AWS. The user approved retaining HTTP API with application payload validation. Reference: https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-open-api.html
- Project=MelAgent tags are applied to all taggable resources. AWS child resources without tagging support inherit ownership through their parent/stack.
- Jev is initialized to REPLACE_ME; a human must set its value. No secret value is queried for this report.
- BUDGET_EMAIL was unset; the optional budget was skipped.
- CloudWatch alarms are visible in the console; no notification destination was requested for them.
- Lambda and container packages select application code when the matching handler/agent exists, otherwise isolated build stubs. Runtime dependencies live in infra/lambda-requirements.txt.
- DynamoDB describe-table reports SSE; PITR is reported by describe-continuous-backups, not describe-table.

## Endpoints

API: https://ib6pvb874g.execute-api.us-west-2.amazonaws.com

Simulator: https://d3eb8n1ufruyva.cloudfront.net

The simulator bucket is private and ready for static files; simulator content is owned by the application team.

## CDK deployment summary

```text
AI agent detected
[WARNING] aws-cdk-lib.Stack#addDependency is deprecated, and will be removed in the next major release.
  Use `addStackDependency` instead.
/private/var/folders/ls/jn99vl0j4r96_k4c326l1z9h0000gn/T/tmpjpely6nq/lib/program.js:1:63996
WARNING Ignoring 'minimumProtocolVersion': it has no effect without a custom 'certificate'. The distribution uses the CloudFront default certificate, whose security policy is fixed at TLSv1. (Construct Annotations)
   MelAgent-Data/SimulatorCdn
   Acknowledge with 'Annotation::@aws-cdk/aws-cloudfront:minimumProtocolVersionWithoutCertificate'

✨  Synthesis time: 1.96s

MelAgent-Data: start: Building MelAgent-Data Template
MelAgent-Data: success: Built MelAgent-Data Template
MelAgent-Secrets: start: Building MelAgent-Secrets Template
MelAgent-Secrets: success: Built MelAgent-Secrets Template
MelAgent-Auth: start: Building MelAgent-Auth Template
MelAgent-Auth: success: Built MelAgent-Auth Template
MelAgent-Agent: start: Building MelAgent-Agent Template
MelAgent-Agent: success: Built MelAgent-Agent Template
MelAgent-Api: start: Building Handler/Code
MelAgent-Api: success: Built Handler/Code
MelAgent-Api: start: Building MelAgent-Api Template
MelAgent-Api: success: Built MelAgent-Api Template
MelAgent-Obs: start: Building MelAgent-Obs Template
MelAgent-Obs: success: Built MelAgent-Obs Template
MelAgent-Data: start: Publishing MelAgent-Data Template (423964648384-us-west-2-9ce8c2c0)
MelAgent-Secrets: start: Publishing MelAgent-Secrets Template (423964648384-us-west-2-78428aa3)
MelAgent-Auth: start: Publishing MelAgent-Auth Template (423964648384-us-west-2-31284752)
MelAgent-Secrets: success: Published MelAgent-Secrets Template (423964648384-us-west-2-78428aa3)
MelAgent-Secrets
MelAgent-Data: success: Published MelAgent-Data Template (423964648384-us-west-2-9ce8c2c0)
MelAgent-Data
MelAgent-Auth: success: Published MelAgent-Auth Template (423964648384-us-west-2-31284752)
MelAgent-Auth
MelAgent-Secrets: creating CloudFormation changeset...
MelAgent-Data: creating CloudFormation changeset...
MelAgent-Auth: creating CloudFormation changeset...
MelAgent-Secrets: deploying... [1/6]
MelAgent-Auth: deploying... [2/6]
MelAgent-Data: deploying... [3/6]

✅  MelAgent-Secrets

✨  Deployment time: 12.12s

Stack ARN:
arn:aws:cloudformation:us-west-2:423964648384:stack/MelAgent-Secrets/d5a727e0-d90d-11f1-974b-02ffd50da131

✅  MelAgent-Auth

✨  Deployment time: 12.25s

Stack ARN:
arn:aws:cloudformation:us-west-2:423964648384:stack/MelAgent-Auth/d5b2c0a0-d90d-11f1-ac24-06d1b48a55c5

✅  MelAgent-Data

✨  Deployment time: 227.21s

Stack ARN:
arn:aws:cloudformation:us-west-2:423964648384:stack/MelAgent-Data/d5ad6970-d90d-11f1-aa3b-0affcd16f033
MelAgent-Agent: start: Publishing MelAgent-Agent Template (423964648384-us-west-2-30e4da1e)
MelAgent-Agent: success: Published MelAgent-Agent Template (423964648384-us-west-2-30e4da1e)
MelAgent-Agent
MelAgent-Agent: creating CloudFormation changeset...
MelAgent-Agent: deploying... [4/6]

✅  MelAgent-Agent

✨  Deployment time: 43.64s

Stack ARN:
arn:aws:cloudformation:us-west-2:423964648384:stack/MelAgent-Agent/61e0ad80-d90e-11f1-a774-066ad4150793
MelAgent-Api: start: Publishing Handler/Code (423964648384-us-west-2-f83b283b)
MelAgent-Api: start: Publishing MelAgent-Api Template (423964648384-us-west-2-35ec0622)
MelAgent-Api: success: Published Handler/Code (423964648384-us-west-2-f83b283b)
MelAgent-Api: success: Published MelAgent-Api Template (423964648384-us-west-2-35ec0622)
MelAgent-Api
MelAgent-Api: creating CloudFormation changeset...
MelAgent-Api: deploying... [5/6]

✅  MelAgent-Api

✨  Deployment time: 33.38s

Stack ARN:
arn:aws:cloudformation:us-west-2:423964648384:stack/MelAgent-Api/807692a0-d90e-11f1-ba63-0609bd750f8f
MelAgent-Obs: start: Publishing MelAgent-Obs Template (423964648384-us-west-2-916364a4)
MelAgent-Obs: success: Published MelAgent-Obs Template (423964648384-us-west-2-916364a4)
MelAgent-Obs
MelAgent-Obs: creating CloudFormation changeset...
MelAgent-Obs: deploying... [6/6]

✅  MelAgent-Obs

✨  Deployment time: 12.18s

Stack ARN:
arn:aws:cloudformation:us-west-2:423964648384:stack/MelAgent-Obs/98edb200-d90e-11f1-8bef-06f5d0a445c3

✨  Total time: 351.25s


```

## SSM parameters

`aws ssm get-parameters-by-path --path /mel --region us-west-2`

```json
{
    "Parameters": [
        {
            "Name": "/mel/agent_role_arn",
            "Type": "String",
            "Value": "arn:aws:iam::423964648384:role/mel-agent-role",
            "Version": 1,
            "LastModifiedDate": "2026-11-05T06:45:50.657000-05:00",
            "ARN": "arn:aws:ssm:us-west-2:423964648384:parameter/mel/agent_role_arn",
            "DataType": "text"
        },
        {
            "Name": "/mel/agent_runtime_arn",
            "Type": "String",
            "Value": "arn:aws:bedrock-agentcore:us-west-2:423964648384:runtime/mel_agent-vUpOFqHRb4",
            "Version": 2,
            "LastModifiedDate": "2026-11-05T06:51:03.087000-05:00",
            "ARN": "arn:aws:ssm:us-west-2:423964648384:parameter/mel/agent_runtime_arn",
            "DataType": "text"
        },
        {
            "Name": "/mel/api_url",
            "Type": "String",
            "Value": "https://ib6pvb874g.execute-api.us-west-2.amazonaws.com",
            "Version": 1,
            "LastModifiedDate": "2026-11-05T06:46:25.887000-05:00",
            "ARN": "arn:aws:ssm:us-west-2:423964648384:parameter/mel/api_url",
            "DataType": "text"
        },
        {
            "Name": "/mel/artifacts_bucket",
            "Type": "String",
            "Value": "melagent-data-artifacts82dd59a1-a242w2kuxstu",
            "Version": 1,
            "LastModifiedDate": "2026-11-05T06:42:07.972000-05:00",
            "ARN": "arn:aws:ssm:us-west-2:423964648384:parameter/mel/artifacts_bucket",
            "DataType": "text"
        },
        {
            "Name": "/mel/ecr_repo_uri",
            "Type": "String",
            "Value": "423964648384.dkr.ecr.us-west-2.amazonaws.com/mel-agent",
            "Version": 1,
            "LastModifiedDate": "2026-11-05T06:45:33.656000-05:00",
            "ARN": "arn:aws:ssm:us-west-2:423964648384:parameter/mel/ecr_repo_uri",
            "DataType": "text"
        },
        {
            "Name": "/mel/jev_secret_arn",
            "Type": "String",
            "Value": "arn:aws:secretsmanager:us-west-2:423964648384:secret:mel/jev-api-key-twLWqn",
            "Version": 1,
            "LastModifiedDate": "2026-11-05T06:41:40.404000-05:00",
            "ARN": "arn:aws:ssm:us-west-2:423964648384:parameter/mel/jev_secret_arn",
            "DataType": "text"
        },
        {
            "Name": "/mel/sim_bucket",
            "Type": "String",
            "Value": "melagent-data-simulatorb4e5c957-gepubrdlyxfv",
            "Version": 1,
            "LastModifiedDate": "2026-11-05T06:42:07.765000-05:00",
            "ARN": "arn:aws:ssm:us-west-2:423964648384:parameter/mel/sim_bucket",
            "DataType": "text"
        },
        {
            "Name": "/mel/table_name",
            "Type": "String",
            "Value": "mel-ledger",
            "Version": 1,
            "LastModifiedDate": "2026-11-05T06:42:12.630000-05:00",
            "ARN": "arn:aws:ssm:us-west-2:423964648384:parameter/mel/table_name",
            "DataType": "text"
        },
        {
            "Name": "/mel/user_pool_client_id",
            "Type": "String",
            "Value": "77e4o94o10nau3utvc9tvjogto",
            "Version": 1,
            "LastModifiedDate": "2026-11-05T06:41:41.213000-05:00",
            "ARN": "arn:aws:ssm:us-west-2:423964648384:parameter/mel/user_pool_client_id",
            "DataType": "text"
        },
        {
            "Name": "/mel/user_pool_id",
            "Type": "String",
            "Value": "us-west-2_9ZHQYVRnk",
            "Version": 1,
            "LastModifiedDate": "2026-11-05T06:41:39.571000-05:00",
            "ARN": "arn:aws:ssm:us-west-2:423964648384:parameter/mel/user_pool_id",
            "DataType": "text"
        },
        {
            "Name": "/mel/dashboard_name",
            "Type": "String",
            "Value": "mel-agent",
            "Version": 1,
            "LastModifiedDate": "2026-11-05T06:47:07.882000-05:00",
            "ARN": "arn:aws:ssm:us-west-2:423964648384:parameter/mel/dashboard_name",
            "DataType": "text"
        },
        {
            "Name": "/mel/followup_dlq_url",
            "Type": "String",
            "Value": "https://sqs.us-west-2.amazonaws.com/423964648384/mel-followups-dlq",
            "Version": 1,
            "LastModifiedDate": "2026-11-05T06:41:38.999000-05:00",
            "ARN": "arn:aws:ssm:us-west-2:423964648384:parameter/mel/followup_dlq_url",
            "DataType": "text"
        },
        {
            "Name": "/mel/followup_queue_url",
            "Type": "String",
            "Value": "https://sqs.us-west-2.amazonaws.com/423964648384/mel-followups",
            "Version": 1,
            "LastModifiedDate": "2026-11-05T06:41:40.174000-05:00",
            "ARN": "arn:aws:ssm:us-west-2:423964648384:parameter/mel/followup_queue_url",
            "DataType": "text"
        },
        {
            "Name": "/mel/sim_url",
            "Type": "String",
            "Value": "https://d3eb8n1ufruyva.cloudfront.net",
            "Version": 1,
            "LastModifiedDate": "2026-11-05T06:42:13.942000-05:00",
            "ARN": "arn:aws:ssm:us-west-2:423964648384:parameter/mel/sim_url",
            "DataType": "text"
        }
    ]
}
```

## Resource inventory

Includes the CDK bootstrap stack and six application stacks. AWS resources without a standalone ARN are identified by their physical ID and parent ARN where applicable. CloudFront ARN formats follow https://docs.aws.amazon.com/service-authorization/latest/reference/list_cloudfront.html.

| Stack / logical ID | Type | Physical name / ID | ARN / parent |
|---|---|---|---|
| CDKToolkit / CdkBootstrapVersion | AWS::SSM::Parameter | `/cdk-bootstrap/hnb659fds/version` | `arn:aws:ssm:us-west-2:423964648384:parameter/cdk-bootstrap/hnb659fds/version` |
| CDKToolkit / CloudFormationExecutionRole | AWS::IAM::Role | `cdk-hnb659fds-cfn-exec-role-423964648384-us-west-2` | `arn:aws:iam::423964648384:role/cdk-hnb659fds-cfn-exec-role-423964648384-us-west-2` |
| CDKToolkit / ContainerAssetsRepository | AWS::ECR::Repository | `cdk-hnb659fds-container-assets-423964648384-us-west-2` | `arn:aws:ecr:us-west-2:423964648384:repository/cdk-hnb659fds-container-assets-423964648384-us-west-2` |
| CDKToolkit / DeploymentActionRole | AWS::IAM::Role | `cdk-hnb659fds-deploy-role-423964648384-us-west-2` | `arn:aws:iam::423964648384:role/cdk-hnb659fds-deploy-role-423964648384-us-west-2` |
| CDKToolkit / FilePublishingRole | AWS::IAM::Role | `cdk-hnb659fds-file-publishing-role-423964648384-us-west-2` | `arn:aws:iam::423964648384:role/cdk-hnb659fds-file-publishing-role-423964648384-us-west-2` |
| CDKToolkit / FilePublishingRoleDefaultPolicy | AWS::IAM::Policy | `CDKTo-FileP-ADZv5Y6Cf4eA` | `arn:aws:iam::423964648384:role/mel-agent-role (inline policy CDKTo-FileP-ADZv5Y6Cf4eA)` |
| CDKToolkit / ImagePublishingRole | AWS::IAM::Role | `cdk-hnb659fds-image-publishing-role-423964648384-us-west-2` | `arn:aws:iam::423964648384:role/cdk-hnb659fds-image-publishing-role-423964648384-us-west-2` |
| CDKToolkit / ImagePublishingRoleDefaultPolicy | AWS::IAM::Policy | `CDKTo-Image-QFUAshTLkjFo` | `arn:aws:iam::423964648384:role/mel-agent-role (inline policy CDKTo-Image-QFUAshTLkjFo)` |
| CDKToolkit / LookupRole | AWS::IAM::Role | `cdk-hnb659fds-lookup-role-423964648384-us-west-2` | `arn:aws:iam::423964648384:role/cdk-hnb659fds-lookup-role-423964648384-us-west-2` |
| CDKToolkit / StagingBucket | AWS::S3::Bucket | `cdk-hnb659fds-assets-423964648384-us-west-2` | `arn:aws:s3:::cdk-hnb659fds-assets-423964648384-us-west-2` |
| CDKToolkit / StagingBucketPolicy | AWS::S3::BucketPolicy | `cdk-hnb659fds-assets-423964648384-us-west-2` | `arn:aws:s3:::cdk-hnb659fds-assets-423964648384-us-west-2 (bucket policy)` |
| MelAgent-Data / AccessLogs8B620ECA | AWS::S3::Bucket | `melagent-data-accesslogs8b620eca-pbuxyfinkfbg` | `arn:aws:s3:::melagent-data-accesslogs8b620eca-pbuxyfinkfbg` |
| MelAgent-Data / AccessLogsPolicyABDC4D2D | AWS::S3::BucketPolicy | `melagent-data-accesslogs8b620eca-pbuxyfinkfbg` | `arn:aws:s3:::melagent-data-accesslogs8b620eca-pbuxyfinkfbg (bucket policy)` |
| MelAgent-Data / Artifacts82DD59A1 | AWS::S3::Bucket | `melagent-data-artifacts82dd59a1-a242w2kuxstu` | `arn:aws:s3:::melagent-data-artifacts82dd59a1-a242w2kuxstu` |
| MelAgent-Data / ArtifactsPolicy6E9058CC | AWS::S3::BucketPolicy | `melagent-data-artifacts82dd59a1-a242w2kuxstu` | `arn:aws:s3:::melagent-data-artifacts82dd59a1-a242w2kuxstu (bucket policy)` |
| MelAgent-Data / CDKMetadata | AWS::CDK::Metadata | `d5ad6970-d90d-11f1-aa3b-0affcd16f033` | `No standalone ARN; see parent resource and physical ID` |
| MelAgent-Data / FollowupDlqAA7B3484 | AWS::SQS::Queue | `https://sqs.us-west-2.amazonaws.com/423964648384/mel-followups-dlq` | `arn:aws:sqs:us-west-2:423964648384:mel-followups-dlq` |
| MelAgent-Data / FollowupDlqPolicy54AFF54B | AWS::SQS::QueuePolicy | `MelAgent-Data-FollowupDlqPolicy54AFF54B-OJ6XDhux4SFY` | `Policy attached to queue ARNs above; no standalone ARN` |
| MelAgent-Data / Followups74D9167A | AWS::SQS::Queue | `https://sqs.us-west-2.amazonaws.com/423964648384/mel-followups` | `arn:aws:sqs:us-west-2:423964648384:mel-followups` |
| MelAgent-Data / FollowupsPolicyAFBBC02A | AWS::SQS::QueuePolicy | `MelAgent-Data-FollowupsPolicyAFBBC02A-GXccqxy76m9N` | `Policy attached to queue ARNs above; no standalone ARN` |
| MelAgent-Data / LedgerB7379752 | AWS::DynamoDB::Table | `mel-ledger` | `arn:aws:dynamodb:us-west-2:423964648384:table/mel-ledger` |
| MelAgent-Data / ParamArtifactsBucket200341BD | AWS::SSM::Parameter | `/mel/artifacts_bucket` | `arn:aws:ssm:us-west-2:423964648384:parameter/mel/artifacts_bucket` |
| MelAgent-Data / ParamFollowupDlqUrl3F779ECB | AWS::SSM::Parameter | `/mel/followup_dlq_url` | `arn:aws:ssm:us-west-2:423964648384:parameter/mel/followup_dlq_url` |
| MelAgent-Data / ParamFollowupQueueUrlD2430F9F | AWS::SSM::Parameter | `/mel/followup_queue_url` | `arn:aws:ssm:us-west-2:423964648384:parameter/mel/followup_queue_url` |
| MelAgent-Data / ParamSimBucketF9FC597E | AWS::SSM::Parameter | `/mel/sim_bucket` | `arn:aws:ssm:us-west-2:423964648384:parameter/mel/sim_bucket` |
| MelAgent-Data / ParamSimUrl46D540C5 | AWS::SSM::Parameter | `/mel/sim_url` | `arn:aws:ssm:us-west-2:423964648384:parameter/mel/sim_url` |
| MelAgent-Data / ParamTableName3CC20FA3 | AWS::SSM::Parameter | `/mel/table_name` | `arn:aws:ssm:us-west-2:423964648384:parameter/mel/table_name` |
| MelAgent-Data / SimulatorB4E5C957 | AWS::S3::Bucket | `melagent-data-simulatorb4e5c957-gepubrdlyxfv` | `arn:aws:s3:::melagent-data-simulatorb4e5c957-gepubrdlyxfv` |
| MelAgent-Data / SimulatorCdnC5AEB59A | AWS::CloudFront::Distribution | `EAI5KCKEHI4VH` | `arn:aws:cloudfront::423964648384:distribution/EAI5KCKEHI4VH` |
| MelAgent-Data / SimulatorCdnOrigin1S3OriginAccessControlA4B6113A | AWS::CloudFront::OriginAccessControl | `EDW6NWLQJU5XY` | `arn:aws:cloudfront::423964648384:origin-access-control/EDW6NWLQJU5XY` |
| MelAgent-Data / SimulatorPolicyDF7A4A93 | AWS::S3::BucketPolicy | `melagent-data-simulatorb4e5c957-gepubrdlyxfv` | `arn:aws:s3:::melagent-data-simulatorb4e5c957-gepubrdlyxfv (bucket policy)` |
| MelAgent-Secrets / CDKMetadata | AWS::CDK::Metadata | `d5a727e0-d90d-11f1-974b-02ffd50da131` | `No standalone ARN; see parent resource and physical ID` |
| MelAgent-Secrets / JevApiKey915F8452 | AWS::SecretsManager::Secret | `arn:aws:secretsmanager:us-west-2:423964648384:secret:mel/jev-api-key-twLWqn` | `arn:aws:secretsmanager:us-west-2:423964648384:secret:mel/jev-api-key-twLWqn` |
| MelAgent-Secrets / ParamJevSecretArnD3C2F495 | AWS::SSM::Parameter | `/mel/jev_secret_arn` | `arn:aws:ssm:us-west-2:423964648384:parameter/mel/jev_secret_arn` |
| MelAgent-Auth / CDKMetadata | AWS::CDK::Metadata | `d5b2c0a0-d90d-11f1-ac24-06d1b48a55c5` | `No standalone ARN; see parent resource and physical ID` |
| MelAgent-Auth / ParamUserPoolClientIdA24E4B5C | AWS::SSM::Parameter | `/mel/user_pool_client_id` | `arn:aws:ssm:us-west-2:423964648384:parameter/mel/user_pool_client_id` |
| MelAgent-Auth / ParamUserPoolId52EC2677 | AWS::SSM::Parameter | `/mel/user_pool_id` | `arn:aws:ssm:us-west-2:423964648384:parameter/mel/user_pool_id` |
| MelAgent-Auth / Users0A0EEA89 | AWS::Cognito::UserPool | `us-west-2_9ZHQYVRnk` | `arn:aws:cognito-idp:us-west-2:423964648384:userpool/us-west-2_9ZHQYVRnk` |
| MelAgent-Auth / UsersApplication8D5D19B7 | AWS::Cognito::UserPoolClient | `77e4o94o10nau3utvc9tvjogto` | `arn:aws:cognito-idp:us-west-2:423964648384:userpool/us-west-2_9ZHQYVRnk (client has no standalone ARN)` |
| MelAgent-Agent / CDKMetadata | AWS::CDK::Metadata | `61e0ad80-d90e-11f1-a774-066ad4150793` | `No standalone ARN; see parent resource and physical ID` |
| MelAgent-Agent / Container97526FE1 | AWS::ECR::Repository | `mel-agent` | `arn:aws:ecr:us-west-2:423964648384:repository/mel-agent` |
| MelAgent-Agent / ExecutionRole605A040B | AWS::IAM::Role | `mel-agent-role` | `arn:aws:iam::423964648384:role/mel-agent-role` |
| MelAgent-Agent / ParamAgentRoleArn051CD94D | AWS::SSM::Parameter | `/mel/agent_role_arn` | `arn:aws:ssm:us-west-2:423964648384:parameter/mel/agent_role_arn` |
| MelAgent-Agent / ParamAgentRuntimeArnDE0289C6 | AWS::SSM::Parameter | `/mel/agent_runtime_arn` | `arn:aws:ssm:us-west-2:423964648384:parameter/mel/agent_runtime_arn` |
| MelAgent-Agent / ParamEcrRepoUri40C16983 | AWS::SSM::Parameter | `/mel/ecr_repo_uri` | `arn:aws:ssm:us-west-2:423964648384:parameter/mel/ecr_repo_uri` |
| MelAgent-Agent / RuntimePolicy8DEBCE9F | AWS::IAM::Policy | `MelAg-Runti-KbpGzjp3nElZ` | `arn:aws:iam::423964648384:role/mel-agent-role (inline policy MelAg-Runti-KbpGzjp3nElZ)` |
| MelAgent-Api / AccessLogD598EBE9 | AWS::Logs::LogGroup | `/aws/apigateway/mel-api` | `arn:aws:logs:us-west-2:423964648384:log-group:/aws/apigateway/mel-api` |
| MelAgent-Api / CDKMetadata | AWS::CDK::Metadata | `807692a0-d90e-11f1-ba63-0609bd750f8f` | `No standalone ARN; see parent resource and physical ID` |
| MelAgent-Api / DefaultStage | AWS::ApiGatewayV2::Stage | `$default` | `arn:aws:apigateway:us-west-2::/apis/ib6pvb874g/stages/$default` |
| MelAgent-Api / Handler886CB40B | AWS::Lambda::Function | `mel-api` | `arn:aws:lambda:us-west-2:423964648384:function:mel-api` |
| MelAgent-Api / HandlerGatewayInvoke5D2A583F | AWS::Lambda::Permission | `MelAgent-Api-HandlerGatewayInvoke5D2A583F-n3eeo1yh3TIe` | `arn:aws:lambda:us-west-2:423964648384:function:mel-api (resource policy statement)` |
| MelAgent-Api / HttpApi | AWS::ApiGatewayV2::Api | `ib6pvb874g` | `arn:aws:apigateway:us-west-2::/apis/ib6pvb874g` |
| MelAgent-Api / Integration | AWS::ApiGatewayV2::Integration | `v6b9zyf` | `arn:aws:apigateway:us-west-2::/apis/ib6pvb874g/integrations/v6b9zyf` |
| MelAgent-Api / Jwt | AWS::ApiGatewayV2::Authorizer | `9hgzun` | `arn:aws:apigateway:us-west-2::/apis/ib6pvb874g/authorizers/9hgzun` |
| MelAgent-Api / LambdaLog82B85DA7 | AWS::Logs::LogGroup | `/aws/lambda/mel-api` | `arn:aws:logs:us-west-2:423964648384:log-group:/aws/lambda/mel-api` |
| MelAgent-Api / ParamApiUrl02C60F2D | AWS::SSM::Parameter | `/mel/api_url` | `arn:aws:ssm:us-west-2:423964648384:parameter/mel/api_url` |
| MelAgent-Api / Route0 | AWS::ApiGatewayV2::Route | `2dw0fpi` | `arn:aws:apigateway:us-west-2::/apis/ib6pvb874g/routes/2dw0fpi` |
| MelAgent-Api / Route1 | AWS::ApiGatewayV2::Route | `hn1dtl8` | `arn:aws:apigateway:us-west-2::/apis/ib6pvb874g/routes/hn1dtl8` |
| MelAgent-Api / Route2 | AWS::ApiGatewayV2::Route | `jt5f7yb` | `arn:aws:apigateway:us-west-2::/apis/ib6pvb874g/routes/jt5f7yb` |
| MelAgent-Api / Route3 | AWS::ApiGatewayV2::Route | `1y04zb3` | `arn:aws:apigateway:us-west-2::/apis/ib6pvb874g/routes/1y04zb3` |
| MelAgent-Api / Route4 | AWS::ApiGatewayV2::Route | `hnsnhcq` | `arn:aws:apigateway:us-west-2::/apis/ib6pvb874g/routes/hnsnhcq` |
| MelAgent-Obs / CDKMetadata | AWS::CDK::Metadata | `98edb200-d90e-11f1-8bef-06f5d0a445c3` | `No standalone ARN; see parent resource and physical ID` |
| MelAgent-Obs / Dashboard9E4231ED | AWS::CloudWatch::Dashboard | `mel-agent` | `arn:aws:cloudwatch::423964648384:dashboard/mel-agent` |
| MelAgent-Obs / DlqNonEmpty68FBFE0E | AWS::CloudWatch::Alarm | `mel-followup-dlq-nonempty` | `arn:aws:cloudwatch:us-west-2:423964648384:alarm:mel-followup-dlq-nonempty` |
| MelAgent-Obs / ModelCallLimit54E6A130 | AWS::CloudWatch::Alarm | `mel-model-calls-over-60` | `arn:aws:cloudwatch:us-west-2:423964648384:alarm:mel-model-calls-over-60` |
| MelAgent-Obs / ParamDashboardName96794EF0 | AWS::SSM::Parameter | `/mel/dashboard_name` | `arn:aws:ssm:us-west-2:423964648384:parameter/mel/dashboard_name` |
| AgentCore | Runtime | `mel_agent` | `arn:aws:bedrock-agentcore:us-west-2:423964648384:runtime/mel_agent-vUpOFqHRb4` |
| AgentCore | Default endpoint | `DEFAULT` | `arn:aws:bedrock-agentcore:us-west-2:423964648384:runtime/mel_agent-vUpOFqHRb4/runtime-endpoint/DEFAULT` |
| AgentCore | Workload identity | `mel_agent-vUpOFqHRb4` | `arn:aws:bedrock-agentcore:us-west-2:423964648384:workload-identity-directory/default/workload-identity/mel_agent-vUpOFqHRb4` |
| AgentCore | Runtime log group | `/aws/bedrock-agentcore/runtimes/mel_agent-vUpOFqHRb4-DEFAULT` | `arn:aws:logs:us-west-2:423964648384:log-group:/aws/bedrock-agentcore/runtimes/mel_agent-vUpOFqHRb4-DEFAULT` |

## Operational commands

Run from the repository root with AWS credentials exported and the CDK CLI on PATH. Initialize infra/.venv with Python and pip install -r infra/requirements.txt. Commands run with an explicit working directory; the parent shell never changes directory.

```bash
export AWS_DEFAULT_REGION=us-west-2
export PATH="$PWD/infra/.venv/bin:$PATH"
# Retrieve the locally generated seed password without printing it:
export SEED_PASSWORD="$(cat /private/tmp/mel-seed-password)"
python scripts/seed_users.py
aws cognito-idp initiate-auth --region us-west-2 --client-id 77e4o94o10nau3utvc9tvjogto --auth-flow USER_PASSWORD_AUTH --auth-parameters "USERNAME=farmer1,PASSWORD=$SEED_PASSWORD" --query AuthenticationResult.TokenType --output text
# Human-only Jev update; /secure/path/jev-key.txt must contain the key:
aws secretsmanager put-secret-value --region us-west-2 --secret-id mel/jev-api-key --secret-string file:///secure/path/jev-key.txt
# Lambda redeploy:
bash scripts/package_lambda.sh
bash scripts/deploy.sh --lambda-only
# Container redeploy (arm64 build, ECR push, agentcore configure then launch):
python infra/runtime.py
# Complete deployment:
bash scripts/deploy.sh
```

Generated seed credentials remain only in the local mode-0600 file; neither the password nor JWT tokens are included here.

## AgentCore Runtime: launched

```json
{
  "status": "launched",
  "image": "423964648384.dkr.ecr.us-west-2.amazonaws.com/mel-agent:deploy-20261105115033-runtime",
  "runtime_arn": "arn:aws:bedrock-agentcore:us-west-2:423964648384:runtime/mel_agent-vUpOFqHRb4",
  "endpoint_arn": "arn:aws:bedrock-agentcore:us-west-2:423964648384:runtime/mel_agent-vUpOFqHRb4/runtime-endpoint/DEFAULT",
  "runtime_status": "READY"
}
```

## Smoke test output

```text
Seeded farmer1: F-000001
Seeded farmer2: F-000002
Seeded farmer3: F-000003
Seeded farmer4: F-000004
Seeded farmer5: F-000005
aws cognito-idp initiate-auth --region us-west-2 --client-id 77e4o94o10nau3utvc9tvjogto --auth-flow USER_PASSWORD_AUTH --auth-parameters "USERNAME=farmer1,PASSWORD=$SEED_PASSWORD" --query AuthenticationResult.TokenType --output text

SSM: all 14 interface parameters resolve (runtime=arn:aws:bedrock-agentcore:us-west-2:423964648384:runtime/mel_agent-vUpOFqHRb4)
Unauthenticated GET /follow-ups: 401 {"message":"Unauthorized"}
JWT identity claims: sub, custom:farmer_id, custom:org_id verified
Authenticated GET /follow-ups (farmer1): 501 {"error":"not implemented"}
aws dynamodb describe-table: {"TableName": "mel-ledger", "SSEDescription": {"Status": "ENABLED", "SSEType": "KMS", "KMSMasterKeyArn": "arn:aws:kms:us-west-2:423964648384:key/ba67de90-ff4f-4f64-aeb5-a6a3a6929bc2"}}
aws dynamodb describe-continuous-backups: {"PointInTimeRecoveryStatus": "ENABLED", "RecoveryPeriodInDays": 35, "EarliestRestorableDateTime": "2026-11-05 06:42:10-05:00", "LatestRestorableDateTime": "2026-11-05 06:49:27.386000-05:00"}
PASS: live infrastructure smoke checks

Runtime ARN: arn:aws:bedrock-agentcore:us-west-2:423964648384:runtime/mel_agent-vUpOFqHRb4
Runtime status: READY
Runtime environment equals Lambda mel-api environment: PASS (all 9 variables)
Runtime and Lambda execution role match: arn:aws:iam::423964648384:role/mel-agent-role
Deployed image: 423964648384.dkr.ecr.us-west-2.amazonaws.com/mel-agent:deploy-20261105115033-runtime
Image platform: linux/arm64; CMD: python -m mel.agent; PASS
Bedrock AgentCore invoke_agent_runtime: {"status": "stub"}
PASS: live runtime smoke checks
Runtime Project=MelAgent tag: PASS
Default endpoint Project=MelAgent tag: PASS
Workload identity Project=MelAgent tag: PASS
Runtime CloudWatch log group Project=MelAgent and retention 14 days: PASS
PASS: runtime resource ownership and log retention verification

```

## Offline verification

```text
test_lambda_only_deploy_preserves_failure_status (__main__.DeployScriptContract.test_lambda_only_deploy_preserves_failure_status) ... ok
test_lambda_only_deploy_uses_infra_cwd (__main__.DeployScriptContract.test_lambda_only_deploy_uses_infra_cwd) ... ok
test_dynamodb_contract (__main__.InfrastructureContract.test_dynamodb_contract) ... ok
test_iam_actions_are_explicit (__main__.InfrastructureContract.test_iam_actions_are_explicit) ... ok
test_lambda_contract (__main__.InfrastructureContract.test_lambda_contract) ... ok
test_no_cross_stack_exports (__main__.InfrastructureContract.test_no_cross_stack_exports) ... ok
test_parameters_are_exact_strings (__main__.InfrastructureContract.test_parameters_are_exact_strings) ... ok
test_queue_contract (__main__.InfrastructureContract.test_queue_contract) ... ok
test_routes_use_jwt (__main__.InfrastructureContract.test_routes_use_jwt) ... ok
test_s3_and_cloudfront_security (__main__.InfrastructureContract.test_s3_and_cloudfront_security) ... ok
test_stub_response_when_stub_is_packaged (__main__.LambdaPackageContract.test_stub_response_when_stub_is_packaged) ... ok
test_ecr_failure_is_recorded_without_aborting (__main__.RuntimeFailureContract.test_ecr_failure_is_recorded_without_aborting) ... ok
test_existing_runtime_log_group_gets_project_tag_and_fourteen_day_retention (__main__.RuntimeFailureContract.test_existing_runtime_log_group_gets_project_tag_and_fourteen_day_retention) ... ok
test_initial_ssm_failure_is_recorded_by_entrypoint (__main__.RuntimeFailureContract.test_initial_ssm_failure_is_recorded_by_entrypoint) ... ok
test_isolated_docker_auth_preserves_context_endpoint_and_plugins (__main__.RuntimeFailureContract.test_isolated_docker_auth_preserves_context_endpoint_and_plugins) ... ok
test_isolated_docker_auth_respects_explicit_host (__main__.RuntimeFailureContract.test_isolated_docker_auth_respects_explicit_host) ... ok
test_new_runtime_log_group_has_project_tag_and_fourteen_day_retention (__main__.RuntimeFailureContract.test_new_runtime_log_group_has_project_tag_and_fourteen_day_retention) ... ok
test_runtime_tagging_covers_runtime_endpoint_and_workload_identity (__main__.RuntimeFailureContract.test_runtime_tagging_covers_runtime_endpoint_and_workload_identity) ... ok
test_creates_exact_five_identities_without_printing_password (__main__.SeedUsersContract.test_creates_exact_five_identities_without_printing_password) ... ok
test_existing_matching_identities_are_idempotent (__main__.SeedUsersContract.test_existing_matching_identities_are_idempotent) ... ok
test_wrong_immutable_identity_stops_before_password_change (__main__.SeedUsersContract.test_wrong_immutable_identity_stops_before_password_change) ... ok

----------------------------------------------------------------------
Ran 21 tests in 0.445s

OK

```

cdk-nag details and one-line suppression reasons: [NAG.md](NAG.md). Independent test and security review results are recorded in [REVIEW.md](REVIEW.md).
