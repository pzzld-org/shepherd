#!/usr/bin/env bash
# shepherd hook — PreToolUse(Agent|Task) role tagger (v5.1.2)
#
# Parses the Agent/Task tool_input.prompt for the canonical flock-agent
# header (`# @<role>` at the top of the injected system prompt) and writes
# a structured record at <ns>/dispatch/<sprint>/<tool_use_id>.json. Downstream
# PreToolUse hooks (bash_guard, lock_guard) read this record to make
# role-conditional decisions.
#
# Input:  PreToolUse JSON { tool_name, tool_use_id, tool_input.prompt, ... }
# Output: silent exit 0 (never blocks; pure side-effect).
#
# Schema written:
#   {
#     "tool_use_id":            "<from hook input>",
#     "agent_role":             "engineer|critic|coder|auditor|worker|discovery|unknown",
#     "sprint":                 "<git branch at dispatch>",
#     "dispatched_at":          <unix-ts>,
#     "model":                  "<from tool_input.model>",
#     "sprint_branch_recorded": "<git rev-parse HEAD>"
#   }

set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

input=$(cat)
is_shepherd_project || exit 0

tool=$(json_field "$input" '.tool_name')
case "$tool" in Agent|Task) ;; *) exit 0 ;; esac

tool_use_id=$(json_field "$input" '.tool_use_id')
[[ -z "$tool_use_id" ]] && exit 0

prompt=$(json_field "$input" '.tool_input.prompt')
model=$(json_field "$input" '.tool_input.model')
session=$(json_field "$input" '.session_id')

# Parse the role from the first 100 lines of the prompt. The shepherd
# dispatch convention is the agent body starts with `# @<role>` after the
# YAML frontmatter. Match the first such header.
role=$(printf '%s\n' "$prompt" | head -100 | grep -m1 -oE '^# @(engineer|critic|coder|auditor|worker|discovery)\b' | sed 's/^# @//' || true)
role="${role:-unknown}"

sprint=$(current_sprint)
sprint_sha=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
ts=$(date +%s 2>/dev/null || echo 0)

ns=$(resolve_namespace)
dispatch_dir="$ns/dispatch/$sprint"
mkdir -p "$dispatch_dir" 2>/dev/null || exit 0
record_file="$dispatch_dir/${tool_use_id}.json"

if command -v jq &>/dev/null; then
  jq -n \
    --arg id "$tool_use_id" --arg role "$role" --arg sprint "$sprint" \
    --argjson ts "$ts" --arg model "$model" --arg sha "$sprint_sha" \
    '{tool_use_id:$id, agent_role:$role, sprint:$sprint, dispatched_at:$ts,
      model:$model, sprint_branch_recorded:$sha}' > "$record_file" 2>/dev/null || true
else
  python3 -c '
import json, sys
record = {
    "tool_use_id":            sys.argv[1],
    "agent_role":             sys.argv[2],
    "sprint":                 sys.argv[3],
    "dispatched_at":          int(sys.argv[4] or 0),
    "model":                  sys.argv[5],
    "sprint_branch_recorded": sys.argv[6],
}
with open(sys.argv[7], "w") as f:
    json.dump(record, f)
' "$tool_use_id" "$role" "$sprint" "$ts" "$model" "$sprint_sha" "$record_file" 2>/dev/null || true
fi

log_event "agent_invocation_tagger" "pass" "$tool" "$role" "$session" \
  "$(emit_json_obj agent_role "$role" sprint "$sprint" tool_use_id "$tool_use_id")"
exit 0
