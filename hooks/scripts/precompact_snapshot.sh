#!/usr/bin/env bash
# shepherd hook — PreCompact: snapshot sprint state before compaction (v6.0.9).
#
# WHY: Claude Code's compaction truncates the conversation transcript only — the
# filesystem (shepherd.db, run graph, shepherd.lock) survives. However, the
# orchestrator's *in-context* cursor (which Stage-Graph node is active, what is
# in-flight, what obligations are outstanding) is held in the model's context
# and is destroyed by compaction. This hook captures that cursor to a JSON
# snapshot as run-scoped diagnostic evidence for later native inspection.
#
# EVENT: PreCompact
# STDIN: { session_id, transcript_path, cwd, trigger: "manual"|"auto",
#           custom_instructions }
# OUTPUT: nothing to stdout (NEVER block compaction — exit 0 always).
#
# BEHAVIOR:
#   1. Gate on [compaction] precompact_snapshot = on (default on) / off.
#   2. Assemble a snapshot JSON from (all fail-open, tolerate missing):
#        • <active-run>/graph/state.json  — jq the `ready` and `in_flight` node id arrays
#        • tail 20 lines of <active-run>/graph/trace.jsonl  — recent trace events
#        • $NS/shepherd.lock  — current lock holder / sprint
#        • focus table row for the current sprint (git branch name) from shepherd.db
#   3. Write snapshot to <active-run>/snapshots/precompact-<session>-<epoch>.json
#   4. Trim <active-run>/snapshots/ to [compaction] snapshot_retention most-recent
#      precompact-*.json files (default 5).
#   5. log_event; exit 0 (NEVER emit a block decision).
#
# GUARANTEE: Every code path exits 0. Missing DB, missing sqlite3, missing jq,
# bad stdin, empty payload — all fail-open silently.

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$HERE/_lib.sh" 2>/dev/null || exit 0

# SQLite text-literal escaping, portable to macOS Bash 3.2.
sql_escape() { printf '%s' "${1:-}" | sed "s/'/''/g"; }

PAYLOAD="$(cat 2>/dev/null || true)"

# --- is_shepherd_project guard -------------------------------------------
is_shepherd_project || exit 0
shepherd_skip_without_jq "precompact_snapshot" || exit 0

# --- config: on (default) | off ------------------------------------------
SNAP_ENABLED="on"
RETENTION=5
# Resolved via the canonical project/user Shepherd config chain.
cfg_snap="$(cfg_get precompact_snapshot | grep -oE '(on|off)' | tail -1 || true)"
[[ -n "$cfg_snap" ]] && SNAP_ENABLED="$cfg_snap"
cfg_ret="$(cfg_get snapshot_retention | grep -oE '[0-9]+' | tail -1 || true)"
[[ -n "$cfg_ret" ]] && RETENTION="$cfg_ret"
[[ "$SNAP_ENABLED" == "off" ]] && exit 0

# --- fields from stdin ---------------------------------------------------
SESSION="$(json_field "$PAYLOAD" '.session_id' 2>/dev/null || true)"
[[ -n "$SESSION" ]] || SESSION="nosession"
TRIGGER="$(json_field "$PAYLOAD" '.trigger' 2>/dev/null || true)"

# --- active run + paths --------------------------------------------------
# The native run resolver accepts only one strict run.json with status
# "executing". A compaction snapshot without that identity would have no
# canonical owner, so this host adapter skips instead of recreating a
# namespace-level scratch directory.
NS="$(resolve_namespace 2>/dev/null || echo .shepherd)"
DB="$(hook_db_path "$NS")"
RUN_DIR="$(primary_active_run_dir 2>/dev/null || true)"
[[ -n "$RUN_DIR" ]] || exit 0
RUN_ID="$(basename "$RUN_DIR")"
STATE_JSON="$RUN_DIR/graph/state.json"
TRACE_JSONL="$RUN_DIR/graph/trace.jsonl"
LOCK_FILE="$NS/shepherd.lock"
SNAP_DIR="$RUN_DIR/snapshots"

# Sanitize session id for use in filenames (keep alphanum, dots, dashes, underscores).
SESSION_SAFE="${SESSION//[^A-Za-z0-9_.-]/_}"
EPOCH="$(date +%s 2>/dev/null || echo 0)"
SNAP_FILE="$SNAP_DIR/precompact-${SESSION_SAFE}-${EPOCH}.json"

mkdir -p "$SNAP_DIR" 2>/dev/null || true

# --- helper: read file safely -------------------------------------------
safe_read() { cat "$1" 2>/dev/null || true; }

# --- 1. graph cursor: ready + in_flight from state.json ------------------
READY_NODES=""
IN_FLIGHT_NODES=""
if [[ -f "$STATE_JSON" ]]; then
  READY_NODES="$(jq -r '[.ready // [] | .[]? | tostring] | join(",")' "$STATE_JSON" 2>/dev/null || true)"
  IN_FLIGHT_NODES="$(jq -r '[.in_flight // [] | .[]? | tostring] | join(",")' "$STATE_JSON" 2>/dev/null || true)"
fi

# --- 2. trace tail (last 20 lines) ----------------------------------------
TRACE_TAIL=""
if [[ -f "$TRACE_JSONL" ]]; then
  TRACE_TAIL="$(tail -20 "$TRACE_JSONL" 2>/dev/null || true)"
fi

# --- 3. shepherd.lock contents -------------------------------------------
# (The former "unread mailbox" snapshot was removed in v6.3.7 (#206): root's
# obligations live in the harness-native SendMessage queue, which survives
# compaction on its own and is not SQLite-readable — nothing to snapshot here.)
LOCK_CONTENT=""
if [[ -f "$LOCK_FILE" ]]; then
  LOCK_CONTENT="$(safe_read "$LOCK_FILE")"
fi

# --- 5. focus table row for current sprint --------------------------------
SPRINT="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'unknown')"
SPRINT_SQL="$(sql_escape "$SPRINT")"
FOCUS_OBJ="{}"
if [[ -f "$DB" ]] && command -v sqlite3 &>/dev/null; then
  if sqlite3 "$DB" "SELECT name FROM sqlite_master WHERE type='table' AND name='focus';" 2>/dev/null | grep -q 'focus'; then
    # Capture the SPRINT-LEVEL cursor. Since migration 0017 the focus table is
    # keyed (sprint, lane); lane='' is the sprint-level record. On a DB still at
    # 0013 (no lane column) the clause is omitted so the query stays valid.
    LANE_CLAUSE=""
    if sqlite3 "$DB" "SELECT 1 FROM pragma_table_info('focus') WHERE name='lane';" 2>/dev/null | grep -q 1; then
      LANE_CLAUSE="AND lane=''"
    fi
    FOCUS_OBJ="$(sqlite3 "$DB" \
      "SELECT json_object('sprint',sprint,'objective',objective,'active_node',active_node,'ready_set',ready_set,'obligations',obligations,'invariants',invariants,'updated_at',updated_at) FROM focus WHERE sprint='$SPRINT_SQL' ${LANE_CLAUSE} LIMIT 1;" \
      2>/dev/null || echo '{}')"
    [[ -n "$FOCUS_OBJ" ]] || FOCUS_OBJ="{}"
  fi
fi

# --- 6. Write snapshot file ----------------------------------------------
# NOTE: ${VAR:-{}} and ${VAR:-[]} are ambiguous under `set -uo pipefail` — the
# `}` inside the braces terminates the parameter expansion, producing a trailing
# literal `}` or `]`. Use explicit temp vars for any JSON-punctuation defaults.
_snap_focus="${FOCUS_OBJ}";   [[ -n "$_snap_focus"  ]] || _snap_focus='{}'
_snap_ts="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo '')"
_snap_trigger="${TRIGGER}"; [[ -n "$_snap_trigger" ]] || _snap_trigger='unknown'

jq -n \
  --arg session "$SESSION" \
  --arg trigger "$_snap_trigger" \
  --arg sprint "$SPRINT" \
  --arg run "$RUN_ID" \
  --arg ts "$_snap_ts" \
  --arg ready_nodes "$READY_NODES" \
  --arg in_flight_nodes "$IN_FLIGHT_NODES" \
  --arg trace_tail "$TRACE_TAIL" \
  --arg lock "$LOCK_CONTENT" \
  --argjson focus "$_snap_focus" \
  '{
    session_id: $session,
    trigger: $trigger,
    sprint: $sprint,
    run: $run,
    captured_at: $ts,
    cursor: {
      ready_nodes: ($ready_nodes | split(",") | map(select(. != ""))),
      in_flight_nodes: ($in_flight_nodes | split(",") | map(select(. != "")))
    },
    trace_tail: $trace_tail,
    lock: $lock,
    focus: $focus
  }' > "$SNAP_FILE" 2>/dev/null || true

# --- 7. Trim snapshots to retention count ---------------------------------
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

# --- 8. log_event ---------------------------------------------------------
log_event "precompact_snapshot" "snapshot" "PreCompact" "shepherd" "$SESSION" \
  "$(emit_json_obj trigger "$_snap_trigger" sprint "$SPRINT" snap_file "$SNAP_FILE")" 2>/dev/null || true

# NEVER block compaction — always exit 0, emit nothing to stdout.
exit 0
