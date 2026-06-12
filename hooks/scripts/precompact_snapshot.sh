#!/usr/bin/env bash
# shepherd hook — PreCompact: snapshot sprint state before compaction (v6.0.9).
#
# WHY: Claude Code's compaction truncates the conversation transcript only — the
# filesystem (root.db, state.json, shepherd.lock) survives. However, the
# orchestrator's *in-context* cursor (which Stage-Graph node is active, what is
# in-flight, what obligations are outstanding) is held in the model's context
# and is destroyed by compaction. This hook captures that cursor to a JSON
# snapshot so focus_rehydrate.sh can re-inject it after compaction.
#
# EVENT: PreCompact
# STDIN: { session_id, transcript_path, cwd, trigger: "manual"|"auto",
#           custom_instructions }
# OUTPUT: nothing to stdout (NEVER block compaction — exit 0 always).
#
# BEHAVIOR:
#   1. Gate on [compaction] precompact_snapshot = on (default on) / off.
#   2. Assemble a snapshot JSON from (all fail-open, tolerate missing):
#        • $NS/graph/state.json  — jq the `ready` and `in_flight` node id arrays
#        • tail 20 lines of $NS/graph/trace.jsonl  — recent trace events
#        • unread mailbox rows from root.db  — outstanding messages
#        • $NS/shepherd.lock  — current lock holder / sprint
#        • focus table row for the current sprint (git branch name) from root.db
#   3. Write snapshot to $NS/snapshots/precompact-<session>-<epoch>.json
#   4. Touch a pending flag: $NS/tmp/rehydrate-pending.<sanitized-session>
#   5. Trim $NS/snapshots/ to [compaction] snapshot_retention most-recent
#      precompact-*.json files (default 5).
#   6. log_event; exit 0 (NEVER emit a block decision).
#
# GUARANTEE: Every code path exits 0. Missing DB, missing sqlite3, missing jq,
# bad stdin, empty payload — all fail-open silently.

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$HERE/_lib.sh" 2>/dev/null || exit 0

PAYLOAD="$(cat 2>/dev/null || true)"

# --- is_shepherd_project guard -------------------------------------------
is_shepherd_project || exit 0

# --- config: on (default) | off ------------------------------------------
SNAP_ENABLED="on"
RETENTION=5
if [[ -f .claude/shepherd.toml ]]; then
  cfg_snap="$(grep -E '^[[:space:]]*precompact_snapshot[[:space:]]*=' .claude/shepherd.toml 2>/dev/null \
               | tail -1 | grep -oE '(on|off)' | tail -1 || true)"
  [[ -n "$cfg_snap" ]] && SNAP_ENABLED="$cfg_snap"

  cfg_ret="$(grep -E '^[[:space:]]*snapshot_retention[[:space:]]*=' .claude/shepherd.toml 2>/dev/null \
              | tail -1 | grep -oE '[0-9]+' | tail -1 || true)"
  [[ -n "$cfg_ret" ]] && RETENTION="$cfg_ret"
fi
[[ "$SNAP_ENABLED" == "off" ]] && exit 0

# --- fields from stdin ---------------------------------------------------
SESSION="$(json_field "$PAYLOAD" '.session_id' 2>/dev/null || true)"
[[ -n "$SESSION" ]] || SESSION="nosession"
TRIGGER="$(json_field "$PAYLOAD" '.trigger' 2>/dev/null || true)"

# --- namespace + paths ---------------------------------------------------
NS="$(resolve_namespace 2>/dev/null || echo .shepherd)"
DB="$NS/root.db"
STATE_JSON="$NS/graph/state.json"
TRACE_JSONL="$NS/graph/trace.jsonl"
LOCK_FILE="$NS/shepherd.lock"
# v6.1.3: snapshots live under memory/snapshots/ (co-located with other
# ephemeral rehydration state). focus_rehydrate.sh reads the SAME path.
SNAP_DIR="$NS/memory/snapshots"
LEGACY_SNAP_DIR="$NS/snapshots"
TMP_DIR="$NS/tmp"

# Sanitize session id for use in filenames (keep alphanum, dots, dashes, underscores).
SESSION_SAFE="${SESSION//[^A-Za-z0-9_.-]/_}"
EPOCH="$(date +%s 2>/dev/null || echo 0)"
SNAP_FILE="$SNAP_DIR/precompact-${SESSION_SAFE}-${EPOCH}.json"
FLAG_FILE="$TMP_DIR/rehydrate-pending.${SESSION_SAFE}"

mkdir -p "$SNAP_DIR" "$TMP_DIR" 2>/dev/null || true

# One-time migration: relocate any snapshots left in the legacy ./snapshots
# directory into memory/snapshots/, then drop the now-empty legacy dir.
# Fail-open: a migration error must never block snapshotting.
if [[ -d "$LEGACY_SNAP_DIR" && "$LEGACY_SNAP_DIR" != "$SNAP_DIR" ]]; then
  mv "$LEGACY_SNAP_DIR"/precompact-*.json "$SNAP_DIR"/ 2>/dev/null || true
  rmdir "$LEGACY_SNAP_DIR" 2>/dev/null || true
fi

# --- helper: read file safely -------------------------------------------
safe_read() { cat "$1" 2>/dev/null || true; }

# --- 1. graph cursor: ready + in_flight from state.json ------------------
READY_NODES=""
IN_FLIGHT_NODES=""
if [[ -f "$STATE_JSON" ]]; then
  if command -v jq &>/dev/null; then
    READY_NODES="$(jq -r '[.ready // [] | .[]? | tostring] | join(",")' "$STATE_JSON" 2>/dev/null || true)"
    IN_FLIGHT_NODES="$(jq -r '[.in_flight // [] | .[]? | tostring] | join(",")' "$STATE_JSON" 2>/dev/null || true)"
  else
    READY_NODES="$(python3 -c '
import json,sys
d=json.load(open(sys.argv[1]))
print(",".join(str(x) for x in d.get("ready",[])))
' "$STATE_JSON" 2>/dev/null || true)"
    IN_FLIGHT_NODES="$(python3 -c '
import json,sys
d=json.load(open(sys.argv[1]))
print(",".join(str(x) for x in d.get("in_flight",[])))
' "$STATE_JSON" 2>/dev/null || true)"
  fi
fi

# --- 2. trace tail (last 20 lines) ----------------------------------------
TRACE_TAIL=""
if [[ -f "$TRACE_JSONL" ]]; then
  TRACE_TAIL="$(tail -20 "$TRACE_JSONL" 2>/dev/null || true)"
fi

# --- 3. unread mailbox rows from root.db ----------------------------------
UNREAD_MAIL="[]"
if [[ -f "$DB" ]] && command -v sqlite3 &>/dev/null; then
  UNREAD_MAIL="$(sqlite3 "$DB" \
    "SELECT json_group_array(json_object('id',id,'recipient',recipient_name,'sent_at',sent_at)) FROM mailbox WHERE read_at IS NULL;" \
    2>/dev/null || echo '[]')"
  [[ -n "$UNREAD_MAIL" ]] || UNREAD_MAIL="[]"
fi

# --- 4. shepherd.lock contents -------------------------------------------
LOCK_CONTENT=""
if [[ -f "$LOCK_FILE" ]]; then
  LOCK_CONTENT="$(safe_read "$LOCK_FILE")"
fi

# --- 5. focus table row for current sprint --------------------------------
SPRINT="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'unknown')"
FOCUS_OBJ="{}"
if [[ -f "$DB" ]] && command -v sqlite3 &>/dev/null; then
  if sqlite3 "$DB" "SELECT name FROM sqlite_master WHERE type='table' AND name='focus';" 2>/dev/null | grep -q 'focus'; then
    if command -v jq &>/dev/null; then
      FOCUS_OBJ="$(sqlite3 "$DB" \
        "SELECT json_object('sprint',sprint,'objective',objective,'active_node',active_node,'ready_set',ready_set,'obligations',obligations,'invariants',invariants,'updated_at',updated_at) FROM focus WHERE sprint='${SPRINT//\'/\'\'}' LIMIT 1;" \
        2>/dev/null || echo '{}')"
      [[ -n "$FOCUS_OBJ" ]] || FOCUS_OBJ="{}"
    else
      FOCUS_OBJ="$(sqlite3 "$DB" \
        "SELECT json_object('sprint',sprint,'objective',objective,'active_node',active_node,'ready_set',ready_set,'obligations',obligations,'invariants',invariants,'updated_at',updated_at) FROM focus WHERE sprint='${SPRINT//\'/\'\'}' LIMIT 1;" \
        2>/dev/null || echo '{}')"
      [[ -n "$FOCUS_OBJ" ]] || FOCUS_OBJ="{}"
    fi
  fi
fi

# --- 6. Write snapshot file ----------------------------------------------
# NOTE: ${VAR:-{}} and ${VAR:-[]} are ambiguous under `set -uo pipefail` — the
# `}` inside the braces terminates the parameter expansion, producing a trailing
# literal `}` or `]`. Use explicit temp vars for any JSON-punctuation defaults.
_snap_unread="${UNREAD_MAIL}"; [[ -n "$_snap_unread" ]] || _snap_unread='[]'
_snap_focus="${FOCUS_OBJ}";   [[ -n "$_snap_focus"  ]] || _snap_focus='{}'
_snap_ts="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo '')"
_snap_trigger="${TRIGGER}"; [[ -n "$_snap_trigger" ]] || _snap_trigger='unknown'

if command -v jq &>/dev/null; then
  jq -n \
    --arg session "$SESSION" \
    --arg trigger "$_snap_trigger" \
    --arg sprint "$SPRINT" \
    --arg ts "$_snap_ts" \
    --arg ready_nodes "$READY_NODES" \
    --arg in_flight_nodes "$IN_FLIGHT_NODES" \
    --arg trace_tail "$TRACE_TAIL" \
    --argjson unread_mail "$_snap_unread" \
    --arg lock "$LOCK_CONTENT" \
    --argjson focus "$_snap_focus" \
    '{
      session_id: $session,
      trigger: $trigger,
      sprint: $sprint,
      captured_at: $ts,
      cursor: {
        ready_nodes: ($ready_nodes | split(",") | map(select(. != ""))),
        in_flight_nodes: ($in_flight_nodes | split(",") | map(select(. != "")))
      },
      trace_tail: $trace_tail,
      unread_mail: $unread_mail,
      lock: $lock,
      focus: $focus
    }' > "$SNAP_FILE" 2>/dev/null || true
else
  python3 -c '
import json, sys, os
d = {
  "session_id":       sys.argv[1],
  "trigger":          sys.argv[2],
  "sprint":           sys.argv[3],
  "captured_at":      sys.argv[4],
  "cursor": {
    "ready_nodes":    [x for x in sys.argv[5].split(",") if x],
    "in_flight_nodes":[x for x in sys.argv[6].split(",") if x],
  },
  "trace_tail":       sys.argv[7],
  "unread_mail":      json.loads(sys.argv[8] or "[]"),
  "lock":             sys.argv[9],
  "focus":            json.loads(sys.argv[10] or "{}"),
}
print(json.dumps(d, indent=2))
' "$SESSION" "$_snap_trigger" "$SPRINT" \
  "$_snap_ts" \
  "$READY_NODES" "$IN_FLIGHT_NODES" \
  "$TRACE_TAIL" "$_snap_unread" "$LOCK_CONTENT" "$_snap_focus" \
  > "$SNAP_FILE" 2>/dev/null || true
fi

# --- 7. Touch the rehydration-pending flag --------------------------------
touch "$FLAG_FILE" 2>/dev/null || true

# --- 8. Trim snapshots to retention count ---------------------------------
# Only trim precompact-*.json files; leave other files in snapshots/ alone.
# Sort by modification time (newest first via `ls -t`) so the N most recently
# WRITTEN snapshots survive, regardless of session-id sort order. The just-written
# snapshot is guaranteed to be the newest and will not be trimmed.
if [[ -d "$SNAP_DIR" ]]; then
  # bash 3.2 (default macOS /bin/bash) lacks `mapfile`/`readarray`; use a
  # portable read loop. Without this the retention trim silently dies under
  # `set -u` and snapshots accumulate without bound (the "so many precompact
  # files" symptom). SNAPS is pre-initialized so `${#SNAPS[@]}` is never unbound.
  SNAPS=()
  while IFS= read -r _snap; do
    [[ -n "$_snap" ]] && SNAPS+=("$_snap")
  done < <(ls -t "$SNAP_DIR"/precompact-*.json 2>/dev/null || true)
  SNAP_COUNT="${#SNAPS[@]}"
  if [[ "$SNAP_COUNT" -gt "$RETENTION" ]]; then
    # SNAPS is newest-first; trim from the tail (oldest entries).
    for (( i=RETENTION; i<SNAP_COUNT; i++ )); do
      rm -f "${SNAPS[$i]}" 2>/dev/null || true
    done
  fi
fi

# --- 9. log_event ---------------------------------------------------------
log_event "precompact_snapshot" "snapshot" "PreCompact" "shepherd" "$SESSION" \
  "$(emit_json_obj trigger "$_snap_trigger" sprint "$SPRINT" snap_file "$SNAP_FILE" pending_flag "$FLAG_FILE")" 2>/dev/null || true

# NEVER block compaction — always exit 0, emit nothing to stdout.
exit 0
