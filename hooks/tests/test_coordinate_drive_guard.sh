#!/usr/bin/env bash
# hooks/tests/test_coordinate_drive_guard.sh — tests for coordinate_drive_guard.sh
#
# Covers the Stop-hook backstop for skills/motivation/SKILL.md §Drive contract (v6.0.5):
#   • No-payload / no-DB → exit 0, no block (fast-path; never touches non-spawn work).
#   • Live spawn session + 0 idle → no block (yield is correct).
#   • Idle teammate → BLOCK (decision:block on stdout).
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
SQL

STALE=$(( NOW - 600000 ))   # 10 min ago — past the guard's 5-min live window
reset_db() { sqlite3 "$DB" "DELETE FROM teammates;" >/dev/null 2>&1; rm -f .artifacts/tmp/coordinate_drive_guard.*.count 2>/dev/null || true; }
# add_teammate <name> <status> [declared_state] [last_seen_ms] [session_id]
add_teammate() {
  local ds="NULL"; [[ -n "${3:-}" ]] && ds="'$3'"
  local seen="${4:-$NOW}"
  local sid="NULL"; [[ -n "${5:-}" ]] && sid="'$5'"
  sqlite3 "$DB" "INSERT INTO teammates (id,team_name,teammate_name,agent_type,session_id,spawned_at,last_seen_at,status,declared_state) VALUES ('$1','team','$1','conductor',$sid,$NOW,$seen,'$2',$ds);" >/dev/null 2>&1
}
guard() { printf '{"hook_event_name":"Stop","session_id":"%s"}' "$1" | bash "$SCRIPT" 2>/dev/null; }

# ---------------------------------------------------------------------------
# 2. Live spawn session present but 0 idle → no block (yield is OK). Also the
#    #206 regression: there is NO mail channel in the DB, so an all-busy flock
#    can never be trapped by a phantom-unread — only idle state can trigger.
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_teammate "lane-a" "active"
out=$(guard "s2")
if ! is_block "$out"; then pass "active-only (no mail channel): no block (#206)"; else fail "active-only: no block" "out=$out"; fi

# ---------------------------------------------------------------------------
# 3. Idle teammate → BLOCK.
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_teammate "lane-a" "idle"
out=$(guard "s3")
if is_block "$out"; then pass "idle teammate: BLOCK"; else fail "idle teammate: BLOCK" "out=$out"; fi

# ---------------------------------------------------------------------------
# 4. No live teammates (all retired) → fast-path, no block.
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_teammate "lane-a" "retired"
out=$(guard "s4")
if ! is_block "$out"; then pass "no live teammates: fast-path no block"; else fail "no live teammates" "out=$out"; fi

# ---------------------------------------------------------------------------
# 5. Runaway cap: idle teammate, same session → block, block, then fail OPEN.
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_teammate "lane-a" "idle"
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
# 6. Config off → never blocks even with an idle teammate.
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_teammate "lane-a" "idle"
printf '[spawn]\ncoordinate_drive_guard = "off"\n' > .claude/shepherd.toml
out=$(guard "s6")
if ! is_block "$out"; then pass "config off: no block"; else fail "config off: no block" "out=$out"; fi

# ---------------------------------------------------------------------------
# 7. Config warn → never blocks (stderr nudge only).
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_teammate "lane-a" "idle"
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
#    live worker root can drain → no block.
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_teammate "ghost" "idle" "" "$STALE" "old-sess"
out=$(guard "root-1")
if ! is_block "$out"; then pass "#195 stale ghost: no block"; else fail "#195 stale ghost: no block" "out=$out"; fi

# ---------------------------------------------------------------------------
# 10. A teammate that DECLARED complete (0019) is terminal, excluded from live
#     even when fresh → no block (finished lane, nothing to drain).
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_teammate "done" "active" "complete"
out=$(guard "root-2")
if ! is_block "$out"; then pass "declared complete: no block (excluded from live)"; else fail "declared complete: no block" "out=$out"; fi

# ---------------------------------------------------------------------------
# 11. A stale row that DECLARED in-progress is NOT a ghost — the declaration
#     keeps it live (never presumed-crashed), so an idle+in-progress teammate is
#     still drainable state root must coordinate → BLOCK.
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_teammate "busy" "idle" "in-progress" "$STALE" "tm-busy"
out=$(guard "root-3")
if is_block "$out"; then pass "declared in-progress (stale): BLOCK (not a ghost)"; else fail "declared in-progress (stale): BLOCK" "out=$out"; fi

echo "—— $((total-fails))/$total passed ——"
exit "$fails"
