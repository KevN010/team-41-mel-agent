# NOTES-F (mel/judge.py)

## Thresholds chosen
All five use the `settings` defaults, 0.5. I did not change them.
- Jev is described as calibrated, so 0.5 is the unbiased cut. There is no real Jev traffic to tune against yet.
- Rule: ok iff `matches_advice >= t` and `gives_new_advice`, `asks_personal_info`, `inappropriate_content`, `language_matches_tag` are each `<= t`. Both bounds are inclusive.
- Errors cost little (a pending_review), a missed new-advice or personal-info case costs more. After the eval run, consider `JEV_THRESHOLD_GIVES_NEW_ADVICE`, `..._ASKS_PERSONAL_INFO`, `..._INAPPROPRIATE_CONTENT` at 0.3 via env. No code change needed.

## Problems with files I do not own
- `language_matches_tag` direction: the task says all four non-`matches_advice` checks pass when `<= t`. A check named "matches" would normally be good when high. I wrote the question as a mismatch ("is the text in a language other than the tag?"), so the stored score is P(mismatch) and low is good. Anyone reading `JudgeVerdict.scores["language_matches_tag"]` must know this.
- `mel/settings.py` has no `JEV_MODEL`, `JEV_MAX_RETRIES` or `JEV_DEADLINE_S`. The reference sends `model` in the payload. I omit `model` unless the constructor arg or the `JEV_MODEL` env var is set. If System One needs it, the integration agent must set `JEV_MODEL`. Retries (2) and the total deadline (6 s) are module constants in `mel/judge.py`.
- `.venv` was created with Python 3.13 in this cloud container; CLAUDE.md says 3.12. Nothing in `mel/judge.py` needs 3.13.
- `survey.rationale` and `self_eval` are model-written text. They are not sent to Jev (the task lists only items). Add them if the review wants them checked.
