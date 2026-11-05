"""Fail unless every stack has a cdk-nag report and zero unsuppressed errors."""
import csv
from pathlib import Path

reports = sorted(Path(__file__).resolve().parent.joinpath("cdk.out").glob("AwsSolutions-*-NagReport.csv"))
if len(reports) != 6:
    raise SystemExit(f"Expected six cdk-nag reports, found {len(reports)}")
errors = []
suppressions = set()
for report in reports:
    for row in csv.DictReader(report.open()):
        if row["Compliance"] == "Non-Compliant" and row["Rule Level"] == "Error":
            errors.append(row)
        if row["Compliance"] == "Suppressed":
            suppressions.add((row["Rule ID"], row["Exception Reason"]))
if errors:
    raise SystemExit(str(errors))
print("cdk-nag AwsSolutions: zero unsuppressed errors across all six stacks")
path = Path(__file__).resolve().parent / "NAG.md"
path.write_text("# cdk-nag AwsSolutions\n\nAll six stacks: zero unsuppressed errors. Suppressions actually used:\n\n" + "\n".join(f"- `{key}`: {reason}" for key, reason in sorted(suppressions)) + "\n")
