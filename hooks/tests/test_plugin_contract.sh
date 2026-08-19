#!/usr/bin/env bash
# The plugin layout contract must fail locally, not 20 minutes later in CI.
#
# scripts/check-plugin.py enforces 10 rules, including the one that matters
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

# Falsification for THIS test: drift the Codex carrier in a scratch copy and
# require a non-zero exit. Without this, a checker that silently stopped
# comparing bytes would leave the test permanently, uselessly green.
SCRATCH="$(mktemp -d)"
trap 'rm -rf "$SCRATCH"' EXIT
# Copy only what the contract rules read; a full-repo copy would be slow
# enough to push this test out of the <2s gate budget it belongs in.
for part in scripts skills agents hooks plugins .claude-plugin; do
  [[ -e "$ROOT/$part" ]] && cp -R "$ROOT/$part" "$SCRATCH/"
done

CARRIER="$SCRATCH/plugins/shepherd/codex/skills/shepherd/SKILL.md"
if [[ -f "$CARRIER" ]]; then
  printf '\n<!-- drift injected by test_plugin_contract.sh -->\n' >>"$CARRIER"
  if (cd "$SCRATCH" && ./scripts/check-plugin.py >/dev/null 2>&1); then
    fail "falsification: a drifted Codex carrier was NOT detected"
  else
    pass "falsification: a drifted Codex carrier is detected"
  fi
else
  fail "falsification fixture: carrier SKILL.md not found at $CARRIER"
fi

printf '%s/%s passed\n' "$((checks - fails))" "$checks"
exit "$fails"
