#!/usr/bin/env bash
# hooks/tests/test_cli_venv_selfheal.sh — GH #266 unprovisioned-venv guard.
#
# `poetry env info --executable` CREATES a venv when none exists and prints the
# interpreter for the empty result. bin/shepherd called that to locate the
# interpreter and exec'd straight into whatever came back, so a fresh upgrade
# produced an empty venv and every command died with
# `ModuleNotFoundError: No module named 'typer'` — a traceback naming a
# dependency rather than the cause. And it never healed: once the directory
# existed, bin/shepherd-venv-ensure's `[ -d "$VENV_DIR" ]` test called the venv
# present and skipped the install.
#
# These cases pin the contract that fixes it:
#   1. both scripts agree on what "provisioned" means (they must, or one skips
#      the install the other needs),
#   2. an empty venv is NOT provisioned — the exact #266 state,
#   3. either poetry's console script or site-packages/typer is sufficient,
#   4. bin/shepherd refuses to exec into an unprovisioned venv and says how to
#      fix it, instead of surfacing an import error.
#
# Deterministic, no network, no poetry required. <2s.

set -eu -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WRAPPER="$ROOT/bin/shepherd"
ENSURE="$ROOT/bin/shepherd-venv-ensure"

total=0; fails=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s — %s\n' "$1" "${2:-}"; fails=$((fails+1)); }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# ---------------------------------------------------------------------------
# 1. Both scripts define `venv_provisioned`, and on the SAME two signals.
#    A drift here is silent and reintroduces #266: whichever script is laxer
#    skips the install the stricter one then demands.
# ---------------------------------------------------------------------------
total=$((total+1))
if grep -q 'venv_provisioned()' "$WRAPPER" && grep -q 'venv_provisioned()' "$ENSURE"; then
  pass "both bin/shepherd and bin/shepherd-venv-ensure define venv_provisioned"
else
  fail "venv_provisioned defined in both" "one of the two is missing the probe"
fi

total=$((total+1))
if grep -q 'site-packages/typer' "$WRAPPER" && grep -q 'site-packages/typer' "$ENSURE" \
   && grep -q 'bin/shepherd' "$ENSURE"; then
  pass "both probe the same two signals (console script + site-packages/typer)"
else
  fail "probes agree" "the two venv_provisioned implementations check different things"
fi

# ---------------------------------------------------------------------------
# 2. bin/shepherd-venv-ensure must NOT gate on mere directory existence — that
#    is the bug. Assert the retired test is gone.
# ---------------------------------------------------------------------------
total=$((total+1))
# Strip comments first: the retirement is DOCUMENTED in a comment quoting the
# old test verbatim, and a naive grep would match its own changelog.
if grep -vE '^[[:space:]]*#' "$ENSURE" | grep -qE '\[ -d "\$VENV_DIR" \]'; then
  fail "no bare -d VENV_DIR gate" "an empty venv passes existence and skips the install (#266)"
else
  pass "venv-ensure gates on provisioned-ness, not directory existence"
fi

# ---------------------------------------------------------------------------
# 3. The probe's own truth table, run against real fixture directories by
#    sourcing the function out of bin/shepherd.
# ---------------------------------------------------------------------------
# Extract just the function so the wrapper's `exec` never runs.
sed -n '/^venv_provisioned() {$/,/^}$/p' "$WRAPPER" > "$tmp/probe.sh"
# shellcheck disable=SC1090
source "$tmp/probe.sh"

mk_venv() {  # <name> -> echoes the fake interpreter path
  local name="$1"
  mkdir -p "$tmp/$name/bin"
  # bin/shepherd derives the venv root from .../bin/python — the probe only
  # reads the path, so the file need not be a real interpreter.
  : > "$tmp/$name/bin/python"
  printf '%s\n' "$tmp/$name/bin/python"
}

total=$((total+1))
EMPTY_PY="$(mk_venv empty)"
if venv_provisioned "$EMPTY_PY"; then
  fail "empty venv is not provisioned" "the #266 state was reported as healthy"
else
  pass "empty venv (bin/ only) reports NOT provisioned — the #266 state"
fi

total=$((total+1))
SCRIPT_PY="$(mk_venv withscript)"
: > "$tmp/withscript/bin/shepherd"; chmod +x "$tmp/withscript/bin/shepherd"
if venv_provisioned "$SCRIPT_PY"; then
  pass "venv with poetry's console script reports provisioned"
else
  fail "console script sufficient" "a normal poetry install was rejected"
fi

total=$((total+1))
DEPS_PY="$(mk_venv withdeps)"
mkdir -p "$tmp/withdeps/lib/python3.11/site-packages/typer"
if venv_provisioned "$DEPS_PY"; then
  pass "venv with site-packages/typer reports provisioned (--no-root install)"
else
  fail "site-packages sufficient" "a --no-root install was rejected"
fi

# ---------------------------------------------------------------------------
# 4. End to end: with poetry absent from PATH the wrapper takes its documented
#    python3 fallback rather than the venv path — so the self-heal branch never
#    strands a machine that never had poetry to begin with.
# ---------------------------------------------------------------------------
total=$((total+1))
fakebin="$tmp/fakebin"; mkdir -p "$fakebin"
for t in bash sed grep dirname mktemp env cat rm; do
  src="$(command -v "$t" 2>/dev/null || true)"
  [[ -n "$src" ]] && ln -sf "$src" "$fakebin/$t"
done
# A python3 that reports which module it was asked to run, and exits 0.
cat > "$fakebin/python3" <<'STUB'
#!/bin/sh
echo "python3-fallback $*"
STUB
chmod +x "$fakebin/python3"
out="$(PATH="$fakebin" CLAUDE_PLUGIN_ROOT="$ROOT" bash "$WRAPPER" --version 2>&1 || true)"
if printf '%s' "$out" | grep -q 'python3-fallback'; then
  pass "poetry absent: falls back to python3 -m shepherd_cli (unchanged contract)"
else
  fail "python3 fallback" "out=${out:0:200}"
fi

# ---------------------------------------------------------------------------
# 5. The wrapper's refusal message names the recovery command, not an import
#    error. This is what turns a 20-minute diagnosis into a copy-paste.
# ---------------------------------------------------------------------------
total=$((total+1))
if grep -q 'poetry install' "$WRAPPER" && grep -q 'doctor' "$WRAPPER"; then
  pass "wrapper's failure message names 'poetry install' and the doctor check"
else
  fail "actionable failure message" "the wrapper does not name the recovery"
fi

echo "—— $((total-fails))/$total passed ——"
exit "$fails"
