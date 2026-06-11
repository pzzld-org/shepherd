#!/usr/bin/env bash
# shepherd hook — SessionStart: toolkit surface (v6.1.2)
#
# WHY: Project-local and user-global tool registries (toolkit.json) hold tools
# the operator has registered — MCP servers, CLI targets, skills, plugins. Without
# a session-start reminder Claude forgets they exist and asks the operator to
# re-explain them. This hook merges both registries and injects a compact tool
# roster into additionalContext so Claude begins every session toolkit-aware.
#
# EVENT:  SessionStart
# STDIN:  { session_id, transcript_path, cwd, source, hook_event_name }
# OUTPUT: {"additionalContext":"🧰 Project toolkit (N tools)..."} or nothing.
#
# FAST-PATHS (exit 0 silently):
#   - not a shepherd project
#   - both toolkit.json files absent or contain zero tools
#   - jq unavailable
# FAIL-OPEN: any error → exit 0. Never blocks.
# BOUNDED: caps at 12 tool lines; pinned entries surface first.
# See: skills/shepherd/doctrines/toolkit.md

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$HERE/_lib.sh" 2>/dev/null || exit 0

PAYLOAD="$(cat 2>/dev/null || true)"

# --- is_shepherd_project guard -----------------------------------------------
is_shepherd_project || exit 0

# --- jq guard ----------------------------------------------------------------
command -v jq &>/dev/null || exit 0

# --- session id for log_event ------------------------------------------------
SESSION="$(json_field "$PAYLOAD" '.session_id' 2>/dev/null || true)"
[[ -n "$SESSION" ]] || SESSION="nosession"

# --- resolve toolkit paths ---------------------------------------------------
NS="$(resolve_namespace 2>/dev/null || echo .shepherd)"
LOCAL_TK="$NS/toolkit.json"
GLOBAL_TK="${XDG_CONFIG_HOME:-$HOME/.config}/shepherd/toolkit.json"

# --- load tools from a toolkit.json, print jq array (or empty array) ---------
load_tools() {
  local f="$1"
  [[ -f "$f" ]] || { printf '[]'; return 0; }
  jq -c '.tools // []' "$f" 2>/dev/null || printf '[]'
}

LOCAL_TOOLS="$(load_tools "$LOCAL_TK")"
GLOBAL_TOOLS="$(load_tools "$GLOBAL_TK")"

# --- merge: global ∪ local; local wins on name collision; pinned first --------
# jq program:
#   1. Build index from global tools keyed by name.
#   2. Override with local tools (same key → local wins).
#   3. Collect values; sort pinned first, then by name.
#   4. Cap at 12 entries.
MERGED="$(jq -cn \
  --argjson g "$GLOBAL_TOOLS" \
  --argjson l "$LOCAL_TOOLS" \
  '($g + $l)
   | group_by(.name)
   | map(last)
   | sort_by([(if .pinned == true then 0 else 1 end), .name])
   | .[0:12]' 2>/dev/null || printf '[]')"

# --- count tools -------------------------------------------------------------
TOOL_COUNT="$(printf '%s' "$MERGED" | jq 'length' 2>/dev/null || echo 0)"
[[ "${TOOL_COUNT:-0}" -gt 0 ]] || exit 0

# --- build compact roster string ---------------------------------------------
ROSTER="$(printf '%s' "$MERGED" | jq -r \
  '.[] | "• \(.name) (\(.type // "?")) — \(.description // "(no description)")"' \
  2>/dev/null || true)"

[[ -n "$ROSTER" ]] || exit 0

MSG="$(printf '%s\n%s' \
  "🧰 Project toolkit ($TOOL_COUNT tool(s)) — consult before assuming a capability is unavailable:" \
  "$ROSTER")"

log_event "toolkit_surface" "context" "SessionStart" "shepherd" "$SESSION" \
  "$(emit_json_obj tool_count "$TOOL_COUNT")" 2>/dev/null || true

emit_context "$MSG" "" "" "shepherd" "$SESSION"
