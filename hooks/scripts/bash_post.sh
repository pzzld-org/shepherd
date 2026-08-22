#!/usr/bin/env bash
# shepherd hook — PostToolUse(Bash): cwd drift detection (v5.1.2).
#
# Fires after every Bash tool call and emits generic worktree-cwd telemetry.
# It does not derive gate provenance from command text or tool status. Gate
# invocation and result evidence belongs to the wave-owned artifact boundary.
# Role-aware authorization belongs to the typed native guard, not a shell
# tool-use id.
#
# Does NOT block (PostToolUse cannot deny). Injects an additionalContext
# warning so the conductor notices the drift before the next operation.

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

input=$(cat)
is_shepherd_project || exit 0
shepherd_skip_without_jq "bash_post" || exit 0

session=$(json_field "$input" '.session_id')
role="unknown"

if in_subworktree; then
  sr=$(sprint_root)
  cwd=$(pwd)
  msg="[shepherd] CWD NOTICE — session is now inside a sub-worktree."$'\n'
  msg+="  cwd:        $cwd"$'\n'
  msg+="  sprint root: $sr"$'\n'
  msg+="Recovery: cd $sr"$'\n'
  msg+="Native dispatch scope determines whether work in this location is authorized."
  emit_context "$msg" "bash_post" "Bash" "$role" "$session"
fi

pass_silent "bash_post" "Bash" "$role" "$session"
