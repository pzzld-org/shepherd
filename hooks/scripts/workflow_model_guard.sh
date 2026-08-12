#!/usr/bin/env bash
# shepherd hook — PreToolUse(Workflow): dispatch-model-pin guard (v6.4.2, #255 enforcement half).
#
# PROBLEM (#178, weakened check found by #255): a Dynamic Workflow's agent()
# calls that omit `model:` and/or `agentType:` silently INHERIT the
# main-loop model — the platform's own stated default ("Default to omitting
# it... the agent inherits the main-loop model", the Workflow tool's own
# docs). shepherd's [models] table (skills/context/references/model-map.md)
# is the single dispatch-model source of truth for every OTHER primitive —
# Agent/Task via dispatch_guard.sh, teammate spawns via commands/spawn.md
# §Model pin — but a raw Workflow `agent()` call bypasses both silently;
# dispatch_guard.sh's PreToolUse(Agent|Task) hook structurally cannot see it
# (the harness runs the script's internal spawns out-of-band, never
# re-entering that hook).
# FIELD INCIDENT (2026-07-07): a Fable-5 planter session dispatched a
# Workflow whose agent() calls omitted model/agentType; every deep-audit
# subagent ran on Fable at xhigh effort until the operator caught it mid-run.
# FIELD INCIDENT (#255): #178's OWN fix let this recur under a DIFFERENT
# shape — the original check passed a call carrying EITHER `model:` OR
# `agentType:`, so a script whose calls carried `agentType:
# "shepherd:<role>"` alone scanned clean while every one of 16 fanned-out
# agents still inherited opus at xhigh over the mandated sonnet, because
# `agentType:` alone pins a role, not a model.
#
# OPERATOR LAW (2026-07-07, sharpened #255): every dispatched subagent =
# sonnet unless explicitly overridden, AND stays inside the closed flock —
# BOTH pins are required, independently, on every call. This guard makes
# that mechanical for the one dispatch primitive dispatch_guard.sh cannot
# reach; it is the Workflow-side twin of dispatch_guard.sh's own
# `DISPATCH-MISSING-SUBAGENT-TYPE`/`DISPATCH-MODEL-UNPINNED` checks on
# `Agent()` (skills/shepherd/SKILL.md §Dispatch law).
#
# SCAN: best-effort JS-lite static scan, delegated to
# hooks/scripts/workflow_model_lint.py — masks string/template literals and
# comments (same length, so a prompt that merely MENTIONS "model:" or
# `agentType: "general-purpose"` in prose is never mistaken for a real opts
# key), then for every top-level `agent(prompt[, opts])` call checks the
# model law and the agentType law INDEPENDENTLY: a top-level `model:` key
# must be present, AND a top-level `agentType:` key must be present AND (if
# statically verifiable) start with `shepherd:`. A single call can trip
# either law, both, or neither — each trip is its own violation entry
# carrying its own `code`. See that file's header for the five distinct
# codes it emits (DISPATCH-MODEL-UNPINNED, DISPATCH-MISSING-SUBAGENT-TYPE,
# WORKFLOW-OFF-FLOCK, WORKFLOW-AGENTTYPE-UNVERIFIABLE,
# WORKFLOW-MODEL-PIN-UNVERIFIABLE).
#
# SCRIPT SOURCE: `tool_input.script` (inline) is scanned directly;
# `tool_input.scriptPath` is read from disk (relative to the hook's `cwd`
# unless absolute) — a missing/unreadable file fails OPEN (cannot scan, do
# not block). `tool_input.name` (a saved/named workflow) has no script text
# visible at PreToolUse time — fails OPEN too, but the gap is logged, never
# silently indistinguishable from "scanned clean".
#
# OPERATOR OVERRIDE: a `// shepherd:model-pin-override` line comment
# anywhere in the submitted script acknowledges unpinned/off-flock dispatch
# for THAT script — mirrors the brief-marker idiom `dispatch_guard.sh`
# already uses (`mode: self-contained`, `dispatcher: engineer-self-contained`).
# Always logged (never a silent bypass) and reported via additionalContext,
# never a deny — even in block mode.
#
# HALT CODE: WORKFLOW-MODEL-PIN-MISSING (umbrella — the deny/context message
#            names every distinct per-violation code it actually saw; see SCAN)
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
DOC="skills/shepherd/SKILL.md §Dispatch law + skills/context/references/model-map.md"

# Distinct violation CODES seen, comma-joined, in first-seen order — the
# operator sees WHICH law(s) broke, not just a bare count (#255; the old
# single-reason report couldn't distinguish "no model" from "off-flock").
# python3 is guaranteed present here (the earlier command -v check above
# already exited 0 if it were missing), so no jq/python fallback split is
# needed the way json_field carries one for portability elsewhere.
CODES="$(printf '%s' "$RESULT" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    data = {}
seen = []
for v in data.get("violations", []) or []:
    c = v.get("code")
    if c and c not in seen:
        seen.append(c)
print(", ".join(seen))
' 2>/dev/null || true)"
[[ -n "$CODES" ]] || CODES="WORKFLOW-MODEL-PIN-MISSING"

if [[ "$OVERRIDE" == "true" ]]; then
  msg="[shepherd] WORKFLOW-MODEL-PIN-MISSING — override marker present, proceeding."$'\n'
  msg+="  ${VIOLATION_COUNT} violation(s) — codes seen: ${CODES}"$'\n'
  msg+="  (would default to the inherited main-loop model and/or an off-flock generic"$'\n'
  msg+="  subagent — operator law 2026-07-07, sharpened #255)."$'\n'
  msg+="$LINES"$'\n'
  msg+="Acknowledged via the \`// shepherd:model-pin-override\` marker in the submitted script."
  emit_context "$msg" "workflow_model_guard" "$TOOL" "shepherd" "$SESSION"
fi

MSG="[shepherd] WORKFLOW-MODEL-PIN-MISSING — ${VIOLATION_COUNT} violation(s) — codes seen: ${CODES}."$'\n'
MSG+="$LINES"$'\n'
MSG+="Every Workflow agent() call MUST carry BOTH an explicit \`model:\` pin AND an explicit"$'\n'
MSG+="\`agentType: \"shepherd:<role>\"\` pin — satisfying only ONE is not enough (#255: a call"$'\n'
MSG+="pinning agentType alone still inherited opus at xhigh over the mandated sonnet on 16"$'\n'
MSG+="fanned-out agents, because the old model:-OR-agentType: check let it pass clean)."$'\n'
MSG+="Fix: model: \"\$(shctx models resolve <role>)\" (default sonnet for every role below"$'\n'
MSG+="root/planter/engineer — [models] in .claude/shepherd.toml) AND agentType: \"shepherd:<role>\"."$'\n'
MSG+="An agentType outside the closed flock (e.g. \"general-purpose\") is WORKFLOW-OFF-FLOCK even"$'\n'
MSG+="with model: pinned; a computed/variable agentType that cannot be checked statically is"$'\n'
MSG+="WORKFLOW-AGENTTYPE-UNVERIFIABLE, flagged rather than assumed compliant."$'\n'
MSG+="One-off acknowledgment: add a \`// shepherd:model-pin-override\` comment to the script."$'\n'
MSG+="Persistent: [hooks].workflow_model_guard = warn|off in .claude/shepherd.toml."$'\n'
MSG+="See $DOC."

if [[ "$MODE" == "warn" ]]; then
  echo "[shctx] workflow_model_guard: ${VIOLATION_COUNT} violation(s) — codes seen: ${CODES} (warn mode — proceeding anyway)" >&2
  emit_context "$MSG" "workflow_model_guard" "$TOOL" "shepherd" "$SESSION"
fi

# block mode (default): emit_deny logs internally and exits 0.
emit_deny "$MSG" "workflow_model_guard" "$TOOL" "shepherd" "$SESSION"
