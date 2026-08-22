#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
GOOD="$ROOT/services/eval/evals/cases/v656/release-trust_good.txt"
BAD="$ROOT/services/eval/evals/cases/v656/release-trust_bad.txt"
RUBRIC="$ROOT/services/eval/rubrics/release-trust.rubric.json"
RUNNER="$ROOT/services/eval/evals/run_eval.sh"
EVIDENCE="$ROOT/.shepherd/runs/v656/lanes/release-trust/evidence/release-trust-live-scores.json"

[[ -s "$GOOD" && -s "$BAD" && -s "$RUBRIC" && -s "$EVIDENCE" ]]
grep -Fq 'tracked `.pi` source' "$GOOD"
grep -Fq 'production closure' "$GOOD"
grep -Fq 'future expiry' "$GOOD"
grep -Fq 'bypassPermissions' "$BAD"
grep -Fq 'passing transcript' "$BAD"
grep -Fq '_pair release-trust v656/release-trust_good.txt v656/release-trust_bad.txt' "$RUNNER"

python3 - "$ROOT" "$EVIDENCE" <<'PY'
from hashlib import sha256
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
evidence = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
assert evidence["judge"] == "local-claude-code"
for name, recorded in evidence["inputs"].items():
    assert sha256((root / recorded["path"]).read_bytes()).hexdigest() == recorded["sha256"], name
threshold = json.loads((root / "services/eval/rubrics/release-trust.rubric.json").read_text())["threshold"]
good = evidence["good"]["overall"]
bad = evidence["bad"]["overall"]
assert evidence["goodExit"] == 0 and evidence["badExit"] == 1
assert good >= threshold, (good, threshold)
assert bad < threshold, (bad, threshold)
assert good - bad >= 15, (good, bad)
print(f"release-trust live discrimination: good={good} bad={bad} threshold={threshold} margin={good-bad}")
PY

echo 'release-trust eval pair: 10 checks passed'
