# restart

Restart check: the AgentCore Runtime was redeployed (new version), then the survey written by
the e2e run was read back through the new deployment.

- Runtime: `arn:aws:bedrock-agentcore:us-west-2:423964648384:runtime/mel_agent-vUpOFqHRb4`
- Runtime version after redeploy: `4`, updated `2026-11-05 12:34:02.945384+00:00`
- Container: `423964648384.dkr.ecr.us-west-2.amazonaws.com/mel-agent:deploy-20261105123353-runtime`
- Org: `org.e2e-20261105123310`

## Calls

| action | farmer | status | latency ms | runtime session | trace id sent (X-Ray format) |
|---|---|---|---|---|---|
| get_survey | F-000245 | 200 | 5823 | `mel-restart-3769c2bf14bd3e30468aba07` | `1-6aec77bd-260a839c40bf37dd90969fe8` |

### get_survey (200)

```json
{
  "survey": {
    "survey_id": "S-00001",
    "farmer_id": "F-000245",
    "source_insight_ids": [
      "I-005330"
    ],
    "language": "en-IN",
    "send_window": {
      "not_before": "2027-01-08T09:00:00+05:30",
      "not_after": "2027-01-11T19:00:00+05:30"
    },
    "items": [
      {
        "item_id": "q1",
        "type": "survey-confirm",
        "prompt": "Did you check the lower potato leaves each morning for 3 days?",
        "options": [
          {
            "value": "yes",
            "label": "Yes"
          },
          {
            "value": "no",
            "label": "No"
          }
        ]
      },
      {
        "item_id": "q2",
        "type": "survey-single-select",
        "prompt": "What do you see on the lower potato leaves now?",
        "options": [
          {
            "value": "no_new_spots",
            "label": "No new spots"
          },
          {
            "value": "same",
            "label": "Same as before"
          },
          {
            "value": "spreading",
            "label": "Spreading",
            "follow_up": "crop_or_animal_damaged"
          },
          {
            "value": "white_growth",
            "label": "White under leaves",
            "follow_up": "crop_or_animal_damaged"
          }
        ]
      }
    ],
    "rationale": "Wait-and-monitor advice for possible potato leaf disease. Ask whether the farmer checked the leaves and whether spots have spread or white growth has appeared.",
    "self_eval": {
      "schema_valid": true,
      "relevance_score": 0.97,
      "gives_new_advice": false,
      "asks_personal_info": false
    }
  }
}
```
