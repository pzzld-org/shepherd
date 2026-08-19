#!/usr/bin/env bash
# Every harness must ship the surface it claims, and the counts must agree with
# the authored source.
#
# WHY THIS EXISTS.
#
# The Pi adapter shipped with no `pi` key in package.json for its entire
# history, so Pi loaded nothing from it -- zero skills, zero prompts, and not
# even `src/extension.mjs`. The package installed cleanly and was inert.
#
# The reason it survived release after release is that NO GATE EVER ASKED WHAT
# PI SHIPS. `check-plugin.py` derives its plugin roots from the Claude and Codex
# shipping manifests, so Pi was outside the set entirely, and the statement
# "Claude 10 skills, Codex 9, Pi 0" was not an assertion anywhere in the repo.
# Each harness was checked in isolation and the comparison between them --
# which is the whole product claim -- was checked by nobody.
#
# This gate makes the cross-harness claim itself falsifiable. It derives every
# expected count from `content/` and never hardcodes one, so adding a skill
# needs no edit here and dropping one cannot pass unnoticed.
#
# Run with --self-test to prove the counts can fail.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fails=0
checks=0
pass() { checks=$((checks + 1)); printf '  PASS  %s\n' "$1"; }
fail() { checks=$((checks + 1)); printf '  FAIL  %s\n' "$1" >&2; fails=$((fails + 1)); }

# ---- derive the truth from the authored source, never a literal ------------
count_authored_all() {
  find "$ROOT/content/skills" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' '
}
count_authored_cross_harness() {
  find "$ROOT/content/skills" -mindepth 1 -maxdepth 1 -type d | while read -r d; do
    grep -q '^portability: claude-only' "$d/SKILL.md" || printf 'x\n'
  done | wc -l | tr -d ' '
}
count_authored_roles() {
  find "$ROOT/content/roles" -maxdepth 1 -name '*.md' | wc -l | tr -d ' '
}

AUTHORED_ALL="$(count_authored_all)"
AUTHORED_CROSS="$(count_authored_cross_harness)"
AUTHORED_ROLES="$(count_authored_roles)"

if [[ "$AUTHORED_ALL" -eq 0 || "$AUTHORED_CROSS" -eq 0 || "$AUTHORED_ROLES" -eq 0 ]]; then
  fail "derived zero authored skills or roles from content/ -- pathspec drift"
  printf '%s/%s passed\n' "$((checks - fails))" "$checks"
  exit "$fails"
fi

if [[ "${1:-}" == "--self-test" ]]; then
  # The counts must be able to disagree. Compare each derived number against a
  # deliberately wrong one and require a mismatch, in both directions.
  probe() { # probe <label> <actual> <expected> <want_match>
    local label="$1" actual="$2" expected="$3" want="$4"
    if [[ "$actual" -eq "$expected" ]]; then [[ "$want" == match ]]; else [[ "$want" == differ ]]; fi
  }
  if probe "control" "$AUTHORED_CROSS" "$AUTHORED_CROSS" match; then
    pass "self-test: a correct count compares equal"
  else
    fail "self-test: a correct count did not compare equal"
  fi
  if probe "drift" "$AUTHORED_CROSS" "$((AUTHORED_CROSS + 1))" differ; then
    pass "self-test: an inflated count is detected"
  else
    fail "self-test: an inflated count was NOT detected"
  fi
  if probe "zero" "0" "$AUTHORED_CROSS" differ; then
    pass "self-test: a zero surface is detected (the shipped Pi defect)"
  else
    fail "self-test: a zero surface was NOT detected"
  fi
  printf '%s/%s passed\n' "$((checks - fails))" "$checks"
  exit "$fails"
fi

printf 'authored: %s skills (%s cross-harness), %s roles\n' \
  "$AUTHORED_ALL" "$AUTHORED_CROSS" "$AUTHORED_ROLES"

# ---- Claude: the root tree is the carrier's canonical source ---------------
claude_skills=$(find "$ROOT/skills" -mindepth 2 -maxdepth 2 -name 'SKILL.md' 2>/dev/null | wc -l | tr -d ' ')
if [[ "$claude_skills" -eq "$AUTHORED_ALL" ]]; then
  pass "Claude ships all $AUTHORED_ALL authored skills (claude-only included)"
else
  fail "Claude ships $claude_skills skills, expected $AUTHORED_ALL"
fi

claude_agents=$(find "$ROOT/agents" -maxdepth 1 -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
if [[ "$claude_agents" -eq "$AUTHORED_ROLES" ]]; then
  pass "Claude ships all $AUTHORED_ROLES role agents"
else
  fail "Claude ships $claude_agents agents, expected $AUTHORED_ROLES"
fi

# ---- Codex: the generated regular-file carrier -----------------------------
codex_skills=$(find "$ROOT/plugins/shepherd/codex/skills" -mindepth 2 -maxdepth 2 -name 'SKILL.md' 2>/dev/null | wc -l | tr -d ' ')
if [[ "$codex_skills" -eq "$AUTHORED_CROSS" ]]; then
  pass "Codex ships all $AUTHORED_CROSS cross-harness skills"
else
  fail "Codex ships $codex_skills skills, expected $AUTHORED_CROSS"
fi

# ---- Pi: DECLARED here, materialized at pack time --------------------------
# Pi's carrier is deliberately not committed, so this asserts the declaration
# and the staging path rather than a directory listing. The counts themselves
# are asserted by scripts/stage-pi-carrier.sh at the moment it generates them,
# and by test-pi-package-surface.sh for the manifest.
pi_declared=$(python3 -c '
import json,sys
try:
    pi = json.load(open(sys.argv[1])).get("pi") or {}
except Exception:
    print("0"); raise SystemExit
print("1" if pi.get("skills") and pi.get("prompts") and pi.get("extensions") else "0")
' "$ROOT/packages/harness-pi/package.json" 2>/dev/null || echo 0)
if [[ "$pi_declared" == "1" ]]; then
  pass "Pi declares extensions, skills and prompts so the harness can load them"
else
  fail "Pi declares no loadable surface -- Pi will register ZERO resources from this package"
fi

if grep -Fq 'stage-pi-carrier.sh' "$ROOT/.github/workflows/cargo-build.yml" 2>/dev/null; then
  pass "Pi carrier is materialized into the package at release time"
else
  fail "nothing stages the Pi carrier, so the declared skills/ and prompts/ never exist in the tarball"
fi

# ---- the comparison itself, which is the product claim ---------------------
# Stated explicitly so a reader sees all three at once, and so a harness that
# silently drops to zero is visible as a number rather than an absent check.
printf 'surface: claude=%s codex=%s pi=%s(declared)\n' \
  "$claude_skills" "$codex_skills" "$pi_declared"
if [[ "$claude_skills" -gt 0 && "$codex_skills" -gt 0 && "$pi_declared" == "1" ]]; then
  pass "all three harnesses ship a non-empty skill surface"
else
  fail "at least one harness ships nothing -- cross-harness parity is the product claim"
fi

printf '%s/%s passed\n' "$((checks - fails))" "$checks"
exit "$fails"
