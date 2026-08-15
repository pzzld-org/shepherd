#!/usr/bin/env bash
# services/llm/tests/run.sh — gate lane for the LLM service.
# Deterministic, free, <2s: tests use mock responses or a local fake binary;
# they never invoke Claude or another hosted inference endpoint.
set -eu -o pipefail
cd "$(dirname "$0")"
shopt -s nullglob
fails=0; total=0
for f in test_*.sh; do
  total=$((total+1))
  echo "[run] $f"
  if bash "$f"; then echo "  PASS"; else echo "  FAIL"; fails=$((fails+1)); fi
done
echo "—— $((total-fails))/$total passed ——"
exit "$fails"
