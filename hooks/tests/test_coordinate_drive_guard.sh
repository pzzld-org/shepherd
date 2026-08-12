#!/usr/bin/env bash
# hooks/tests/test_coordinate_drive_guard.sh — tests for coordinate_drive_guard.sh
#
# Covers the Stop-hook backstop for skills/motivation/SKILL.md §Drive contract (v6.0.5):
#   • No-payload / no-DB → exit 0, no block (fast-path; never touches non-spawn work).
#   • Live spawn session + 0 idle → no block (yield is correct).
#   • Idle teammate + recorded lead → BLOCK (decision:block on stdout).
#   • Runaway cap: blocks twice, then fails OPEN on the 3rd consecutive stop.
#   • [spawn].coordinate_drive_guard = off → never blocks.
#   • [spawn].coordinate_drive_guard = warn → never blocks (stderr only).
#
# v6.3.7 (#206): the guard NO LONGER reads any mailbox/mail channel. Root's
# canonical inbox is the harness-native SendMessage queue, which a Stop hook
# cannot read from SQLite — so the ONLY root-clearable state this guard keys on
# is an IDLE teammate. The retired mailbox's phantom-unread desync (an empty
# inbox reading "N unread" and re-firing the guard every session) is structurally
# gone: there is no mail table to miscount. This suite proves idle-only triggering.
#
# v6.4.1 (#232/#228/#229): POSITIVE identity + hygiene —
#   • The guard fires ONLY for the recorded spawn lead (spawn_leads row); a
#     session with NO lead row is never nudged (the pre-#232 no-lead fallback
#     is retired), so every actionable case below records the lead first.
#   • A session-tier teammate marker (stamped by user_prompt_submit.sh at
#     boot) is fail-CLOSED: a marked session is never nudged, registered or not.
#   • Reboot stale-sweep: other sessions' rows unseen past the horizon and not
#     declared in-progress are marked crashed before any count is taken.
#
# Conventions match hooks/tests/run.sh and test_worktree_lifecycle.sh: pass/fail/
# skip tally; DB-dependent cases skip silently if sqlite3 is unavailable.

set -eu -o pipefail
cd "$(dirname "$0")"
HOOKS_DIR="$(cd .. && pwd)/scripts"
SCRIPT="$HOOKS_DIR/coordinate_drive_guard.sh"

fails=0
total=0
pass()  { printf '  PASS  %s\n' "$1"; }
fail()  { printf '  FAIL  %s — %s\n' "$1" "$2"; fails=$((fails+1)); }
skip()  { printf '  SKIP  %s — %s\n' "$1" "$2"; }

is_block() { printf '%s' "$1" | grep -q '"decision"[[:space:]]*:[[:space:]]*"block"'; }

# ---------------------------------------------------------------------------
# 1. No-payload invocation: exit 0, no block.
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(: | bash "$SCRIPT" 2>/dev/null) && rc=0 || rc=$?
if [[ "${rc:-0}" -eq 0 ]] && ! is_block "$out"; then
  pass "no-payload: exit 0, no block"
else
  fail "no-payload: exit 0, no block" "rc=${rc:-0} out=$out"
fi

if ! command -v sqlite3 >/dev/null 2>&1; then
  skip "DB-dependent cases" "sqlite3 binary missing"
  echo "—— $((total-fails))/$total passed ——"
  exit "$fails"
fi

# ---------------------------------------------------------------------------
# Ephemeral shepherd-flagged repo + minimal canonical DB (teammates +
# v_teammates_live), mirroring migration 0007. No mailbox table exists here at
# all (v6.3.7 #206) — the guard must never depend on one. No FK to projects.
# ---------------------------------------------------------------------------
tmp=$(mktemp -d -t shep-cdg-test.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q .
git config user.email t@t
git config user.name t
git -c commit.gpgsign=false commit -q --allow-empty -m init
mkdir -p .claude .artifacts
touch .claude/shepherd.toml
DB=".artifacts/root.db"
NOW=$(( $(date +%s) * 1000 ))

sqlite3 "$DB" <<SQL >/dev/null 2>&1
CREATE TABLE teammates (
  id TEXT PRIMARY KEY, team_name TEXT, teammate_name TEXT,
  agent_type TEXT, session_id TEXT, spawned_at INTEGER, last_seen_at INTEGER,
  status TEXT, declared_state TEXT
);
CREATE VIEW v_teammates_live AS
  SELECT t.*, (strftime('%s','now')*1000 - t.last_seen_at) AS ms_since_seen
  FROM teammates t WHERE t.status NOT IN ('crashed','retired');
CREATE TABLE spawn_leads (
  team_name TEXT PRIMARY KEY, session_id TEXT, spawned_at INTEGER
);
SQL

STALE=$(( NOW - 600000 ))     # 10 min ago — past the guard's 5-min live window
REBOOT=$(( NOW - 7200000 ))   # 2 h ago — past the #229 60-min reboot horizon
reset_db() { sqlite3 "$DB" "DELETE FROM teammates; DELETE FROM spawn_leads;" >/dev/null 2>&1; rm -f .artifacts/tmp/coordinate_drive_guard.*.count .artifacts/tmp/session-tier-* 2>/dev/null || true; }
# add_teammate <name> <status> [declared_state] [last_seen_ms] [session_id]
add_teammate() {
  local ds="NULL"; [[ -n "${3:-}" ]] && ds="'$3'"
  local seen="${4:-$NOW}"
  local sid="NULL"; [[ -n "${5:-}" ]] && sid="'$5'"
  sqlite3 "$DB" "INSERT INTO teammates (id,team_name,teammate_name,agent_type,session_id,spawned_at,last_seen_at,status,declared_state) VALUES ('$1','team','$1','conductor',$sid,$NOW,$seen,'$2',$ds);" >/dev/null 2>&1
}
# add_lead <lead_session_id> — records <lead_session_id> as the #223 recorded
# lead of team_name='team' (matching add_teammate's hardcoded team_name).
add_lead() {
  sqlite3 "$DB" "INSERT OR REPLACE INTO spawn_leads (team_name,session_id,spawned_at) VALUES ('team','$1',$NOW);" >/dev/null 2>&1
}
guard() { printf '{"hook_event_name":"Stop","session_id":"%s"}' "$1" | bash "$SCRIPT" 2>/dev/null; }

# ---------------------------------------------------------------------------
# 2. Live spawn session present but 0 idle → no block (yield is OK). Also the
#    #206 regression: there is NO mail channel in the DB, so an all-busy flock
#    can never be trapped by a phantom-unread — only idle state can trigger.
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_teammate "lane-a" "active"; add_lead "s2"
out=$(guard "s2")
if ! is_block "$out"; then pass "active-only (no mail channel): no block (#206)"; else fail "active-only: no block" "out=$out"; fi

# ---------------------------------------------------------------------------
# 3. Idle teammate + recorded lead → BLOCK. (#232: every actionable case
#    records the lead — the guard fires ONLY for the recorded spawn lead.)
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_teammate "lane-a" "idle"; add_lead "s3"
out=$(guard "s3")
if is_block "$out"; then pass "idle teammate (recorded lead): BLOCK"; else fail "idle teammate (recorded lead): BLOCK" "out=$out"; fi

# ---------------------------------------------------------------------------
# 4. No live teammates (all retired) → fast-path, no block.
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_teammate "lane-a" "retired"; add_lead "s4"
out=$(guard "s4")
if ! is_block "$out"; then pass "no live teammates: fast-path no block"; else fail "no live teammates" "out=$out"; fi

# ---------------------------------------------------------------------------
# 5. Runaway cap: idle teammate, same lead session → block, block, then fail OPEN.
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_teammate "lane-a" "idle"; add_lead "scap"
o1=$(guard "scap"); o2=$(guard "scap"); o3=$(guard "scap"); o4=$(guard "scap")
# block, block, then fail-open AND STAY open (o4 also yields) until state clears.
if is_block "$o1" && is_block "$o2" && ! is_block "$o3" && ! is_block "$o4"; then
  pass "runaway cap: block,block,fail-open,stay-open"
else
  fail "runaway cap" "o1=$(is_block "$o1" && echo B || echo -) o2=$(is_block "$o2" && echo B || echo -) o3=$(is_block "$o3" && echo B || echo -) o4=$(is_block "$o4" && echo B || echo -)"
fi

# 5b. After the cap trips, clearing the state re-arms the guard (next idle blocks).
total=$((total+1))
sqlite3 "$DB" "UPDATE teammates SET status='active' WHERE teammate_name='lane-a';" >/dev/null 2>&1
ocl=$(guard "scap")               # not actionable now → resets counter
sqlite3 "$DB" "UPDATE teammates SET status='idle' WHERE teammate_name='lane-a';" >/dev/null 2>&1
orearm=$(guard "scap")            # actionable again → blocks (re-armed)
if ! is_block "$ocl" && is_block "$orearm"; then
  pass "cap re-arms after state clears"
else
  fail "cap re-arms after state clears" "clear=$(is_block "$ocl" && echo B || echo -) rearm=$(is_block "$orearm" && echo B || echo -)"
fi

# ---------------------------------------------------------------------------
# 6. Config off → never blocks even with an idle teammate + recorded lead.
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_teammate "lane-a" "idle"; add_lead "s6"
printf '[spawn]\ncoordinate_drive_guard = "off"\n' > .claude/shepherd.toml
out=$(guard "s6")
if ! is_block "$out"; then pass "config off: no block"; else fail "config off: no block" "out=$out"; fi

# ---------------------------------------------------------------------------
# 7. Config warn → never blocks (stderr nudge only), even for the lead.
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_teammate "lane-a" "idle"; add_lead "s7"
printf '[spawn]\ncoordinate_drive_guard = "warn"\n' > .claude/shepherd.toml
out=$(printf '{"hook_event_name":"Stop","session_id":"s7"}' | bash "$SCRIPT" 2>/dev/null)
if ! is_block "$out"; then pass "config warn: no block"; else fail "config warn: no block" "out=$out"; fi
printf '' > .claude/shepherd.toml

# ---------------------------------------------------------------------------
# 8. (#197) Hook fires on a TEAMMATE's OWN session → must NEVER block. A teammate
#    (e.g. the self-contained engineer) must not run the root's drain loop, even
#    when it is itself idle. Detection mirrors teammate_git_guard.sh: session match.
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db
add_teammate "eng" "idle" "" "" "sess-eng"     # session_id = sess-eng
out=$(guard "sess-eng")
if ! is_block "$out"; then pass "#197 teammate session: no block (root-only gate)"; else fail "#197 teammate session: no block" "out=$out"; fi

# ---------------------------------------------------------------------------
# 9. (#195) A stale, undeclared row from a prior session (a ghost) is not a
#    live worker root can drain → no block, even for the recorded lead.
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_teammate "ghost" "idle" "" "$STALE" "old-sess"; add_lead "root-1"
out=$(guard "root-1")
if ! is_block "$out"; then pass "#195 stale ghost: no block"; else fail "#195 stale ghost: no block" "out=$out"; fi

# ---------------------------------------------------------------------------
# 10. A teammate that DECLARED complete (0019) is terminal, excluded from live
#     even when fresh → no block (finished lane, nothing to drain).
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_teammate "done" "active" "complete"; add_lead "root-2"
out=$(guard "root-2")
if ! is_block "$out"; then pass "declared complete: no block (excluded from live)"; else fail "declared complete: no block" "out=$out"; fi

# ---------------------------------------------------------------------------
# 11. A stale row that DECLARED in-progress is NOT a ghost — the declaration
#     keeps it live (never presumed-crashed), so an idle+in-progress teammate is
#     still drainable state root must coordinate → BLOCK. Also the #229 sweep
#     boundary: a REBOOT-old in-progress row is NEVER swept (status untouched).
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_teammate "busy" "idle" "in-progress" "$REBOOT" "tm-busy"; add_lead "root-3"
out=$(guard "root-3")
st_busy=$(sqlite3 "$DB" "SELECT status FROM teammates WHERE teammate_name='busy';" 2>/dev/null || echo '?')
if is_block "$out" && [[ "$st_busy" == "idle" ]]; then
  pass "declared in-progress (reboot-old): BLOCK, never swept (#229 boundary)"
else
  fail "declared in-progress (reboot-old): BLOCK, never swept" "out=${out:0:80} status=$st_busy"
fi

# ---------------------------------------------------------------------------
# 12. (#223) BYSTANDER-EXEMPT: a live idle teammate exists, but the recorded
#     spawn_leads lead for that team is a DIFFERENT session than the one
#     stopping. The stopping session is conclusively a bystander sharing this
#     repo's DB with someone else's spawn — must NEVER block.
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_teammate "lane-a" "idle"; add_lead "root-lead"
out=$(guard "root-bystander")
if ! is_block "$out"; then pass "#223 bystander (different recorded lead): no block"; else fail "#223 bystander: no block" "out=$out"; fi

# ---------------------------------------------------------------------------
# 13. (#223) LEAD-STILL-BLOCKS: a live idle teammate exists, and the recorded
#     spawn_leads lead for that team IS the session stopping. The drive-guard
#     contract still applies to its own lead → must still BLOCK.
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_teammate "lane-a" "idle"; add_lead "root-lead"
out=$(guard "root-lead")
if is_block "$out"; then pass "#223 recorded lead: STILL BLOCKS"; else fail "#223 recorded lead: STILL BLOCKS" "out=$out"; fi

# ---------------------------------------------------------------------------
# 14. (#232) NO LEAD RECORDED → no block. The pre-#232 fallback (nudge anyway
#     when no spawn_leads row exists) is retired: an unresolvable identity is
#     never nudged — register-lead is mandatory at spawn (commands/spawn.md).
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_teammate "lane-a" "idle"
out=$(guard "root-nolead")
if ! is_block "$out"; then pass "#232 no lead recorded: no block (positive identity only)"; else fail "#232 no lead recorded: no block" "out=$out"; fi

# ---------------------------------------------------------------------------
# 15. (#232/#228) TEAMMATE MARKER = fail-CLOSED: even the recorded lead session
#     is never nudged while a session-tier marker exists for it (an unregistered
#     teammate whose boot prompt user_prompt_submit.sh stamped). Marker removed
#     → the same state blocks again (control). The marker is created by the REAL
#     stamper: user_prompt_submit.sh fed a rendered boot prompt.
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_teammate "lane-a" "idle"; add_lead "root-m"
BOOT_PROMPT='You are a spawned teammate-conductor.\n  Lane plan (YOURS):    .shepherd/runs/v100-dev0/lanes/lane-a/plan.md\nROOT-SESSION-NAME: shepherd-root @ abc\nINVOCATION-CONTEXT:\n  dispatcher: teammate-conductor\n  spawn_session: team-1\n'
printf '{"session_id":"root-m","hook_event_name":"UserPromptSubmit","prompt":"%s"}' "$BOOT_PROMPT" \
  | bash "$HOOKS_DIR/user_prompt_submit.sh" >/dev/null 2>&1 || true
MARKER=".artifacts/tmp/session-tier-root-m"
out_marked=$(guard "root-m")
rm -f "$MARKER" 2>/dev/null || true
out_unmarked=$(guard "root-m")
if ! is_block "$out_marked" && is_block "$out_unmarked"; then
  pass "#232/#228 tier marker: fail-closed while marked, re-arms when removed"
else
  fail "#232/#228 tier marker" "marked=$(is_block "$out_marked" && echo B || echo -) unmarked=$(is_block "$out_unmarked" && echo B || echo -) marker_existed=$([[ -f $MARKER ]] && echo 1 || echo 0)"
fi

# 15b. The stamper wrote the marker with the dispatcher + lane_plan fields.
total=$((total+1)); reset_db
printf '{"session_id":"root-m2","hook_event_name":"UserPromptSubmit","prompt":"%s"}' "$BOOT_PROMPT" \
  | bash "$HOOKS_DIR/user_prompt_submit.sh" >/dev/null 2>&1 || true
M2=".artifacts/tmp/session-tier-root-m2"
if [[ -f "$M2" ]] && grep -q 'teammate-conductor' "$M2" && grep -q 'runs/v100-dev0/lanes/lane-a/plan.md' "$M2"; then
  pass "#232 stamper: marker carries dispatcher + lane_plan"
else
  fail "#232 stamper: marker carries dispatcher + lane_plan" "content=$(cat "$M2" 2>/dev/null || echo MISSING)"
fi
# 15c. A plain operator prompt never stamps.
total=$((total+1)); rm -f .artifacts/tmp/session-tier-root-m3 2>/dev/null || true
printf '{"session_id":"root-m3","hook_event_name":"UserPromptSubmit","prompt":"please discuss the dispatcher: teammate-conductor concept"}' \
  | bash "$HOOKS_DIR/user_prompt_submit.sh" >/dev/null 2>&1 || true
if [[ ! -f ".artifacts/tmp/session-tier-root-m3" ]]; then
  pass "#232 stamper: plain prompt (no INVOCATION-CONTEXT block) never stamps"
else
  fail "#232 stamper: plain prompt never stamps" "marker unexpectedly created"
fi

# ---------------------------------------------------------------------------
# 16. (#229) REBOOT STALE-SWEEP: a declared-error row from ANOTHER session,
#     unseen for 2 h, previously stayed in v_teammates_live FOREVER (the
#     declaration overrides the freshness window) and trapped every later lead
#     in phantom nudges. The sweep marks it crashed → LIVE=0 → no block.
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db
add_teammate "zombie" "idle" "error" "$REBOOT" "dead-sess"; add_lead "root-s"
out=$(guard "root-s")
st_zombie=$(sqlite3 "$DB" "SELECT status FROM teammates WHERE teammate_name='zombie';" 2>/dev/null || echo '?')
if ! is_block "$out" && [[ "$st_zombie" == "crashed" ]]; then
  pass "#229 sweep: reboot-old declared-error ghost swept to crashed, no block"
else
  fail "#229 sweep: ghost swept" "out=${out:0:80} status=$st_zombie"
fi

# 16b. The sweep NEVER touches the current session's own rows (scope: other
#      sessions only) — an own-session row is the #197 exemption's business.
total=$((total+1)); reset_db
add_teammate "mine" "idle" "error" "$REBOOT" "self-sess"
out=$(guard "self-sess")   # own row → #197 self-teammate exit, sweep never ran on it
st_mine=$(sqlite3 "$DB" "SELECT status FROM teammates WHERE teammate_name='mine';" 2>/dev/null || echo '?')
if ! is_block "$out" && [[ "$st_mine" == "idle" ]]; then
  pass "#229 sweep: own-session row untouched (#197 exit precedes sweep)"
else
  fail "#229 sweep: own-session row untouched" "out=${out:0:80} status=$st_mine"
fi

echo "—— $((total-fails))/$total passed ——"
exit "$fails"
