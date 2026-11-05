"""Survey eval harness: the numbers for the last demo slide and the evidence bundle.

Sections
  rules      decision engine on all 150 golden rows: per-rule table and misses
  timing     golden_v1 send windows on the golden R8 rows (rules_v1 shown for information)
  outcomes   every pack outcome fixture through mel.outcomes.apply_event, contradictions listed
  generation (AWS) the 5 actionable pack scenarios, one generation run each, with the model from
             models/models.yaml and the live Jev judge: schema pass rate, Jev verdicts,
             p50/p95 latency, tokens, cost per accepted survey, total spend
  inventory  (AWS) CloudFormation outputs and resourcegroupstaggingapi get-resources, Project=MelAgent

    .venv/bin/python evals/survey_eval.py                 # offline sections, then AWS sections if credentials work
    .venv/bin/python evals/survey_eval.py --offline       # offline sections only
    .venv/bin/python evals/survey_eval.py --report-only   # rebuild evidence/REPORT.md from evidence/*.json

Writes evidence/survey_eval.json, evidence/inventory.json and evidence/REPORT.md.

Privacy: only the 6 pack scenarios are ever sent to a model. Nothing here prints or stores
insight text, survey text, farmer ids, keys or secret values; results hold ids, codes and numbers.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
# The package may be installed editable from another checkout; always use this one.
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(ROOT / "tests"))

EVIDENCE = ROOT / "evidence"
REGION = "us-west-2"
RULE_IDS = [f"R{i}" for i in range(1, 9)]
SCENARIO_LANGUAGE = "en-IN"
TAG_KEY, TAG_VALUE = "Project", "MelAgent"


# --------------------------------------------------------------------------- helpers


def percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile; None for an empty list."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(math.ceil(pct / 100 * len(ordered)) - 1, 0)]


def _clock():
    from mel.models import IST
    from mel.protocols import FakeClock

    return FakeClock(datetime(2026, 11, 5, 9, 0, tzinfo=IST))


# --------------------------------------------------------------------------- offline sections


def eval_rules() -> dict[str, Any]:
    from mel import fixtures as pack
    from mel.rules import decide

    golden, calendar, rules, clock = pack.load_golden(), pack.load_crop_calendar(), pack.load_rules(), _clock()
    per_rule = {r: {"expected": 0, "got": 0, "matched": 0} for r in RULE_IDS}
    confusion: Counter[tuple[str, str]] = Counter()
    misses = []
    for row in golden:
        exp = row["expected"]
        d = decide(row["insight"], clock, calendar, rules)
        confusion[(exp["rule"], d.rule_id)] += 1
        per_rule[exp["rule"]]["expected"] += 1
        per_rule[d.rule_id]["got"] += 1
        want = (exp["survey"], exp.get("reason_code"), exp["rule"])
        got = (d.survey, d.reason_code, d.rule_id)
        if got == want:
            per_rule[exp["rule"]]["matched"] += 1
        else:
            misses.append({"golden_id": row["golden_id"], "expected": list(want), "got": list(got)})
    return {
        "total": len(golden),
        "matched": len(golden) - len(misses),
        "per_rule": per_rule,
        "confusion": {f"{e}->{g}": n for (e, g), n in sorted(confusion.items())},
        "misses": misses,
    }


def eval_timing() -> dict[str, Any]:
    from mel import fixtures as pack
    from mel.models import SendWindow
    from mel.timing import send_window

    rules, clock = pack.load_rules(), _clock()
    r8 = [r for r in pack.load_golden() if r["expected"].get("survey")]

    def run(profile: str) -> tuple[int, list[str], int]:
        matched, bad, exceptions = 0, [], 0
        for row in r8:
            got = send_window(row["insight"], profile, clock, rules)
            exp = row["expected"]["send_window"]
            if isinstance(got, SendWindow):
                if (got.not_before.isoformat(), got.not_after.isoformat()) == (exp["start"], exp["end"]):
                    matched += 1
                    continue
            else:
                exceptions += 1
            bad.append(row["golden_id"])
        return matched, bad, exceptions

    g_ok, g_bad, g_exc = run("golden_v1")
    r_ok, r_bad, r_exc = run("rules_v1")
    return {
        "r8_rows": len(r8),
        "golden_v1": {"matched": g_ok, "mismatched_ids": g_bad, "timing_exceptions": g_exc},
        "rules_v1_informational": {"matched": r_ok, "mismatched": len(r_bad), "timing_exceptions": r_exc,
                                   "note": "rules_v1 follows rules.json, not the golden windows; a low match is expected"},
    }


def eval_outcomes() -> dict[str, Any]:
    from outcome_events import (
        FixedClock,
        attempt_from_fixture,
        case_id,
        event_from_fixture,
        load_codes,
        load_fixture,
        load_survey,
        outcome_paths,
    )

    from mel.outcomes import apply_event

    fields = ("status", "failure_code", "sheet_outcome", "answers", "complete", "retry_decision",
              "retry_after_minutes", "counts_toward_cap", "needs_follow_up", "follow_up_reasons")
    codes = load_codes()
    paths = outcome_paths()
    contradictions = []
    for path in paths:
        fx = load_fixture(path)
        try:
            rec = apply_event(load_survey(fx["survey_id"], fx["language"]), attempt_from_fixture(fx),
                              event_from_fixture(fx), FixedClock(fx["recorded_at"]), codes)
        except Exception as exc:  # noqa: BLE001 - a crash is a contradiction too
            contradictions.append({"case": case_id(path), "fields": [f"raised:{type(exc).__name__}"]})
            continue
        bad = []
        for name in fields:
            actual = rec[name] if isinstance(rec, dict) else getattr(rec, name)
            if name == "follow_up_reasons":
                actual = list(actual)
            if actual != fx[name]:
                bad.append(name)
        if bad:  # field names only: values may hold farmer answers
            contradictions.append({"case": case_id(path), "fields": bad})
    return {"total": len(paths), "passed": len(paths) - len(contradictions), "contradictions": contradictions}


# --------------------------------------------------------------------------- AWS sections


def aws_identity() -> tuple[bool, str]:
    """(ok, reason). The ARN is not returned: it can carry a user name."""
    try:
        import boto3

        boto3.client("sts", region_name=REGION).get_caller_identity()
        return True, "ok"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}"


def fetch_jev_key() -> tuple[str | None, str]:
    """Read the Jev key from Secrets Manager into memory. Never printed. (key, status)."""
    try:
        import boto3

        arn = os.environ.get("MEL_JEV_SECRET_ARN")
        if not arn:
            arn = boto3.client("ssm", region_name=REGION).get_parameter(Name="/mel/jev_secret_arn")["Parameter"]["Value"]
        raw = boto3.client("secretsmanager", region_name=REGION).get_secret_value(SecretId=arn)["SecretString"].strip()
        if raw.startswith("{"):
            data = json.loads(raw)
            raw = next((str(data[k]) for k in ("api_key", "key", "value") if k in data), "").strip()
        if not raw or raw == "REPLACE_ME":
            return None, "secret_is_placeholder"
        return raw, "loaded"
    except Exception as exc:  # noqa: BLE001
        return None, f"secret_unavailable:{type(exc).__name__}"


class TimedJudge:
    """Wraps a Judge to record wall time and the verdict of every call."""

    def __init__(self, inner: Any) -> None:
        self.inner, self.calls = inner, []

    def check_survey(self, insight: Any, survey: Any) -> Any:
        t0 = time.monotonic()
        verdict = self.inner.check_survey(insight, survey)
        self.calls.append({"latency_ms": round((time.monotonic() - t0) * 1000), "verdict": verdict})
        return verdict


class RecordingClient:
    """Wraps the bedrock-runtime client and keeps the raw usage and stop reason of every response,
    failed parses included. The provider drops usage when it raises, so spend would be understated.
    A call that raised before any response is recorded with ``error`` and no usage."""

    def __init__(self, inner: Any) -> None:
        self._inner, self.calls = inner, []

    def converse(self, **request: Any) -> Any:
        t0 = time.perf_counter()
        try:
            response = self._inner.converse(**request)
        except Exception as exc:
            code = getattr(exc, "response", {}).get("Error", {}).get("Code", type(exc).__name__)
            self.calls.append({"latency_ms": round((time.perf_counter() - t0) * 1000),
                               "stop_reason": None, "usage": {}, "error": str(code)})
            raise
        self.calls.append({"latency_ms": round((time.perf_counter() - t0) * 1000),
                           "stop_reason": response.get("stopReason"), "usage": dict(response.get("usage") or {})})
        return response


class RecordingTransport(httpx.BaseTransport):
    """httpx transport wrapper that keeps status and body of every non-2xx Jev response (body capped)."""

    BODY_CAP = 2000

    def __init__(self) -> None:
        self._inner, self.errors = httpx.HTTPTransport(), []

    def handle_request(self, request: Any) -> Any:
        response = self._inner.handle_request(request)
        if not 200 <= response.status_code < 300:
            response.read()
            body = response.text[: self.BODY_CAP]
            if not any(e["status"] == response.status_code and e["body"] == body for e in self.errors):
                self.errors.append({"status": response.status_code, "body": body})
        return response

    def close(self) -> None:  # JevJudge closes its httpx client after every post; keep the pool open
        pass


def _call_row(call: dict[str, Any], price_in: float | None, price_out: float | None,
              est_input: int | None = None) -> dict[str, Any]:
    """Token counts from the raw Converse usage block. Input = totalTokens - outputTokens, so cached prompt
    tokens count. A call that raised before any response has no usage: it is counted at ``est_input``
    (median input tokens of the metered calls), no output, and flagged ``estimated``."""
    u = call["usage"]
    estimated = bool(call.get("error")) or not u
    out = int(u.get("outputTokens", 0))
    cached = int(u.get("cacheReadInputTokens", 0)) + int(u.get("cacheWriteInputTokens", 0))
    if estimated:
        total_in = est_input or 0
    else:
        total_in = int(u["totalTokens"]) - out if "totalTokens" in u else int(u.get("inputTokens", 0)) + cached
    cost = None if price_in is None or price_out is None else (total_in * price_in + out * price_out) / 1_000_000
    return {"latency_ms": call["latency_ms"], "stop_reason": call["stop_reason"], "error": call.get("error"),
            "estimated": estimated, "input_tokens": total_in,
            "uncached_input_tokens": int(u.get("inputTokens", 0)), "output_tokens": out, "cost_usd": cost}


def eval_generation() -> dict[str, Any]:
    from mel import fixtures as pack
    from mel.generate import LlmSurveyGenerator, generate_survey, load_model_choice
    from mel.judge import JevJudge
    from mel.providers.bedrock import BedrockChat, _default_client
    from mel.rules import decide
    from mel.settings import settings
    from mel.timing import TimingException, send_window
    from mel.validate import validate_against_pack

    clock, rules, calendar = _clock(), pack.load_rules(), pack.load_crop_calendar()
    choice = load_model_choice()
    key, key_status = fetch_jev_key()
    transport = RecordingTransport()
    judge = TimedJudge(JevJudge(api_key=key, transport=transport))
    chats: dict[str, BedrockChat] = {}
    recorder = RecordingClient(_default_client(REGION))

    def chat_for(model_key: str) -> BedrockChat:
        if model_key not in chats:
            chats[model_key] = BedrockChat(model_key, client=recorder)
        return chats[model_key]

    generator = LlmSurveyGenerator(chat_for)
    scenarios = [s for s in pack.load_scenarios() if s["survey_by_lang"]]
    rows = []
    for seq, sc in enumerate(scenarios, start=1):
        insight = sc["insight"]
        decision = decide(insight, clock, calendar, rules)
        window = send_window(insight, decision.timing_profile, clock, rules)
        if not decision.survey or isinstance(window, TimingException):
            rows.append({"scenario": sc["name"], "status": "skipped", "reason": f"rule {decision.rule_id}"})
            continue
        n_judge, n_calls = len(judge.calls), len(recorder.calls)
        res = generate_survey(insight, decision, window, SCENARIO_LANGUAGE, generator, judge, clock,
                              survey_seq=seq, models=choice)
        schema_ok = False
        if res.survey is not None:
            schema_ok, _ = validate_against_pack(res.survey, "survey")  # our validator, never the model's flag
        verdict = res.verdict
        judge_call = judge.calls[n_judge] if len(judge.calls) > n_judge else None
        spec = next(iter(chats.values())).spec
        metered = sorted(int(c["usage"]["totalTokens"]) - int(c["usage"].get("outputTokens", 0))
                         for c in recorder.calls if c["usage"].get("totalTokens"))
        est_input = metered[len(metered) // 2] if metered else None
        calls = [_call_row(c, spec.input_per_m, spec.output_per_m, est_input) for c in recorder.calls[n_calls:]]
        rows.append({
            "scenario": sc["name"],
            "status": res.status,
            "attempts": res.attempts,
            "models": res.model_keys,
            "schema_valid": bool(schema_ok),
            "jev": None if verdict is None else {
                "ok": verdict.ok, "pending_review": verdict.pending_review, "reason": verdict.reason,
                "scores": {k: round(v, 3) for k, v in verdict.scores.items()},
                "latency_ms": judge_call["latency_ms"] if judge_call else None,
            },
            "calls": calls,
            "cost_usd": sum(c["cost_usd"] or 0.0 for c in calls),
            "reasons": res.reasons,  # safe codes only (generate never echoes draft text)
        })

    ran = [r for r in rows if r["status"] != "skipped"]
    accepted = [r for r in ran if r["status"] == "accepted"]
    latencies = [c["latency_ms"] for r in ran for c in r["calls"]]
    jev_counts = Counter(
        "no_verdict" if r["jev"] is None else "pending_review" if r["jev"]["pending_review"]
        else "ok" if r["jev"]["ok"] else "not_ok"
        for r in ran
    )
    # A call is "used" when it produced the survey that went to Jev; every other call is a failed call.
    used_calls: list[dict[str, Any]] = []
    failed_calls: list[dict[str, Any]] = []
    for r in ran:
        if r["status"] == "failed_review":
            failed_calls.extend(r["calls"])
        else:
            failed_calls.extend(r["calls"][:-1])
            used_calls.extend(r["calls"][-1:])
    all_calls = used_calls + failed_calls

    def tok(calls: list[dict[str, Any]], field: str) -> int:
        return sum(c[field] for c in calls)

    def cost(calls: list[dict[str, Any]]) -> float:
        return sum(c["cost_usd"] or 0.0 for c in calls)

    total_cost, spec = cost(all_calls), (next(iter(chats.values())).spec if chats else None)
    n_acc = len(accepted)
    return {
        "model": {"generation": choice.generation, "retry": choice.retry,
                  "price_input_per_m": getattr(spec, "input_per_m", None),
                  "price_output_per_m": getattr(spec, "output_per_m", None),
                  "price_verified": False},
        "language": SCENARIO_LANGUAGE,
        "max_tokens": settings.MAX_TOKENS,
        "jev_key_status": key_status,
        "jev": {"model": getattr(judge.inner, "_model", None), "http_errors": transport.errors},
        "scenarios": rows,
        "summary": {
            "scenarios_run": len(ran),
            "schema_valid": sum(r["schema_valid"] for r in ran),
            "accepted": n_acc,
            "jev_verdicts": dict(jev_counts),
            "model_calls": len(latencies),
            "unmetered_calls_estimated": sum(1 for c in all_calls if c["estimated"]),
            "latency_ms_p50": percentile(latencies, 50),
            "latency_ms_p95": percentile(latencies, 95),
            "input_tokens": tok(all_calls, "input_tokens"),
            "output_tokens": tok(all_calls, "output_tokens"),
            "failed_call_count": len(failed_calls),
            "failed_input_tokens": tok(failed_calls, "input_tokens"),
            "failed_output_tokens": tok(failed_calls, "output_tokens"),
            "failed_calls_cost_usd": cost(failed_calls),
            "used_calls_cost_usd": cost(used_calls),
            "total_cost_usd": total_cost,
            "cost_per_accepted_survey_usd": (total_cost / n_acc) if n_acc else None,
            "cost_per_accepted_survey_used_calls_only_usd": (cost(used_calls) / n_acc) if n_acc else None,
            "cost_per_generated_survey_usd": (total_cost / len(ran)) if ran else None,
        },
    }


def eval_inventory() -> dict[str, Any]:
    import boto3

    cfn = boto3.client("cloudformation", region_name=REGION)
    outputs: dict[str, dict[str, str]] = {}
    for page in cfn.get_paginator("describe_stacks").paginate():
        for st in page["Stacks"]:
            if st["StackName"].startswith("MelAgent-"):
                outputs[st["StackName"]] = {o["OutputKey"]: o["OutputValue"] for o in st.get("Outputs", [])}
    tagging = boto3.client("resourcegroupstaggingapi", region_name=REGION)
    arns: list[str] = []
    for page in tagging.get_paginator("get_resources").paginate(
        TagFilters=[{"Key": TAG_KEY, "Values": [TAG_VALUE]}]
    ):
        arns.extend(r["ResourceARN"] for r in page["ResourceTagMappingList"])
    return {"region": REGION, "tag": f"{TAG_KEY}={TAG_VALUE}", "stack_outputs": outputs, "tagged_arns": sorted(set(arns))}


# --------------------------------------------------------------------------- security controls

# (control, test ids that prove it). Each id is checked to exist in the repo when the report builds.
CONTROLS: list[tuple[str, list[str]]] = [
    ("farmer_id and org_id come from the Cognito JWT claims only, never the request body",
     ["tests/test_auth.py::test_body_headers_query_and_path_are_ignored",
      "tests/test_auth.py::test_body_cannot_stand_in_for_missing_claims",
      "tests/test_intake.py::test_no_body_field_can_override_identity",
      "tests/test_intake.py::test_stored_record_carries_jwt_identity_not_body"]),
    ("Every ledger read and write is scoped by org_id and farmer_id",
     ["tests/test_ledger.py::test_cross_org_read_returns_nothing",
      "tests/test_ledger.py::test_cross_farmer_read_returns_nothing",
      "tests/test_ledger.py::test_ids_that_could_forge_a_key_are_rejected",
      "tests/test_intake.py::test_every_ledger_call_is_scoped_to_identity",
      "tests/test_intake.py::test_org_comes_from_identity_for_every_write"]),
    ("A survey cannot be answered by a different farmer (identity_mismatch) or read across orgs",
     ["tests/test_intake.py::test_wrong_farmer_is_identity_mismatch",
      "tests/test_intake.py::test_wrong_org_looks_like_unknown_survey",
      "tests/test_ledger.py::test_survey_id_cannot_be_taken_by_another_farmer"]),
    ("Insight and advice text are untrusted data: user turn only, never the system prompt",
     ["tests/test_generate.py::test_system_prompt_is_stable_and_has_no_insight_text",
      "tests/test_providers.py::test_openai_request_has_strict_schema_and_user_turn_only",
      "tests/test_judge.py::test_untrusted_text_only_in_state_never_in_questions"]),
    ("Jev checks the final survey; any failure or Jev outage blocks acceptance (pending_review)",
     ["tests/test_judge.py::test_each_failing_check_blocks",
      "tests/test_judge.py::test_timeout_retries_then_pending",
      "tests/test_generate.py::test_judge_not_ok_is_pending_review",
      "tests/test_intake.py::test_unaccepted_survey_is_not_stored_or_handed_off"]),
    ("Jev key is sent only to the allowed host and never logged or shown in repr",
     ["tests/test_judge.py::test_wrong_host_never_sends_key",
      "tests/test_judge.py::test_key_and_insight_text_never_logged_or_in_repr",
      "tests/test_judge.py::test_redirect_is_not_followed"]),
    ("No insight, draft or answer text in logs",
     ["tests/test_generate.py::test_reasons_do_not_echo_draft_text",
      "tests/test_intake.py::test_no_answer_text_in_logs",
      "tests/test_invariants.py::test_messages_never_echo_values",
      "tests/test_providers.py::test_bad_output_raises_provider_error_without_echo"]),
    ("Every record is validated against the pack schema before persisting; schema_valid is ours, not the model's",
     ["tests/test_intake.py::test_record_failing_pack_schema_is_not_stored",
      "tests/test_generate.py::test_model_schema_valid_true_on_invalid_draft_is_ignored",
      "tests/test_generate.py::test_garbage_drafts_fail_closed"]),
    ("60 requests/minute process-wide token bucket on all model calls",
     ["tests/test_providers.py::test_bucket_never_exceeds_rpm_in_a_minute",
      "tests/test_providers.py::test_every_attempt_takes_a_rate_limit_token"]),
    ("Model region fixed to us-west-2",
     ["tests/test_providers.py::test_region_must_be_us_west_2"]),
    ("Timestamps are Asia/Kolkata with explicit offset; naive datetimes are rejected",
     ["tests/test_models_roundtrip.py::test_naive_datetime_rejected",
      "tests/test_ledger.py::test_naive_timestamp_is_rejected"]),
    ("Tests never call real APIs (network blocked in make test)",
     ["tests/test_models_roundtrip.py::test_network_is_blocked"]),
    ("API Gateway routes require the JWT authorizer",
     ["infra/test_contract.py::test_routes_use_jwt"]),
    ("DynamoDB: SSE on, point-in-time recovery on, TTL attribute",
     ["infra/test_contract.py::test_dynamodb_contract"]),
    ("S3 block public access and default encryption; CloudFront uses OAC and HTTPS",
     ["infra/test_contract.py::test_s3_and_cloudfront_security"]),
    ("IAM policies list explicit actions (no wildcard actions)",
     ["infra/test_contract.py::test_iam_actions_are_explicit"]),
    ("SQS follow-up queue encrypted with a dead-letter queue",
     ["infra/test_contract.py::test_queue_contract"]),
]


def control_test_exists(test_id: str) -> bool:
    path, _, name = test_id.partition("::")
    f = ROOT / path
    return f.is_file() and re.search(rf"def {re.escape(name)}\b", f.read_text(encoding="utf-8")) is not None


# --------------------------------------------------------------------------- report


def _fmt_usd(v: float | None) -> str:
    return "n/a" if v is None else f"${v:.6f}"


def _fmt_ms(v: float | None) -> str:
    return "n/a" if v is None else f"{v:,.0f} ms"


def build_report(res: dict[str, Any], inventory: dict[str, Any] | None) -> str:
    out: list[str] = []
    w = out.append
    w("# mel-agent evidence report\n")
    w(f"Generated {res['generated_at']} by `evals/survey_eval.py`. Region {REGION}. "
      "Numbers below come from `evidence/survey_eval.json` and `evidence/inventory.json`; "
      "a section that could not run says so and carries no numbers.\n")

    # rules
    r = res["rules"]
    w("## 1. Decision rules on the golden set\n")
    w(f"**{r['matched']}/{r['total']}** golden rows match on survey flag, reason code and rule id.\n")
    w("| Rule | Expected rows | Rows we assigned | Matched |\n|---|---|---|---|")
    for rid in RULE_IDS:
        p = r["per_rule"][rid]
        w(f"| {rid} | {p['expected']} | {p['got']} | {p['matched']} |")
    w("")
    if r["misses"]:
        w("Misses:\n")
        for m in r["misses"]:
            w(f"- {m['golden_id']}: expected {m['expected']}, got {m['got']}")
    else:
        w("Misses: none.")
    w("")

    # timing
    t = res["timing"]
    w("## 2. Timing\n")
    w(f"`golden_v1` reproduces **{t['golden_v1']['matched']}/{t['r8_rows']}** golden R8 send windows "
      f"({t['golden_v1']['timing_exceptions']} timing exceptions).")
    if t["golden_v1"]["mismatched_ids"]:
        w(f"Mismatched: {', '.join(t['golden_v1']['mismatched_ids'])}.")
    ri = t["rules_v1_informational"]
    w(f"\nFor information, `rules_v1` (rules.json interpretation) matches {ri['matched']}/{t['r8_rows']} golden "
      f"windows with {ri['timing_exceptions']} timing exceptions. {ri['note']}.\n")

    # outcomes
    o = res["outcomes"]
    w("## 3. Outcome fixtures\n")
    w(f"**{o['passed']}/{o['total']}** pack outcome fixtures pass through `mel.outcomes.apply_event` "
      "(10 asserted fields each).\n")
    if o["contradictions"]:
        w("Contradictions (fixture, fields that differ):\n")
        for c in o["contradictions"]:
            w(f"- {c['case']}: {', '.join(c['fields'])}")
    else:
        w("Contradictions: none.")
    w("")

    # generation
    w("## 4. Generation on the 5 actionable scenarios\n")
    g = res.get("generation")
    if g is None:
        w(f"NOT RUN: {res['generation_skipped']}\n")
    else:
        s, m = g["summary"], g["model"]
        override = " (Dwayne's override of the 600 in CLAUDE.md, set with the MAX_TOKENS env var)" \
            if g.get("max_tokens") != 600 else ""
        w(f"Model `{m['generation']}` (retry `{m['retry']}`), **max_tokens {g.get('max_tokens')}**{override}, "
          f"language {g['language']}, one run per scenario, live Jev judge model `{g['jev']['model']}` "
          f"(key status: {g['jev_key_status']}).\n")
        w("| Metric | Value |\n|---|---|")
        w(f"| Scenarios run | {s['scenarios_run']} |")
        w(f"| Schema valid (our validator) | {s['schema_valid']}/{s['scenarios_run']} = "
          f"{s['schema_valid'] / max(s['scenarios_run'], 1):.2f} |")
        w(f"| Accepted (schema valid and Jev ok) | {s['accepted']}/{s['scenarios_run']} |")
        w("| Jev verdicts | " + (", ".join(f"{k}: {v}" for k, v in sorted(s["jev_verdicts"].items())) or "none") + " |")
        w(f"| Model calls | {s['model_calls']} |")
        w(f"| Latency p50 / p95 per model call | {_fmt_ms(s['latency_ms_p50'])} / {_fmt_ms(s['latency_ms_p95'])} |")
        w(f"| Tokens in / out, all calls | {s['input_tokens']:,} / {s['output_tokens']:,} |")
        w(f"| Of which failed calls ({s['failed_call_count']}) in / out | "
          f"{s['failed_input_tokens']:,} / {s['failed_output_tokens']:,} ({_fmt_usd(s['failed_calls_cost_usd'])}) |")
        cpa, cpu = s["cost_per_accepted_survey_usd"], s["cost_per_accepted_survey_used_calls_only_usd"]
        none = "n/a (0 accepted)"
        w(f"| Cost per accepted survey, failed calls counted | {_fmt_usd(cpa) if cpa is not None else none} |")
        w(f"| Cost per accepted survey, successful calls only | {_fmt_usd(cpu) if cpu is not None else none} |")
        jevd = g["jev"]
        verdicts = s["jev_verdicts"]
        jev_up = verdicts.get("ok", 0) + verdicts.get("not_ok", 0) > 0
        w(f"| Jev pass count (verdict ok) | {verdicts.get('ok', 0)}/{s['scenarios_run']} |")
        w(f"| Jev | {'available' if jev_up else 'UNAVAILABLE'}; model `{jevd['model']}`; verdicts "
          + (", ".join(f"{k}: {v}" for k, v in sorted(verdicts.items())) or "none") + " |")
        w(f"| Cost per generated survey | {_fmt_usd(s['cost_per_generated_survey_usd'])} |")
        w(f"| Total spend of this run (Bedrock) | {_fmt_usd(s['total_cost_usd'])} |")
        w("")
        w(f"Prices used: ${m['price_input_per_m']} in / ${m['price_output_per_m']} out per 1M tokens, "
          "from the CLAUDE.md model table. They are **unverified**, so cost figures are estimates. "
          "Jev usage is not billed through Bedrock and is not in the total.\n")
        w("| Scenario | Status | Attempts | Schema | Jev | Calls ms | Tokens in/out | Cost |\n|---|---|---|---|---|---|---|---|")
        for row in g["scenarios"]:
            if row["status"] == "skipped":
                w(f"| {row['scenario']} | skipped ({row['reason']}) | | | | | | |")
                continue
            j = row["jev"]
            jt = "no verdict" if j is None else ("pending_review: " + str(j["reason"])) if j["pending_review"] \
                else "ok" if j["ok"] else f"not ok: {j['reason']}"
            tin = sum(c["input_tokens"] for c in row["calls"])
            tout = sum(c["output_tokens"] for c in row["calls"])
            ms = "/".join(str(c["latency_ms"]) for c in row["calls"]) or "n/a"
            w(f"| {row['scenario']} | {row['status']} | {row['attempts']} | "
              f"{'valid' if row['schema_valid'] else 'invalid'} | {jt} | {ms} | {tin}/{tout} | {_fmt_usd(row['cost_usd'])} |")
        w("")
        findings = []
        ran = [r for r in g["scenarios"] if r["status"] != "skipped"]
        jev_errs = Counter(r["jev"]["reason"] for r in ran if r["jev"] and r["jev"]["pending_review"])
        for reason, n in sorted(jev_errs.items()):
            findings.append(f"Jev did not return scores on {n} of {len(ran)} surveys ({reason}). Those verdicts are "
                            "`pending_review` from a Jev error, not a quality judgment, so they say nothing about "
                            "the surveys and nothing was accepted because of them.")
        for r in ran:
            if r["status"] == "failed_review":
                stops = ", ".join(str(c.get("stop_reason")) for c in r["calls"]) or "no response"
                findings.append(f"{r['scenario']}: failed review after {r['attempts']} attempts "
                                f"({'; '.join(r['reasons'])}). Stop reasons of the metered responses: {stops}.")
        for e in g["jev"]["http_errors"]:
            findings.append(f"Jev HTTP {e['status']}, exact response body (capped at 2,000 characters): "
                            f"`{e['body']}`")
        if s["unmetered_calls_estimated"]:
            findings.append(f"{s['unmetered_calls_estimated']} call(s) raised before any response; they are counted "
                            "at the median input tokens of the metered calls and no output (estimate).")
        for r in ran:
            if r["attempts"] > 1 and r["status"] != "failed_review":
                stops = ", ".join(str(c.get("stop_reason")) for c in r["calls"])
                findings.append(f"{r['scenario']} needed {r['attempts']} attempts; the retry produced the accepted "
                                f"survey. First-attempt reasons: {'; '.join(x for x in r['reasons'] if x.startswith('attempt1'))}. "
                                f"Stop reasons per call: {stops}; output tokens per call: "
                                f"{', '.join(str(c['output_tokens']) for c in r['calls'])} (max_tokens {g.get('max_tokens')}).")
        scored = [(r["jev"]["scores"].get("matches_advice"), r["scenario"]) for r in ran
                  if r["jev"] and r["jev"]["scores"].get("matches_advice") is not None]
        if scored:
            low = min(scored)
            findings.append(f"Closest Jev score to its threshold: matches_advice {low[0]} on {low[1]} "
                            "(accept needs at least the matches_advice threshold, 0.5 by default; the other four "
                            "checks must be at or below theirs).")
        findings.append("Token counts are all input tokens per call (Converse `totalTokens` minus output), cached "
                        "or not; spend covers every response received, failed parses included. A call that raised "
                        "before any response carries no usage and is not metered.")
        w("Findings:\n")
        for f in findings:
            w(f"- {f}")
        w("")

    # model selection
    w("## 5. Model selection\n")
    md = (ROOT / "models/results/model_select.md").read_text(encoding="utf-8").splitlines()
    table = [ln for ln in md if ln.startswith("|")]
    pick = [ln for ln in md if ln.startswith(("- generation:", "- retry:"))]
    intro = next((ln for ln in md if ln.startswith("Eval:")), "")
    w(intro + "\n")
    w("\n".join(table) + "\n")
    w("\n".join(pick) + "\n")

    # inventory
    w("## 6. AWS resource inventory\n")
    if inventory is None:
        w(f"NOT RUN: {res['inventory_skipped']}\n")
    else:
        w(f"Region {inventory['region']}. CDK stack outputs, then `aws resourcegroupstaggingapi get-resources` "
          f"filtered by tag `{inventory['tag']}`.\n")
        w("### CDK stack outputs\n")
        if any(inventory["stack_outputs"].values()):
            w("| Stack | Output | Value |\n|---|---|---|")
            for stack, outs in sorted(inventory["stack_outputs"].items()):
                for k, v in sorted(outs.items()):
                    w(f"| {stack} | {k} | `{v}` |")
        else:
            w("The deployed stacks define no CloudFormation outputs; cross-stack values are the `/mel/*` SSM "
              "parameters listed in `infra/INFRA.md`. Stacks found: "
              + ", ".join(sorted(inventory["stack_outputs"])) + ".")
        w("")
        w(f"### Tagged resources ({len(inventory['tagged_arns'])})\n")
        for arn in inventory["tagged_arns"]:
            w(f"- `{arn}`")
        w("\nResources that do not support tagging (for example API Gateway routes and the AgentCore endpoint) "
          "inherit ownership through their parent stack; `infra/INFRA.md` lists them.\n")

    # security
    w("## 7. Security controls and the test that proves each\n")
    w("`make test` runs `tests/` offline. Paths starting `infra/` are CDK template and script tests run with "
      "`pytest infra/test_contract.py`.\n")
    w("| Control | Proof |\n|---|---|")
    for control, tests in CONTROLS:
        missing = [t for t in tests if not control_test_exists(t)]
        if missing:
            raise SystemExit(f"report refused: test not found: {missing}")
        w(f"| {control} | " + "<br>".join(f"`{t}`" for t in tests) + " |")
    w("\nControls with no unit test, verified live or by configuration only:\n")
    w("- API Gateway stage throttle (rate 1, burst 10), access logs and request payload validation: "
      "defined in CDK; HTTP API has no native request validation, so payload validation is in the Lambda "
      "(`tests/test_intake.py::test_invalid_request`). See `infra/INFRA.md`.")
    w("- Unauthenticated requests are rejected: live smoke result (HTTP 401) recorded in `infra/INFRA.md`.")
    w("")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="skip the AWS sections")
    ap.add_argument("--skip-generation", action="store_true",
                    help="AWS read-only inventory but no paid model calls (keeps any earlier generation result)")
    ap.add_argument("--report-only", action="store_true", help="rebuild REPORT.md from evidence/*.json")
    args = ap.parse_args(argv)
    EVIDENCE.mkdir(exist_ok=True)
    result_path, inv_path = EVIDENCE / "survey_eval.json", EVIDENCE / "inventory.json"

    if args.report_only:
        res = json.loads(result_path.read_text())
        inv = json.loads(inv_path.read_text()) if inv_path.exists() else None
    else:
        res = {"generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
               "rules": eval_rules(), "timing": eval_timing(), "outcomes": eval_outcomes(),
               "generation": None, "generation_skipped": "", "inventory_skipped": ""}
        inv = None
        ok, why = (False, "--offline given") if args.offline else aws_identity()
        if ok:
            if args.skip_generation:
                res["generation_skipped"] = "generation not run in this invocation (--skip-generation)"
                prev = json.loads(result_path.read_text()) if result_path.exists() else {}
                res["generation"] = prev.get("generation")
            else:
                res["generation"] = eval_generation()
            inv = eval_inventory()
        else:
            res["generation_skipped"] = res["inventory_skipped"] = f"no AWS credentials ({why})"
        result_path.write_text(json.dumps(res, indent=2) + "\n")
        if inv is not None:
            inv_path.write_text(json.dumps(inv, indent=2) + "\n")

    (EVIDENCE / "REPORT.md").write_text(build_report(res, inv), encoding="utf-8")
    s = res["generation"]["summary"] if res.get("generation") else None
    print(f"rules {res['rules']['matched']}/{res['rules']['total']}; "
          f"timing golden_v1 {res['timing']['golden_v1']['matched']}/{res['timing']['r8_rows']}; "
          f"outcomes {res['outcomes']['passed']}/{res['outcomes']['total']}")
    if s:
        cpa = s["cost_per_accepted_survey_usd"]
        print(f"generation accepted {s['accepted']}/{s['scenarios_run']}; schema {s['schema_valid']}/{s['scenarios_run']}; "
              f"cost per accepted survey {_fmt_usd(cpa) if cpa is not None else 'n/a (0 accepted)'}; "
              f"total spend {_fmt_usd(s['total_cost_usd'])}")
    else:
        print(f"generation/inventory not run: {res['generation_skipped']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
