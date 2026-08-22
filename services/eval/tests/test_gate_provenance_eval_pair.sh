#!/usr/bin/env bash
# Deterministic contract test for the v656 gate-provenance periodic pair.
set -eu -o pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
RUNNER="$ROOT/services/eval/evals/run_eval.sh"
RUBRIC="$ROOT/services/eval/rubrics/gate-provenance.rubric.json"
ARTIFACT_RUNNER="$ROOT/scripts/gate-artifact.py"
ARTIFACT_TEST="$ROOT/scripts/tests/test-gate-artifact.py"
GATE="$ROOT/scripts/gate.sh"
WIRING="$ROOT/scripts/check-gate-wiring.py"
GOOD="$ROOT/services/eval/evals/cases/v656/gate-provenance_good.txt"
BAD="$ROOT/services/eval/evals/cases/v656/gate-provenance_bad.txt"
checks=0
fails=0

pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s — %s\n' "$1" "$2"; fails=$((fails + 1)); }

file_check() {
  local label="$1" path="$2"
  checks=$((checks + 1))
  if [[ -s "$path" ]]; then pass "$label"; else fail "$label" "missing or empty: $path"; fi
}

grep_check() {
  local label="$1" needle="$2" path="$3"
  checks=$((checks + 1))
  if grep -Fq -- "$needle" "$path"; then pass "$label"; else fail "$label" "missing text: $needle"; fi
}

file_check "periodic runner exists" "$RUNNER"
file_check "gate-provenance rubric exists" "$RUBRIC"
file_check "wave-owned gate writer/reader exists" "$ARTIFACT_RUNNER"
file_check "wave-owned gate writer/reader test exists" "$ARTIFACT_TEST"
file_check "good case exists" "$GOOD"
file_check "bad case exists" "$BAD"

grep_check "runner declares the v656 pair" \
  '_pair gate-provenance v656/gate-provenance_good.txt v656/gate-provenance_bad.txt' "$RUNNER"

grep_check "good case requires wave-owned evidence" \
  'wave-owned execution artifact' "$GOOD"
grep_check "good case defines attempt correlation" \
  'attempt_id' "$GOOD"
grep_check "good case defines latest-attempt retry semantics" \
  'latest attempt' "$GOOD"
grep_check "good case orders retries explicitly" \
  'Invocation append order defines the latest attempt' "$GOOD"
grep_check "good case makes incomplete retries override older passes" \
  'older attempt Passed' "$GOOD"
grep_check "good case names the implemented writer/reader" \
  'scripts/gate-artifact.py' "$GOOD"
grep_check "good case binds the declared command" \
  'requires the expected command' "$GOOD"
grep_check "good case linearizes concurrent retries" \
  'locking makes status linearizable' "$GOOD"
grep_check "good case rejects partial framing" \
  'non-newline-terminated' "$GOOD"
grep_check "bad case rejects arbitrary command certification" \
  '--gate hooks run -- true' "$BAD"
grep_check "fast gate executes periodic eval contracts" \
  'step "periodic eval contracts" bash services/eval/tests/run.sh' "$GATE"
grep_check "wiring checker discovers service eval tests" \
  '"services/eval/tests"' "$WIRING"
grep_check "bad case contains substring authority" \
  'substring' "$BAD"
grep_check "bad case contains shell-parser authority" \
  'Parse shell syntax' "$BAD"
grep_check "bad case contains outer-status authority" \
  'outer Bash status' "$BAD"
grep_check "bad case contains stale-retry authority" \
  'older passing attempt survive a newer attempt' "$BAD"

checks=$((checks + 1))
if python3 "$ARTIFACT_TEST" >/dev/null 2>&1; then
  pass "gate artifact behavior passes from the eval lane"
else
  fail "gate artifact behavior passes from the eval lane" "artifact behavioral tests failed"
fi

checks=$((checks + 1))
if jq -e '
  .kind == "gate-provenance"
  and .scale == 5
  and .threshold == 80
  and ([.dimensions[].key] | sort) == [
    "authority_boundary",
    "correlation_retry",
    "execution_evidence",
    "truthful_scope"
  ]
  and ([.dimensions[].weight] | add) == 10
' "$RUBRIC" >/dev/null 2>&1; then
  pass "gate-provenance rubric has the deterministic contract"
else
  fail "gate-provenance rubric has the deterministic contract" "invalid kind, scale, threshold, keys, or weights"
fi

(( checks > 0 )) || { printf 'FAIL: zero deterministic pair checks executed\n' >&2; exit 1; }
printf '—— %d/%d deterministic pair checks passed, %d failed ——\n' "$((checks - fails))" "$checks" "$fails"
exit "$fails"
