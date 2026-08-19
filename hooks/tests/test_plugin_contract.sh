#!/usr/bin/env bash
# The plugin layout contract must fail locally, not 20 minutes later in CI.
#
# scripts/check-plugin.py enforces 11 rules, including the one that matters
# most for a cross-harness plugin: plugins/shepherd/codex/skills/*/SKILL.md
# must be BYTE-IDENTICAL to the canonical skills/*/SKILL.md it projects.
# Until this file existed, that script ran in .github/workflows/rust.yml and
# NOWHERE else, so editing a canonical skill and forgetting its Codex carrier
# produced a green local suite and a red `fmt + workspace invariants` job.
# That is exactly how v6.5.1 broke: skills/shepherd/SKILL.md gained a
# Preconditions section, the carrier did not, and the local gate lane had
# nothing to say about it.
#
# The script is deterministic, offline, and finishes in well under a second,
# so there was never a budget reason to keep it out of the gate lane.
#
# Both modes CI runs are reproduced here: --self-test (does the checker's own
# falsification harness still hold) and the plain scan (does this repo pass).
#
# D6, on THIS file's own falsification: the scratch copy this file builds to
# inject drift into used to list only (scripts skills agents hooks plugins
# .claude-plugin) -- it omitted .agents/ (rule_codex_carrier_is_regular_and_
# canonical reads .agents/plugins/marketplace.json) and content/ (it drives
# the Codex reconciliation count and portability logic). The checker exited
# non-zero on that scratch copy with NO DRIFT INJECTED AT ALL, so the one
# falsification this file ran was vacuous from the hour it was written: it
# would have stayed green even if the checker stopped comparing bytes
# entirely. Every falsification below is now a TWO-SIDED control, in this
# fixed order: FIRST assert the unmutated scratch copy is CLEAN (the checker
# exits 0 on it) -- a failure there is reported as its own distinct, loud
# failure naming what the fixture is missing, never papered over -- THEN
# inject drift and require a non-zero exit. A rule that fails on everything,
# including a correct tree, is indistinguishable from a rule that works.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CHECKER="$ROOT/scripts/check-plugin.py"
fails=0
checks=0

fail() { checks=$((checks + 1)); printf '  FAIL  %s\n' "$1" >&2; fails=$((fails + 1)); }
pass() { checks=$((checks + 1)); printf '  PASS  %s\n' "$1"; }

if [[ ! -x "$CHECKER" ]]; then
  fail "scripts/check-plugin.py is missing or not executable: $CHECKER"
  printf '%s/%s passed\n' "$((checks - fails))" "$checks"
  exit "$fails"
fi

# The checker ships its own falsification harness. If that harness stops
# holding, every rule below it is unverified, so it is checked first.
if output="$("$CHECKER" --self-test 2>&1)"; then
  pass "check-plugin.py --self-test holds (the rules can still fail)"
else
  fail "check-plugin.py --self-test: ${output}"
fi

if output="$("$CHECKER" 2>&1)"; then
  pass "all plugin contract rules hold ($(printf '%s' "$output" | tail -1))"
else
  fail "plugin contract violation: ${output}"
fi

# Every tree scripts/check-plugin.py opens: the component dirs, both
# marketplace manifests, the thin carrier, and the authored content that
# drives the Codex reconciliation rule (content/RECONCILIATION.md, the
# `portability: claude-only` markers in content/skills/*/SKILL.md). This
# list is measured, not assumed -- see the D6 note above: dropping .agents/
# or content/ makes assert_scratch_clean (below) fail on an UNMUTATED copy.
PLUGIN_CONTRACT_PARTS=(scripts skills agents hooks plugins .claude-plugin .agents content bin)

SCRATCH_DIRS=()
trap 'rm -rf "${SCRATCH_DIRS[@]:-}"' EXIT

# Build a fresh scratch copy of the whole plugin-contract surface. `cp -R`
# preserves symlinks as symlinks on macOS (the thin carrier is symlink-based:
# plugins/shepherd/hooks/scripts, plugins/shepherd/bin, plugins/shepherd/
# {agents,skills}), which each falsification below verifies rather than
# trusts, before it relies on that symlink existing. Prints the new scratch
# root's path on stdout; callers must NOT call this from inside another
# function whose own output is captured, since command substitution runs
# this in a subshell and any state mutated here (besides the printed path)
# would not survive back to the caller.
build_scratch() {
  local scratch
  scratch="$(mktemp -d)"
  for part in "${PLUGIN_CONTRACT_PARTS[@]}"; do
    if [[ -e "$ROOT/$part" ]]; then
      cp -R "$ROOT/$part" "$scratch/"
    fi
  done
  printf '%s\n' "$scratch"
}

# First half of every two-sided falsification: the checker must exit 0 on
# the scratch copy before anything is mutated. A failure here means the
# fixture itself -- not the checker, not the drift -- is incomplete, and is
# reported as its own distinct failure so it is never mistaken for a
# genuine detection.
assert_scratch_clean() {
  local scratch="$1" label="$2"
  if output="$(cd "$scratch" && ./scripts/check-plugin.py 2>&1)"; then
    pass "scratch fixture for '$label' is clean before drift is injected"
  else
    fail "scratch fixture for '$label' is NOT clean before drift is injected -- the copy list omits something the checker reads: ${output}"
  fi
}

# Second half: after drift is injected, the checker must exit non-zero.
assert_checker_now_fails() {
  local scratch="$1" label="$2"
  if output="$(cd "$scratch" && ./scripts/check-plugin.py 2>&1)"; then
    fail "falsification: $label was NOT detected"
  else
    pass "falsification: $label is detected"
  fi
}

# Falsification 1 -- the headline case: a carrier missing its hooks/scripts
# symlink. This is the original D1 defect (43 hook registrations pointing at
# scripts that no longer existed, shipped dead for four releases) reproduced
# exactly: every ${CLAUDE_PLUGIN_ROOT}/hooks/scripts/... ref in
# plugins/shepherd/hooks/hooks.json resolves through this one link.
scratch="$(build_scratch)"
SCRATCH_DIRS+=("$scratch")
assert_scratch_clean "$scratch" "carrier hook-script reachability"
CARRIER_SCRIPTS_LINK="$scratch/plugins/shepherd/hooks/scripts"
if [[ -L "$CARRIER_SCRIPTS_LINK" ]]; then
  rm -f "$CARRIER_SCRIPTS_LINK"
  assert_checker_now_fails "$scratch" "a carrier missing plugins/shepherd/hooks/scripts"
else
  fail "falsification fixture: plugins/shepherd/hooks/scripts is not a symlink at $CARRIER_SCRIPTS_LINK (cp -R did not preserve it, or the carrier layout changed)"
fi

# Falsification 2: drift the Codex carrier in a scratch copy and require a
# non-zero exit. Without this, a checker that silently stopped comparing
# bytes would leave this test permanently, uselessly green.
scratch="$(build_scratch)"
SCRATCH_DIRS+=("$scratch")
assert_scratch_clean "$scratch" "Codex carrier byte-identity"
CARRIER_SKILL="$scratch/plugins/shepherd/codex/skills/shepherd/SKILL.md"
if [[ -f "$CARRIER_SKILL" ]]; then
  printf '\n<!-- drift injected by test_plugin_contract.sh -->\n' >>"$CARRIER_SKILL"
  assert_checker_now_fails "$scratch" "a drifted Codex carrier"
else
  fail "falsification fixture: carrier SKILL.md not found at $CARRIER_SKILL"
fi

printf '%s/%s passed\n' "$((checks - fails))" "$checks"
exit "$fails"
