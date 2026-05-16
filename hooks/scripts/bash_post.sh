#!/usr/bin/env bash
# shepherd hook — PostToolUse(Bash): cwd drift detection (v5.1.2)
#
# Fires after every Bash tool call. Detects if the conductor's cwd has drifted
# into a sub-worktree — the most common silent fault (conductor-cwd.md §IV).
#
# Does NOT block (PostToolUse cannot deny). Injects an additionalContext
# warning so the conductor notices the drift before the next operation.

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

input=$(cat)
is_shepherd_project || exit 0

session=$(json_field "$input" '.session_id')
tool_use_id=$(json_field "$input" '.tool_use_id')
sprint=$(current_sprint)
role=$(current_role "$tool_use_id" "$sprint")

if in_subworktree; then
  sr=$(sprint_root)
  cwd=$(pwd)
  msg="[shepherd] CWD DRIFT DETECTED — conductor is now inside a sub-worktree."$'\n'
  msg+="  cwd:        $cwd"$'\n'
  msg+="  sprint root: $sr"$'\n'
  msg+="Recovery: cd $sr"$'\n'
  msg+="Then verify: git rev-parse --abbrev-ref HEAD (should be sprint branch)"$'\n'
  msg+="See doctrines/conductor-cwd.md §Mandatory verification"
  emit_context "$msg" "bash_post" "Bash" "$role" "$session"
fi

pass_silent "bash_post" "Bash" "$role" "$session"
