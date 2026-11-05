#!/usr/bin/env python3
"""Build/push arm64 image and run the requested AgentCore starter toolkit."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone

import boto3
from botocore.exceptions import BotoCoreError, ClientError
import yaml

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "infra/evidence"
WORK = ROOT / "infra/.agentcore-work"



def tag_runtime_resources(control, runtime_arn):
    runtime_id = runtime_arn.rsplit("/", 1)[-1]
    runtime = control.get_agent_runtime(agentRuntimeId=runtime_id)
    endpoint = control.get_agent_runtime_endpoint(agentRuntimeId=runtime_id, endpointName="DEFAULT")
    arns = [runtime_arn, endpoint["agentRuntimeEndpointArn"]]
    identity = runtime.get("workloadIdentityDetails", {}).get("workloadIdentityArn")
    if identity:
        arns.append(identity)
    for arn in arns:
        control.tag_resource(resourceArn=arn, tags={"Project": "MelAgent"})
    return runtime, endpoint


def configure_runtime_logs(logs_client, runtime_id):
    name = "/aws/bedrock-agentcore/runtimes/" + runtime_id + "-DEFAULT"
    try:
        logs_client.create_log_group(logGroupName=name, tags={"Project": "MelAgent"})
    except logs_client.exceptions.ResourceAlreadyExistsException:
        logs_client.tag_log_group(logGroupName=name, tags={"Project": "MelAgent"})
    logs_client.put_retention_policy(logGroupName=name, retentionInDays=14)


def main():
    EVIDENCE.mkdir(exist_ok=True)
    WORK.mkdir(exist_ok=True)
    original_docker_config = Path(os.environ.get("DOCKER_CONFIG", os.path.expanduser("~/.docker")))
    docker_config = None
    session = boto3.Session(region_name="us-west-2")
    ssm = session.client("ssm")
    def read(name):
        return ssm.get_parameter(Name="/mel/" + name)["Parameter"]["Value"]
    repo, role = read("ecr_repo_uri"), read("agent_role_arn")
    env = {
        "MEL_REGION": "us-west-2", "MEL_TABLE": read("table_name"),
        "MEL_ARTIFACTS_BUCKET": read("artifacts_bucket"),
        "MEL_FOLLOWUP_QUEUE_URL": read("followup_queue_url"),
        "MEL_JEV_SECRET_ARN": read("jev_secret_arn"),
        "MEL_USER_POOL_ID": read("user_pool_id"), "MEL_USER_POOL_CLIENT_ID": read("user_pool_client_id"),
        "MEL_MODELS_FILE": "models/models.yaml", "MEL_METRICS_NAMESPACE": "MelAgent",
    }
    tag = datetime.now(timezone.utc).strftime("deploy-%Y%m%d%H%M%S")
    image = repo + ":" + tag
    status = {"status": "not launched", "image": image}
    log_path = EVIDENCE / "agentcore.log"
    def run(args, *, cwd=WORK, input=None):
        command = shlex.join([str(a) for a in args])
        with log_path.open("a") as log:
            log.write("\n$ " + command + "\n")
            log.flush()
            result = subprocess.run(args, cwd=cwd, text=True, input=input,
                                    stdout=log, stderr=subprocess.STDOUT, timeout=900)
        if result.returncode:
            status.update(command=command, error=log_path.read_text().rsplit("\n$ " + command + "\n", 1)[-1][-18000:])
            raise RuntimeError(f"Command exited {result.returncode}: {command}")
    try:
        if not os.environ.get("DOCKER_HOST"):
            command = ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"]
            context = subprocess.run(command, capture_output=True, text=True, timeout=30)
            if context.returncode:
                status.update(command=shlex.join(command), error=context.stderr)
                raise RuntimeError("Docker context discovery failed")
            os.environ["DOCKER_HOST"] = context.stdout.strip()
        os.environ.pop("DOCKER_CONTEXT", None)
        docker_config = Path(tempfile.mkdtemp(prefix="mel-docker-auth-"))
        config_file = docker_config / "config.json"
        config_file.write_text(json.dumps({"cliPluginsExtraDirs": [str(original_docker_config / "cli-plugins")]}))
        config_file.chmod(0o600)
        os.environ["DOCKER_CONFIG"] = str(docker_config)
        source = ROOT / "mel" if (ROOT / "mel/agent.py").is_file() else ROOT / "infra/stub/mel"
        shutil.copytree(source, WORK / "mel", dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copytree(ROOT / "models", WORK / "models", dirs_exist_ok=True)
        (WORK / "infra").mkdir(exist_ok=True)
        requirements = ROOT / "infra/lambda-requirements.txt" if source == ROOT / "mel" else ROOT / "infra/agent-requirements.txt"
        shutil.copy2(requirements, WORK / "infra/agent-requirements.txt")
        # Supply paths only from the isolated staging context; never send repo secrets to Docker.
        dockerfile = (ROOT / "infra/Dockerfile.agent").read_text().replace("ARG MEL_SOURCE=infra/stub/mel", "ARG MEL_SOURCE=mel")
        (WORK / "Dockerfile.agent").write_text(dockerfile)
        run(["agentcore", "configure", "--entrypoint", "mel/agent.py", "--name", "mel_agent",
             "--execution-role", role, "--ecr", repo, "--region", "us-west-2", "--requirements-file",
             "infra/agent-requirements.txt", "--deployment-type", "container", "--disable-otel", "--disable-memory", "--non-interactive"])
        config_path = WORK / ".bedrock_agentcore.yaml"
        config = yaml.safe_load(config_path.read_text())
        agent = config["agents"]["mel_agent"]
        agent["tags"] = {"Project": "MelAgent"}
        config_path.write_text(yaml.safe_dump(config, sort_keys=False))
        # The toolkit may generate its own Dockerfile. Replace it with the owned arm64 image definition.
        for path in WORK.rglob("Dockerfile"):
            path.write_text(dockerfile)
        auth = session.client("ecr").get_authorization_token()["authorizationData"][0]
        import base64
        username, password = base64.b64decode(auth["authorizationToken"]).decode().split(":", 1)
        run(["docker", "login", "--username", username, "--password-stdin", auth["proxyEndpoint"]], input=password)
        run(["docker", "build", "--platform", "linux/arm64", "-f", "Dockerfile.agent", "-t", image, "."])
        run(["docker", "push", image])
        args = ["agentcore", "launch", "--local-build", "--auto-update-on-conflict", "--image-tag", tag + "-runtime"]
        for key, value in env.items():
            args.extend(["--env", key + "=" + value])
        run(args)
        config = yaml.safe_load(config_path.read_text())
        runtime_arn = config["agents"]["mel_agent"]["bedrock_agentcore"].get("agent_arn")
        if not runtime_arn or not runtime_arn.startswith("arn:aws:bedrock-agentcore:us-west-2:"):
            status.update(command=shlex.join(args), error="Toolkit returned success without a runtime ARN in its configuration")
            raise RuntimeError(status["error"])
        runtime, endpoint = tag_runtime_resources(session.client("bedrock-agentcore-control"), runtime_arn)
        configure_runtime_logs(session.client("logs"), runtime["agentRuntimeId"])
        (EVIDENCE / "runtime-live.json").write_text(json.dumps({"runtime": runtime, "endpoint": endpoint}, indent=2, default=str))
        ssm.put_parameter(Name="/mel/agent_runtime_arn", Type="String", Value=runtime_arn, Overwrite=True)
        status.update(status="launched", runtime_arn=runtime_arn, endpoint_arn=endpoint["agentRuntimeEndpointArn"], runtime_status=runtime["status"], image=repo + ":" + tag + "-runtime")
    except (RuntimeError, OSError, subprocess.TimeoutExpired, BotoCoreError, ClientError, KeyError, ValueError, yaml.YAMLError) as exc:
        status.setdefault("error", str(exc))
        status.setdefault("command", "AWS SDK " + getattr(exc, "operation_name", "runtime configuration / launch"))
        print(f"AgentCore Runtime: not launched ({exc})")
    finally:
        if docker_config is not None:
            shutil.rmtree(docker_config, ignore_errors=True)
        (EVIDENCE / "runtime.json").write_text(json.dumps(status, indent=2))
    print("AgentCore Runtime: " + status["status"])


if __name__ == "__main__":
    try:
        main()
    except (BotoCoreError, ClientError, KeyError, ValueError, yaml.YAMLError) as exc:
        EVIDENCE.mkdir(exist_ok=True)
        operation = getattr(exc, "operation_name", "runtime initialization")
        (EVIDENCE / "runtime.json").write_text(json.dumps({"status": "not launched", "command": "AWS SDK " + operation, "error": str(exc)}, indent=2))
        print("AgentCore Runtime: not launched (" + str(exc) + ")")
