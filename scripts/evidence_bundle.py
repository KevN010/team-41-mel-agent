"""Zip the evidence and upload it to the artifacts bucket.

Bundle contents (relative to the repo root; missing optional items are listed in the manifest):
  evidence/  models/results/  REVIEW.md  KNOWN-ISSUES.md  proposals/

    .venv/bin/python scripts/evidence_bundle.py --no-upload   # build the zip only
    .venv/bin/python scripts/evidence_bundle.py               # build, then upload to the artifacts bucket

The bucket comes from MEL_ARTIFACTS_BUCKET, else SSM /mel/artifacts_bucket (region us-west-2).
The upload uses server-side encryption (AES256) under the key evidence/<zip name>.

Safety: the build stops, and nothing is uploaded, if any file looks like a secret (.env, key or
credential files, or text containing an AWS access key id or private key block). Only the pack's
6 scenarios may hold farmer rows, and this script adds none: it zips files that already exist.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGION = "us-west-2"
INCLUDE = ["evidence", "models/results", "REVIEW.md", "KNOWN-ISSUES.md", "proposals"]
OUT_DIR = ROOT / "evidence" / "bundle"  # excluded from the bundle itself

FORBIDDEN_NAMES = re.compile(r"(^\.env|\.pem$|\.key$|^credentials$|^config$|id_rsa|\.p12$|\.pfx$|secret)", re.IGNORECASE)
SECRET_PATTERNS = [
    re.compile(rb"AKIA[0-9A-Z]{16}"),
    re.compile(rb"ASIA[0-9A-Z]{16}"),
    re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(rb"aws_secret_access_key\s*=", re.IGNORECASE),
    re.compile(rb"aws_session_token\s*=", re.IGNORECASE),
]


def collect() -> tuple[list[Path], list[str]]:
    files: list[Path] = []
    missing: list[str] = []
    for item in INCLUDE:
        p = ROOT / item
        if p.is_file():
            files.append(p)
        elif p.is_dir():
            files.extend(sorted(f for f in p.rglob("*") if f.is_file() and OUT_DIR not in f.parents))
        else:
            missing.append(item)
    return files, missing


def screen(files: list[Path]) -> list[str]:
    """Reasons to refuse the bundle: file names and contents that look like secrets."""
    problems = []
    for f in files:
        rel = f.relative_to(ROOT).as_posix()
        if FORBIDDEN_NAMES.search(f.name):
            problems.append(f"{rel}: file name looks like a secret")
            continue
        data = f.read_bytes()
        for pat in SECRET_PATTERNS:
            if pat.search(data):
                problems.append(f"{rel}: contains text matching a secret pattern")
                break
    return problems


def build(files: list[Path], missing: list[str]) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"mel-agent-evidence-{stamp}.zip"
    manifest = {
        "created_utc": stamp,
        "files": [
            {"path": f.relative_to(ROOT).as_posix(), "bytes": f.stat().st_size,
             "sha256": hashlib.sha256(f.read_bytes()).hexdigest()}
            for f in files
        ],
        "missing_optional": missing,
    }
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, f.relative_to(ROOT).as_posix())
        z.writestr("MANIFEST.json", json.dumps(manifest, indent=2) + "\n")
    return out


def artifacts_bucket() -> str:
    name = os.environ.get("MEL_ARTIFACTS_BUCKET")
    if name:
        return name
    import boto3

    return boto3.client("ssm", region_name=REGION).get_parameter(Name="/mel/artifacts_bucket")["Parameter"]["Value"]


def upload(zip_path: Path) -> str:
    import boto3

    bucket = artifacts_bucket()
    key = f"evidence/{zip_path.name}"
    boto3.client("s3", region_name=REGION).upload_file(
        str(zip_path), bucket, key, ExtraArgs={"ServerSideEncryption": "AES256"}
    )
    return f"s3://{bucket}/{key}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-upload", action="store_true", help="build the zip only")
    args = ap.parse_args(argv)

    files, missing = collect()
    if not any(f.name == "REPORT.md" for f in files):
        print("evidence/REPORT.md is missing; run evals/survey_eval.py first", file=sys.stderr)
        return 2
    problems = screen(files)
    if problems:
        print("refusing to bundle:", *problems, sep="\n  ", file=sys.stderr)
        return 3
    zip_path = build(files, missing)
    print(f"bundle: {zip_path.relative_to(ROOT)} ({zip_path.stat().st_size:,} bytes, {len(files)} files)")
    if missing:
        print("not present (skipped): " + ", ".join(missing))
    if args.no_upload:
        print("upload skipped (--no-upload)")
    else:
        print("uploaded:", upload(zip_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
