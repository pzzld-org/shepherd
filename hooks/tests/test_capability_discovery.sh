#!/usr/bin/env bash
# hooks/tests/test_capability_discovery.sh — tests for capability_discovery.sh
# (v6.1.5, #146).
#
# Covers the SessionStart capability-discovery probe:
#   1. Not a shepherd project → silent no-op, no roster written.
#   2. [discovery].auto_capabilities = off → no-op, no roster written.
#   3. Enabled (default) → writes EPHEMERAL roster to cache/, NOT toolkit.json.
#   4. Discovered plugins (/remember, superpowers) land in the roster.
#   5. Idempotent within a session (marker fast-path; roster unchanged).
#   6. Graceful-degrade — roster always carries the agent_fillin contract
#      (workflow-tool presence hand-off) even with zero discovered capabilities.
#   7. The roster is valid JSON and never the curated toolkit.json path.

set -eu -o pipefail
cd "$(dirname "$0")"
HOOKS_DIR="$(cd .. && pwd)/scripts"
SCRIPT="$HOOKS_DIR/capability_discovery.sh"

fails=0; total=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s — %s\n' "$1" "${2:-}"; fails=$((fails+1)); }

if ! command -v jq >/dev/null 2>&1; then
  echo "  SKIP  jq unavailable — capability_discovery requires jq"
  echo "—— 0/0 passed (skipped) ——"; exit 0
fi

run_hook() { printf '%s' "$1" | bash "$SCRIPT" 2>/dev/null; return 0; }
PAYLOAD='{"session_id":"sess-cap","source":"startup","hook_event_name":"SessionStart"}'

# 1. No shepherd.toml → silent no-op, no roster.
total=$((total+1))
bare=$(mktemp -d -t shep-cap-bare.XXXXXX)
(
  cd "$bare"; git init -q .; git config user.email t@t; git config user.name t
  git -c commit.gpgsign=false commit -q --allow-empty -m init
  out=$(run_hook "$PAYLOAD")
  if [[ -z "$out" && ! -f ".shepherd/cache/discovered-capabilities.json" && ! -f ".artifacts/cache/discovered-capabilities.json" ]]; then
    printf '  PASS  no-shepherd-toml: silent, no roster\n'
  else
    printf '  FAIL  no-shepherd-toml: out=%s\n' "${out:0:60}"; exit 1
  fi
) || fails=$((fails+1))
rm -rf "$bare"

# Shared shepherd-flagged repo. Isolate XDG + a fake CLAUDE_CONFIG_DIR plugin/
# skill tree so the probe enumerates a controlled environment, not the host's.
tmp=$(mktemp -d -t shep-cap.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"; git init -q .; git config user.email t@t; git config user.name t
git -c commit.gpgsign=false commit -q --allow-empty -m init
mkdir -p .claude .artifacts; touch .claude/shepherd.toml
export XDG_CONFIG_HOME="$tmp/xdg"; mkdir -p "$XDG_CONFIG_HOME/shepherd"
# Fake Claude config tree with two opportunistic plugins + one skill.
export CLAUDE_CONFIG_DIR="$tmp/cc"
mkdir -p "$CLAUDE_CONFIG_DIR/plugins/remember/.claude-plugin"
mkdir -p "$CLAUDE_CONFIG_DIR/plugins/superpowers/.claude-plugin"
mkdir -p "$CLAUDE_CONFIG_DIR/skills/deep-research"
touch "$CLAUDE_CONFIG_DIR/skills/deep-research/SKILL.md"

ROSTER=".artifacts/cache/discovered-capabilities.json"
TOOLKIT=".artifacts/toolkit.json"
# Seed a curated toolkit.json to prove discovery never writes into it.
printf '{"version":1,"scope":"local","updated_at":1,"tools":[]}\n' > "$TOOLKIT"
TOOLKIT_BEFORE=$(cat "$TOOLKIT")

# 2. Disabled via config → no-op, no roster.
total=$((total+1))
printf '[discovery]\nauto_capabilities = off\n' > .claude/shepherd.toml
rm -f "$ROSTER"
run_hook "$PAYLOAD" >/dev/null
if [[ ! -f "$ROSTER" ]]; then
  pass "disabled: no roster written"
else
  fail "disabled" "roster exists despite auto_capabilities=off"
fi

# Re-enable (empty toml = default on).
printf '' > .claude/shepherd.toml
# Clear any stale per-session marker so the probe runs.
rm -f .artifacts/cache/.capdisc-*.probed "$ROSTER" 2>/dev/null || true

# 3. Enabled → writes ephemeral roster to cache/, NOT toolkit.json.
total=$((total+1))
run_hook "$PAYLOAD" >/dev/null
if [[ -f "$ROSTER" ]] && jq -e . "$ROSTER" >/dev/null 2>&1; then
  pass "enabled: ephemeral roster written + valid JSON"
else
  fail "enabled" "roster missing or invalid JSON"
fi

# 3b. Curated toolkit.json untouched.
total=$((total+1))
if [[ "$(cat "$TOOLKIT")" == "$TOOLKIT_BEFORE" ]]; then
  pass "curated toolkit.json never written by discovery"
else
  fail "toolkit-untouched" "toolkit.json changed"
fi

# 4. Discovered plugins land in the roster (/remember, superpowers, skill).
total=$((total+1))
names=$(jq -r '.capabilities[].name' "$ROSTER" 2>/dev/null | tr '\n' ' ')
if grep -q "remember" <<<"$names" && grep -q "superpowers" <<<"$names" && grep -q "deep-research" <<<"$names"; then
  pass "discovers plugins + skills: remember, superpowers, deep-research"
else
  fail "discovers" "names=[$names]"
fi

# 4b. The /remember entry carries the guarded handoff/CLOSE-FINALIZE guidance.
total=$((total+1))
rem_desc=$(jq -r '.capabilities[] | select(.name=="remember") | .description' "$ROSTER" 2>/dev/null || true)
if grep -qi "handoff" <<<"$rem_desc"; then
  pass "remember entry carries handoff/CLOSE-FINALIZE guidance"
else
  fail "remember-guidance" "desc=$rem_desc"
fi

# 5. Idempotent within a session: re-run no-ops (marker fast-path), roster same.
total=$((total+1))
before=$(cat "$ROSTER")
# Mutate the env so a (wrongly) re-running probe would change the roster.
mkdir -p "$CLAUDE_CONFIG_DIR/plugins/zzz-new-plugin/.claude-plugin"
run_hook "$PAYLOAD" >/dev/null
after=$(cat "$ROSTER")
if [[ "$before" == "$after" ]]; then
  pass "idempotent within session: marker fast-path skips re-probe"
else
  fail "idempotent" "roster changed on second run within session"
fi

# 6. Graceful-degrade: agent_fillin contract present + workflow-tool hand-off.
total=$((total+1))
has_fillin=$(jq -r 'has("agent_fillin") and (.agent_fillin | has("workflow_tool"))' "$ROSTER" 2>/dev/null || echo false)
present_field=$(jq -r '.agent_fillin.workflow_tool | has("present")' "$ROSTER" 2>/dev/null || echo false)
if [[ "$has_fillin" == "true" && "$present_field" == "true" ]]; then
  pass "agent_fillin: workflow-tool presence hand-off contract present"
else
  fail "agent-fillin" "has_fillin=$has_fillin present=$present_field"
fi

# 6b. Empty environment (no plugins/skills) still writes a roster with the
#     contract (graceful-degrade on missing tools).
total=$((total+1))
empty_cc="$tmp/cc-empty"; mkdir -p "$empty_cc"
CLAUDE_CONFIG_DIR="$empty_cc" \
  bash -c 'rm -f .artifacts/cache/.capdisc-*.probed .artifacts/cache/discovered-capabilities.json 2>/dev/null; printf "%s" "$0" | bash "$1"' \
  "$PAYLOAD" "$SCRIPT" >/dev/null 2>&1 || true
if [[ -f "$ROSTER" ]] && [[ "$(jq -r '.count' "$ROSTER" 2>/dev/null)" == "0" ]] \
   && [[ "$(jq -r 'has("agent_fillin")' "$ROSTER" 2>/dev/null)" == "true" ]]; then
  pass "empty-env: roster written with count=0 + agent_fillin contract"
else
  fail "empty-env" "count=$(jq -r '.count' "$ROSTER" 2>/dev/null) roster=$ROSTER"
fi

echo "—— $((total-fails))/$total passed ——"
exit "$fails"
