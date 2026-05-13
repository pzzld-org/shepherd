#!/usr/bin/env bash
# shepherd hook — PostToolUse(Bash): cwd drift detection (v5.0.9)
#
# Fires after every Bash tool call. Detects if the conductor's cwd has drifted
# into a sub-worktree — the most common silent fault (conductor-cwd.md §IV).
#
# Does NOT block (PostToolUse cannot deny). Injects an additionalContext
# warning so the conductor notices the drift before the next operation.
#
# Input (stdin): PostToolUse JSON payload { tool_name, tool_input, tool_response, ... }
# Output: {"additionalContext":"..."} warning, or exit 0 if anchor is clean.

set -euo pipefail

# Consume stdin — not needed for this check
cat > /dev/null

# Skip if not a shepherd project
[[ -f ".claude/shepherd.toml" ]] || exit 0

# Check if we are inside a sub-worktree
git_dir=$(git rev-parse --git-dir 2>/dev/null || echo "")
git_common=$(git rev-parse --git-common-dir 2>/dev/null || echo "")

if [[ -n "$git_dir" && "$git_dir" != "$git_common" ]]; then
  sprint_root=$(git rev-parse --git-common-dir 2>/dev/null | sed 's|/\.git$||; s|/.git$||' || echo "unknown")
  cwd=$(pwd)
  msg="[shepherd] CWD DRIFT DETECTED — conductor is now inside a sub-worktree."$'\n'
  msg+="  cwd:        $cwd"$'\n'
  msg+="  sprint root: $sprint_root"$'\n'
  msg+="Recovery: cd $sprint_root"$'\n'
  msg+="Then verify: git rev-parse --abbrev-ref HEAD (should be sprint branch)"$'\n'
  msg+="See doctrines/conductor-cwd.md §Mandatory verification"

  if command -v jq &>/dev/null; then
    jq -n --arg ctx "$msg" '{"additionalContext": $ctx}'
  else
    python3 -c "import json,sys; print(json.dumps({'additionalContext': sys.argv[1]}))" "$msg"
  fi
fi
