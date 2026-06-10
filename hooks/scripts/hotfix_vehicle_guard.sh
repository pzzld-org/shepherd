#!/usr/bin/env bash
# shepherd hook — PreToolUse(Agent|Task): hotfix vehicle guard (v6.0.9, #135).
#
# ENFORCES: doctrines/hotfix-dispatch.md cardinality ladder.
#   H == 1 cluster  → one @coder subagent, NEVER a teammate-conductor.
#   H ∈ (1, 5]      → batched Dynamic Workflow (multiple subagents); pass.
#   H >= 6          → dedicated HOT-FIX lane + conductor + loop; pass.
#
# PROBLEM: hotfix-dispatch.md is prose-only. When H == 1, root sometimes
# spawns a teammate-conductor anyway (WRONG-VEHICLE: a lane costs a full
# Agent-Teams round-trip and a conductor profile load; a single-subagent
# @coder is cheaper, faster, and never races for the worktree). This guard
# is the mechanical enforcement.
#
# EVENT: PreToolUse(Agent|Task)
# STDIN: { session_id, tool_name, tool_input.{subagent_type, prompt, description,
#           team_name?}, cwd, ... }
# OUTPUT:
#   {"permissionDecision":"deny","message":"..."} — H==1 teammate spawn blocked
#   silent exit 0 — non-teammate, or H != 1, or H unknown (fail-open)
#
# HALT CODE: WRONG-VEHICLE (registered in agents/conductor.md + agents/shepherd.md)
#
# H-DETECTION: reads $NS/tmp/hotfix-context.json written by the walk step
# (pipeline.md §XIII-bis) before any dispatch. Format:
#   { "cluster_count": <N> }
# If the file is absent, unreadable, or cluster_count is not present / not an
# integer, the guard PASSES — fail-open on uncertainty.
#
# TEAMMATE DETECTION: a spawned teammate / TeamCreate path is signalled by
# team_name being set in tool_input (see dispatch_guard.sh for the platform
# note: real Agent/Task input has no team_name field; the guard blocks if
# the conductor supplies it via the AgentTeams spawn path). Secondary signal:
# subagent_type == "shepherd:conductor" — which is the lane subagent type.

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$HERE/_lib.sh" 2>/dev/null || exit 0

PAYLOAD="$(cat 2>/dev/null || true)"

# --- is_shepherd_project guard -------------------------------------------
is_shepherd_project || exit 0

# --- tool filter: only Agent or Task ------------------------------------
TOOL="$(json_field "$PAYLOAD" '.tool_name' 2>/dev/null || true)"
case "$TOOL" in Agent|Task) ;; *) exit 0 ;; esac

SESSION="$(json_field "$PAYLOAD" '.session_id' 2>/dev/null || true)"
[[ -n "$SESSION" ]] || SESSION="nosession"
SUBAGENT_TYPE="$(json_field "$PAYLOAD" '.tool_input.subagent_type' 2>/dev/null || true)"
TEAM_NAME="$(json_field "$PAYLOAD" '.tool_input.team_name' 2>/dev/null || true)"

# --- is this spawning a teammate-conductor? ------------------------------
# Signal 1: team_name is set (AgentTeams spawn path).
# Signal 2: subagent_type is shepherd:conductor.
IS_TEAMMATE_SPAWN=0
if [[ -n "$TEAM_NAME" ]] || [[ "${SUBAGENT_TYPE,,}" == "shepherd:conductor" ]]; then
  IS_TEAMMATE_SPAWN=1
fi

# Not a teammate spawn → not relevant to this guard.
[[ "$IS_TEAMMATE_SPAWN" -eq 0 ]] && {
  pass_silent "hotfix_vehicle_guard" "$TOOL" "shepherd" "$SESSION"
}

# --- read H from hotfix-context.json -------------------------------------
NS="$(resolve_namespace 2>/dev/null || echo .shepherd)"
HF_CTX_FILE="$NS/tmp/hotfix-context.json"

H=""
if [[ -f "$HF_CTX_FILE" ]]; then
  if command -v jq &>/dev/null; then
    H="$(jq -r '.cluster_count // ""' "$HF_CTX_FILE" 2>/dev/null || true)"
  else
    H="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("cluster_count",""))' \
         "$HF_CTX_FILE" 2>/dev/null || true)"
  fi
fi

# If H is absent, empty, or not a positive integer → fail-open, do not block.
if [[ -z "$H" ]] || ! [[ "$H" =~ ^[0-9]+$ ]]; then
  log_event "hotfix_vehicle_guard" "pass-unknown-H" "$TOOL" "shepherd" "$SESSION" \
    "$(emit_json_obj note "H-indeterminate" subagent_type "$SUBAGENT_TYPE" team_name "$TEAM_NAME")" 2>/dev/null || true
  exit 0
fi

# H must equal exactly 1 to trigger the deny.
if [[ "$H" -ne 1 ]]; then
  log_event "hotfix_vehicle_guard" "pass" "$TOOL" "shepherd" "$SESSION" \
    "$(emit_json_obj H "$H" note "H>1 teammate-spawn-allowed")" 2>/dev/null || true
  exit 0
fi

# --- H == 1 teammate spawn — DENY with WRONG-VEHICLE ---------------------
MSG="[shepherd] WRONG-VEHICLE — H=1 hotfix MUST use a single @coder subagent, never a teammate-conductor."$'\n'
MSG+="  H (cluster_count) : 1"$'\n'
MSG+="  Attempted spawn   : ${SUBAGENT_TYPE:-unknown}${TEAM_NAME:+ (team: $TEAM_NAME)}"$'\n'
MSG+="The hotfix cardinality ladder (doctrines/hotfix-dispatch.md):"$'\n'
MSG+="  H == 1  → one @coder subagent via Agent({subagent_type: \"shepherd:coder\", ...})"$'\n'
MSG+="  H ∈ (1,5] → batched Dynamic Workflow dispatching multiple @coder subagents"$'\n'
MSG+="  H >= 6  → dedicated HOT-FIX lane + teammate-conductor + loop"$'\n'
MSG+="Spawning a teammate for H=1 incurs an Agent-Teams round-trip, a conductor profile"$'\n'
MSG+="load, and a worktree allocation — all unnecessary for a single-file fix."$'\n'
MSG+="Dispatch the fix as: Agent({subagent_type: \"shepherd:coder\", ...}) with no team_name."

emit_deny "$MSG" "hotfix_vehicle_guard" "$TOOL" "shepherd" "$SESSION"
