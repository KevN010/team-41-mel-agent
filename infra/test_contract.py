"""Offline checks against the synthesized infrastructure interface contract."""

import importlib.util
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
ASSEMBLY = ROOT / "infra" / "cdk.out"
PARAMETERS = {
    "/mel/table_name", "/mel/artifacts_bucket", "/mel/sim_bucket", "/mel/sim_url",
    "/mel/followup_queue_url", "/mel/followup_dlq_url", "/mel/user_pool_id",
    "/mel/user_pool_client_id", "/mel/api_url", "/mel/jev_secret_arn",
    "/mel/agent_role_arn", "/mel/ecr_repo_uri", "/mel/agent_runtime_arn",
    "/mel/dashboard_name",
}
ENVIRONMENT = {
    "MEL_REGION", "MEL_TABLE", "MEL_ARTIFACTS_BUCKET", "MEL_FOLLOWUP_QUEUE_URL",
    "MEL_JEV_SECRET_ARN", "MEL_USER_POOL_ID", "MEL_USER_POOL_CLIENT_ID",
    "MEL_MODELS_FILE", "MEL_METRICS_NAMESPACE",
}
ROUTES = {
    "POST /surveys/decide", "GET /surveys/{id}", "POST /surveys/{id}/responses",
    "GET /follow-ups", "POST /farmers/me/opt-out",
}


class InfrastructureContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        templates = sorted(ASSEMBLY.glob("MelAgent-*.template.json"))
        if not templates:
            raise unittest.SkipTest("Run cdk synth before template contract verification")
        cls.templates = {p.stem: json.loads(p.read_text()) for p in templates}
        cls.resources = [r for t in cls.templates.values() for r in t.get("Resources", {}).values()]

    def resources_of_type(self, resource_type):
        return [r["Properties"] for r in self.resources if r["Type"] == resource_type]

    def test_parameters_are_exact_strings(self):
        parameters = self.resources_of_type("AWS::SSM::Parameter")
        self.assertEqual({p["Name"] for p in parameters}, PARAMETERS)
        self.assertEqual(len(parameters), len(PARAMETERS))
        self.assertTrue(all(p["Type"] == "String" for p in parameters))

    def test_dynamodb_contract(self):
        table, = self.resources_of_type("AWS::DynamoDB::Table")
        self.assertEqual(table["TableName"], "mel-ledger")
        self.assertEqual(table["BillingMode"], "PAY_PER_REQUEST")
        self.assertEqual(table["KeySchema"], [{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}])
        self.assertEqual({a["AttributeName"]: a["AttributeType"] for a in table["AttributeDefinitions"]}, {"pk": "S", "sk": "S", "gsi1pk": "S", "gsi1sk": "S"})
        gsi, = table["GlobalSecondaryIndexes"]
        self.assertEqual(gsi["IndexName"], "GSI1")
        self.assertEqual(gsi["KeySchema"], [{"AttributeName": "gsi1pk", "KeyType": "HASH"}, {"AttributeName": "gsi1sk", "KeyType": "RANGE"}])
        self.assertTrue(table["SSESpecification"]["SSEEnabled"])
        self.assertTrue(table["PointInTimeRecoverySpecification"]["PointInTimeRecoveryEnabled"])
        self.assertEqual(table["TimeToLiveSpecification"], {"AttributeName": "ttl", "Enabled": True})

    def test_s3_and_cloudfront_security(self):
        buckets = self.resources_of_type("AWS::S3::Bucket")
        self.assertGreaterEqual(len(buckets), 2)
        for bucket in buckets:
            self.assertTrue(all(bucket["PublicAccessBlockConfiguration"].values()))
            encryption = bucket["BucketEncryption"]["ServerSideEncryptionConfiguration"]
            self.assertTrue(all(e["ServerSideEncryptionByDefault"]["SSEAlgorithm"] == "AES256" for e in encryption))
        oac, = self.resources_of_type("AWS::CloudFront::OriginAccessControl")
        self.assertEqual(oac["OriginAccessControlConfig"]["SigningBehavior"], "always")
        distribution, = self.resources_of_type("AWS::CloudFront::Distribution")
        self.assertIn(distribution["DistributionConfig"]["DefaultCacheBehavior"]["ViewerProtocolPolicy"], ["redirect-to-https", "https-only"])

    def test_routes_use_jwt(self):
        routes = self.resources_of_type("AWS::ApiGatewayV2::Route")
        self.assertEqual({r["RouteKey"] for r in routes}, ROUTES)
        self.assertTrue(all(r["AuthorizationType"] == "JWT" and r.get("AuthorizerId") for r in routes))
        authorizer, = self.resources_of_type("AWS::ApiGatewayV2::Authorizer")
        self.assertEqual(authorizer["AuthorizerType"], "JWT")

    def test_lambda_contract(self):
        functions = self.resources_of_type("AWS::Lambda::Function")
        function, = [f for f in functions if f.get("FunctionName") == "mel-api"]
        self.assertEqual(function["Handler"], "mel.api.handler.lambda_handler")
        self.assertEqual(function["Runtime"], "python3.12")
        self.assertEqual(function["Architectures"], ["arm64"])
        self.assertEqual(function["MemorySize"], 512)
        self.assertEqual(function["Timeout"], 30)
        env = function["Environment"]["Variables"]
        self.assertEqual(set(env), ENVIRONMENT)
        self.assertEqual(env["MEL_REGION"], "us-west-2")
        self.assertEqual(env["MEL_MODELS_FILE"], "models/models.yaml")
        self.assertEqual(env["MEL_METRICS_NAMESPACE"], "MelAgent")

    def test_no_cross_stack_exports(self):
        for name, template in self.templates.items():
            with self.subTest(stack=name):
                self.assertNotIn("Fn::ImportValue", json.dumps(template))
                self.assertTrue(all("Export" not in o for o in template.get("Outputs", {}).values()))

    def test_iam_actions_are_explicit(self):
        for policy in self.resources_of_type("AWS::IAM::Policy") + self.resources_of_type("AWS::IAM::ManagedPolicy"):
            statements = policy["PolicyDocument"]["Statement"]
            for statement in statements:
                actions = statement.get("Action", [])
                if isinstance(actions, str):
                    actions = [actions]
                self.assertTrue(all("*" not in action for action in actions), actions)

    def test_queue_contract(self):
        queues = {q["QueueName"]: q for q in self.resources_of_type("AWS::SQS::Queue")}
        self.assertTrue(queues["mel-followups"].get("SqsManagedSseEnabled") or queues["mel-followups"].get("KmsMasterKeyId"))
        self.assertEqual(queues["mel-followups"]["RedrivePolicy"]["maxReceiveCount"], 3)
        self.assertEqual(queues["mel-followups-dlq"]["MessageRetentionPeriod"], 1209600)


class LambdaPackageContract(unittest.TestCase):
    def test_stub_response_when_stub_is_packaged(self):
        handler = ROOT / "build" / "lambda" / "mel" / "api" / "handler.py"
        if not handler.exists():
            self.skipTest("Lambda package not built")
        if (ROOT / "mel" / "api" / "handler.py").exists():
            self.skipTest("Application handler has arrived; stub-only check does not apply")
        spec = importlib.util.spec_from_file_location("packaged_stub_handler", handler)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        response = module.lambda_handler({}, None)
        self.assertEqual(response["statusCode"], 501)
        self.assertEqual(json.loads(response["body"]), {"error": "not implemented"})


def load_script(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SeedUsersContract(unittest.TestCase):
    def setUp(self):
        self.module = load_script("seed_users_under_test", ROOT / "scripts/seed_users.py")

        class UserExists(Exception):
            pass

        self.exists = UserExists
        self.cognito = MagicMock()
        self.cognito.exceptions.UsernameExistsException = UserExists
        self.ssm = MagicMock()
        self.ssm.get_parameter.side_effect = lambda Name: {
            "Parameter": {"Value": "pool" if Name.endswith("pool_id") else "client"}}
        self.session = MagicMock()
        self.session.client.side_effect = lambda name: self.ssm if name == "ssm" else self.cognito

    def invoke(self):
        with patch.dict(os.environ, {"SEED_PASSWORD": "test-secret-not-for-deployment"}), \
                patch.object(self.module.boto3, "Session", return_value=self.session), \
                redirect_stdout(io.StringIO()) as output:
            self.module.main()
        return output.getvalue()

    def test_creates_exact_five_identities_without_printing_password(self):
        output = self.invoke()
        self.assertEqual(self.cognito.admin_create_user.call_count, 5)
        self.assertEqual(self.cognito.admin_set_user_password.call_count, 5)
        for i, call in enumerate(self.cognito.admin_create_user.call_args_list, 1):
            self.assertEqual(call.kwargs["Username"], f"farmer{i}")
            self.assertEqual({a["Name"]: a["Value"] for a in call.kwargs["UserAttributes"]},
                             {"custom:farmer_id": f"F-{i:06d}", "custom:org_id": "org.farmerchat"})
        self.assertTrue(all(c.kwargs["Permanent"] for c in self.cognito.admin_set_user_password.call_args_list))
        self.assertNotIn("test-secret-not-for-deployment", output)
        self.assertIn("aws cognito-idp initiate-auth", output)
        self.assertIn("$SEED_PASSWORD", output)

    def test_existing_matching_identities_are_idempotent(self):
        self.cognito.admin_create_user.side_effect = self.exists
        self.cognito.admin_get_user.side_effect = lambda **kw: {"UserAttributes": [
            {"Name": "custom:farmer_id", "Value": f"F-{int(kw['Username'][6:]):06d}"},
            {"Name": "custom:org_id", "Value": "org.farmerchat"}]}
        self.invoke()
        self.assertEqual(self.cognito.admin_get_user.call_count, 5)
        self.assertEqual(self.cognito.admin_set_user_password.call_count, 5)

    def test_wrong_immutable_identity_stops_before_password_change(self):
        self.cognito.admin_create_user.side_effect = self.exists
        self.cognito.admin_get_user.return_value = {"UserAttributes": [
            {"Name": "custom:farmer_id", "Value": "wrong-farmer"},
            {"Name": "custom:org_id", "Value": "org.farmerchat"}]}
        with self.assertRaisesRegex(SystemExit, "different immutable identity attributes"):
            self.invoke()
        self.cognito.admin_set_user_password.assert_not_called()


class RuntimeFailureContract(unittest.TestCase):
    def test_new_runtime_log_group_has_project_tag_and_fourteen_day_retention(self):
        module = load_script("runtime_logs_new_under_test", ROOT / "infra/runtime.py")
        logs = MagicMock()
        name = "/aws/bedrock-agentcore/runtimes/fixture-runtime-DEFAULT"
        module.configure_runtime_logs(logs, "fixture-runtime")
        logs.create_log_group.assert_called_once_with(logGroupName=name, tags={"Project": "MelAgent"})
        logs.put_retention_policy.assert_called_once_with(logGroupName=name, retentionInDays=14)

    def test_existing_runtime_log_group_gets_project_tag_and_fourteen_day_retention(self):
        module = load_script("runtime_logs_existing_under_test", ROOT / "infra/runtime.py")
        logs = MagicMock()

        class AlreadyExists(Exception):
            pass

        logs.exceptions.ResourceAlreadyExistsException = AlreadyExists
        logs.create_log_group.side_effect = AlreadyExists
        name = "/aws/bedrock-agentcore/runtimes/fixture-runtime-DEFAULT"
        module.configure_runtime_logs(logs, "fixture-runtime")
        logs.tag_log_group.assert_called_once_with(logGroupName=name, tags={"Project": "MelAgent"})
        logs.put_retention_policy.assert_called_once_with(logGroupName=name, retentionInDays=14)

    def test_runtime_tagging_covers_runtime_endpoint_and_workload_identity(self):
        from unittest.mock import call

        module = load_script("runtime_tagging_under_test", ROOT / "infra/runtime.py")
        control = MagicMock()
        arn = "arn:aws:bedrock-agentcore:us-west-2:423964648384:runtime/fixture-runtime"
        endpoint_arn = arn + "/runtime-endpoint/DEFAULT"
        identity_arn = "arn:aws:bedrock-agentcore:us-west-2:423964648384:workload-identity-directory/default/workload-identity/fixture"
        runtime = {"agentRuntimeArn": arn, "workloadIdentityDetails": {"workloadIdentityArn": identity_arn}}
        endpoint = {"agentRuntimeEndpointArn": endpoint_arn}
        control.get_agent_runtime.return_value = runtime
        control.get_agent_runtime_endpoint.return_value = endpoint
        self.assertEqual(module.tag_runtime_resources(control, arn), (runtime, endpoint))
        control.get_agent_runtime.assert_called_once_with(agentRuntimeId="fixture-runtime")
        control.get_agent_runtime_endpoint.assert_called_once_with(agentRuntimeId="fixture-runtime", endpointName="DEFAULT")
        control.tag_resource.assert_has_calls([
            call(resourceArn=resource, tags={"Project": "MelAgent"})
            for resource in [arn, endpoint_arn, identity_arn]], any_order=True)
        self.assertEqual(control.tag_resource.call_count, 3)

    def test_ecr_failure_is_recorded_without_aborting(self):
        from botocore.exceptions import ClientError

        module = load_script("runtime_under_test", ROOT / "infra/runtime.py")
        session = MagicMock()
        ssm = MagicMock()
        ssm.get_parameter.return_value = {"Parameter": {"Value": "placeholder"}}
        ecr = MagicMock()
        ecr.get_authorization_token.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "fixture denial"}}, "GetAuthorizationToken")
        session.client.side_effect = lambda name: ssm if name == "ssm" else ecr
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work, evidence = root / "work", root / "evidence"
            (root / "infra/stub/mel").mkdir(parents=True)
            (root / "models").mkdir()
            (root / "infra/agent-requirements.txt").write_text("")
            (root / "infra/Dockerfile.agent").write_text("FROM scratch\n")
            observed = {}

            def configure(*args, **kwargs):
                if args[0][:3] == ["docker", "context", "inspect"]:
                    return subprocess.CompletedProcess(args[0], 0, "unix:///fixture/docker.sock\n", "")
                observed["docker_config"] = Path(os.environ["DOCKER_CONFIG"])
                (work / ".bedrock_agentcore.yaml").write_text("agents:\n  mel_agent: {}\n")
                return MagicMock(returncode=0)

            with patch.object(module, "ROOT", root), patch.object(module, "WORK", work), \
                    patch.object(module, "EVIDENCE", evidence), \
                    patch.object(module.boto3, "Session", return_value=session), \
                    patch.object(module.subprocess, "run", side_effect=configure), \
                    patch.dict(os.environ), \
                    redirect_stdout(io.StringIO()):
                module.main()
            status = json.loads((evidence / "runtime.json").read_text())
            self.assertEqual(status["status"], "not launched")
            self.assertIn("GetAuthorizationToken", status["command"])
            self.assertIn("fixture denial", status["error"])
            ssm.put_parameter.assert_not_called()
            self.assertFalse(observed["docker_config"].exists())

    def test_initial_ssm_failure_is_recorded_by_entrypoint(self):
        import boto3
        from botocore.exceptions import ClientError

        session = MagicMock()
        session.client.return_value.get_parameter.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "fixture SSM denial"}}, "GetParameter")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "infra").mkdir()
            script = root / "infra/runtime.py"
            script.write_text((ROOT / "infra/runtime.py").read_text())
            with patch.object(boto3, "Session", return_value=session), patch.dict(os.environ), redirect_stdout(io.StringIO()):
                runpy.run_path(str(script), run_name="__main__")
            status = json.loads((root / "infra/evidence/runtime.json").read_text())
            self.assertEqual(status["status"], "not launched")
            self.assertIn("GetParameter", status["command"])
            self.assertIn("fixture SSM denial", status["error"])

    def verify_docker_context(self, existing_host):
        module = load_script("runtime_docker_context_under_test", ROOT / "infra/runtime.py")
        session = MagicMock()
        session.client.return_value.get_parameter.return_value = {"Parameter": {"Value": "placeholder"}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work, evidence, original = root / "work", root / "evidence", root / "original-docker"
            (root / "infra/stub/mel").mkdir(parents=True)
            (root / "models").mkdir()
            original.mkdir()
            (root / "infra/agent-requirements.txt").write_text("")
            (root / "infra/Dockerfile.agent").write_text("FROM scratch\n")
            observed = {}

            def execute(args, **kwargs):
                if args[:3] == ["docker", "context", "inspect"]:
                    observed["context_config"] = os.environ.get("DOCKER_CONFIG")
                    return subprocess.CompletedProcess(args, 0, "unix:///fixture/current-context.sock\n", "")
                observed["host"] = os.environ.get("DOCKER_HOST")
                observed["config_path"] = os.environ.get("DOCKER_CONFIG")
                observed["config"] = json.loads(Path(observed["config_path"]).joinpath("config.json").read_text())
                observed["config_mode"] = Path(observed["config_path"]).joinpath("config.json").stat().st_mode & 0o777
                observed["directory_mode"] = Path(observed["config_path"]).stat().st_mode & 0o777
                raise OSError("fixture stops after Docker config verification")

            with patch.dict(os.environ, {"DOCKER_CONFIG": str(original)}), \
                    patch.object(module, "ROOT", root), patch.object(module, "WORK", work), \
                    patch.object(module, "EVIDENCE", evidence), \
                    patch.object(module.boto3, "Session", return_value=session), \
                    patch.object(module.subprocess, "run", side_effect=execute), redirect_stdout(io.StringIO()):
                if existing_host:
                    os.environ["DOCKER_HOST"] = existing_host
                else:
                    os.environ.pop("DOCKER_HOST", None)
                module.main()
            self.assertEqual(observed.get("host"), existing_host or "unix:///fixture/current-context.sock")
            self.assertIn(str(original / "cli-plugins"), observed["config"]["cliPluginsExtraDirs"])
            self.assertNotEqual(observed["config_path"], str(original))
            self.assertEqual(observed["config_mode"], 0o600)
            self.assertEqual(observed["directory_mode"], 0o700)
            self.assertFalse(Path(observed["config_path"]).exists())
            if existing_host:
                self.assertNotIn("context_config", observed)
            else:
                self.assertEqual(observed["context_config"], str(original))

    def test_isolated_docker_auth_preserves_context_endpoint_and_plugins(self):
        self.verify_docker_context(None)

    def test_isolated_docker_auth_respects_explicit_host(self):
        self.verify_docker_context("unix:///fixture/explicit.sock")


class DeployScriptContract(unittest.TestCase):
    def invoke_lambda_only(self, exit_code):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "infra/.venv/bin").mkdir(parents=True)
            (root / "tools").mkdir()
            (root / "unrelated-cwd").mkdir()
            (root / "scripts/deploy.sh").write_text((ROOT / "scripts/deploy.sh").read_text())
            (root / "scripts/package_lambda.sh").write_text("#!/usr/bin/env bash\nset -eu\necho fixture-package\n")
            (root / "infra/.venv/bin/python").symlink_to(sys.executable)
            aws = root / "tools/aws"
            aws.write_text("#!/usr/bin/env bash\nprintf '423964648384\\n'\n")
            aws.chmod(0o700)
            cdk = root / "tools/cdk"
            cdk.write_text("#!/usr/bin/env bash\npwd > \"$FIXTURE_ROOT/cdk-cwd\"\nprintf '%s\\n' \"$@\" > \"$FIXTURE_ROOT/cdk-args\"\nexit \"$FIXTURE_EXIT\"\n")
            cdk.chmod(0o700)
            env = dict(os.environ, PATH=str(root / "tools") + os.pathsep + os.environ["PATH"],
                       FIXTURE_ROOT=str(root), FIXTURE_EXIT=str(exit_code))
            result = subprocess.run(["bash", str(root / "scripts/deploy.sh"), "--lambda-only"],
                                    cwd=root / "unrelated-cwd", env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, exit_code, result.stderr)
            self.assertEqual(Path((root / "cdk-cwd").read_text().strip()).resolve(), (root / "infra").resolve())
            self.assertEqual((root / "cdk-args").read_text().splitlines(),
                             ["deploy", "MelAgent-Api", "--require-approval", "never"])

    def test_lambda_only_deploy_uses_infra_cwd(self):
        self.invoke_lambda_only(0)

    def test_lambda_only_deploy_preserves_failure_status(self):
        self.invoke_lambda_only(17)


if __name__ == "__main__":
    unittest.main(verbosity=2)
