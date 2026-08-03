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
#   • Identity.    POSITIVE identity only (#232/#228): fires solely when THIS
#                  session is the recorded spawn lead (spawn_leads) AND carries
#                  no session-tier teammate marker. A marker or an unresolvable
#                  identity → exit silently (fail-open for bystanders,
#                  fail-CLOSED for marked teammates).
#   • Hygiene.     Reboot stale-sweep (#229): other sessions' rows unseen past
#                  [spawn].stale_sweep_minutes (default 60) and not declared
#                  in-progress are marked crashed before any count is taken.
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

# --- #232/#228: POSITIVE teammate identity. user_prompt_submit.sh stamps a
# session-tier marker at boot when the incoming prompt carries the rendered
# INVOCATION-CONTEXT dispatcher field. A marked session is a TEAMMATE even
# when its registry row is missing or mismatched (the #197 query above can
# only see REGISTERED teammates) — fail CLOSED for it: this guard NEVER
# nudges a marked teammate, no matter what the registry says. ---
[[ -f "$(session_tier_marker "$NS" "$SESSION")" ]] && exit 0

# --- #229: reboot stale-sweep (lead-session-start hygiene, run at Stop so the
# counts below are computed over a clean live set). Rows left by OTHER
# sessions — a prior boot of this repo's spawn — whose last_seen is older than
# the reboot horizon AND whose declared_state is neither in-progress (the 0019
# protected long-runner) nor complete (already terminal for the live set) are
# ghosts: a declared error/idle row otherwise stays in v_teammates_live
# FOREVER and traps every later lead session in phantom drive nudges. Mark
# them status='crashed' — the teammates CHECK constraint has no 'stale' value,
# and 'crashed' is the exact status the liveness heuristic already derives for
# this condition ("presumed-crashed"); the log_event records it was a sweep.
# Config: [spawn].stale_sweep_minutes (default 60; 0 disables). Fail-open:
# a pre-0019 DB (no declared_state column) errors the count → sweep no-ops. ---
SWEEP_MIN="$(cfg_get stale_sweep_minutes | grep -oE '[0-9]+' | tail -1 || true)"
[[ -n "$SWEEP_MIN" ]] || SWEEP_MIN=60
if [[ "$SWEEP_MIN" -gt 0 ]]; then
  HORIZON_MS=$(( $(date +%s) * 1000 - SWEEP_MIN * 60000 ))
  SWEEP_PRED="(session_id IS NULL OR session_id<>'${SESSION//\'/\'\'}') AND status IN ('booting','active','idle') AND last_seen_at < $HORIZON_MS AND COALESCE(declared_state,'') NOT IN ('in-progress','complete')"
  SWEPT="$(sqlite3 "$DB" "SELECT count(*) FROM teammates WHERE $SWEEP_PRED;" 2>/dev/null || echo 0)"
  [[ "$SWEPT" =~ ^[0-9]+$ ]] || SWEPT=0
  if [[ "$SWEPT" -gt 0 ]]; then
    sqlite3 "$DB" "UPDATE teammates SET status='crashed' WHERE $SWEEP_PRED;" 2>/dev/null || true
    log_event "coordinate_drive_guard" "stale-sweep" "Stop" "shepherd" "$SESSION" \
      "$(emit_json_obj swept "$SWEPT" horizon_min "$SWEEP_MIN")" 2>/dev/null || true
  fi
fi

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

# --- #223→#232: POSITIVE lead gate. A shepherd.db is scoped PER REPO, not per
# session — two unrelated sessions (one that spawned a team, and a second
# opened in the same repo) can share it. #223 exempted a bystander only when a
# DIFFERENT session was the recorded lead, and fell through to nudging when NO
# lead was recorded at all — registry INFERENCE. #232 flips the gate to
# positive identity: this guard fires ONLY when THIS session is the recorded
# spawn lead (spawn_leads.session_id) of at least one live team.
#
# MY_LEAD = # of live teams (per v_teammates_live) for which THIS session is
#           the recorded spawn_leads.session_id.
#
# MY_LEAD=0 — whether a different session is the recorded lead (a bystander
# sharing the per-repo DB), or no lead row exists at all (a spawn that skipped
# `shctx teammate register-lead`, or a pre-#223 DB) — is a negative or
# UNRESOLVABLE identity → exit silently. The pre-#232 no-lead fallback (nudge
# anyway) is retired: commands/spawn.md §Register teammates makes
# register-lead mandatory, so an absent row means this session has no team to
# drain. Fail-open for bystanders; the marker check above stays fail-CLOSED
# for marked teammates. Uses the identical single-quote escaping idiom as the
# SELF_TM query above so quoting matches.
MY_LEAD="$(sqlite3 "$DB" "SELECT count(*) FROM spawn_leads sl WHERE sl.session_id='${SESSION//\'/\'\'}' AND sl.team_name IN (SELECT DISTINCT team_name FROM v_teammates_live);" 2>/dev/null || echo 0)"
[[ "$MY_LEAD" =~ ^[0-9]+$ ]] || MY_LEAD=0
[[ "$MY_LEAD" -gt 0 ]] || exit 0

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
