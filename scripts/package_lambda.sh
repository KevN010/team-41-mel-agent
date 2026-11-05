#!/usr/bin/env bash
set -euo pipefail
ROOT="$(/usr/bin/dirname "$(/usr/bin/dirname "$(realpath "$0")")")"
TARGET="$ROOT/build/lambda"
mkdir -p "$TARGET"
# Clear only this script's build output, never the application working tree.
find "$TARGET" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
if [[ -f "$ROOT/mel/api/handler.py" ]]; then
  cp -R "$ROOT/mel" "$TARGET/mel"
  "${PYTHON:-python3}" -m pip install --requirement "$ROOT/infra/lambda-requirements.txt" \
    --target "$TARGET" --platform manylinux2014_aarch64 --python-version 3.12 \
    --implementation cp --abi cp312 --only-binary=:all: --upgrade
else
  mkdir -p "$TARGET/mel/api"
  touch "$TARGET/mel/__init__.py" "$TARGET/mel/api/__init__.py"
  cat > "$TARGET/mel/api/handler.py" <<'PY'
def lambda_handler(event, context):
    return {"statusCode": 501, "headers": {"content-type": "application/json"},
            "body": '{"error":"not implemented"}'}
PY
fi
if [[ -d "$ROOT/models" ]]; then cp -R "$ROOT/models" "$TARGET/models"; fi
find "$TARGET" -type d -name __pycache__ -prune -exec rm -rf {} +
"${PYTHON:-python3}" - "$TARGET" <<'PY'
import pathlib, sys, zipfile
root = pathlib.Path(sys.argv[1])
archive = root.parent / "lambda.zip"
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
    for file in sorted(root.rglob("*")):
        if file.is_file():
            z.write(file, file.relative_to(root))
print(f"Lambda zip size: {archive.stat().st_size} bytes")
if sum(f.stat().st_size for f in root.rglob("*") if f.is_file()) > 250 * 1024 * 1024:
    raise SystemExit("Lambda uncompressed package exceeds 250 MiB")
if archive.stat().st_size > 50 * 1024 * 1024:
    raise SystemExit("Lambda compressed package exceeds the 50 MiB direct-upload limit")
PY
