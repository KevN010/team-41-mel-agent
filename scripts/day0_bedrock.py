"""Day 0: prove each candidate model answers from us-west-2 via Converse. Writes models/day0.json."""
import json, time, boto3, sys
REGION = "us-west-2"
CANDIDATES = ["global.openai.gpt-6-luna", "global.openai.gpt-6.1-terra", "global.openai.gpt-6.1-luna"]
# Add the Claude Haiku profile id from models/candidates.txt here if present.
try:
    for line in open("models/candidates.txt"):
        if "haiku" in line and "anthropic" in line:
            CANDIDATES.append(line.strip().strip('",'))
except FileNotFoundError:
    pass
rt = boto3.client("bedrock-runtime", region_name=REGION)
out = {}
for m in CANDIDATES:
    t = time.perf_counter()
    try:
        r = rt.converse(modelId=m, messages=[{"role": "user", "content": [{"text": "Reply with the single word OK."}]}],
                        inferenceConfig={"maxTokens": 8})
        out[m] = {"ok": True, "text": r["output"]["message"]["content"][0]["text"], "usage": r.get("usage"),
                  "ms": round((time.perf_counter() - t) * 1000)}
    except Exception as e:
        out[m] = {"ok": False, "error": str(e)[:300]}
    print(m, out[m])
json.dump(out, open("models/day0.json", "w"), indent=2)
sys.exit(0 if any(v["ok"] for v in out.values()) else 1)
