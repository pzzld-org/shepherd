#!/usr/bin/env bash
# shepherd hook — Stop: coordinate-mode active-drive guard (v6.0.5).
#
# Backstop for skills/motivation/SKILL.md §Drive contract. Fires at Stop (root about to
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
# Resolved via cfg_get → honors .claude/shepherd.local.toml + XDG global (v6.1.5).
cfg="$(cfg_get coordinate_drive_guard | grep -oE '(block|warn|off)' | tail -1 || true)"
[[ -n "$cfg" ]] && MODE="$cfg"
[[ "$MODE" == "off" ]] && exit 0

command -v sqlite3 >/dev/null 2>&1 || exit 0
NS="$(resolve_namespace 2>/dev/null || echo .)"
DB="$(hook_db_path "$NS")"
[[ -f "$DB" ]] || exit 0

# --- #197: root/lead-only. If THIS session is itself a registered, non-retired
# teammate, the coordinate-drive contract does not apply — a teammate (e.g. the
# self-contained @engineer, which reaches turn boundaries while authoring its
# plan) must NEVER run the root's "drain the work first" loop, or it is trapped
# churning root instructions instead of its own task and its output silently
# degrades. Mirror the exact teammate detection teammate_git_guard.sh uses
# (session_id match); fail-open (treat as root) if the query errors. ---
SESSION="$(json_field "$PAYLOAD" '.session_id' 2>/dev/null || true)"
[[ -n "$SESSION" ]] || SESSION="nosession"
SELF_TM="$(sqlite3 "$DB" "SELECT count(*) FROM teammates WHERE session_id='${SESSION//\'/\'\'}' AND status NOT IN ('retired','crashed');" 2>/dev/null || echo 0)"
[[ "$SELF_TM" =~ ^[0-9]+$ ]] || SELF_TM=0
[[ "$SELF_TM" -gt 0 ]] && exit 0

# --- fast-path: only ever engage inside a live spawn session. A teammate that
# DECLARED complete (0019), or an undeclared row gone stale past the window (a
# prior-session ghost, #195), is not a live worker root can drain — exclude both
# so a stale ghost never traps root in a phantom coordinate loop. Falls back to
# the pre-0019 count when declared_state predates migration 0019. ---
STALE_MS=300000   # 5 min, matching `shctx teammate liveness` default
# A row counts as a live worker unless it declared complete (terminal) or is an
# undeclared/init row gone stale past the window (a ghost). in-progress/error/idle
# declarations keep it live regardless of the heartbeat gap; init falls through to
# the freshness check (a stale boot is a ghost), matching liveness + prune.
LIVE_PRED="COALESCE(declared_state,'') <> 'complete' AND (declared_state IN ('in-progress','error','idle') OR ms_since_seen <= $STALE_MS)"
LIVE="$(sqlite3 "$DB" "SELECT count(*) FROM v_teammates_live WHERE $LIVE_PRED;" 2>/dev/null || true)"
if [[ "$LIVE" =~ ^[0-9]+$ ]]; then
  IDLE_Q="SELECT count(*) FROM v_teammates_live WHERE ($LIVE_PRED) AND (status='idle' OR declared_state='idle');"
else
  # Pre-0019 DB (no declared_state column) → original behavior.
  LIVE="$(sqlite3 "$DB" "SELECT count(*) FROM v_teammates_live;" 2>/dev/null || echo 0)"
  IDLE_Q="SELECT count(*) FROM teammates WHERE status='idle';"
fi
[[ "$LIVE" =~ ^[0-9]+$ ]] || LIVE=0
[[ "$LIVE" -eq 0 ]] && exit 0

# --- #223: lead-only gate. A shepherd.db is scoped PER REPO, not per session —
# two unrelated sessions (e.g. one that spawned a team, and a second,
# unrelated session opened in the same repo) can share it. Before #223 this
# guard only ever exempted registered TEAMMATES (#197 above); a non-teammate
# BYSTANDER session reading the very same v_teammates_live live/idle counts
# had no way to tell "I am the lead who spawned this team" apart from "someone
# else spawned this team and I merely share their DB" — so it got nudged with
# [coordinate-active-drive] on every turn despite owning no team to drain.
#
# MY_LEAD  = # of live teams (per v_teammates_live) for which THIS session is
#            the recorded spawn_leads.session_id.
# OTHER_LEAD = # of live teams for which a DIFFERENT session is the recorded
#            lead.
#
# If I lead none of the live teams (MY_LEAD=0) AND some OTHER session is
# recorded as lead of at least one (OTHER_LEAD>0), I am conclusively a
# bystander to someone else's team → exit 0 (never trap a session that isn't
# the drive-guard contract's audience).
#
# CONSERVATIVE BY DESIGN — this is NOT a plain fail-open-on-no-match. When NO
# lead is recorded at all for the live team(s) (a pre-#223 DB that predates
# this migration, or a spawn that never called `teammate register-lead`),
# OTHER_LEAD is 0 and this gate does nothing: control falls through to the
# pre-#223 behavior below (proceed to the idle/actionable check) rather than
# silently no-op a genuine lazy-root stop just because lead data is absent.
# Uses the identical single-quote escaping idiom as the SELF_TM query above so
# quoting matches.
MY_LEAD="$(sqlite3 "$DB" "SELECT count(*) FROM spawn_leads sl WHERE sl.session_id='${SESSION//\'/\'\'}' AND sl.team_name IN (SELECT DISTINCT team_name FROM v_teammates_live);" 2>/dev/null || echo 0)"
OTHER_LEAD="$(sqlite3 "$DB" "SELECT count(*) FROM spawn_leads sl WHERE sl.session_id<>'${SESSION//\'/\'\'}' AND sl.team_name IN (SELECT DISTINCT team_name FROM v_teammates_live);" 2>/dev/null || echo 0)"
[[ "$MY_LEAD" =~ ^[0-9]+$ ]] || MY_LEAD=0
[[ "$OTHER_LEAD" =~ ^[0-9]+$ ]] || OTHER_LEAD=0
[[ "$MY_LEAD" -eq 0 && "$OTHER_LEAD" -gt 0 ]] && exit 0

# --- actionable, root-clearable coordinate state ----------------------------
# The ONLY root-clearable state this guard keys on is an IDLE teammate whose
# payload root must materialize. Undrained "mail" is deliberately NOT a signal
# here (v6.3.7 #206): root's canonical inbox is the harness-native SendMessage
# queue — teammate messages arrive inline as native message blocks, NOT as rows
# in a SQLite table — so a Stop hook cannot and must not try to count it. The
# retired mailbox's phantom-unread desync (an empty inbox reading "N unread" and
# re-firing this guard every fresh session, because an abandoned --staged row sat
# read_at IS NULL forever in the shared per-repo DB) is gone with the table.
IDLE="$(sqlite3 "$DB" "$IDLE_Q" 2>/dev/null || echo 0)"
[[ "$IDLE" =~ ^[0-9]+$ ]] || IDLE=0

# --- counter (per-session; bounds the block) --------------------------------
# SESSION resolved above (used for the #197 self-teammate gate + this counter).
CNT_DIR="$NS/tmp"
CNT_FILE="$CNT_DIR/coordinate_drive_guard.${SESSION//[^A-Za-z0-9_.-]/_}.count"
CAP=2

if [[ "$IDLE" -eq 0 ]]; then
  # No undrained state: teammates are genuinely busy. Yielding to events here is
  # correct (doctrine §IV.4 / §VIII). Reset the counter and let the root stop.
  rm -f "$CNT_FILE" 2>/dev/null || true
  exit 0
fi

# Actionable state present and the root is trying to stop → the passive-wait bug.
mkdir -p "$CNT_DIR" 2>/dev/null || true
CNT="$(cat "$CNT_FILE" 2>/dev/null || echo 0)"
[[ "$CNT" =~ ^[0-9]+$ ]] || CNT=0

REASON="[coordinate-active-drive] You are the root shepherd in coordinate mode with ${LIVE} live teammate(s), ${IDLE} of them idle. Do NOT end your turn waiting — drain the work first (skills/motivation/SKILL.md §Drive contract §IV): read every teammate message the native SendMessage queue delivered inline and route by halt_code; on a WAVE-COMPLETE materialize the payload, commit the wave, release the next wave-gate; prune each idle teammate whose payload is materialized and refresh its lane next wave (scoped to that one lane's worktree via 'git worktree remove .worktrees/<sprint_slug>-<lane>' — NEVER a blanket 'git worktree list | grep agent- | remove' loop or 'git worktree prune' while siblings are live); probe any teammate that went idle without WAVE-COMPLETE. THEN sweep liveness + per-lane git diff --stat for drift before yielding. If instead you are stopping to surface a HARD-STOP or operator-question, emit that concrete question now and stop — that is the one legitimate pause."

if [[ "$CNT" -ge "$CAP" ]]; then
  # Runaway cap: state hasn't cleared after CAP nudges → the operator is
  # deliberately stopping (or cannot act). Fail OPEN and STAY open — pin the
  # counter at the cap (do NOT reset here) so subsequent stops also yield until
  # the actionable state clears (the not-actionable branch above resets it).
  # This makes the breaker a one-way trip per stuck-state, not a block/yield
  # oscillation (#114 runaway-loop class).
  echo "$CAP" > "$CNT_FILE" 2>/dev/null || true
  echo "[shctx] coordinate-drive guard: yielding after ${CAP} nudges (${IDLE} idle teammate(s) still pending — handle teammates or set [spawn].coordinate_drive_guard=warn)" >&2
  log_event "coordinate_drive_guard" "pass" "Stop" "shepherd" "$SESSION" \
    "$(emit_json_obj note "runaway-cap-failopen" idle "$IDLE")" 2>/dev/null || true
  exit 0
fi

if [[ "$MODE" == "warn" ]]; then
  echo "[shctx] coordinate-drive: ${IDLE} idle teammate(s) — drain before yielding (coordinate-active-drive.md §IV)" >&2
  log_event "coordinate_drive_guard" "warn" "Stop" "shepherd" "$SESSION" \
    "$(emit_json_obj idle "$IDLE")" 2>/dev/null || true
  exit 0
fi

# block mode (default): re-engage the root.
echo $((CNT + 1)) > "$CNT_FILE" 2>/dev/null || true
log_event "coordinate_drive_guard" "block" "Stop" "shepherd" "$SESSION" \
  "$(emit_json_obj idle "$IDLE" nudge "$((CNT + 1))")" 2>/dev/null || true
emit_json_obj decision "block" reason "$REASON"
exit 0
