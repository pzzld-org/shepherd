#!/usr/bin/env bash
# shepherd hook — git commit guard (conductor-cwd doctrine §Ban 2)
#
# Fires at PreToolUse(Bash). Blocks any 'git commit' command when the
# conductor HEAD is on an agent/lane branch. The conductor MUST commit to
# the sprint branch; lane-branch commits are an auditor-detectable violation.
#
# Input (stdin): PreToolUse JSON payload { tool_name, tool_input.command, ... }
# Output: {"permissionDecision":"deny","message":"..."} to block, or exit 0 to allow.

set -euo pipefail

input=$(cat)

# Skip if not a shepherd project
[[ -f ".claude/shepherd.toml" ]] || exit 0

# Extract the Bash command from the PreToolUse payload
if command -v jq &>/dev/null; then
  cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null || true)
else
  cmd=$(printf '%s' "$input" | python3 -c \
    "import json,sys; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('command',''))" \
    2>/dev/null || true)
fi

# Only intercept git commit commands
[[ "$cmd" == *"git commit"* ]] || exit 0

# Check HEAD branch
branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
[[ "$branch" =~ ^(agent-|lane-) ]] || exit 0  # Not on a lane branch — allow

# Deny
msg="[shepherd] git commit BLOCKED — HEAD is on agent lane '$branch'."$'\n'
msg+="The conductor must only commit to the sprint branch, never an agent-* or lane-* branch."$'\n'
msg+="Recover: git checkout <sprint_branch>  (see doctrines/conductor-cwd.md §Ban 2)"

if command -v jq &>/dev/null; then
  jq -n --arg m "$msg" '{"permissionDecision": "deny", "message": $m}'
else
  python3 -c "import json,sys; print(json.dumps({'permissionDecision':'deny','message':sys.argv[1]}))" "$msg"
fi
