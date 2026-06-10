#!/usr/bin/env bash
# shepherd hook — Stop: coordinate-mode active-drive guard (v6.0.5).
#
# Backstop for doctrines/coordinate-active-drive.md. Fires at Stop (root about to
# end its turn). If a /shepherd:spawn session is live AND the root is stopping
# with undrained, root-clearable coordinate state (an idle teammate, or lead-bound
# unread mail), the root is exhibiting the passive-wait bug (#113/#98/#112): it
# yields instead of draining the work. The guard re-engages it via a Stop block.
#
# Discipline (per the doctrine §VII):
#   • Fast-path.   No DB / no live teammates → exit 0 silently. Solo /start,
#                  /plant, and ALL non-spawn work are never touched.
#   • Bounded.     2-nudge cap (configurable). Past the cap → fail OPEN so a
#                  legitimate "stop with idle teammates" is never trapped (#114
#                  runaway-loop class). Counter resets when state clears.
#   • Fail-open.   Missing DB, no sqlite3, bad payload, any error → exit 0.
#                  The guard NEVER blocks on uncertainty.
#   • Config.      [spawn].coordinate_drive_guard = block (default) | warn | off.
#
# Input  (stdin): Stop JSON { "session_id": "...", ... } (fields optional).
# Output (stdout): nothing, OR a single-line {"decision":"block","reason":"..."}.
# Output (stderr): one-line nudge in `warn` mode or at the runaway cap.
# Exit: always 0 (the block is carried by stdout JSON, not the exit code).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$HERE/_lib.sh" 2>/dev/null || exit 0

PAYLOAD="$(cat 2>/dev/null || true)"

# --- config: block (default) | warn | off ----------------------------------
# Cheap grep, mirroring _lib.sh quiet_warnings(); no TOML parser needed.
MODE="block"
if [[ -f .claude/shepherd.toml ]]; then
  # Find the (last) coordinate_drive_guard assignment line, then pull the bare
  # value token. The key name contains none of block/warn/off, so a plain token
  # match on the line is robust to quoting/spacing.
  cfg="$(grep -E '^[[:space:]]*coordinate_drive_guard[[:space:]]*=' .claude/shepherd.toml 2>/dev/null \
           | tail -1 | grep -oE '(block|warn|off)' | tail -1 || true)"
  [[ -n "$cfg" ]] && MODE="$cfg"
fi
[[ "$MODE" == "off" ]] && exit 0

command -v sqlite3 >/dev/null 2>&1 || exit 0
NS="$(resolve_namespace 2>/dev/null || echo .)"
DB="$NS/root.db"
[[ -f "$DB" ]] || exit 0

# --- fast-path: only ever engage inside a live spawn session ----------------
LIVE="$(sqlite3 "$DB" "SELECT count(*) FROM v_teammates_live;" 2>/dev/null || echo 0)"
[[ "$LIVE" =~ ^[0-9]+$ ]] || LIVE=0
[[ "$LIVE" -eq 0 ]] && exit 0

# --- actionable, root-clearable coordinate state ----------------------------
IDLE="$(sqlite3 "$DB" "SELECT count(*) FROM teammates WHERE status='idle';" 2>/dev/null || echo 0)"
[[ "$IDLE" =~ ^[0-9]+$ ]] || IDLE=0
# Lead-bound unread = unread mail addressed to anything that is NOT a teammate
# (root / lead / shepherd-root — name varies, so match by exclusion). Robust to
# whatever the lead's mailbox name is.
UNREAD="$(sqlite3 "$DB" \
  "SELECT count(*) FROM mailbox WHERE read_at IS NULL AND recipient_name NOT IN (SELECT teammate_name FROM teammates);" \
  2>/dev/null || echo 0)"
[[ "$UNREAD" =~ ^[0-9]+$ ]] || UNREAD=0

# --- counter (per-session; bounds the block) --------------------------------
SESSION="$(json_field "$PAYLOAD" '.session_id' 2>/dev/null || true)"
[[ -n "$SESSION" ]] || SESSION="nosession"
CNT_DIR="$NS/tmp"
CNT_FILE="$CNT_DIR/coordinate_drive_guard.${SESSION//[^A-Za-z0-9_.-]/_}.count"
CAP=2

if [[ "$IDLE" -eq 0 && "$UNREAD" -eq 0 ]]; then
  # No undrained state: teammates are genuinely busy. Yielding to events here is
  # correct (doctrine §IV.4 / §VIII). Reset the counter and let the root stop.
  rm -f "$CNT_FILE" 2>/dev/null || true
  exit 0
fi

# Actionable state present and the root is trying to stop → the passive-wait bug.
mkdir -p "$CNT_DIR" 2>/dev/null || true
CNT="$(cat "$CNT_FILE" 2>/dev/null || echo 0)"
[[ "$CNT" =~ ^[0-9]+$ ]] || CNT=0

REASON="[coordinate-active-drive] You are the root shepherd in coordinate mode with ${LIVE} live teammate(s): ${IDLE} idle, ${UNREAD} unread message(s) addressed to you. Do NOT end your turn waiting — drain the work first (doctrines/coordinate-active-drive.md §IV): read every unread message and route by halt_code; on a WAVE-COMPLETE materialize the payload, commit the wave, release the next wave-gate; prune each idle teammate whose payload is materialized and refresh its lane next wave (scoped to that one lane's worktree via 'git worktree remove .worktrees/<sprint_slug>-<lane>' — NEVER a blanket 'git worktree list | grep agent- | remove' loop or 'git worktree prune' while siblings are live); probe any teammate that went idle without WAVE-COMPLETE. THEN sweep liveness + per-lane git diff --stat for drift before yielding. If instead you are stopping to surface a HARD-STOP or operator-question, emit that concrete question now and stop — that is the one legitimate pause."

if [[ "$CNT" -ge "$CAP" ]]; then
  # Runaway cap: state hasn't cleared after CAP nudges → the operator is
  # deliberately stopping (or cannot act). Fail OPEN and STAY open — pin the
  # counter at the cap (do NOT reset here) so subsequent stops also yield until
  # the actionable state clears (the not-actionable branch above resets it).
  # This makes the breaker a one-way trip per stuck-state, not a block/yield
  # oscillation (#114 runaway-loop class).
  echo "$CAP" > "$CNT_FILE" 2>/dev/null || true
  echo "[shctx] coordinate-drive guard: yielding after ${CAP} nudges (${IDLE} idle / ${UNREAD} unread still pending — handle teammates or set [spawn].coordinate_drive_guard=warn)" >&2
  log_event "coordinate_drive_guard" "pass" "Stop" "shepherd" "$SESSION" \
    "$(emit_json_obj note "runaway-cap-failopen" idle "$IDLE" unread "$UNREAD")" 2>/dev/null || true
  exit 0
fi

if [[ "$MODE" == "warn" ]]; then
  echo "[shctx] coordinate-drive: ${IDLE} idle teammate(s) / ${UNREAD} unread — drain before yielding (coordinate-active-drive.md §IV)" >&2
  log_event "coordinate_drive_guard" "warn" "Stop" "shepherd" "$SESSION" \
    "$(emit_json_obj idle "$IDLE" unread "$UNREAD")" 2>/dev/null || true
  exit 0
fi

# block mode (default): re-engage the root.
echo $((CNT + 1)) > "$CNT_FILE" 2>/dev/null || true
log_event "coordinate_drive_guard" "block" "Stop" "shepherd" "$SESSION" \
  "$(emit_json_obj idle "$IDLE" unread "$UNREAD" nudge "$((CNT + 1))")" 2>/dev/null || true
emit_json_obj decision "block" reason "$REASON"
exit 0
