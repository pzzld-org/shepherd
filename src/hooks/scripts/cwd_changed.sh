#!/usr/bin/env bash
# shepherd hook — cwd-change early-warning (v5.1.8)
#
# Fires at CwdChanged (Claude Code v2.1+). Triggers any time cwd changes
# mid-session — e.g. when Claude executes a `cd` via Bash.
#
# The conductor must stay anchored to the sprint root per
# skills/shepherd/references/flock.md §Ban 1. Subagents (coders/auditors/workers)
# may legitimately inhabit a worktree, so this hook only surfaces a warning
# when the active role is `conductor`.
#
# CwdChanged payload (per https://code.claude.com/docs/en/hooks):
#   { "session_id", "transcript_path", "cwd", "hook_event_name" }
# Note: the event does NOT carry a `previous_cwd` field. The spec also
# states CwdChanged has no decision control — output is informational
# (stderr to user, JSON suppressOutput-style fields only). We still emit
# additionalContext via emit_context for telemetry parity with
# session_open.sh; the runtime may relegate it to user-only display but
# the log_event side-effect is what we care about for audit.
#
# Output: informational only — never blocks (exit 0 unconditionally).

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

input=$(cat 2>/dev/null || true)

is_shepherd_project || exit 0

session=$(json_field "$input" '.session_id')
new_cwd=$(json_field "$input" '.cwd')

sprint=$(current_sprint)
# CwdChanged has no tool_use_id; resolve role with empty id (returns "conductor").
role=$(current_role "" "$sprint")

# Subagents may freely cd into their own worktree — only warn when the
# conductor's primary session has drifted.
if [[ "$role" != "conductor" ]]; then
  pass_silent "cwd_changed" "Cwd" "$role" "$session" \
    "$(emit_json_obj cwd "$new_cwd" reason "non-conductor role; cd permitted")"
fi

# in_subworktree inspects the actual filesystem state (git-dir vs git-common-dir),
# which is more reliable than parsing the cwd string itself.
if in_subworktree; then
  sr=$(sprint_root)
  msg="[shepherd] CwdChanged WARN — conductor cwd drifted into a sub-worktree."$'\n'
  msg+="  Cwd:         ${new_cwd:-$(pwd)}"$'\n'
  msg+="  Sprint root: $sr"$'\n'
  msg+="Recover: cd $sr"$'\n'
  msg+="Worktrees should be inspected with 'git -C <path>' and absolute Read/Write —"$'\n'
  msg+="never cd'd into. See skills/shepherd/references/flock.md §Ban 1."
  emit_context "$msg" "cwd_changed" "Cwd" "$role" "$session"
fi

pass_silent "cwd_changed" "Cwd" "$role" "$session" \
  "$(emit_json_obj cwd "$new_cwd")"
