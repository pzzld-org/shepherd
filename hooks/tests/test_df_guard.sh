#!/usr/bin/env bash
# hooks/tests/test_df_guard.sh — smoke tests for scripts/df-guard.sh (#214).
#
# Covers the disk-pressure precheck's CLI contract:
#   • --min=0 always passes (0 GiB required) → exit 0, "— OK".
#   • --min=99999999 always fails (no disk has that much) → exit 1, "— INSUFFICIENT".
#   • default threshold is 12Gi, and the OK/INSUFFICIENT line says so.
#   • --help prints usage and exits 0.
#
# Conventions match hooks/tests/test_exec_bits.sh: set -euo pipefail, a fails
# counter, a note() helper, a final PASS/FAIL summary, exit code = fails.

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/../../scripts/df-guard.sh"

fails=0

note() { # name pass|fail detail
  local name="$1" verdict="$2" detail="${3:-}"
  if [[ "$verdict" == "pass" ]]; then
    printf '  PASS  %s\n' "$name"
  else
    printf '  FAIL  %s — %s\n' "$name" "$detail"
    fails=$((fails+1))
  fi
}

[[ -x "$SCRIPT" ]] || { echo "  FAIL  df-guard.sh not found or not executable at $SCRIPT" >&2; exit 1; }

# --- Case 1: --min=0 . always has >=0 GiB available -> OK, exit 0. ---------
out=""; rc=0
out="$("$SCRIPT" --min=0 . 2>&1)" || rc=$?
if [[ "$rc" -eq 0 && "$out" == *"— OK"* ]]; then
  note "min=0 exits 0 with OK" pass
else
  note "min=0 exits 0 with OK" fail "rc=$rc out=$out"
fi

# --- Case 2: --min=99999999 . exceeds any real disk -> INSUFFICIENT, exit 1.
out=""; rc=0
out="$("$SCRIPT" --min=99999999 . 2>&1)" || rc=$?
if [[ "$rc" -eq 1 && "$out" == *"— INSUFFICIENT"* ]]; then
  note "min=99999999 exits 1 with INSUFFICIENT" pass
else
  note "min=99999999 exits 1 with INSUFFICIENT" fail "rc=$rc out=$out"
fi

# --- Case 3: default threshold (no --min) is 12Gi. -------------------------
out=""; rc=0
out="$("$SCRIPT" . 2>&1)" || rc=$?
if [[ "$out" == *"(min 12Gi)"* ]]; then
  note "default min is 12Gi" pass
else
  note "default min is 12Gi" fail "rc=$rc out=$out"
fi

# --- Case 4: --help prints usage and exits 0. -------------------------------
out=""; rc=0
out="$("$SCRIPT" --help 2>&1)" || rc=$?
if [[ "$rc" -eq 0 && "$out" == *"Usage"* ]]; then
  note "--help exits 0 with Usage" pass
else
  note "--help exits 0 with Usage" fail "rc=$rc out=$out"
fi

# --- Case 5: non-numeric --min → exit 2 (distinct from INSUFFICIENT's 1). ---
# Verify-wave regression: a typo'd threshold must fail loud and distinct, not
# crash with an unbound-variable and exit 1 (indistinguishable from a real
# disk-pressure failure).
out=""; rc=0
out="$("$SCRIPT" --min=abc . 2>&1)" || rc=$?
if [[ "$rc" -eq 2 && "$out" == *"non-negative integer"* ]]; then
  note "non-numeric --min exits 2 with a clear error" pass
else
  note "non-numeric --min exits 2 with a clear error" fail "rc=$rc out=$out"
fi

if [[ "$fails" -eq 0 ]]; then
  echo "PASS: test_df_guard"
else
  echo "FAIL: test_df_guard ($fails failure(s))"
fi
exit "$fails"
