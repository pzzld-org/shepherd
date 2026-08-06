#!/usr/bin/env bash
# shepherd hook — SessionStart / UserPromptSubmit: focus rehydration (v6.0.9).
#
# WHY: After compaction the orchestrator resumes with a lean context. The
# precompact_snapshot.sh hook captured the sprint cursor (active node, ready-set,
# obligations, invariants) to a JSON snapshot and set a rehydration-pending flag.
# This hook detects the flag, builds a compact digest from the snapshot, emits it
# as `additionalContext` so the orchestrator resumes deterministically, and then
# drains (removes) the flag so this fires exactly once per compaction event.
#
# DUAL-EVENT REGISTRATION (hooks.json wires this to both events):
#   PRIMARY path  — SessionStart with source == "compact" (model resumed after
#                   a compaction, new session).
#   FALLBACK path — UserPromptSubmit (first user turn after compaction, same
#                   session continues). The fallback ensures rehydration even if
#                   the platform does not expose source == "compact" on SessionStart.
#   Both paths drain the flag on first fire; subsequent calls are silent no-ops.
#
# EVENT: SessionStart | UserPromptSubmit
# STDIN (SessionStart): { session_id, transcript_path, cwd, source, hook_event_name }
# STDIN (UserPromptSubmit): { session_id, transcript_path, cwd, prompt, hook_event_name }
# OUTPUT: {"additionalContext":"<digest>"} once, then silent.
#
# GATE: [focus] rehydrate = on (default) | off
# NEVER blocks — exit 0 always.

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$HERE/_lib.sh" 2>/dev/null || exit 0

PAYLOAD="$(cat 2>/dev/null || true)"

# --- is_shepherd_project guard -------------------------------------------
is_shepherd_project || exit 0

# --- config: on (default) | off ------------------------------------------
REHYDRATE_ENABLED="on"
# Resolved via cfg_get → honors .claude/shepherd.local.toml + XDG global (v6.1.5).
cfg="$(cfg_get rehydrate | grep -oE '(on|off)' | tail -1 || true)"
[[ -n "$cfg" ]] && REHYDRATE_ENABLED="$cfg"
[[ "$REHYDRATE_ENABLED" == "off" ]] && exit 0

# --- fields from stdin ---------------------------------------------------
SESSION="$(json_field "$PAYLOAD" '.session_id' 2>/dev/null || true)"
[[ -n "$SESSION" ]] || SESSION="nosession"
EVENT="$(json_field "$PAYLOAD" '.hook_event_name' 2>/dev/null || true)"
SOURCE="$(json_field "$PAYLOAD" '.source' 2>/dev/null || true)"

# --- namespace + flag file -----------------------------------------------
NS="$(resolve_namespace 2>/dev/null || echo .shepherd)"
SESSION_SAFE="${SESSION//[^A-Za-z0-9_.-]/_}"
FLAG_FILE="$NS/tmp/rehydrate-pending.${SESSION_SAFE}"

# --- fast-path: no pending flag for this session -------------------------
# (Also handles: non-compact SessionStart when no snapshot was taken.)
[[ -f "$FLAG_FILE" ]] || exit 0

# --- find the newest matching snapshot for this session ------------------
# v6.4.4: snapshots live under cache/snapshots/ (written by
# precompact_snapshot.sh). The two retired locations — v6.1.3's
# memory/snapshots/ and the pre-v6.1.3 top-level snapshots/ — are still read
# so a snapshot taken just before an upgrade still rehydrates.
#
# Search ALL THREE, then pick the newest by filename, rather than picking the
# first directory that happens to exist: the old first-existing-dir rule made
# a stale snapshot in a leftover memory/snapshots/ shadow a fresh one in
# cache/snapshots/, rehydrating pre-upgrade state forever.
SNAP_DIRS=("$NS/cache/snapshots" "$NS/memory/snapshots" "$NS/snapshots")
SNAP_FILE=""
# Snapshots are named precompact-<session_safe>-<epoch>.json. Sort by BASENAME
# (field 2 of the "<basename>\t<path>" pairs) so epoch ordering holds across
# directories — a plain full-path sort would order by directory name instead.
_newest_snapshot() {
  local pattern="$1" dir
  for dir in "${SNAP_DIRS[@]}"; do
    [[ -d "$dir" ]] || continue
    ls -1 "$dir"/$pattern 2>/dev/null || true
  done | awk -F/ '{print $NF "\t" $0}' | sort | tail -1 | cut -f2-
}
SNAP_FILE="$(_newest_snapshot "precompact-${SESSION_SAFE}-*.json")"
# Fallback: newest precompact-*.json regardless of session (e.g., nosession).
[[ -n "$SNAP_FILE" ]] || SNAP_FILE="$(_newest_snapshot "precompact-*.json")"

# No snapshot file available — drain the flag silently and exit.
if [[ -z "$SNAP_FILE" || ! -f "$SNAP_FILE" ]]; then
  rm -f "$FLAG_FILE" 2>/dev/null || true
  log_event "focus_rehydrate" "drain-no-snap" "${EVENT:-SessionStart}" "shepherd" "$SESSION" \
    "$(emit_json_obj note "flag-drained-no-snapshot")" 2>/dev/null || true
  exit 0
fi

# --- build digest from snapshot ------------------------------------------
OBJECTIVE=""
ACTIVE_NODE=""
READY_SET=""
OBLIGATIONS=""
INVARIANTS=""
SPRINT=""
RUN_ID=""
TRIGGER=""
CAPTURED_AT=""

if command -v jq &>/dev/null; then
  SPRINT="$(jq -r '.sprint // ""' "$SNAP_FILE" 2>/dev/null || true)"
  RUN_ID="$(jq -r '.run // ""' "$SNAP_FILE" 2>/dev/null || true)"
  TRIGGER="$(jq -r '.trigger // ""' "$SNAP_FILE" 2>/dev/null || true)"
  CAPTURED_AT="$(jq -r '.captured_at // ""' "$SNAP_FILE" 2>/dev/null || true)"
  ACTIVE_NODE="$(jq -r '.focus.active_node // ""' "$SNAP_FILE" 2>/dev/null || true)"
  READY_SET="$(jq -r '.focus.ready_set // ""' "$SNAP_FILE" 2>/dev/null || true)"
  OBLIGATIONS="$(jq -r '.focus.obligations // ""' "$SNAP_FILE" 2>/dev/null || true)"
  INVARIANTS="$(jq -r '.focus.invariants // ""' "$SNAP_FILE" 2>/dev/null || true)"
  OBJECTIVE="$(jq -r '.focus.objective // ""' "$SNAP_FILE" 2>/dev/null || true)"
  # Cursor from graph/state.json (ready + in_flight nodes)
  CURSOR_READY="$(jq -r '(.cursor.ready_nodes // []) | join(", ")' "$SNAP_FILE" 2>/dev/null || true)"
  CURSOR_INFLIGHT="$(jq -r '(.cursor.in_flight_nodes // []) | join(", ")' "$SNAP_FILE" 2>/dev/null || true)"
else
  SPRINT="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("sprint",""))' "$SNAP_FILE" 2>/dev/null || true)"
  RUN_ID="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("run",""))' "$SNAP_FILE" 2>/dev/null || true)"
  TRIGGER="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("trigger",""))' "$SNAP_FILE" 2>/dev/null || true)"
  CAPTURED_AT="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("captured_at",""))' "$SNAP_FILE" 2>/dev/null || true)"
  ACTIVE_NODE="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("focus",{}).get("active_node",""))' "$SNAP_FILE" 2>/dev/null || true)"
  READY_SET="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("focus",{}).get("ready_set",""))' "$SNAP_FILE" 2>/dev/null || true)"
  OBLIGATIONS="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("focus",{}).get("obligations",""))' "$SNAP_FILE" 2>/dev/null || true)"
  INVARIANTS="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("focus",{}).get("invariants",""))' "$SNAP_FILE" 2>/dev/null || true)"
  OBJECTIVE="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("focus",{}).get("objective",""))' "$SNAP_FILE" 2>/dev/null || true)"
  CURSOR_READY="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(", ".join(d.get("cursor",{}).get("ready_nodes",[])))' "$SNAP_FILE" 2>/dev/null || true)"
  CURSOR_INFLIGHT="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(", ".join(d.get("cursor",{}).get("in_flight_nodes",[])))' "$SNAP_FILE" 2>/dev/null || true)"
fi

# --- drain the flag (fire-once guarantee) --------------------------------
rm -f "$FLAG_FILE" 2>/dev/null || true

# --- assemble digest message ---------------------------------------------
DIGEST="[shepherd] FOCUS REHYDRATE — compaction recovery digest (trigger: ${TRIGGER:-unknown}, captured: ${CAPTURED_AT:-unknown})"$'\n'
DIGEST+="Sprint: ${SPRINT:-unknown}"$'\n'
# v6.4.1: the snapshot records which run was executing at capture time —
# surface the run-scoped state home so the resumed session re-reads the graph
# cursor from runs/{run}/graph/ (legacy graph/ at the namespace root when
# the field is absent/empty — the same compat shim precompact_snapshot.sh reads by).
[[ -n "$RUN_ID" ]] && DIGEST+="Run: ${RUN_ID} (graph state: runs/${RUN_ID}/graph/)"$'\n'
[[ -n "$OBJECTIVE" ]] && DIGEST+="Objective: ${OBJECTIVE}"$'\n'
DIGEST+="Active node: ${ACTIVE_NODE:-unknown}"$'\n'
[[ -n "$READY_SET" ]] && DIGEST+="Ready set (focus table): ${READY_SET}"$'\n'
[[ -n "$CURSOR_READY" ]] && DIGEST+="Ready nodes (graph cursor): ${CURSOR_READY}"$'\n'
[[ -n "$CURSOR_INFLIGHT" ]] && DIGEST+="In-flight nodes (graph cursor): ${CURSOR_INFLIGHT}"$'\n'
[[ -n "$OBLIGATIONS" ]] && DIGEST+="Obligations: ${OBLIGATIONS}"$'\n'
[[ -n "$INVARIANTS" ]] && DIGEST+="Invariants: ${INVARIANTS}"$'\n'
DIGEST+="Resume your drive from the active node above. The registry (root.db) is intact."$'\n'
DIGEST+="Run 'shctx status' for a full state summary if needed."

log_event "focus_rehydrate" "rehydrate" "${EVENT:-SessionStart}" "shepherd" "$SESSION" \
  "$(emit_json_obj trigger "${TRIGGER:-unknown}" sprint "${SPRINT:-unknown}" snap_file "$SNAP_FILE" active_node "${ACTIVE_NODE:-}")" 2>/dev/null || true

emit_context "$DIGEST" "" "" "shepherd" "$SESSION"
