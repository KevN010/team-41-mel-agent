"""Day 0: prove each candidate model answers from us-west-2 via Converse. Writes models/day0.json."""
import json, time, boto3, sys
REGION = "us-west-2"
CANDIDATES = ["global.openai.gpt-6-luna", "global.openai.gpt-6.1-terra"]


def _summaries():
    """models/candidates.txt is the JSON output of `aws bedrock list-foundation-models`."""
    try:
        return json.load(open("models/candidates.txt")).get("modelSummaries", [])
    except (FileNotFoundError, ValueError):
        return []


_ids = {m["modelId"] for m in _summaries()}
# gpt-6.1-luna is a candidate only if the account's model list contains it.
if "openai.gpt-6.1-luna" in _ids:
    CANDIDATES.append("global.openai.gpt-6.1-luna")
# Claude Haiku models are INFERENCE_PROFILE only, so try the global profile, then the US one.
for mid in sorted(_ids):
    if mid.startswith("anthropic.claude-haiku"):
        CANDIDATES.extend([f"global.{mid}", f"us.{mid}"])

rt = boto3.client("bedrock-runtime", region_name=REGION)
out = {}
for m in CANDIDATES:
    t = time.perf_counter()
    try:
        # OpenAI models reject max output tokens below 16.
        r = rt.converse(modelId=m, messages=[{"role": "user", "content": [{"text": "Reply with the single word OK."}]}],
                        inferenceConfig={"maxTokens": 16})
        text = "".join(b["text"] for b in r["output"]["message"]["content"] if "text" in b)
        out[m] = {"ok": True, "text": text, "usage": r.get("usage"),
                  "ms": round((time.perf_counter() - t) * 1000)}
    except Exception as e:
        out[m] = {"ok": False, "error": str(e)[:300]}
    print(m, out[m])
json.dump(out, open("models/day0.json", "w"), indent=2)
sys.exit(0 if any(v["ok"] for v in out.values()) else 1)
