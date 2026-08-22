#!/usr/bin/env bash
set -eu -o pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNNER="$ROOT/evals/run_eval.sh"
CASES="$ROOT/evals/cases"
count=0

while read -r _ kind good bad; do
  [[ -f "$CASES/$good" ]] || { echo "missing $kind good eval: $good" >&2; exit 1; }
  [[ -f "$CASES/$bad" ]] || { echo "missing $kind bad eval: $bad" >&2; exit 1; }
  [[ "$good" == *_good.txt ]] || { echo "bad good-case name: $good" >&2; exit 1; }
  [[ "$bad" == *_bad.txt ]] || { echo "bad bad-case name: $bad" >&2; exit 1; }
  count=$((count + 1))
done < <(grep '^_pair ' "$RUNNER")

(( count > 0 )) || { echo "no periodic eval pairs discovered" >&2; exit 1; }
echo "ok: $count periodic eval pair(s) are complete"
