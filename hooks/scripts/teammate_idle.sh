#!/usr/bin/env bash
# shepherd hook — TeammateIdle: lead-side reaction when a teammate idles (v5.1.7;
# routing hardened v6.0.5).
#
# Runs in the LEAD's context when a teammate signals idle. Marks the teammate's
# status in the canonical SQLite store, then scans for unresolved escalations
# and stalled deliverables and surfaces a single-line warning to stderr.
#
# Discipline:
#   • Never block.    Exit 0 unconditionally; any DB/IO failure is swallowed.
#   • Non-blocking.   Output is stderr only — operators see the warning inline,
#                     but the agent loop is not affected.
#   • Fail LOUD on a missed flip (v6.0.5). A silent no-op here means the
#     coordinate-drive backstop (coordinate_drive_guard.sh) never sees the idle.
#
# Input (stdin): TeammateIdle JSON. Per the live hooks docs
#   (https://code.claude.com/docs/en/hooks#teammateidle) the payload carries
#   `session_id` (+ optional `agent_id`/`agent_type`); `teammate_name` is NOT a
#   guaranteed field. We therefore route by `teammate_name` when present and fall
#   back to `session_id` (which the teammate registered via `cmd_teammate.sh
#   register --session=`).
#
# Output (stdout): silent.
# Output (stderr): one-line `[shctx] teammate <id> idle | open-escalations=N | stalled-deliverables=N`
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

# Hook payload arrives on stdin as JSON per Claude Code hooks API.
PAYLOAD="$(cat || true)"
TEAMMATE="$(json_field "$PAYLOAD" '.teammate_name' 2>/dev/null || true)"
SESSION="$(json_field "$PAYLOAD" '.session_id' 2>/dev/null || true)"
# Need at least one routing key; otherwise nothing to flip.
[[ -z "$TEAMMATE" && -z "$SESSION" ]] && exit 0

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo .)"
NS="$(resolve_namespace)"
DB="$(hook_db_path "$NS")"
[[ -f "$DB" ]] || exit 0

# Flip status to idle. Prefer teammate_name (when the payload carries it); fall
# back to session_id. Capture changes() so we can fail LOUD if no row matched.
# Pre-escape single quotes for SQL, matching the repo idiom (cmd_mailbox.sh).
safe_t="${TEAMMATE//\'/''}"
safe_s="${SESSION//\'/''}"
changed=0
if [[ -n "$TEAMMATE" ]]; then
  bash "$ROOT/skills/context/scripts/cmd_teammate.sh" \
    heartbeat "$TEAMMATE" --note='idle' 2>/dev/null || true
  changed=$(sqlite3 "$DB" \
    "UPDATE teammates SET status='idle' WHERE teammate_name='$safe_t' AND status NOT IN ('crashed','retired'); SELECT changes();" 2>/dev/null || echo 0)
fi
[[ "${changed:-0}" =~ ^[0-9]+$ ]] || changed=0
if [[ "$changed" -lt 1 && -n "$SESSION" ]]; then
  changed=$(sqlite3 "$DB" \
    "UPDATE teammates SET status='idle' WHERE session_id='$safe_s' AND status NOT IN ('crashed','retired'); SELECT changes();" 2>/dev/null || echo 0)
  [[ "${changed:-0}" =~ ^[0-9]+$ ]] || changed=0
fi

if [[ "$changed" -lt 1 ]]; then
  echo "[shctx] TeammateIdle: no teammates row matched (name='${TEAMMATE:-}' session='${SESSION:-}') — status not flipped; coordinate-drive backstop will not see this idle" >&2
fi

# Surface open escalations + stalled deliverables. `wc -l` includes the header
# row from sqlite3 -header, so subtract 1 to get the data-row count.
LABEL="${TEAMMATE:-${SESSION:-unknown}}"
ESC=$(bash "$ROOT/skills/context/scripts/cmd_escalate.sh" list --open-only 2>/dev/null | wc -l)
STALLED=$(bash "$ROOT/skills/context/scripts/cmd_deliverable.sh" stalled --since-mins=10 2>/dev/null | wc -l)

if [[ "$ESC" -gt 1 ]] || [[ "$STALLED" -gt 1 ]]; then
  echo "[shctx] teammate $LABEL idle | open-escalations=$((ESC-1)) | stalled-deliverables=$((STALLED-1))" >&2
fi

exit 0
