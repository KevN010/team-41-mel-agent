# NOTES-A (rules)

- `decide(insight, clock, calendar, rules, *, profile=None, window_fn=None)`. The two keyword-only
  arguments are additions to the prompt's signature. R8's `send_window` comes from `window_fn`;
  the default lazily imports `mel.timing.send_window(insight, profile, clock, rules)` and returns
  `None` when that module does not exist yet (wave 1 B). Integration should check the default
  wiring once B has merged. A `TimingException` from B is not caught here; `rules_v1` can raise it
  for an R8 row. Integration decides what that maps to.
- `DecisionRecord.created_at` is the decision time (`clock.now()`), not the insight's `created_at`.
- R6 compares dates: created date + lo days of the timing bucket, strictly after 2027-03-31.
  For timing `none` the start is created + action_window_days (default 2 when null) + 1 day.
  Season end is read from `rules.json window_rules.season_end`.
- R7 uses `>=` on the created date. It applies only to `asset.category == "crop"` with a name in the
  calendar. Crops not in the calendar fall through to R8.
- R1 fires for schema failures. Ids missing from a bad dict become `"unknown"` so the record still builds.
- Pack disagreement: none found. 150/150 on golden v1, including the R7 `>=` reading.
