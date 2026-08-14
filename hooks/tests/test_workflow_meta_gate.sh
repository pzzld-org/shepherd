#!/usr/bin/env bash
# hooks/tests/test_workflow_meta_gate.sh — wraps scripts/check-workflow-meta.sh's
# own --self-test for the hooks suite (DF-69).
#
# `workflows/wave.js` shipped in 686084d with a `+`-concatenated `meta`
# field and stayed unloadable — invisible to `bin/shepherd lint`, invisible
# to `node --check`, invisible to every gate in the repo — until a live
# conductor tried to dispatch it. The remediation is
# `scripts/check-workflow-meta.sh`; this file is its hooks-suite tripwire
# so a later edit that quietly breaks the checker (or lets a new
# `workflows/*.js` regress) fails `hooks/tests/run.sh`, not just a
# standalone invocation nobody runs.
#
# This wraps the checker's OWN `--self-test`, rather than re-deriving its
# assertions: the self-test is the falsifiability proof (a NEGATIVE control
# recovered live from 686084d, a POSITIVE control against the real shipped
# file, a FALSE-POSITIVE guard for a description string that legitimately
# contains `+ ( ) '`, and a DF-59 zero-files pin) — duplicating that logic
# here would just be a second copy that could drift from the first. It then
# separately proves the checker's NORMAL mode passes against the real repo
# right now, so a red run.sh always means something is actually broken.
#
# Deterministic, no network, no LLM, <2s.

set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="$ROOT/scripts/check-workflow-meta.sh"
fails=0
note() { printf '  %s\n' "$*"; }

[[ -f "$SCRIPT" ]] || { note "FAIL: scripts/check-workflow-meta.sh missing"; exit 1; }
[[ -x "$SCRIPT" ]] || { note "FAIL: scripts/check-workflow-meta.sh is not executable (chmod +x)"; exit 1; }

out="$("$SCRIPT" --self-test 2>&1)"
rc=$?
if [[ "$rc" -ne 0 ]]; then
  note "FAIL  --self-test exited $rc"
  printf '%s\n' "$out" | sed 's/^/    /'
  fails=$((fails + 1))
else
  note "PASS  --self-test exited 0"
fi

check() {  # <needle> <label>
  if printf '%s\n' "$out" | grep -qF -- "$1"; then
    note "PASS  $2"
  else
    note "FAIL  $2 — expected line containing: $1"
    fails=$((fails + 1))
  fi
}
check "PASS  NEGATIVE control"      "self-test proves the 686084d concatenated whenToUse is rejected"
check "PASS  POSITIVE control"      "self-test proves the current workflows/wave.js meta block passes"
check "PASS  FALSE-POSITIVE GUARD"  "self-test proves a legitimate + ( ) ' description string passes"
check "PASS  ZERO-FILES guard"      "self-test proves an empty scan set exits non-zero (DF-59)"

# The self-test proves the MECHANISM is falsifiable; this proves the
# currently-shipped workflow actually satisfies it, right now, for real.
real_out="$("$SCRIPT" 2>&1)"
real_rc=$?
if [[ "$real_rc" -eq 0 ]]; then
  note "PASS  normal-mode scan of the real workflows/*.js exits 0"
else
  note "FAIL  normal-mode scan of the real workflows/*.js exited $real_rc"
  printf '%s\n' "$real_out" | sed 's/^/    /'
  fails=$((fails + 1))
fi

if [[ "$fails" -gt 0 ]]; then
  printf '  FAIL  %d workflow-meta-gate assertion(s) failed\n' "$fails" >&2
  exit 1
fi
printf '  PASS  workflow-meta-gate: pure-literal meta check is wired and falsifiable (DF-69)\n'
