Model: Sonnet. Branch: w1-F.
Goal: Jev survey checks, reusing the existing FarmerChat pattern.
Read first: CLAUDE.md, reference_jev_service.py (whole file), mel/protocols.py (Judge), pack/json/scenarios/3-potato-blight-wait/insight.json and survey.en-IN.json.
You own: mel/judge.py, tests/test_judge.py, NOTES-F.md.
Deliver: JevJudge implementing Judge. One POST to settings.JEV_URL with state = {insight: {query_summary,
advice_summary, resolution_type, concern, asset}, survey: {items}} and five noul questions:
matches_advice, gives_new_advice, asks_personal_info, inappropriate_content, language_matches_tag.
Copy the _noul helper, timeout, deadline, retry set and ALLOWED_HOSTS behaviour from the reference.
Verdict ok iff matches_advice >= t and each of the other four <= its threshold (settings). Validate every
value is a finite float in [0,1]; otherwise verdict = pending_review. On timeout or non-2xx after retries:
pending_review, never ok. The key comes from an env var populated from Secrets Manager; never log it.
tests: httpx MockTransport; cases for ok, each failing check, timeout, malformed JSON, NaN, wrong host.
Done when: tests pass. Report: thresholds you chose and why.
