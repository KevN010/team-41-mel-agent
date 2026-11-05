#!/usr/bin/env bash
# Deploy all MelAgent stacks to us-west-2. Needs AWS credentials in the environment.
# ALERT_EMAIL receives the budget alert (80% of $50/month). Optional: HAIKU_PROFILE_ID adds the
# Haiku inference profile (from models/candidates.txt) to the agent role.
set -euo pipefail

export AWS_REGION=us-west-2 AWS_DEFAULT_REGION=us-west-2
cd "$(dirname "$0")/../infra"

: "${ALERT_EMAIL:?set ALERT_EMAIL to the address for budget alerts}"

ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
export CDK_DEFAULT_ACCOUNT="$ACCOUNT" CDK_DEFAULT_REGION=us-west-2

# Bootstrap only if the CDKToolkit stack is missing.
if ! aws cloudformation describe-stacks --stack-name CDKToolkit --region us-west-2 >/dev/null 2>&1; then
  echo "Bootstrapping aws://$ACCOUNT/us-west-2"
  cdk bootstrap "aws://$ACCOUNT/us-west-2"
fi

CTX=(-c "alert_email=$ALERT_EMAIL")
if [[ -n "${HAIKU_PROFILE_ID:-}" ]]; then CTX+=(-c "haiku_profile_id=$HAIKU_PROFILE_ID"); fi

cdk deploy --all --require-approval never --outputs-file cdk-outputs.json "${CTX[@]}"

echo
echo "== Stack outputs =="
python3 - <<'PY'
import json
for stack, outs in json.load(open("cdk-outputs.json")).items():
    print(stack)
    for k, v in outs.items():
        print(f"  {k} = {v}")
PY
