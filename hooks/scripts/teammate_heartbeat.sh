#!/usr/bin/env bash
# shepherd hook — PreToolUse: automatic teammate liveness heartbeat (v6.3.3 #193).
#
# PROBLEM (#193): non-conductor teammates — the self-contained @engineer, and any
# role that does not call `shctx teammate heartbeat` on a cadence — never advance
# `last_seen_at`, so it stays frozen at `spawned_at`. `shctx teammate liveness` then
# reports a permanent FALSE verdict (idle → presumed-crashed) while the teammate is
# actively running a multi-minute fan-out, and every stall-guard keyed on
# `sec_since_seen` false-fires. The 0019 `declared_state` read-verdict was only a
# half-fix: it still requires the teammate to MANUALLY declare its state.
#
# FIX (#193 option b — the robust one the issue asked for): derive liveness from a
# signal every role updates FOR FREE. This PreToolUse hook fires on every tool call;
# when the current session is a registered teammate, it stamps `last_seen_at = now`
# (and flips booting → active). No role has to remember to self-report, and a new
# role can never forget it. Intent (`declared_state`, phase) is still declared
# explicitly via `shctx teammate state/heartbeat`; this hook owns only the
# free, mechanical liveness signal.
#
# EVENT: PreToolUse (matched broadly — any tool call proves the teammate is alive).
# STDIN: { session_id, tool_name, tool_input, tool_use_id, ... }
# OUTPUT: always silent exit 0. Observational — it NEVER blocks a tool.
#
# Fail-open by contract: not a shepherd project / no sqlite3 / missing DB / not a
# registered teammate / any error → exit 0. A single indexed UPDATE, cheap enough to
# run on every call. It does NOT insert a heartbeats row (that would bloat the table
# on every tool call); `last_seen_at` is the whole liveness signal.
#
# TOGGLE: [hooks].teammate_heartbeat = on (default) | off.

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$HERE/_lib.sh" 2>/dev/null || exit 0

is_shepherd_project || exit 0

# Toggle (default on). Only the literal 'off' disables it.
[[ "$(cfg_section_get hooks teammate_heartbeat 2>/dev/null || true)" == "off" ]] && exit 0

PAYLOAD="$(cat 2>/dev/null || true)"
SESSION="$(json_field "$PAYLOAD" '.session_id' 2>/dev/null || true)"
[[ -n "$SESSION" ]] || exit 0

command -v sqlite3 >/dev/null 2>&1 || exit 0
NS="$(resolve_namespace 2>/dev/null || echo .shepherd)"
DB="$(hook_db_path "$NS")"
[[ -f "$DB" ]] || exit 0

esc="${SESSION//\'/\'\'}"
# Is this session a live (non-terminal) teammate? If the teammates table does not
# exist yet, sqlite3 errors → empty → exit 0 (fail-open). Most recent row wins.
TID="$(sqlite3 "$DB" \
  "SELECT id FROM teammates WHERE session_id='$esc' AND status NOT IN ('retired','crashed') ORDER BY spawned_at DESC LIMIT 1;" \
  2>/dev/null || true)"
[[ -n "$TID" ]] || exit 0

TS=$(( $(date +%s) * 1000 ))
# Self-heal the tmux pane id from $TMUX_PANE when unset (a teammate's tool call runs
# inside its own pane), mirroring `shctx teammate heartbeat`. COALESCE keeps any id
# root already set.
PANE_SET=""
[[ -n "${TMUX_PANE:-}" ]] && PANE_SET=", tmux_pane_id = COALESCE(tmux_pane_id, '${TMUX_PANE//\'/\'\'}')"

# Advance last_seen_at + revive booting → active. Best-effort; never surface an error.
sqlite3 "$DB" \
  "UPDATE teammates SET last_seen_at=$TS, status=CASE WHEN status='booting' THEN 'active' ELSE status END${PANE_SET} WHERE id='$TID';" \
  2>/dev/null || true

exit 0
