#!/usr/bin/env bash
# Run from ~/GitHub/team-41/mel-agent. Creates the working tree for the agents.
set -euo pipefail
test -d ../participant-pack || { echo "participant-pack not found next to this dir"; exit 1; }
mkdir -p pack mel tests infra sim models evals scripts
rsync -a --exclude 'spreadsheets' ../participant-pack/ pack/
cp ../../FarmerChat/rag_service/jev_service.py reference_jev_service.py 2>/dev/null || true
python3 -m venv .venv && . .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt
git init -q 2>/dev/null || true
cat > .gitignore <<'G'
.venv/
__pycache__/
*.pyc
.env
cdk.out/
models/results/
evidence/
G
git add -A && git commit -qm "bootstrap mel-agent kit" || true
echo "OK. Next: aws bedrock list-foundation-models --region us-west-2 > models/candidates.txt"
