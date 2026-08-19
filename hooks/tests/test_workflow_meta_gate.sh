#!/usr/bin/env bash
# hooks/tests/test_workflow_meta_gate.sh — wraps scripts/check-workflow-meta.sh's
# own --self-test for the hooks suite (DF-69).
#
# `workflows/wave.js` shipped with a `+`-concatenated `meta` field and stayed
# unloadable — invisible to `bin/shepherd lint`, invisible to `node --check`,
# invisible to every gate in the repo — until a live conductor tried to
# dispatch it. The remediation is `scripts/check-workflow-meta.sh`; this file
# is its hooks-suite tripwire so a later edit that quietly breaks the checker
# (or lets a new `workflows/*.js` regress) fails `hooks/tests/run.sh`, not just
# a standalone invocation nobody runs.
#
# This wraps the checker's OWN `--self-test`, rather than re-deriving its
# assertions: the self-test is the falsifiability proof (a NEGATIVE control
# read from the tracked fixture
# `hooks/tests/fixtures/df69-concatenated-meta.js`, a POSITIVE control against
# the real shipped file, a FALSE-POSITIVE guard for a description string that
# legitimately contains `+ ( ) '`, and a DF-59 zero-files pin) — duplicating
# that logic here would just be a second copy that could drift from the first.
# It then separately proves the checker's NORMAL mode passes against the real
# repo right now, so a red run.sh always means something is actually broken.
#
# The one assertion below that is NOT a restatement of the self-test is the
# git-less run. The NEGATIVE control used to recover its corpus with
# `git show <sha>:workflows/wave.js`, which cannot resolve in a clone whose
# history was truncated and cannot resolve in CI at all — `actions/checkout`
# defaults to `fetch-depth: 1`. Re-running the self-test with `git` shimmed to
# exit 127 proves no control has crawled back into git archaeology. That
# assertion fails even in a repository where the old object still resolves,
# which is what makes it a real regression test rather than a restatement of
# today's environment.
#
# Deterministic, no network, no LLM, <2s.

set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="$ROOT/scripts/check-workflow-meta.sh"
fails=0
note() { printf '  %s\n' "$*"; }

SHIM_DIR=""
cleanup() {
  [[ -n "$SHIM_DIR" && -d "$SHIM_DIR" ]] && rm -rf "$SHIM_DIR"
  return 0
}
trap cleanup EXIT

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
  # G5: `grep -q` exit 1 is "looked, absent" and is the only non-zero status
  # this may treat as a missing needle; anything above 1 means grep could not
  # look, which is its own failure and must not read as a plain absence.
  printf '%s\n' "$out" | grep -qF -- "$1"
  local grep_rc=$?
  case "$grep_rc" in
    0) note "PASS  $2" ;;
    1)
      note "FAIL  $2 — expected line containing: $1"
      fails=$((fails + 1))
      ;;
    *)
      note "FAIL  $2 — grep exited $grep_rc (could not search the self-test output)"
      fails=$((fails + 1))
      ;;
  esac
}
check "PASS  NEGATIVE control"      "self-test proves the concatenated whenToUse fixture is rejected"
check "PASS  POSITIVE control"      "self-test proves the current workflows/wave.js meta block passes"
check "PASS  FALSE-POSITIVE GUARD"  "self-test proves a legitimate + ( ) ' description string passes"
check "PASS  ZERO-FILES guard"      "self-test proves an empty scan set exits non-zero (DF-59)"

# A NEGATIVE control is only worth something if the rejection names the defect
# under test. `BinaryExpression` is the gate's word for a `+` that survived
# string masking, which is precisely DF-69's shape; a fixture rejected for any
# other reason would be a control that keeps passing after the `+` check breaks.
check 'BinaryExpression: a `+` operator is present outside any string literal' \
      "the NEGATIVE control's stated reason IS the concatenation, not an unrelated parse failure"

# G4: a gate states how many things it checked. The count is pinned so that
# quietly dropping a control turns the suite red instead of turning it a
# quieter green. Adding a fifth control is meant to require an edit here.
check "ok: all 4 self-test control(s) behaved as designed." \
      "self-test reports its control count and still runs all four (G4)"

# --- the controls must not need git ------------------------------------------
# Shim `git` to a hard failure and re-run. A self-test whose controls read the
# working tree passes identically; one that reaches for `git show` cannot.
SHIM_DIR="$(mktemp -d -t workflow-meta-nogit.XXXXXX)"
cat >"$SHIM_DIR/git" <<'SHIM_EOF'
#!/bin/sh
printf 'git: deliberately unavailable for this test\n' >&2
exit 127
SHIM_EOF
chmod +x "$SHIM_DIR/git"

nogit_out="$(PATH="$SHIM_DIR:$PATH" "$SCRIPT" --self-test 2>&1)"
nogit_rc=$?
if [[ "$nogit_rc" -eq 0 ]]; then
  note "PASS  --self-test still exits 0 with git shimmed to fail (no control depends on git history)"
else
  note "FAIL  --self-test exited $nogit_rc with git shimmed to fail — a control is reaching into git history"
  printf '%s\n' "$nogit_out" | sed 's/^/    /'
  fails=$((fails + 1))
fi

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
