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
# T3-startup-cost added a VENV_PY_CACHE fast path to bin/shepherd, checked
# BEFORE poetry is ever consulted, to kill a measured ~300ms `poetry env info
# --executable` call paid on every invocation. That fast path sits directly
# in front of case 4's poetry-absent fallback below: on any machine that has
# ever run bin/shepherd successfully once, a valid ambient cache wins and
# case 4's synthetic poetry-absent PATH is never reached (reproduced on this
# run's own dev box — W12 central-verify audit, this file 8/8 -> 7/8, first
# misattributed as pre-existing before being traced to the interaction). Two
# more cases close that gap instead of leaving it silently untested:
#   5. case 4 itself now runs under a throwaway CLAUDE_PLUGIN_ROOT rather than
#      the real repo root, so its CLI_DIR/cache path starts empty every run
#      and the poetry-absent branch is reachable regardless of ambient cache
#      state on the machine executing this suite,
#   6. a cache file that IS present and valid is proven to actually be used —
#      zero poetry invocations — when poetry IS on PATH. The perf fix
#      previously had a timing test only (services/cli/tests/
#      test_cli_startup_cost.py); nothing pinned its behavior.
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

# A throwaway CLAUDE_PLUGIN_ROOT with a fresh, empty services/cli/.venv — never
# the real repo root. bin/shepherd resolves ROOT from CLAUDE_PLUGIN_ROOT when
# it is set (never touching BASH_SOURCE), so this is enough to give VENV_PY_CACHE
# a path that starts every run with no cache file, no matter what has run on
# the real repo's own .venv on this machine.
mk_fake_root() {  # <name> -> echoes a throwaway CLAUDE_PLUGIN_ROOT path
  local name="$1"
  local root="$tmp/$name"
  mkdir -p "$root/services/cli/.venv"
  printf '%s\n' "$root"
}

# ---------------------------------------------------------------------------
# 4. End to end: with poetry absent from PATH the wrapper takes its documented
#    python3 fallback rather than the venv path — so the self-heal branch never
#    strands a machine that never had poetry to begin with.
#
#    Run under a throwaway root (mk_fake_root), NOT the real repo root: the
#    T3-startup-cost VENV_PY_CACHE fast path is checked before poetry is ever
#    consulted, so reusing the real ROOT here would let an ambient cache —
#    present on any machine that has run bin/shepherd once, including this
#    dev box and CI mid-run after any earlier gate step invokes it — win
#    before the synthetic poetry-absent PATH built below is ever reached,
#    silently retiring this case (exactly what happened; see this file's
#    header comment). A fresh throwaway root can never carry that cache.
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
FALLBACK_ROOT="$(mk_fake_root fallback-root)"
out="$(PATH="$fakebin" CLAUDE_PLUGIN_ROOT="$FALLBACK_ROOT" bash "$WRAPPER" --version 2>&1 || true)"
if printf '%s' "$out" | grep -q 'python3-fallback'; then
  pass "poetry absent, no ambient cache: falls back to python3 -m shepherd_cli (unchanged contract)"
else
  fail "python3 fallback" "out=${out:0:200}"
fi

# ---------------------------------------------------------------------------
# 5. The other half of the T3-startup-cost interaction: a cache file that IS
#    present and valid must actually be TRUSTED — zero poetry invocations —
#    not merely "not break case 4 above". Builds a synthetic provisioned venv
#    (a `bin/shepherd` console script is enough for venv_provisioned() — the
#    SAME function the uncached path already runs — to pass it), points
#    VENV_PY_CACHE at its interpreter, and puts a poetry STUB on PATH that
#    drops a marker file if it is ever invoked at all, then asserts BOTH that
#    the cached interpreter's own output came back and that the marker was
#    never created. Before this case, nothing asserted the cache was used for
#    anything — the perf fix had a timing test only (services/cli/tests/
#    test_cli_startup_cost.py), never a behavioral one.
# ---------------------------------------------------------------------------
total=$((total+1))
CACHE_ROOT="$(mk_fake_root cache-hit-root)"
CACHE_VENV="$CACHE_ROOT/services/cli/.venv"
mkdir -p "$CACHE_VENV/bin"
cat > "$CACHE_VENV/bin/python" <<'STUB'
#!/bin/sh
echo "cached-python-used $*"
STUB
chmod +x "$CACHE_VENV/bin/python"
: > "$CACHE_VENV/bin/shepherd"; chmod +x "$CACHE_VENV/bin/shepherd"
printf '%s\n' "$CACHE_VENV/bin/python" > "$CACHE_VENV/.shepherd-venv-python"

poetry_marker="$tmp/poetry-was-invoked"
fakebin_poetry="$tmp/fakebin-poetry-present"; mkdir -p "$fakebin_poetry"
for t in bash sed grep dirname mktemp env cat rm; do
  src="$(command -v "$t" 2>/dev/null || true)"
  [[ -n "$src" ]] && ln -sf "$src" "$fakebin_poetry/$t"
done
cat > "$fakebin_poetry/poetry" <<STUB
#!/bin/sh
# Shell-builtin marker write, not \`touch\` -- this stub's own PATH is the
# same minimal fakebin_poetry set bin/shepherd would see, so the marker
# itself must never depend on an external command being resolvable.
: > "$poetry_marker"
echo "poetry stub invoked -- the cache fast path should have skipped this" >&2
exit 1
STUB
chmod +x "$fakebin_poetry/poetry"

cache_out="$(PATH="$fakebin_poetry" CLAUDE_PLUGIN_ROOT="$CACHE_ROOT" bash "$WRAPPER" --version 2>&1 || true)"
if printf '%s' "$cache_out" | grep -q 'cached-python-used' && [ ! -e "$poetry_marker" ]; then
  pass "valid cache + poetry present: fast path trusts the cache, poetry never invoked"
else
  invoked=no; [ -e "$poetry_marker" ] && invoked=yes
  fail "cache fast path is used" "out=${cache_out:0:200} poetry_invoked=$invoked"
fi

# ---------------------------------------------------------------------------
# 6. The wrapper's refusal message names the recovery command, not an import
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
