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
#   guaranteed field. Named-Agent teammates register under (team, teammate_name)
#   — the row is keyed by NAME, never the teammate's own session id (#183) — so
#   NAME is the primary match. We read the name from any identity field the
#   payload may carry (`teammate_name` / `agent_id` / `name`) and fall back to
#   `session_id` only as a last resort. The row must EXIST for the flip to land:
#   root registers every teammate at spawn (`commands/spawn.md`,
#   `shctx teammate register`); an unregistered teammate is invisible here — the
#   root-cause the #183 idle flood grew out of.
#
# Output (stdout): silent.
# Output (stderr): one-line `[shctx] teammate <id> idle | open-escalations=N | stalled-deliverables=N`
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

# Hook payload arrives on stdin as JSON per Claude Code hooks API.
PAYLOAD="$(cat || true)"
# Route by NAME first, across the identity fields the platform may use, then
# session_id (#183).
TEAMMATE="$(json_field "$PAYLOAD" '.teammate_name' 2>/dev/null || true)"
[[ -n "$TEAMMATE" ]] || TEAMMATE="$(json_field "$PAYLOAD" '.agent_id' 2>/dev/null || true)"
[[ -n "$TEAMMATE" ]] || TEAMMATE="$(json_field "$PAYLOAD" '.name' 2>/dev/null || true)"
SESSION="$(json_field "$PAYLOAD" '.session_id' 2>/dev/null || true)"
# Need at least one routing key; otherwise nothing to flip.
[[ -z "$TEAMMATE" && -z "$SESSION" ]] && exit 0

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo .)"
NS="$(resolve_namespace)"
DB="$(hook_db_path "$NS")"
[[ -f "$DB" ]] || exit 0

# Flip status to idle. Prefer teammate_name (when the payload carries it); fall
# back to session_id. Capture changes() so we can fail LOUD if no row matched.
# Pre-escape single quotes for SQL, matching the repo idiom (cmd_signal.sh).
safe_t="${TEAMMATE//\'/''}"
safe_s="${SESSION//\'/''}"
changed=0
if [[ -n "$TEAMMATE" ]]; then
  "$ROOT/bin/shepherd" teammate \
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
  # Fail LOUD only when a spawn is genuinely live (≥1 non-terminal teammate row)
  # yet none matched — the real anomaly: a live teammate that was never
  # registered, so the coordinate-drive backstop can't see its idle. When the
  # table has no live rows (non-spawn session, or an ephemeral subagent idling),
  # stay silent — screaming on every such idle is exactly the #183 flood that
  # masked the real stalls.
  live=$(sqlite3 "$DB" \
    "SELECT count(*) FROM teammates WHERE status NOT IN ('crashed','retired');" 2>/dev/null || echo 0)
  [[ "${live:-0}" =~ ^[0-9]+$ ]] || live=0
  if [[ "$live" -gt 0 ]]; then
    echo "[shctx] TeammateIdle: no teammates row matched (name='${TEAMMATE:-}' session='${SESSION:-}') — status not flipped; register the teammate at spawn (shctx teammate register) so the coordinate-drive backstop sees its idle" >&2
  fi
fi

# Surface stalled deliverables. `wc -l` includes the header row from
# sqlite3 -header, so subtract 1 to get the data-row count. (Escalations
# travel via SendMessage payloads — `shctx escalate` was pruned in v6.2.8.)
LABEL="${TEAMMATE:-${SESSION:-unknown}}"
STALLED=$("$ROOT/bin/shepherd" deliverable stalled --since-mins=10 2>/dev/null | wc -l)

if [[ "$STALLED" -gt 1 ]]; then
  echo "[shctx] teammate $LABEL idle | stalled-deliverables=$((STALLED-1))" >&2
fi

exit 0
