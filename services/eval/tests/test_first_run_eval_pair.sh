#!/usr/bin/env bash
set -eu -o pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
GOOD="$ROOT/services/eval/evals/cases/v656/first-run_good.txt"
BAD="$ROOT/services/eval/evals/cases/v656/first-run_bad.txt"
RUBRIC="$ROOT/services/eval/rubrics/first-run.rubric.json"
RUNNER="$ROOT/services/eval/evals/run_eval.sh"
PROJECTION="$ROOT/scripts/tests/test-generate-compiler-package-content.py"
for path in "$GOOD" "$BAD" "$RUBRIC" "$PROJECTION"; do [[ -s "$path" ]] || { echo "FAIL: missing $path"; exit 1; }; done
grep -Fq '_pair first-run v656/first-run_good.txt v656/first-run_bad.txt' "$RUNNER"
grep -Fq '`shepherd run init <run>` → invoke `plant` → invoke `spawn` again' "$GOOD"
grep -Fq 'never initializes, plants, retries itself' "$GOOD"
grep -Fq 'runs `shepherd init --confirm` as a side effect' "$GOOD"
grep -Fq 'source file and `paths.reports`' "$GOOD"
grep -Fq 'silently initialize' "$BAD"
grep -Fq 'second compatibility parser' "$BAD"
grep -Fq 'test_projection_check_rejects_removed_first_run_action' "$PROJECTION"
jq -e '.kind == "first-run" and .threshold == 80 and ([.dimensions[].weight] | add) == 10' "$RUBRIC" >/dev/null
printf 'ok: first-run periodic eval pair is wired
'
