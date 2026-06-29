#!/usr/bin/env bash
# services/eval/tests/run.sh — gate lane for the eval harness.
# Deterministic, free, <2s: the judge is mocked (SHEPHERD_LLM_MOCK), so every
# test exercises the real eval→llm boundary while the model returns a canned
# verdict. The latent part is stubbed; everything deterministic is tested for real.
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
