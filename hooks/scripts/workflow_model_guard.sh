#!/usr/bin/env bash
# shepherd hook — PreToolUse(Workflow): dispatch-model-pin guard (v6.2.9, #178).
#
# PROBLEM (#178): a Dynamic Workflow's agent() calls that omit BOTH `model:`
# and `agentType:` silently INHERIT the main-loop model — the platform's own
# stated default ("Default to omitting it... the agent inherits the
# main-loop model", the Workflow tool's own docs). shepherd's [models] table
# (skills/context/references/model-map.md) is the single dispatch-model
# source of truth for every OTHER primitive — Agent/Task via
# dispatch_guard.sh, teammate spawns via commands/spawn.md §Model pin — but a
# raw Workflow `agent()` call bypasses both silently; dispatch_guard.sh's
# PreToolUse(Agent|Task) hook structurally cannot see it (the harness runs
# the script's internal spawns out-of-band, never re-entering that hook).
# FIELD INCIDENT (2026-07-07): a Fable-5 planter session dispatched a
# Workflow whose agent() calls omitted model/agentType; every deep-audit
# subagent ran on Fable at xhigh effort until the operator caught it mid-run.
#
# OPERATOR LAW (2026-07-07): every dispatched subagent = sonnet unless
# explicitly overridden; large waves are authorized ONLY because they run
# sonnet. This guard makes that mechanical for the one dispatch primitive
# dispatch_guard.sh cannot reach.
#
# SCAN: best-effort JS-lite static scan, delegated to
# hooks/scripts/workflow_model_lint.py — masks string/template literals and
# comments (same length, so a prompt that merely MENTIONS "model:" in prose
# is never mistaken for a real opts key), then for every top-level
# `agent(prompt[, opts])` call checks whether `opts` is an object literal
# carrying a TOP-LEVEL `model:` or `agentType:` key. See that file's header
# for the three violation shapes it distinguishes.
#
# SCRIPT SOURCE: `tool_input.script` (inline) is scanned directly;
# `tool_input.scriptPath` is read from disk (relative to the hook's `cwd`
# unless absolute) — a missing/unreadable file fails OPEN (cannot scan, do
# not block). `tool_input.name` (a saved/named workflow) has no script text
# visible at PreToolUse time — fails OPEN too, but the gap is logged, never
# silently indistinguishable from "scanned clean".
#
# OPERATOR OVERRIDE: a `// shepherd:model-pin-override` line comment
# anywhere in the submitted script acknowledges unpinned dispatch for THAT
# script — mirrors the brief-marker idiom `dispatch_guard.sh` already uses
# (`mode: self-contained`, `dispatcher: engineer-self-contained`). Always
# logged (never a silent bypass) and reported via additionalContext, never
# a deny — even in block mode.
#
# HALT CODE: WORKFLOW-MODEL-PIN-MISSING
# CONFIG:    [hooks].workflow_model_guard = block (default) | warn | off
# EVENT:     PreToolUse(Workflow)
# STDIN:     { session_id, tool_name, tool_input.{script?, scriptPath?, name?}, cwd, ... }
# OUTPUT:    {"permissionDecision":"deny","message":"..."}  — block mode, violation(s) found
#            {"additionalContext":"..."}                     — warn mode, or override acknowledged
#            silent exit 0 — off mode / no violations / script not visible / python3 absent
# EXIT:      always 0 (fail-open on any error or uncertainty — never blocks on OUR bug).

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$HERE/_lib.sh" 2>/dev/null || exit 0

PAYLOAD="$(cat 2>/dev/null || true)"
is_shepherd_project || exit 0

TOOL="$(json_field "$PAYLOAD" '.tool_name' 2>/dev/null || true)"
[[ "$TOOL" == "Workflow" ]] || exit 0

SESSION="$(json_field "$PAYLOAD" '.session_id' 2>/dev/null || true)"
[[ -n "$SESSION" ]] || SESSION="nosession"

# --- config: block (default) | warn | off ------------------------------------
MODE="block"
cfg="$(cfg_get workflow_model_guard | grep -oE '(block|warn|off)' | tail -1 || true)"
[[ -n "$cfg" ]] && MODE="$cfg"
[[ "$MODE" == "off" ]] && exit 0

command -v python3 &>/dev/null || {
  log_event "workflow_model_guard" "pass-no-python3" "$TOOL" "shepherd" "$SESSION" "{}" 2>/dev/null || true
  exit 0
}

SCRIPT_TEXT="$(json_field "$PAYLOAD" '.tool_input.script' 2>/dev/null || true)"
SCRIPT_PATH="$(json_field "$PAYLOAD" '.tool_input.scriptPath' 2>/dev/null || true)"
WF_NAME="$(json_field "$PAYLOAD" '.tool_input.name' 2>/dev/null || true)"
CWD="$(json_field "$PAYLOAD" '.cwd' 2>/dev/null || true)"

if [[ -z "$SCRIPT_TEXT" && -n "$SCRIPT_PATH" ]]; then
  path="$SCRIPT_PATH"
  [[ "$path" == /* ]] || path="${CWD:-.}/$path"
  if [[ -r "$path" ]]; then
    SCRIPT_TEXT="$(cat "$path" 2>/dev/null || true)"
  fi
fi

if [[ -z "$SCRIPT_TEXT" ]]; then
  # A saved/named workflow (resolved server-side) or an unreadable scriptPath
  # — no script text is visible at PreToolUse time. Fail open; log the gap
  # so it never reads as "scanned clean" in the hook event log.
  log_event "workflow_model_guard" "pass-no-script-visible" "$TOOL" "shepherd" "$SESSION" \
    "$(emit_json_obj name "${WF_NAME:-}" scriptPath "${SCRIPT_PATH:-}")" 2>/dev/null || true
  exit 0
fi

RESULT="$(printf '%s' "$SCRIPT_TEXT" | python3 "$HERE/workflow_model_lint.py" 2>/dev/null || true)"
[[ -n "$RESULT" ]] || exit 0   # the lint script crashed — fail open, never block on OUR bug

VIOLATION_COUNT="$(json_field "$RESULT" '.violation_count' 2>/dev/null || true)"
[[ "$VIOLATION_COUNT" =~ ^[0-9]+$ ]] || exit 0

if [[ "$VIOLATION_COUNT" -eq 0 ]]; then
  TOTAL="$(json_field "$RESULT" '.total_agent_calls' 2>/dev/null || true)"
  pass_silent "workflow_model_guard" "$TOOL" "shepherd" "$SESSION" \
    "$(emit_json_obj total_agent_calls "${TOTAL:-0}")"
fi

OVERRIDE="$(json_field "$RESULT" '.override' 2>/dev/null || true)"
LINES="$(json_field "$RESULT" '.lines_text' 2>/dev/null || true)"
DOC="skills/context/references/model-map.md + skills/harness/references/workflow-templates.md"

if [[ "$OVERRIDE" == "true" ]]; then
  msg="[shepherd] WORKFLOW-MODEL-PIN-MISSING — override marker present, proceeding."$'\n'
  msg+="  ${VIOLATION_COUNT} agent() call(s) with no explicit model:/agentType: pin"$'\n'
  msg+="  (would default to sonnet per [models] policy — operator law 2026-07-07)."$'\n'
  msg+="$LINES"$'\n'
  msg+="Acknowledged via the \`// shepherd:model-pin-override\` marker in the submitted script."
  emit_context "$msg" "workflow_model_guard" "$TOOL" "shepherd" "$SESSION"
fi

MSG="[shepherd] WORKFLOW-MODEL-PIN-MISSING — ${VIOLATION_COUNT} agent() call(s) with no explicit model:/agentType:."$'\n'
MSG+="$LINES"$'\n'
MSG+="Every Workflow agent() call MUST carry an explicit \`model:\` or \`agentType: \"shepherd:<role>\"\`"$'\n'
MSG+="pin — omitting BOTH silently inherits the MAIN-LOOP model (the platform's own default), which is"$'\n'
MSG+="how a Fable-5 planter session ran a deep-audit wave on Fable at xhigh (2026-07-07 field incident)."$'\n'
MSG+="Fix: model: \"\$(shctx models resolve <role>)\" (default sonnet for every role below"$'\n'
MSG+="root/planter/engineer — [models] in .claude/shepherd.toml) or agentType: \"shepherd:<role>\"."$'\n'
MSG+="One-off acknowledgment: add a \`// shepherd:model-pin-override\` comment to the script."$'\n'
MSG+="Persistent: [hooks].workflow_model_guard = warn|off in .claude/shepherd.toml."$'\n'
MSG+="See $DOC."

if [[ "$MODE" == "warn" ]]; then
  echo "[shctx] workflow_model_guard: ${VIOLATION_COUNT} agent() call(s) unpinned (warn mode — proceeding anyway)" >&2
  emit_context "$MSG" "workflow_model_guard" "$TOOL" "shepherd" "$SESSION"
fi

# block mode (default): emit_deny logs internally and exits 0.
emit_deny "$MSG" "workflow_model_guard" "$TOOL" "shepherd" "$SESSION"
