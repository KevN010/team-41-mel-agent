"""Model selection eval: pick the cheapest candidate that writes valid surveys.

For each candidate profile that answered in models/day0.json, for each actionable pack
scenario, N runs: call Converse with evals/prompt_v0.md and the insight, require strict JSON,
assemble a full survey, validate it against pack survey.schema.json plus the invariants
below. Score = pass rate. Writes models/models.yaml and models/results/model_select.{md,json}.

    .venv/bin/python evals/model_select.py              # full run (needs AWS credentials)
    .venv/bin/python evals/model_select.py --selftest   # offline: check validator on golden surveys

Prices are USD per 1M tokens (input, output). Unverified prices are marked in every output.
Insight text is untrusted data: it goes in the user turn only and is never printed or stored.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
REGION = "us-west-2"
MAX_TOKENS = 600
MIN_INTERVAL_S = 1.05  # 60 requests/minute process-wide
PASS_THRESHOLD = 0.9

SCHEMA = json.loads((ROOT / "pack/json/schemas/survey.schema.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA)

# (input $/1M, output $/1M, source, verified). None = no price known.
PRICES: dict[str, tuple[float, float, str, bool] | None] = {
    "openai.gpt-6-luna": (0.10, 0.50, "CLAUDE.md model table (marked 'verify')", False),
    "openai.gpt-6.1-terra": (1.00, 5.00, "CLAUDE.md model table (~, OpenAI list; Bedrock card unconfirmed)", False),
    "openai.gpt-6.1-luna": None,
    "anthropic.claude-haiku-4-5-20251001-v1:0": (1.00, 5.00, "Anthropic list price, not in CLAUDE.md", False),
    "anthropic.claude-haiku-5-5": None,
}

# Strict-mode generation schema with no nullable fields: bad-outcome options and scale items
# are separate anyOf variants, so the model never spends tokens on null placeholders.
_REASONS = ["advice_did_not_work", "crop_or_animal_damaged", "could_not_get_input", "could_not_reach_expert"]
_OPT = {"type": "object", "additionalProperties": False, "required": ["value", "label"],
        "properties": {"value": {"type": "string"}, "label": {"type": "string"}}}
_OPT_BAD = {"type": "object", "additionalProperties": False, "required": ["value", "label", "follow_up"],
            "properties": {"value": {"type": "string"}, "label": {"type": "string"},
                           "follow_up": {"type": "string", "enum": _REASONS}}}
_CHOICE_ITEM = {
    "type": "object", "additionalProperties": False, "required": ["item_id", "type", "prompt", "options"],
    "properties": {
        "item_id": {"type": "string"},
        "type": {"type": "string", "enum": ["survey-single-select", "survey-confirm"]},
        "prompt": {"type": "string"},
        "options": {"type": "array", "items": {"anyOf": [_OPT, _OPT_BAD]}},
    },
}
_SCALE_ITEM = {
    "type": "object", "additionalProperties": False,
    "required": ["item_id", "type", "prompt", "scale_min", "scale_max", "follow_up_at_or_below", "follow_up_reason"],
    "properties": {
        "item_id": {"type": "string"},
        "type": {"type": "string", "enum": ["survey-scale"]},
        "prompt": {"type": "string"},
        "scale_min": {"type": "integer"},
        "scale_max": {"type": "integer"},
        "follow_up_at_or_below": {"type": "integer"},
        "follow_up_reason": {"type": "string", "enum": _REASONS},
    },
}
GEN_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items", "rationale"],
    "properties": {
        "items": {"type": "array", "items": {"anyOf": [_CHOICE_ITEM, _SCALE_ITEM]}},
        "rationale": {"type": "string"},
    },
}

INSIGHT_FIELDS = ["asset", "concern", "severity", "query_summary", "advice_summary", "resolution_type",
                  "action_window_days", "verification"]


def strip_nulls(o):
    if isinstance(o, dict):
        return {k: strip_nulls(v) for k, v in o.items() if v is not None}
    if isinstance(o, list):
        return [strip_nulls(v) for v in o]
    return o


def invariant_errors(survey: dict) -> list[str]:
    """Checks beyond the JSON schema, from the task prompt."""
    errs = []
    items = survey.get("items", [])
    if not 1 <= len(items) <= 3:
        errs.append("items count not in 1..3")
    ids = [i.get("item_id") for i in items]
    if len(set(ids)) != len(ids):
        errs.append("duplicate item_id")
    for it in items:
        opts = it.get("options")
        if opts is not None:
            if not 2 <= len(opts) <= 10:
                errs.append("options count not in 2..10")
            for o in opts:
                if len(o.get("label", "")) > 20:  # len() counts code points
                    errs.append("label longer than 20 code points")
        if it.get("type") == "survey-scale":
            lo, hi = it.get("scale_min"), it.get("scale_max")
            if isinstance(lo, int) and isinstance(hi, int) and hi - lo + 1 > 10:
                errs.append("scale has more than 10 steps")
    return errs


def validate(survey: dict) -> list[str]:
    errs = [f"{e.json_path}: {e.validator}" for e in VALIDATOR.iter_errors(survey)]
    return errs + invariant_errors(survey)


def assemble(generated: dict, scenario_dir: Path) -> dict:
    """Wrap model output into a full survey. Fixed fields come from code, never from the model."""
    insight = json.loads((scenario_dir / "insight.json").read_text())
    golden = json.loads((scenario_dir / "survey.en-IN.json").read_text())
    return {
        "survey_id": "S-99999",
        "farmer_id": insight["farmer_id"],
        "source_insight_ids": [insight["insight_id"]],
        "language": "en-IN",
        "send_window": golden["send_window"],  # timing is rules code, not an eval target
        "items": strip_nulls(generated.get("items", [])),
        "rationale": generated.get("rationale", ""),
    }


def user_turn(scenario_dir: Path) -> str:
    insight = json.loads((scenario_dir / "insight.json").read_text())
    slim = {k: insight.get(k) for k in INSIGHT_FIELDS}
    return "<insight>\n" + json.dumps(slim, ensure_ascii=False, indent=2) + "\n</insight>"


def base_id(profile: str) -> str:
    return re.sub(r"^(global|us|eu|apac)\.", "", profile)


def is_claude(profile: str) -> bool:
    return "anthropic.claude" in profile


def parse_output(resp: dict, claude: bool):
    blocks = resp["output"]["message"]["content"]
    if claude:
        for b in blocks:
            if "toolUse" in b:
                return b["toolUse"]["input"]
    text = "".join(b["text"] for b in blocks if "text" in b).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    return json.loads(text)


REASONING_EFFORT = "low"  # OpenAI models only; dropped automatically if Bedrock rejects it


def call_model(rt, profile: str, system: str, user: str, features: set[str]):
    """features (OpenAI only): "format" = strict json_schema output, "reasoning" = low reasoning effort."""
    kwargs = dict(
        modelId=profile,
        system=[{"text": system}],
        messages=[{"role": "user", "content": [{"text": user}]}],
        inferenceConfig={"maxTokens": MAX_TOKENS},
    )
    if is_claude(profile):
        kwargs["toolConfig"] = {
            "tools": [{"toolSpec": {"name": "submit_survey", "description": "Submit the survey.",
                                    "inputSchema": {"json": GEN_SCHEMA}}}],
            "toolChoice": {"tool": {"name": "submit_survey"}},
        }
    else:
        extra = {}
        if "format" in features:
            extra["text"] = {"format": {"type": "json_schema", "name": "survey", "strict": True,
                                        "schema": GEN_SCHEMA}}
        if "reasoning" in features:
            extra["reasoning"] = {"effort": REASONING_EFFORT}
        if extra:
            kwargs["additionalModelRequestFields"] = extra
    return rt.converse(**kwargs)


def pick_profiles(day0: dict) -> list[str]:
    """One working profile per model, preferring global.* over regional."""
    best: dict[str, str] = {}
    for profile, r in day0.items():
        if not r.get("ok"):
            continue
        b = base_id(profile)
        if b not in best or profile.startswith("global."):
            best[b] = profile
    return list(best.values())


def error_code(e: Exception) -> str:
    """Error text safe to store: an AWS error code, never message text that could echo the request."""
    resp = getattr(e, "response", None)
    if isinstance(resp, dict):
        return resp.get("Error", {}).get("Code", "unknown")
    return "parse" if isinstance(e, ValueError) else "unknown"


def percentile50(xs):
    return statistics.median(xs) if xs else None


def run_eval(runs: int, only: list[str] | None):
    import boto3  # imported late so --selftest works without credentials

    day0 = json.loads((ROOT / "models/day0.json").read_text())
    profiles = pick_profiles(day0)
    if only:
        profiles = [p for p in profiles if any(o in p for o in only)]
    system = (ROOT / "evals/prompt_v0.md").read_text()
    scenarios = sorted(d for d in (ROOT / "pack/json/scenarios").iterdir() if (d / "survey.en-IN.json").exists())
    rt = boto3.client("bedrock-runtime", region_name=REGION)
    last_call = 0.0
    results = {}
    for profile in profiles:
        features = {"format", "reasoning"} if REASONING_EFFORT else {"format"}
        dropped: list[str] = []
        rows = []
        for sc in scenarios:
            user = user_turn(sc)
            for n in range(runs):
                row = {"scenario": sc.name, "run": n, "pass": False, "errors": []}
                t = time.perf_counter()
                try:
                    resp = None
                    for _attempt in range(3):
                        wait = MIN_INTERVAL_S - (time.monotonic() - last_call)
                        if wait > 0:
                            time.sleep(wait)
                        last_call = time.monotonic()
                        try:
                            resp = call_model(rt, profile, system, user, features)
                            break
                        except Exception as e:
                            # An OpenAI request field Bedrock does not accept: drop that feature, retry.
                            msg = str(e)
                            culprit = next((f for f, kw in (("reasoning", "reasoning"), ("format", "format|text"))
                                            if f in features and re.search(kw, msg)), None)
                            if is_claude(profile) or "ValidationException" not in msg or culprit is None:
                                raise
                            features.discard(culprit)
                            dropped.append(f"{culprit}: {error_code(e)}")
                    row["ms"] = round((time.perf_counter() - t) * 1000)
                    u = resp["usage"]
                    # cached input still costs something; count it at the full rate (upper bound)
                    row["in_tokens"] = u["inputTokens"] + u.get("cacheReadInputTokens", 0) + u.get("cacheWriteInputTokens", 0)
                    row["out_tokens"] = u["outputTokens"]
                    row["stop_reason"] = resp.get("stopReason")
                    survey = assemble(parse_output(resp, is_claude(profile)), sc)
                    row["errors"] = validate(survey)
                    row["pass"] = not row["errors"]
                except Exception as e:
                    row["ms"] = round((time.perf_counter() - t) * 1000)
                    row["errors"] = [f"call_or_parse_error: {type(e).__name__}: {error_code(e)}"]
                rows.append(row)
                print(profile, sc.name, n, "PASS" if row["pass"] else "FAIL", row.get("in_tokens"),
                      row.get("out_tokens"), row.get("stop_reason"), row["ms"], flush=True)
        results[profile] = summarise(profile, rows)
        results[profile]["features_dropped"] = dropped
        results[profile]["features_used"] = sorted(features) if not is_claude(profile) else ["tool_use"]
    return results


def summarise(profile: str, rows: list[dict]) -> dict:
    ok = [r for r in rows if r["pass"]]
    done = [r for r in rows if "in_tokens" in r]
    price = PRICES.get(base_id(profile))
    s = {
        "profile": profile,
        "runs": len(rows),
        "accepted": len(ok),
        "pass_rate": len(ok) / len(rows) if rows else 0.0,
        "avg_in_tokens": statistics.mean(r["in_tokens"] for r in done) if done else None,
        "avg_out_tokens": statistics.mean(r["out_tokens"] for r in done) if done else None,
        "latency_p50_ms": percentile50([r["ms"] for r in rows if "ms" in r]),
        "max_tokens_stops": sum(r.get("stop_reason") == "max_tokens" for r in rows),
        "price": None,
        "cost_total": None,
        "cost_per_accepted": None,
        "failures": {},
        "rows": rows,
    }
    for r in rows:
        for e in r["errors"]:
            key = re.sub(r"\d+", "N", e)[:120]
            s["failures"][key] = s["failures"].get(key, 0) + 1
    if price and done:
        pin, pout, src, verified = price
        s["price"] = {"input_per_m": pin, "output_per_m": pout, "source": src, "verified": verified}
        s["cost_total"] = sum(r["in_tokens"] * pin + r["out_tokens"] * pout for r in done) / 1e6
        s["cost_per_accepted"] = s["cost_total"] / len(ok) if ok else None
    return s


def select(results: dict):
    eligible = [r for r in results.values() if r["pass_rate"] >= PASS_THRESHOLD]
    priced = sorted((r for r in eligible if r["cost_per_accepted"] is not None), key=lambda r: r["cost_per_accepted"])
    if not priced:
        return None, None, eligible
    gen = priced[0]
    # retry tier: next-cheapest eligible profile with at least the same pass rate; else the same profile
    retry = next((r for r in priced[1:] if r["pass_rate"] >= gen["pass_rate"]), gen)
    return gen, retry, eligible


def fmt_money(x):
    return "n/a" if x is None else f"${x:.6f}"


def write_outputs(results: dict, runs: int):
    gen, retry, eligible = select(results)
    (ROOT / "models/results").mkdir(parents=True, exist_ok=True)
    (ROOT / "models/results/model_select.json").write_text(json.dumps(results, indent=2))
    lines = [
        "# Model selection results", "",
        f"Eval: {len(next(iter(results.values()))['rows']) // runs if results else 0} actionable pack scenarios x {runs} runs, "
        f"Converse in {REGION}, max_tokens {MAX_TOKENS}, prompt evals/prompt_v0.md. "
        f"Pass = full survey validates against pack survey.schema.json and the invariants "
        f"(1..3 items, unique item_id, 2..10 options, label <= 20 code points, scale <= 10 steps).", "",
        "| Profile | Pass rate | Avg in tok | Avg out tok | Latency p50 ms | Price in/out per 1M | Cost per call | Cost per accepted survey | Hit max_tokens |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(results.values(), key=lambda r: -r["pass_rate"]):
        p = r["price"]
        price = "unpriced" if not p else f"${p['input_per_m']}/${p['output_per_m']}" + ("" if p["verified"] else " (unverified)")
        per_call = None if r["cost_total"] is None else r["cost_total"] / r["runs"]
        lines.append(
            f"| {r['profile']} | {r['accepted']}/{r['runs']} = {r['pass_rate']:.2f} | "
            f"{r['avg_in_tokens'] and round(r['avg_in_tokens'])} | {r['avg_out_tokens'] and round(r['avg_out_tokens'])} | "
            f"{r['latency_p50_ms'] and round(r['latency_p50_ms'])} | {price} | {fmt_money(per_call)} | "
            f"{fmt_money(r['cost_per_accepted'])} | {r['max_tokens_stops']}/{r['runs']} |")
    lines += ["", "## Most common failures", ""]
    for r in results.values():
        top = sorted(r["failures"].items(), key=lambda kv: -kv[1])[:3]
        lines.append(f"- {r['profile']}: " + ("none" if not top else "; ".join(f"{k} (x{v})" for k, v in top)))
    lines += ["", "## Request features", ""]
    for r in results.values():
        dropped = r.get("features_dropped") or []
        lines.append(f"- {r['profile']}: used {', '.join(r.get('features_used', []))}"
                     + (f"; rejected by Bedrock and dropped: {'; '.join(dropped)}" if dropped else ""))
    lines += ["", "## Pick", ""]
    if gen is None:
        lines.append("No candidate reached a 0.9 pass rate with a known price. See NOTES-MODEL.md.")
    else:
        lines.append(f"- generation: {gen['profile']}")
        lines.append(f"- retry: {retry['profile']}")
        lines.append(f"- {gen['profile']}: pass rate {gen['pass_rate']:.2f}, "
                     f"{fmt_money(gen['cost_per_accepted'])} per accepted survey.")
    unpriced = [r["profile"] for r in eligible if r["cost_per_accepted"] is None]
    if unpriced:
        lines.append(f"- Passed but not ranked, no price known: {', '.join(unpriced)}.")
    (ROOT / "models/results/model_select.md").write_text("\n".join(lines) + "\n")
    if gen is None:
        return
    prices = {}
    for r in (gen, retry):
        prices[r["profile"]] = r["price"]
    cfg = {
        "generation": gen["profile"],
        "retry": retry["profile"],
        "region": REGION,
        "max_tokens": MAX_TOKENS,
        "prices": prices,
        "chosen_because": (
            f"{gen['profile']} passed {gen['accepted']}/{gen['runs']} ({gen['pass_rate']:.2f}) at "
            f"{fmt_money(gen['cost_per_accepted'])} per accepted survey"
            + ("" if gen["price"]["verified"] else " (price unverified)")
            + f"; retry {retry['profile']} passed {retry['accepted']}/{retry['runs']}."
        ),
    }
    (ROOT / "models/models.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))


def selftest() -> int:
    """Offline: golden en-IN surveys must pass our validator; mutations must fail."""
    bad = 0
    for sc in sorted((ROOT / "pack/json/scenarios").iterdir()):
        f = sc / "survey.en-IN.json"
        if not f.exists():
            continue
        survey = json.loads(f.read_text())
        survey.pop("self_eval", None)
        errs = validate(survey)
        print(sc.name, "golden:", "ok" if not errs else errs)
        bad += bool(errs)
        # the null-free generation schema must admit what the pack's own golden items look like
        gen_errs = [e.message[:80] for e in Draft202012Validator(GEN_SCHEMA).iter_errors(
            {"items": survey["items"], "rationale": survey["rationale"]})]
        print(sc.name, "golden fits generation schema:", "ok" if not gen_errs else gen_errs)
        bad += bool(gen_errs)
        survey["items"][0]["options"] = [{"value": "x", "label": "this label is far too long"}] * 2
        mutated = validate(survey)
        print(sc.name, "mutation caught:", bool(mutated))
        bad += not mutated
    # model-shaped output round trip: nulls stripped
    gen = {"items": [{"item_id": "q1", "type": "survey-confirm", "prompt": "Did you spray?",
                      "options": [{"value": "yes", "label": "Yes"}, {"value": "no", "label": "No"}]}],
           "rationale": "r"}
    bad += bool(list(Draft202012Validator(GEN_SCHEMA).iter_errors(gen)))
    first = next(d for d in sorted((ROOT / "pack/json/scenarios").iterdir()) if (d / "survey.en-IN.json").exists())
    errs = validate(assemble(gen, first))
    print("model-shaped output:", "ok" if not errs else errs)
    bad += bool(errs)
    return 1 if bad else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--only", nargs="*", help="substring filter on profile ids")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--reasoning-effort", default=REASONING_EFFORT, help="OpenAI only; '' to disable")
    ap.add_argument("--price", action="append", default=[], metavar="MODEL=IN,OUT",
                    help="override a price (USD per 1M), e.g. anthropic.claude-haiku-5-5=1,5")
    a = ap.parse_args()
    for spec in a.price:
        k, v = spec.split("=")
        pin, pout = (float(x) for x in v.split(","))
        PRICES[k] = (pin, pout, "command-line override", False)
    REASONING_EFFORT = a.reasoning_effort
    if a.selftest:
        sys.exit(selftest())
    res = run_eval(a.runs, a.only)
    write_outputs(res, a.runs)
    print((ROOT / "models/results/model_select.md").read_text())
