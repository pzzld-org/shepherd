#!/usr/bin/env bash
# hooks/tests/hotfix_vehicle_guard_test.sh — tests for hotfix_vehicle_guard.sh
#
# Covers the PreToolUse(Agent|Task) hotfix cardinality guard (v6.0.9, Item D, #135):
#   1. H == 1 + teammate spawn (team_name set) → DENY with WRONG-VEHICLE.
#   2. H == 1 + teammate spawn (shepherd:conductor) → DENY with WRONG-VEHICLE.
#   3. H == 1 + non-teammate subagent (@coder, no team_name) → PASS.
#   4. H == 2 + teammate spawn → PASS (H > 1 allows teammate).
#   5. H == 6 + teammate spawn → PASS (H >= 6 allows full lane).
#   6. No hotfix-context.json (H unknown) → PASS (fail-open).
#   7. cluster_count absent from context JSON → PASS (fail-open).
#   8. Non-Agent/Task tool → PASS (guard ignores it).
#   9. No shepherd.toml → PASS (not a shepherd project).

set -eu -o pipefail
cd "$(dirname "$0")"
HOOKS_DIR="$(cd .. && pwd)/scripts"
SCRIPT="$HOOKS_DIR/hotfix_vehicle_guard.sh"

fails=0
total=0
pass()  { printf '  PASS  %s\n' "$1"; }
fail()  { printf '  FAIL  %s — %s\n' "$1" "$2"; fails=$((fails+1)); }

is_deny()  { printf '%s' "$1" | grep -q '"permissionDecision"[[:space:]]*:[[:space:]]*"deny"'; }
has_code() { printf '%s' "$1" | grep -q "WRONG-VEHICLE"; }

run_hook() {
  local payload="$1"
  printf '%s' "$payload" | bash "$SCRIPT" 2>/dev/null
  return 0
}

# ---------------------------------------------------------------------------
# 1. No shepherd.toml → PASS.
# ---------------------------------------------------------------------------
total=$((total+1))
tmp_bare=$(mktemp -d -t shep-hvg-bare.XXXXXX)
(
  cd "$tmp_bare"
  git init -q . && git config user.email t@t && git config user.name t
  git -c commit.gpgsign=false commit -q --allow-empty -m init
  out=$(printf '{"session_id":"s1","tool_name":"Agent","tool_input":{"subagent_type":"shepherd:conductor","team_name":"hotfix-lane"}}' | bash "$SCRIPT" 2>/dev/null) || true
  if ! is_deny "$out"; then
    printf '  PASS  no-shepherd-toml: pass (not a shepherd project)\n'
  else
    printf '  FAIL  no-shepherd-toml: pass — got deny: %s\n' "${out:0:80}"
    exit 1
  fi
) || fails=$((fails+1))
rm -rf "$tmp_bare"

# ---------------------------------------------------------------------------
# Shared ephemeral shepherd-flagged repo with a hotfix-context.json.
# ---------------------------------------------------------------------------
tmp=$(mktemp -d -t shep-hvg-test.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q .
git config user.email t@t
git config user.name t
git -c commit.gpgsign=false commit -q --allow-empty -m init
mkdir -p .claude .artifacts/tmp
touch .claude/shepherd.toml

HF_CTX=".artifacts/tmp/hotfix-context.json"

set_H() { printf '{"cluster_count":%d}' "$1" > "$HF_CTX"; }
clear_H() { rm -f "$HF_CTX" 2>/dev/null || true; }

# Payload builders.
P_TEAMMATE_TEAM_NAME() {
  # Spawning via team_name (AgentTeams path).
  printf '{"session_id":"s1","tool_name":"Agent","tool_input":{"subagent_type":"shepherd:conductor","team_name":"hotfix-lane"}}'
}
P_TEAMMATE_CONDUCTOR() {
  # Spawning via subagent_type=shepherd:conductor (no explicit team_name, but type signals teammate).
  printf '{"session_id":"s1","tool_name":"Agent","tool_input":{"subagent_type":"shepherd:conductor"}}'
}
P_STEP_CODER() {
  # Regular subagent dispatch — not a teammate.
  printf '{"session_id":"s1","tool_name":"Agent","tool_input":{"subagent_type":"shepherd:coder"}}'
}
P_TASK_TEAMMATE() {
  printf '{"session_id":"s1","tool_name":"Task","tool_input":{"subagent_type":"shepherd:conductor","team_name":"hotfix-lane"}}'
}
P_BASH() {
  printf '{"session_id":"s1","tool_name":"Bash","tool_input":{"command":"ls"}}'
}

# ---------------------------------------------------------------------------
# 2. H == 1 + teammate spawn (team_name) → DENY + WRONG-VEHICLE.
# ---------------------------------------------------------------------------
total=$((total+1))
set_H 1
out=$(run_hook "$(P_TEAMMATE_TEAM_NAME)")
if is_deny "$out" && has_code "$out"; then
  pass "H=1 + team_name: DENY + WRONG-VEHICLE"
else
  fail "H=1 + team_name: DENY + WRONG-VEHICLE" "out=${out:0:120}"
fi

# ---------------------------------------------------------------------------
# 3. H == 1 + shepherd:conductor subagent_type → DENY + WRONG-VEHICLE.
# ---------------------------------------------------------------------------
total=$((total+1))
set_H 1
out=$(run_hook "$(P_TEAMMATE_CONDUCTOR)")
if is_deny "$out" && has_code "$out"; then
  pass "H=1 + shepherd:conductor: DENY + WRONG-VEHICLE"
else
  fail "H=1 + shepherd:conductor: DENY + WRONG-VEHICLE" "out=${out:0:120}"
fi

# ---------------------------------------------------------------------------
# 4. H == 1 + non-teammate subagent (@coder, no team_name) → PASS.
# ---------------------------------------------------------------------------
total=$((total+1))
set_H 1
out=$(run_hook "$(P_STEP_CODER)")
if ! is_deny "$out"; then
  pass "H=1 + coder-subagent (no team_name): PASS"
else
  fail "H=1 + coder-subagent (no team_name): PASS" "unexpectedly denied: ${out:0:80}"
fi

# ---------------------------------------------------------------------------
# 5. H == 2 + teammate spawn → PASS.
# ---------------------------------------------------------------------------
total=$((total+1))
set_H 2
out=$(run_hook "$(P_TEAMMATE_TEAM_NAME)")
if ! is_deny "$out"; then
  pass "H=2 + teammate: PASS (H>1 allows teammate)"
else
  fail "H=2 + teammate: PASS" "out=${out:0:80}"
fi

# ---------------------------------------------------------------------------
# 6. H == 6 + teammate spawn → PASS.
# ---------------------------------------------------------------------------
total=$((total+1))
set_H 6
out=$(run_hook "$(P_TEAMMATE_TEAM_NAME)")
if ! is_deny "$out"; then
  pass "H=6 + teammate: PASS"
else
  fail "H=6 + teammate: PASS" "out=${out:0:80}"
fi

# ---------------------------------------------------------------------------
# 7. No hotfix-context.json → PASS (fail-open on unknown H).
# ---------------------------------------------------------------------------
total=$((total+1))
clear_H
out=$(run_hook "$(P_TEAMMATE_TEAM_NAME)")
if ! is_deny "$out"; then
  pass "no-context-file: PASS (fail-open)"
else
  fail "no-context-file: PASS (fail-open)" "should not deny when H unknown; out=${out:0:80}"
fi

# ---------------------------------------------------------------------------
# 8. cluster_count absent from context JSON → PASS (fail-open).
# ---------------------------------------------------------------------------
total=$((total+1))
printf '{"note":"no cluster_count key here"}' > "$HF_CTX"
out=$(run_hook "$(P_TEAMMATE_TEAM_NAME)")
if ! is_deny "$out"; then
  pass "cluster_count-absent: PASS (fail-open)"
else
  fail "cluster_count-absent: PASS (fail-open)" "out=${out:0:80}"
fi

# ---------------------------------------------------------------------------
# 9. H == 1 + Task tool (not just Agent) → DENY.
# ---------------------------------------------------------------------------
total=$((total+1))
set_H 1
out=$(run_hook "$(P_TASK_TEAMMATE)")
if is_deny "$out" && has_code "$out"; then
  pass "H=1 + Task-tool teammate: DENY + WRONG-VEHICLE"
else
  fail "H=1 + Task-tool teammate: DENY + WRONG-VEHICLE" "out=${out:0:80}"
fi

# ---------------------------------------------------------------------------
# 10. Non-Agent/Task tool (Bash) → PASS regardless of H.
# ---------------------------------------------------------------------------
total=$((total+1))
set_H 1
out=$(run_hook "$(P_BASH)")
if ! is_deny "$out"; then
  pass "non-agent-tool: PASS (Bash is not guarded)"
else
  fail "non-agent-tool: PASS" "out=${out:0:80}"
fi

echo "—— $((total-fails))/$total passed ——"
exit "$fails"
