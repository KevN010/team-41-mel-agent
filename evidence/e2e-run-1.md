# e2e-run-1

Real run against the deployed stack in us-west-2 (account 423964648384), through the AgentCore
Runtime with IAM SigV4. Scenario 3 (potato) and scenario 6 (no survey).

- Runtime: `arn:aws:bedrock-agentcore:us-west-2:423964648384:runtime/mel_agent-vUpOFqHRb4`
- DynamoDB table: `mel-ledger`
- Org (fresh per run): `org.e2e-20261105123310`
- Survey: `S-00001`

## Calls

| action | farmer | status | latency ms | runtime session | trace id sent (X-Ray format) |
|---|---|---|---|---|---|
| clock | F-000245 | 200 | 5736 | `mel-e2e-20261105123310-f6fe906b1e4966d5` | `1-6aec7787-cf839a705d79ae6bce52f39c` |
| decide | F-000245 | 201 | 3708 | `mel-e2e-20261105123310-f6fe906b1e4966d5` | `1-6aec778c-6052b47569485588cec3bae8` |
| get_survey | F-000245 | 200 | 170 | `mel-e2e-20261105123310-f6fe906b1e4966d5` | `1-6aec7790-880f108225ef1ff8fe1a8f8d` |
| clock | F-000245 | 200 | 172 | `mel-e2e-20261105123310-f6fe906b1e4966d5` | `1-6aec7790-2da5adea4b254c75a0de20d2` |
| respond | F-000245 | 201 | 235 | `mel-e2e-20261105123310-f6fe906b1e4966d5` | `1-6aec7791-7bb43e64e18f1195d6b1b0ba` |
| follow_ups | F-000245 | 200 | 174 | `mel-e2e-20261105123310-f6fe906b1e4966d5` | `1-6aec7791-0fe2d1682d9c181e350d90da` |
| decide | F-000519 | 200 | 193 | `mel-e2e-20261105123310-f6fe906b1e4966d5` | `1-6aec7791-a2a80c11bbf66b62e5e0c79a` |

### clock (200)

```json
{
  "now": "2027-01-06T08:04:59.915948+05:30",
  "offset_s": 5320903
}
```

### decide (201)

```json
{
  "status": "survey_scheduled",
  "decision": {
    "insight_id": "I-005330",
    "farmer_id": "F-000245",
    "survey": true,
    "rule_id": "R8",
    "reason_code": null,
    "timing_profile": "golden_v1",
    "send_window": {
      "not_before": "2027-01-08T09:00:00+05:30",
      "not_after": "2027-01-11T19:00:00+05:30"
    },
    "created_at": "2027-01-06T08:05:00+05:30"
  },
  "no_survey": null,
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
  },
  "handoff": {
    "handoff_id": "H-00001",
    "created_at": "2027-01-06T08:05:03+05:30",
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
    },
    "send_window": {
      "not_before": "2027-01-08T09:00:00+05:30",
      "not_after": "2027-01-11T19:00:00+05:30"
    },
    "send_hours": {
      "from": "07:00",
      "to": "19:00"
    },
    "channel_order": [
      {
        "channel": "web",
        "wait_hours": 24
      },
      {
        "channel": "app",
        "wait_hours": 24
      },
      {
        "channel": "whatsapp",
        "wait_hours": null
      }
    ],
    "frequency_cap": {
      "key": "mel:farmer:F-000245",
      "max_surveys": 1,
      "window_days": 7,
      "exempt": false
    },
    "priority": "normal",
    "expires_at": "2027-01-13T19:00:00+05:30",
    "farmerchat_flow": {
      "org_id": "org.farmerchat",
      "flow_key": "mel_s_00001",
      "version": 1,
      "campaign_id": "283df456-256d-5d97-912f-1a6c4fdde6d0",
      "flow_id": "673a8ca3-a996-5dff-9399-cc4c7343d170"
    }
  },
  "reasons": [
    "attempt1"
  ],
  "cost_usd": 0.0009048999999999999
}
```

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

### clock (200)

```json
{
  "now": "2027-01-08T09:59:59.968146+05:30",
  "offset_s": 5500599
}
```

### respond (201)

```json
{
  "response": {
    "response_key": "e2e-20261105123310-1",
    "survey_id": "S-00001",
    "farmer_id": "F-000245",
    "source_insight_ids": [
      "I-005330"
    ],
    "channel": "web",
    "language": "en-IN",
    "status": "negative_outcome",
    "failure_code": null,
    "answers": {
      "q2": "spreading"
    },
    "items": [
      {
        "item_id": "q1",
        "item_type": "survey-confirm",
        "result": "skipped",
        "value": null,
        "raw_input": null,
        "input_kind": null,
        "attempts": 1
      },
      {
        "item_id": "q2",
        "item_type": "survey-single-select",
        "result": "answered",
        "value": "spreading",
        "raw_input": null,
        "input_kind": null,
        "attempts": 1
      }
    ],
    "complete": false,
    "delivery_attempt": 1,
    "timestamps": {
      "sent": "2027-01-08T10:00:00+05:30",
      "delivered": null,
      "opened": null,
      "answered": "2027-01-08T10:00:00+05:30"
    },
    "recorded_at": "2027-01-08T10:00:00+05:30",
    "answered_by": "F-000245",
    "sheet_outcome": "closed_partway",
    "raw_event": null,
    "retry_decision": "none",
    "retry_after_minutes": null,
    "counts_toward_cap": true,
    "farmerchat_reply": {
      "http_status": 201,
      "outcome": "accepted"
    },
    "needs_follow_up": true,
    "follow_up_reasons": [
      "crop_or_animal_damaged"
    ]
  }
}
```

### follow_ups (200)

```json
{
  "items": [
    {
      "follow_up_id": "FU-S-00001-5507413106e7",
      "farmer_id": "F-000245",
      "survey_id": "S-00001",
      "response_key": "e2e-20261105123310-1",
      "source_insight_ids": [
        "I-005330"
      ],
      "reasons": [
        "crop_or_animal_damaged"
      ],
      "accepted_answers": {
        "q2": "spreading"
      },
      "created_at": "2027-01-08T10:00:00+05:30"
    }
  ]
}
```

### decide (200)

```json
{
  "status": "no_survey",
  "decision": {
    "insight_id": "I-004101",
    "farmer_id": "F-000519",
    "survey": false,
    "rule_id": "R3",
    "reason_code": "nothing_to_verify",
    "timing_profile": "golden_v1",
    "send_window": null,
    "created_at": "2027-01-08T10:00:00+05:30"
  },
  "no_survey": {
    "insight_id": "I-004101",
    "farmer_id": "F-000519",
    "decision": "no_survey",
    "reason_code": "generic_information",
    "reason": "No action was advised, so there is no advice to check on."
  },
  "survey": null,
  "handoff": null,
  "reasons": [],
  "cost_usd": 0.0
}
```

## CloudWatch log lines (runtime log group, mel.* loggers, metric lines left out)

```json
[
  {
    "ts": 1793881996916,
    "level": "INFO",
    "logger": "mel.service",
    "msg": "demo clock",
    "op": "set",
    "offset_s": 5320903
  },
  {
    "ts": 1793881998372,
    "level": "INFO",
    "logger": "mel.providers.bedrock",
    "msg": "model_call model=global.openai.gpt-6-luna in=2902 out=261 latency_ms=1202"
  },
  {
    "ts": 1793881998406,
    "level": "INFO",
    "logger": "mel.generate",
    "msg": "generate attempt",
    "insight_id": "I-005330",
    "survey_id": "S-00001",
    "model_id": "global.openai.gpt-6-luna",
    "model_key": "global.openai.gpt-6-luna",
    "input_tokens": 2902,
    "output_tokens": 261,
    "latency_ms": 1201.7,
    "attempt": 1
  },
  {
    "ts": 1793882000294,
    "level": "INFO",
    "logger": "mel.providers.bedrock",
    "msg": "model_call model=global.openai.gpt-6-luna in=2957 out=377 latency_ms=1888"
  },
  {
    "ts": 1793882000340,
    "level": "INFO",
    "logger": "mel.generate",
    "msg": "generate attempt",
    "insight_id": "I-005330",
    "survey_id": "S-00001",
    "model_id": "global.openai.gpt-6-luna",
    "model_key": "global.openai.gpt-6-luna",
    "input_tokens": 2957,
    "output_tokens": 377,
    "latency_ms": 1888.2,
    "attempt": 2
  },
  {
    "ts": 1793882000498,
    "level": "INFO",
    "logger": "mel.judge",
    "msg": "Jev verdict ok=True failed=[] latency_ms=82 scores={'matches_advice': 0.97, 'gives_new_advice': 0.06, 'asks_personal_info': 0.02, 'inappropriate_content': 0.02, 'language_matches_tag': 0.02}"
  },
  {
    "ts": 1793882000499,
    "level": "INFO",
    "logger": "mel.generate",
    "msg": "generate result",
    "status": "accepted",
    "insight_id": "I-005330",
    "survey_id": "S-00001",
    "model_keys": [
      "global.openai.gpt-6-luna",
      "global.openai.gpt-6-luna"
    ],
    "input_tokens": 5859,
    "output_tokens": 638,
    "cost_usd": 0.0009048999999999999,
    "attempts": 2,
    "reasons": [
      "attempt1: schema:$.items[1].options[3].label",
      "attempt1: $.items[1].options[3].label: 25 code points, at most 20 allowed (INV-LABEL)"
    ],
    "prompt_sha": "22e5048a640d"
  },
  {
    "ts": 1793882000617,
    "level": "INFO",
    "logger": "mel.service",
    "msg": "decision",
    "rule_id": "R8",
    "reason_code": null,
    "status": "survey_scheduled",
    "insight_id": "I-005330",
    "survey_id": "S-00001",
    "latency_ms": 3530.6,
    "cost_usd": 0.0009048999999999999
  },
  {
    "ts": 1793882000968,
    "level": "INFO",
    "logger": "mel.service",
    "msg": "demo clock",
    "op": "set",
    "offset_s": 5500599
  },
  {
    "ts": 1793882001147,
    "level": "INFO",
    "logger": "mel.intake",
    "msg": "intake stored",
    "status": "negative_outcome",
    "failure_code": null
  },
  {
    "ts": 1793882001205,
    "level": "INFO",
    "logger": "mel.service",
    "msg": "response",
    "http_status": 201,
    "status": "negative_outcome",
    "failure_code": null,
    "survey_id": "S-00001"
  },
  {
    "ts": 1793882001565,
    "level": "INFO",
    "logger": "mel.service",
    "msg": "decision",
    "rule_id": "R3",
    "reason_code": "nothing_to_verify",
    "status": "no_survey",
    "insight_id": "I-004101",
    "survey_id": null,
    "latency_ms": 18.8,
    "cost_usd": 0.0
  }
]
```

## DynamoDB items for the run

```json
[
  {
    "pk": "ORG#org.e2e-20261105123310",
    "seq": 1,
    "sk": "COUNTER#SURVEY"
  },
  {
    "pk": "ORG#org.e2e-20261105123310",
    "offset_s": 5500599,
    "sk": "DEMOCLOCK"
  },
  {
    "pk": "ORG#org.e2e-20261105123310",
    "farmer_id": "F-000245",
    "sk": "SURVEYOWNER#S-00001"
  },
  {
    "at_us": 1799382600136656,
    "pk": "ORG#org.e2e-20261105123310#FARMER#F-000245",
    "sk": "CAP#S-00001"
  },
  {
    "gsi1sk": "FOLLOWUP#2027-01-08T10:00:00+05:30#FU-S-00001-5507413106e7",
    "pk": "ORG#org.e2e-20261105123310#FARMER#F-000245",
    "data": "{\"accepted_answers\":{\"q2\":\"spreading\"},\"created_at\":\"2027-01-08T10:00:00+05:30\",\"farmer_id\":\"F-000245\",\"follow_up_id\":\"FU-S-00001-5507413106e7\",\"reasons\":[\"crop_or_animal_damaged\"],\"response_key\":\"e2e-20261105123310-1\",\"source_insight_ids\":[\"I-005330\"],\"survey_id\":\"S-00001\"}",
    "gsi1pk": "ORG#org.e2e-20261105123310",
    "sk": "FOLLOWUP#FU-S-00001-5507413106e7"
  },
  {
    "ttl": 1800451800,
    "pk": "ORG#org.e2e-20261105123310#FARMER#F-000245",
    "data": "{\"channel_order\":[{\"channel\":\"web\",\"wait_hours\":24},{\"channel\":\"app\",\"wait_hours\":24},{\"channel\":\"whatsapp\",\"wait_hours\":null}],\"created_at\":\"2027-01-06T08:05:03+05:30\",\"expires_at\":\"2027-01-13T19:00:00+05:30\",\"farmerchat_flow\":{\"campaign_id\":\"283df456-256d-5d97-912f-1a6c4fdde6d0\",\"flow_id\":\"673a8ca3-a996-5dff-9399-cc4c7343d170\",\"flow_key\":\"mel_s_00001\",\"org_id\":\"org.farmerchat\",\"version\":1},\"frequency_cap\":{\"exempt\":false,\"key\":\"mel:farmer:F-000245\",\"max_surveys\":1,\"window_days\":7},\"handoff_id\":\"H-00001\",\"priority\":\"normal\",\"send_hours\":{\"from\":\"07:00\",\"to\":\"19:00\"},\"send_window\":{\"not_after\":\"2027-01-11T19:00:00+05:30\",\"not_before\":\"2027-01-08T09:00:00+05:30\"},\"survey\":{\"farmer_id\":\"F-000245\",\"items\":[{\"item_id\":\"q1\",\"options\":[{\"label\":\"Yes\",\"value\":\"yes\"},{\"label\":\"No\",\"value\":\"no\"}],\"prompt\":\"Did you check the lower potato leaves each morning for 3 days?\",\"type\":\"survey-confirm\"},{\"item_id\":\"q2\",\"options\":[{\"label\":\"No new spots\",\"value\":\"no_new_spots\"},{\"label\":\"Same as before\",\"value\":\"same\"},{\"follow_up\":\"crop_or_animal_damaged\",\"label\":\"Spreading\",\"value\":\"spreading\"},{\"follow_up\":\"crop_or_animal_damaged\",\"label\":\"White under leaves\",\"value\":\"white_growth\"}],\"prompt\":\"What do you see on the lower potato leaves now?\",\"type\":\"survey-single-select\"}],\"language\":\"en-IN\",\"rationale\":\"Wait-and-monitor advice for possible potato leaf disease. Ask whether the farmer checked the leaves and whether spots have spread or white growth has appeared.\",\"self_eval\":{\"asks_personal_info\":false,\"gives_new_advice\":false,\"relevance_score\":0.97,\"schema_valid\":true},\"send_window\":{\"not_after\":\"2027-01-11T19:00:00+05:30\",\"not_before\":\"2027-01-08T09:00:00+05:30\"},\"source_insight_ids\":[\"I-005330\"],\"survey_id\":\"S-00001\"}}",
    "sk": "HANDOFF#H-00001"
  },
  {
    "pk": "ORG#org.e2e-20261105123310#FARMER#F-000245",
    "data": "{\"answered_by\":\"F-000245\",\"answers\":{\"q2\":\"spreading\"},\"channel\":\"web\",\"complete\":false,\"counts_toward_cap\":true,\"delivery_attempt\":1,\"failure_code\":null,\"farmer_id\":\"F-000245\",\"farmerchat_reply\":{\"http_status\":201,\"outcome\":\"accepted\"},\"follow_up_reasons\":[\"crop_or_animal_damaged\"],\"items\":[{\"attempts\":1,\"input_kind\":null,\"item_id\":\"q1\",\"item_type\":\"survey-confirm\",\"raw_input\":null,\"result\":\"skipped\",\"value\":null},{\"attempts\":1,\"input_kind\":null,\"item_id\":\"q2\",\"item_type\":\"survey-single-select\",\"raw_input\":null,\"result\":\"answered\",\"value\":\"spreading\"}],\"language\":\"en-IN\",\"needs_follow_up\":true,\"raw_event\":null,\"recorded_at\":\"2027-01-08T10:00:00+05:30\",\"response_key\":\"e2e-20261105123310-1\",\"retry_after_minutes\":null,\"retry_decision\":\"none\",\"sheet_outcome\":\"closed_partway\",\"source_insight_ids\":[\"I-005330\"],\"status\":\"negative_outcome\",\"survey_id\":\"S-00001\",\"timestamps\":{\"answered\":\"2027-01-08T10:00:00+05:30\",\"delivered\":null,\"opened\":null,\"sent\":\"2027-01-08T10:00:00+05:30\"}}",
    "sk": "RESPONSE#e2e-20261105123310-1"
  },
  {
    "sk": "SURVEY#S-00001",
    "ttl": 1800451800,
    "data": "{\"farmer_id\":\"F-000245\",\"items\":[{\"item_id\":\"q1\",\"options\":[{\"label\":\"Yes\",\"value\":\"yes\"},{\"label\":\"No\",\"value\":\"no\"}],\"prompt\":\"Did you check the lower potato leaves each morning for 3 days?\",\"type\":\"survey-confirm\"},{\"item_id\":\"q2\",\"options\":[{\"label\":\"No new spots\",\"value\":\"no_new_spots\"},{\"label\":\"Same as before\",\"value\":\"same\"},{\"follow_up\":\"crop_or_animal_damaged\",\"label\":\"Spreading\",\"value\":\"spreading\"},{\"follow_up\":\"crop_or_animal_damaged\",\"label\":\"White under leaves\",\"value\":\"white_growth\"}],\"prompt\":\"What do you see on the lower potato leaves now?\",\"type\":\"survey-single-select\"}],\"language\":\"en-IN\",\"rationale\":\"Wait-and-monitor advice for possible potato leaf disease. Ask whether the farmer checked the leaves and whether spots have spread or white growth has appeared.\",\"self_eval\":{\"asks_personal_info\":false,\"gives_new_advice\":false,\"relevance_score\":0.97,\"schema_valid\":true},\"send_window\":{\"not_after\":\"2027-01-11T19:00:00+05:30\",\"not_before\":\"2027-01-08T09:00:00+05:30\"},\"source_insight_ids\":[\"I-005330\"],\"survey_id\":\"S-00001\"}",
    "pk": "ORG#org.e2e-20261105123310#FARMER#F-000245"
  }
]
```

## SQS follow-up message (mel-followups, read with VisibilityTimeout 0, not deleted)

```json
[
  {
    "MessageId": "796b2662-2402-4e54-b45a-c80319e911d3",
    "SentTimestamp": "1793882001196",
    "body": {
      "org_id": "org.e2e-20261105123310",
      "follow_up_id": "FU-S-00001-5507413106e7",
      "farmer_id": "F-000245",
      "survey_id": "S-00001",
      "response_key": "e2e-20261105123310-1",
      "source_insight_ids": [
        "I-005330"
      ],
      "reasons": [
        "crop_or_animal_damaged"
      ],
      "accepted_answers": {
        "q2": "spreading"
      },
      "created_at": "2027-01-08T10:00:00+05:30"
    }
  }
]
```
