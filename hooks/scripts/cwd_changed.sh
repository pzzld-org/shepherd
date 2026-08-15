#!/usr/bin/env bash
# shepherd hook — cwd-change early-warning (v5.1.8)
#
# Fires at CwdChanged (Claude Code v2.1+). Triggers any time cwd changes
# mid-session — e.g. when Claude executes a `cd` via Bash.
#
# The event does not carry a portable role identity. This telemetry hook emits
# a generic warning when the current session is inside a worktree; typed native
# dispatch ownership decides whether that location is authorized.
#
# CwdChanged payload (per https://code.claude.com/docs/en/hooks):
#   { "session_id", "transcript_path", "cwd", "hook_event_name" }
# Note: the event does NOT carry a `previous_cwd` field. The spec also
# states CwdChanged has no decision control — output is informational
# (stderr to user, JSON suppressOutput-style fields only). We still emit
# additionalContext via emit_context; the runtime may relegate it to
# user-only display, while the run-scoped event remains available for audit.
#
# Output: informational only — never blocks (exit 0 unconditionally).

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

input=$(cat 2>/dev/null || true)

is_shepherd_project || exit 0
shepherd_skip_without_jq "cwd_changed" || exit 0

session=$(json_field "$input" '.session_id')
new_cwd=$(json_field "$input" '.cwd')

role="unknown"

# in_subworktree inspects the actual filesystem state (git-dir vs git-common-dir),
# which is more reliable than parsing the cwd string itself.
if in_subworktree; then
  sr=$(sprint_root)
  msg="[shepherd] CwdChanged WARN — session cwd is inside a sub-worktree."$'\n'
  msg+="  Cwd:         ${new_cwd:-$(pwd)}"$'\n'
  msg+="  Sprint root: $sr"$'\n'
  msg+="Recover: cd $sr"$'\n'
  msg+="Use 'git -C <path>' for inspection. Native dispatch scope determines whether"$'\n'
  msg+="the session may work in this location."
  emit_context "$msg" "cwd_changed" "Cwd" "$role" "$session"
fi

pass_silent "cwd_changed" "Cwd" "$role" "$session" \
  "$(emit_json_obj cwd "$new_cwd")"
