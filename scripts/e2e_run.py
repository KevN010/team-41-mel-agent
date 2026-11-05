"""End-to-end trace against the deployed stack (us-west-2). Writes evidence/<name>.md and .json.

Path: AgentCore Runtime (IAM SigV4, the caller's AWS credentials), action by action:
  scenario 3 (potato):  clock -> insight time, decide, get_survey, clock -> window start + 1h,
                        respond q2="spreading", follow_ups
  scenario 6 (no survey): decide
Then it collects the real identifiers: AgentCore trace ids, CloudWatch log lines (rule id, model id,
tokens, cost), the DynamoDB items for the run, and the SQS follow-up message.

Each run uses a fresh org id (org.e2e-<stamp>) so the frequency cap and survey counter of earlier
runs do not interfere. Nothing secret is read or printed. Insight text is sent to the runtime only.

    .venv/bin/python scripts/e2e_run.py [--name e2e-run-1]
    .venv/bin/python scripts/e2e_run.py --restart-check S-00001 --org org.e2e-... --name restart
    .venv/bin/python scripts/e2e_run.py --set-clock 2027-01-08T10:00:00+05:30   # live simulator demo
    .venv/bin/python scripts/e2e_run.py --set-clock reset
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import boto3

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mel.fixtures import load_scenarios
from mel.ledger_mem import farmer_pk, org_pk

REGION = "us-west-2"
API_URL = "https://ib6pvb874g.execute-api.us-west-2.amazonaws.com"


def ssm(name: str) -> str:
    return boto3.client("ssm", region_name=REGION).get_parameter(Name="/mel/" + name)["Parameter"]["Value"]


def xray_id() -> str:
    return f"1-{int(time.time()):08x}-{secrets.token_hex(12)}"


class Runtime:
    def __init__(self, arn: str, session_id: str) -> None:
        self.arn = arn
        self.session = session_id
        self.client = boto3.client("bedrock-agentcore", region_name=REGION)
        self.calls: list[dict[str, Any]] = []

    def call(self, action: str, identity: dict[str, str], payload: dict[str, Any] | None = None) -> dict[str, Any]:
        trace = xray_id()
        started = time.perf_counter()
        resp = self.client.invoke_agent_runtime(
            agentRuntimeArn=self.arn, qualifier="DEFAULT", runtimeSessionId=self.session,
            contentType="application/json", accept="application/json", traceId=trace,
            payload=json.dumps({"action": action, "identity": identity, "payload": payload or {}}).encode(),
        )
        body = json.loads(resp["response"].read())
        entry = {
            "action": action,
            "farmer_id": identity["farmer_id"],
            "trace_id_sent": trace,
            "trace_id": resp.get("traceId"),
            "runtime_session_id": resp.get("runtimeSessionId"),
            "status_code": resp.get("statusCode"),
            "status": body.get("status"),
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "body": body.get("body"),
            "at_utc": datetime.now(UTC).isoformat(),
        }
        self.calls.append(entry)
        print(f"{action:<11} -> {entry['status']} trace={entry['trace_id']} {entry['latency_ms']} ms", flush=True)
        return entry


def scenario(prefix: str) -> dict[str, Any]:
    return next(s for s in load_scenarios() if s["name"].startswith(prefix))


def collect_logs(group: str, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
    logs = boto3.client("logs", region_name=REGION)
    out: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {"logGroupName": group, "startTime": start_ms, "endTime": end_ms}
    while True:
        resp = logs.filter_log_events(**kwargs)
        for ev in resp.get("events", []):
            msg = ev["message"].strip()
            if not msg.startswith("{"):
                continue
            try:
                line = json.loads(msg)
            except ValueError:
                continue
            if str(line.get("logger", "")).startswith("mel"):
                out.append({"stream": ev["logStreamName"][-12:], "ts": ev["timestamp"], **line})
        if "nextToken" not in resp:
            return out
        kwargs["nextToken"] = resp["nextToken"]


def ddb_items(table: str, org: str, farmers: list[str]) -> list[dict[str, Any]]:
    ddb = boto3.resource("dynamodb", region_name=REGION).meta.client
    items: list[dict[str, Any]] = []
    for pk in [org_pk(org)] + [farmer_pk(org, f) for f in farmers]:
        resp = ddb.query(TableName=table, KeyConditionExpression="pk = :p",
                         ExpressionAttributeValues={":p": pk}, ConsistentRead=True)
        items.extend(resp.get("Items", []))
    return items


def sqs_messages(queue_url: str, org: str) -> list[dict[str, Any]]:
    sqs = boto3.client("sqs", region_name=REGION)
    found: list[dict[str, Any]] = []
    for _ in range(5):
        # VisibilityTimeout=0: look without hiding the message from the real consumer. Nothing is deleted.
        resp = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10, VisibilityTimeout=0,
                                   WaitTimeSeconds=2, AttributeNames=["SentTimestamp"])
        for m in resp.get("Messages", []):
            body = json.loads(m["Body"])
            if body.get("org_id") == org and all(f["MessageId"] != m["MessageId"] for f in found):
                found.append({"MessageId": m["MessageId"], "SentTimestamp": m["Attributes"]["SentTimestamp"],
                              "body": body})
        if found:
            return found
    return found


def _jsonable(v: Any) -> Any:
    from decimal import Decimal

    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    raise TypeError(type(v))


def run(name: str) -> dict[str, Any]:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    org = f"org.e2e-{stamp}"
    arn = ssm("agent_runtime_arn")
    table, queue_url = ssm("table_name"), ssm("followup_queue_url")
    rt = Runtime(arn, f"mel-e2e-{stamp}-{secrets.token_hex(8)}")
    start_ms = int(time.time() * 1000) - 5000

    potato, info = scenario("3-"), scenario("6-")
    me = {"farmer_id": potato["insight"]["farmer_id"], "org_id": org}
    rt.call("clock", me, {"op": "set", "at": potato["insight"]["created_at"]})
    decided = rt.call("decide", me, potato["insight"])
    survey = (decided["body"] or {}).get("survey")
    result: dict[str, Any] = {"name": name, "org_id": org, "runtime_arn": arn, "table": table}
    if decided["status"] == 201 and survey:
        sid = survey["survey_id"]
        rt.call("get_survey", me, {"survey_id": sid})
        start = datetime.fromisoformat(survey["send_window"]["not_before"]) + timedelta(hours=1)
        rt.call("clock", me, {"op": "set", "at": start.isoformat()})
        channel = decided["body"]["handoff"]["channel_order"][0]["channel"]
        rt.call("respond", me, {"survey_id": sid, "response": {
            "response_key": f"e2e-{stamp}-1", "channel": channel, "answers": {"q2": "spreading"}}})
        rt.call("follow_ups", me)
        result["survey_id"] = sid
    rt.call("decide", {"farmer_id": info["insight"]["farmer_id"], "org_id": org}, info["insight"])

    time.sleep(12)  # CloudWatch Logs ingestion delay
    end_ms = int(time.time() * 1000) + 1000
    result["calls"] = rt.calls
    result["logs"] = collect_logs(f"/aws/bedrock-agentcore/runtimes/{arn.rsplit('/', 1)[-1]}-DEFAULT", start_ms, end_ms)
    result["dynamodb"] = ddb_items(table, org, [potato["insight"]["farmer_id"], info["insight"]["farmer_id"]])
    result["sqs"] = sqs_messages(queue_url, org)
    return result


def restart_check(name: str, org: str, farmer: str, survey_id: str) -> dict[str, Any]:
    arn = ssm("agent_runtime_arn")
    control = boto3.client("bedrock-agentcore-control", region_name=REGION)
    runtime = control.get_agent_runtime(agentRuntimeId=arn.rsplit("/", 1)[-1])
    rt = Runtime(arn, f"mel-restart-{secrets.token_hex(12)}")
    rt.call("get_survey", {"farmer_id": farmer, "org_id": org}, {"survey_id": survey_id})
    return {"name": name, "org_id": org, "runtime_arn": arn,
            "runtime_version": runtime.get("agentRuntimeVersion"),
            "runtime_updated": str(runtime.get("lastUpdatedAt")),
            "container": (runtime.get("agentRuntimeArtifact") or {}).get("containerConfiguration", {}).get("containerUri"),
            "calls": rt.calls}


def _fence(obj: Any) -> str:
    return "```json\n" + json.dumps(obj, indent=2, default=_jsonable) + "\n```"


def render(result: dict[str, Any]) -> str:
    calls = result["calls"]
    lines = [f"# {result['name']}", ""]
    if "runtime_version" in result:
        lines += [
            "Restart check: the AgentCore Runtime was redeployed (new version), then the survey written by",
            "the e2e run was read back through the new deployment.", "",
            f"- Runtime: `{result['runtime_arn']}`",
            f"- Runtime version after redeploy: `{result['runtime_version']}`, updated `{result['runtime_updated']}`",
            f"- Container: `{result['container']}`",
            f"- Org: `{result['org_id']}`", "",
        ]
    else:
        lines += [
            "Real run against the deployed stack in us-west-2 (account 423964648384), through the AgentCore",
            "Runtime with IAM SigV4. Scenario 3 (potato) and scenario 6 (no survey).", "",
            f"- Runtime: `{result['runtime_arn']}`",
            f"- DynamoDB table: `{result['table']}`",
            f"- Org (fresh per run): `{result['org_id']}`",
            f"- Survey: `{result.get('survey_id')}`", "",
        ]
    lines += ["## Calls", "", "| action | farmer | status | latency ms | runtime session | trace id sent (X-Ray format) |",
              "|---|---|---|---|---|---|"]
    for c in calls:
        lines.append(f"| {c['action']} | {c['farmer_id']} | {c['status']} | {c['latency_ms']} | "
                     f"`{c['runtime_session_id']}` | `{c['trace_id_sent']}` |")
    lines.append("")
    for c in calls:
        lines += [f"### {c['action']} ({c['status']})", "", _fence(c["body"]), ""]
    if "logs" in result:
        keep = [{k: v for k, v in entry.items() if k != "stream"} for entry in result["logs"]
                if entry.get("msg") != "metric"]
        lines += ["## CloudWatch log lines (runtime log group, mel.* loggers, metric lines left out)", "",
                  _fence(keep), "", "## DynamoDB items for the run", "", _fence(result["dynamodb"]), "",
                  "## SQS follow-up message (mel-followups, read with VisibilityTimeout 0, not deleted)", "",
                  _fence(result["sqs"]), ""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="e2e-run-1")
    ap.add_argument("--restart-check", metavar="SURVEY_ID")
    ap.add_argument("--org")
    ap.add_argument("--farmer", default="F-000245")
    ap.add_argument("--render-only", action="store_true", help="rewrite <name>.md from <name>.json")
    ap.add_argument("--set-clock", metavar="ISO|reset",
                    help="only move the server demo clock of --org (default org.farmerchat) and exit")
    a = ap.parse_args()
    if a.set_clock:
        rt = Runtime(ssm("agent_runtime_arn"), f"mel-clock-{secrets.token_hex(12)}")
        op = {"op": "reset"} if a.set_clock == "reset" else {"op": "set", "at": a.set_clock}
        out = rt.call("clock", {"farmer_id": a.farmer, "org_id": a.org or "org.farmerchat"}, op)
        print(json.dumps(out["body"]))
        return
    out_dir = ROOT / "evidence"
    out_dir.mkdir(exist_ok=True)
    if a.render_only:
        result = json.loads((out_dir / f"{a.name}.json").read_text())
        (out_dir / f"{a.name}.md").write_text(render(result))
        return
    if a.restart_check:
        result = restart_check(a.name, a.org, a.farmer, a.restart_check)
    else:
        result = run(a.name)
    path = out_dir / f"{a.name}.json"
    path.write_text(json.dumps(result, indent=2, default=_jsonable))
    (out_dir / f"{a.name}.md").write_text(render(result))
    print(f"wrote {path.relative_to(ROOT)} and .md")


if __name__ == "__main__":
    main()
