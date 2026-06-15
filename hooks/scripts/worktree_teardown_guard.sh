#!/usr/bin/env bash
# shepherd hook — PreToolUse(Bash): worktree teardown guard (v6.1.0).
#
# BACKSTOP for the blanket-teardown-mid-sprint incident (#141).
#
# PROBLEM: A /shepherd:spawn session ran a blanket `git worktree list | … |
# git worktree remove --force` followed by `git worktree prune` WHILE teammate
# sessions were still live in their own tmux panes. Every teammate worktree was
# removed; all panes died; the lead quit. This hook is the mechanical hard stop.
#
# RULE: When live teammates exist (v_teammates_live count > 0):
#   DENY — git worktree prune (any form)
#   DENY — blanket remove: a command that contains both 'worktree list' AND
#           'worktree remove', or a 'git worktree remove' whose target argument
#           is NOT a single explicit .worktrees/... path.
#   ALLOW — git worktree remove [--force] .worktrees/<slug>-<lane>
#            (scoped single-lane idle-prune — the legitimate form).
#
# HALT CODE: WORKTREE-TEARDOWN-LIVE
#
# CONFIG: [spawn].worktree_teardown_guard = block (default) | warn | off
#
# EVENT: PreToolUse(Bash)
# STDIN: { session_id, tool_name, tool_input.command, tool_use_id, ... }
# OUTPUT:
#   {"permissionDecision":"deny","message":"..."}  — blanket teardown blocked
#   silent exit 0 — not a worktree-destructive command, or no live teammates
# EXIT: always 0 (fail-open on any error/uncertainty).

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$HERE/_lib.sh" 2>/dev/null || exit 0

PAYLOAD="$(cat 2>/dev/null || true)"

# --- fast-path: only relevant inside a shepherd project ----------------------
is_shepherd_project || exit 0

# --- fast-path: only Bash tool -----------------------------------------------
TOOL="$(json_field "$PAYLOAD" '.tool_name' 2>/dev/null || true)"
[[ "$TOOL" == "Bash" ]] || exit 0

CMD="$(json_field "$PAYLOAD" '.tool_input.command' 2>/dev/null || true)"
[[ -n "$CMD" ]] || exit 0

# --- fast-path: must mention 'git worktree' ----------------------------------
printf '%s' "$CMD" | grep -qE '(^|[[:space:];|&`$(])git[[:space:]]+worktree[[:space:]]' 2>/dev/null || exit 0

# --- fast-path: sqlite3 and DB must be present --------------------------------
command -v sqlite3 >/dev/null 2>&1 || exit 0
NS="$(resolve_namespace 2>/dev/null || echo .)"
DB="$(hook_db_path "$NS")"
[[ -f "$DB" ]] || exit 0

# --- config: block (default) | warn | off ------------------------------------
# Resolved via cfg_get → honors .claude/shepherd.local.toml + XDG global (v6.1.5).
MODE="block"
cfg="$(cfg_get worktree_teardown_guard | grep -oE '(block|warn|off)' | tail -1 || true)"
[[ -n "$cfg" ]] && MODE="$cfg"
[[ "$MODE" == "off" ]] && exit 0

# --- live teammate count -----------------------------------------------------
LIVE="$(sqlite3 "$DB" "SELECT count(*) FROM v_teammates_live;" 2>/dev/null || echo 0)"
[[ "$LIVE" =~ ^[0-9]+$ ]] || LIVE=0
[[ "$LIVE" -eq 0 ]] && exit 0

SESSION="$(json_field "$PAYLOAD" '.session_id' 2>/dev/null || true)"
[[ -n "$SESSION" ]] || SESSION="nosession"

# --- classify the worktree command -------------------------------------------
# DENY pattern 1: any form of 'git worktree prune'
is_prune() {
  printf '%s' "$CMD" | grep -qE '(^|[[:space:];|&`$(])git[[:space:]]+worktree[[:space:]]+prune([[:space:]]|$|;|&|\|)?' 2>/dev/null
}

# DENY pattern 2: blanket remove — command contains both 'worktree list' AND
# 'worktree remove' (loop/pipe construct sweeping all worktrees), OR a bare
# 'git worktree remove' whose first non-flag argument is NOT a .worktrees/ path.
is_blanket_remove() {
  # Sub-case A: command combines 'worktree list' with 'worktree remove' —
  # this is the canonical sweep pattern: `git worktree list | grep … | … git worktree remove`
  if printf '%s' "$CMD" | grep -qE 'worktree[[:space:]]+list' 2>/dev/null && \
     printf '%s' "$CMD" | grep -qE 'worktree[[:space:]]+remove' 2>/dev/null; then
    return 0
  fi

  # Sub-case B: a 'git worktree remove' with no .worktrees/... target.
  # Extract the portion starting at 'worktree remove', then check whether a
  # .worktrees/ path follows immediately.  If no such path → blanket/ambiguous.
  local remove_tail
  remove_tail="$(printf '%s' "$CMD" | grep -oE 'worktree[[:space:]]+remove.*' 2>/dev/null | head -1 || true)"
  [[ -z "$remove_tail" ]] && return 1  # no 'worktree remove' clause → not this pattern

  # Strip flags (--force, -f, etc.) from the tail to reach the positional arg.
  local args_tail
  args_tail="$(printf '%s' "$remove_tail" | sed 's/worktree[[:space:]]*remove[[:space:]]*//' | \
               sed 's/--force[[:space:]]*//' | sed 's/-f[[:space:]]*//' | \
               sed 's/^[[:space:]]*//' || true)"

  # If the remaining arg starts with .worktrees/ → scoped (single-lane) → allow.
  if printf '%s' "$args_tail" | grep -qE '^\.worktrees/' 2>/dev/null; then
    return 1  # NOT a blanket remove — it is scoped
  fi

  # No .worktrees/ target found → treat as blanket/ambiguous → deny.
  return 0
}

DENY=0
REASON_CODE=""

if is_prune; then
  DENY=1
  REASON_CODE="prune"
elif is_blanket_remove; then
  DENY=1
  REASON_CODE="blanket-remove"
fi

[[ "$DENY" -eq 0 ]] && exit 0

# --- emit decision -----------------------------------------------------------
MSG="[shepherd] WORKTREE-TEARDOWN-LIVE — blanket/destructive worktree teardown blocked."$'\n'
MSG+="  Halt code  : WORKTREE-TEARDOWN-LIVE"$'\n'
MSG+="  Reason     : ${REASON_CODE}"$'\n'
MSG+="  Command    : ${CMD:0:200}"$'\n'
MSG+="  Live mates : ${LIVE}"$'\n'
MSG+=""$'\n'
MSG+="${LIVE} live teammate session(s) exist. Each teammate runs inside a"$'\n'
MSG+=".worktrees/{sprint_slug}-{lane_id} worktree. Removing or pruning those"$'\n'
MSG+="worktrees kills the pane and terminates the teammate session mid-sprint."$'\n'
MSG+=""$'\n'
MSG+="Teardown is a CLOSE-only operation — run it AFTER all teammates have"$'\n'
MSG+="committed their work and you have confirmed the sprint is fully closed."$'\n'
MSG+=""$'\n'
MSG+="To prune a SINGLE idle lane legitimately:"$'\n'
MSG+="  git worktree remove .worktrees/<sprint_slug>-<lane_id>"$'\n'
MSG+="or:"$'\n'
MSG+="  git worktree remove --force .worktrees/<sprint_slug>-<lane_id>"$'\n'
MSG+=""$'\n'
MSG+="To tear down ALL worktrees at CLOSE (once no live teammates remain),"$'\n'
MSG+="use the scoped form in a loop after verifying v_teammates_live = 0."$'\n'
MSG+="See doctrines/worktree-confinement.md and agents/shepherd.md CLOSE section."

if [[ "$MODE" == "warn" ]]; then
  echo "[shctx] worktree-teardown-guard: ${REASON_CODE} blocked (warn mode — proceeding anyway; live=${LIVE})" >&2
  log_event "worktree_teardown_guard" "warn" "Bash" "shepherd" "$SESSION" \
    "$(emit_json_obj reason "$REASON_CODE" live "$LIVE")" 2>/dev/null || true
  exit 0
fi

# block mode (default): emit_deny logs internally.
emit_deny "$MSG" "worktree_teardown_guard" "Bash" "shepherd" "$SESSION"
