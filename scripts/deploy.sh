#!/usr/bin/env bash
set -euo pipefail
ROOT="$(/usr/bin/dirname "$(/usr/bin/dirname "$(realpath "$0")")")"
export AWS_DEFAULT_REGION=us-west-2 AWS_REGION=us-west-2 AWS_PAGER=""
export PATH="$ROOT/infra/.venv/bin:$PATH"
export PYTHON="$ROOT/infra/.venv/bin/python"
EVIDENCE="$ROOT/infra/evidence"
mkdir -p "$EVIDENCE"
aws sts get-caller-identity --region us-west-2 > "$EVIDENCE/identity.json"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text --region us-west-2)"
export CDK_DEFAULT_ACCOUNT="$ACCOUNT"
bash "$ROOT/scripts/package_lambda.sh" | tee "$EVIDENCE/package.log"
# Give each command its own working directory; /usr/bin/cd is an external
# utility on macOS and cannot change its parent shell's working directory.
in_infra() {
  "$PYTHON" - "$ROOT/infra" "$@" <<'PYRUN'
import subprocess, sys
raise SystemExit(subprocess.call(sys.argv[2:], cwd=sys.argv[1]))
PYRUN
}
if [[ "${1:-}" == "--lambda-only" ]]; then
  in_infra cdk deploy MelAgent-Api --require-approval never
  exit
fi
in_infra cdk synth --quiet 2>&1 | tee "$EVIDENCE/synth.log"
in_infra python -m unittest test_contract -v 2>&1 | tee "$EVIDENCE/contracts.log"
in_infra python check_nag.py
if ! aws ssm get-parameter --name /cdk-bootstrap/hnb659fds/version --region us-west-2 > "$EVIDENCE/bootstrap-check.json" 2> "$EVIDENCE/bootstrap-check.err"; then
  if grep -q ParameterNotFound "$EVIDENCE/bootstrap-check.err"; then
    in_infra cdk bootstrap "aws://$ACCOUNT/us-west-2" --tags Project=MelAgent 2>&1 | tee "$EVIDENCE/bootstrap.log"
  else
    cat "$EVIDENCE/bootstrap-check.err" >&2
    exit 1
  fi
fi
set +e
in_infra cdk deploy --all --concurrency 6 --require-approval never 2>&1 | tee "$EVIDENCE/deploy.log"
DEPLOY_STATUS=${PIPESTATUS[0]}
set -e
if [[ "$DEPLOY_STATUS" -ne 0 ]]; then
  in_infra python report.py --incomplete
  exit "$DEPLOY_STATUS"
fi
in_infra python runtime.py
if [[ -n "${SEED_PASSWORD:-}" ]]; then
  python "$ROOT/scripts/seed_users.py" | tee "$EVIDENCE/seed.log"
  in_infra python smoke.py | tee "$EVIDENCE/smoke.log"
else
  echo 'SEED_PASSWORD is unset: seed and authenticated smoke test require it.' > "$EVIDENCE/smoke.log"
fi
aws ssm get-parameters-by-path --path /mel --region us-west-2 --output json > "$EVIDENCE/ssm.json"
in_infra python report.py
