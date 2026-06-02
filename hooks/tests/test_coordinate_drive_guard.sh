#!/usr/bin/env bash
# hooks/tests/test_coordinate_drive_guard.sh — tests for coordinate_drive_guard.sh
#
# Covers the Stop-hook backstop for doctrines/coordinate-active-drive.md (v6.0.6):
#   • No-payload / no-DB → exit 0, no block (fast-path; never touches non-spawn work).
#   • Live spawn session + 0 idle + 0 unread → no block (yield is correct).
#   • Idle teammate → BLOCK (decision:block on stdout).
#   • Active teammate + lead-bound unread → BLOCK.
#   • Runaway cap: blocks twice, then fails OPEN on the 3rd consecutive stop.
#   • [spawn].coordinate_drive_guard = off → never blocks.
#   • [spawn].coordinate_drive_guard = warn → never blocks (stderr only).
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
# Ephemeral shepherd-flagged repo + minimal canonical DB (teammates + mailbox +
# v_teammates_live), mirroring migration 0007. No FK to projects (standalone).
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
  agent_type TEXT, spawned_at INTEGER, last_seen_at INTEGER, status TEXT
);
CREATE TABLE mailbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT, recipient_name TEXT,
  read_at INTEGER, sent_at INTEGER
);
CREATE VIEW v_teammates_live AS
  SELECT t.*, (strftime('%s','now')*1000 - t.last_seen_at) AS ms_since_seen
  FROM teammates t WHERE t.status NOT IN ('crashed','retired');
SQL

reset_db() { sqlite3 "$DB" "DELETE FROM teammates; DELETE FROM mailbox;" >/dev/null 2>&1; rm -f .artifacts/tmp/coordinate_drive_guard.*.count 2>/dev/null || true; }
add_teammate() { sqlite3 "$DB" "INSERT INTO teammates (id,team_name,teammate_name,agent_type,spawned_at,last_seen_at,status) VALUES ('$1','team','$1','conductor',$NOW,$NOW,'$2');" >/dev/null 2>&1; }
add_unread()   { sqlite3 "$DB" "INSERT INTO mailbox (recipient_name,read_at,sent_at) VALUES ('$1',NULL,$NOW);" >/dev/null 2>&1; }
guard() { printf '{"hook_event_name":"Stop","session_id":"%s"}' "$1" | bash "$SCRIPT" 2>/dev/null; }

# ---------------------------------------------------------------------------
# 2. Live spawn session present but 0 idle + 0 unread → no block (yield is OK).
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_teammate "lane-a" "active"
out=$(guard "s2")
if ! is_block "$out"; then pass "active-only: no block (yield correct)"; else fail "active-only: no block" "out=$out"; fi

# ---------------------------------------------------------------------------
# 3. Idle teammate → BLOCK.
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_teammate "lane-a" "idle"
out=$(guard "s3")
if is_block "$out"; then pass "idle teammate: BLOCK"; else fail "idle teammate: BLOCK" "out=$out"; fi

# ---------------------------------------------------------------------------
# 4. Active teammate + lead-bound unread mail → BLOCK.
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_teammate "lane-a" "active"; add_unread "root"
out=$(guard "s4")
if is_block "$out"; then pass "lead-bound unread: BLOCK"; else fail "lead-bound unread: BLOCK" "out=$out"; fi

# ---------------------------------------------------------------------------
# 4b. Unread addressed to a TEAMMATE (not the lead) → no block (not root's).
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_teammate "lane-a" "active"; add_unread "lane-a"
out=$(guard "s4b")
if ! is_block "$out"; then pass "teammate-bound unread: no block"; else fail "teammate-bound unread: no block" "out=$out"; fi

# ---------------------------------------------------------------------------
# 5. No live teammates (all retired) → fast-path, no block.
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_teammate "lane-a" "retired"
out=$(guard "s5")
if ! is_block "$out"; then pass "no live teammates: fast-path no block"; else fail "no live teammates" "out=$out"; fi

# ---------------------------------------------------------------------------
# 6. Runaway cap: idle teammate, same session → block, block, then fail OPEN.
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_teammate "lane-a" "idle"
o1=$(guard "scap"); o2=$(guard "scap"); o3=$(guard "scap"); o4=$(guard "scap")
# block, block, then fail-open AND STAY open (o4 also yields) until state clears.
if is_block "$o1" && is_block "$o2" && ! is_block "$o3" && ! is_block "$o4"; then
  pass "runaway cap: block,block,fail-open,stay-open"
else
  fail "runaway cap" "o1=$(is_block "$o1" && echo B || echo -) o2=$(is_block "$o2" && echo B || echo -) o3=$(is_block "$o3" && echo B || echo -) o4=$(is_block "$o4" && echo B || echo -)"
fi

# 6b. After the cap trips, clearing the state re-arms the guard (next idle blocks).
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
# 7. Config off → never blocks even with an idle teammate.
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_teammate "lane-a" "idle"
printf '[spawn]\ncoordinate_drive_guard = "off"\n' > .claude/shepherd.toml
out=$(guard "s7")
if ! is_block "$out"; then pass "config off: no block"; else fail "config off: no block" "out=$out"; fi

# ---------------------------------------------------------------------------
# 8. Config warn → never blocks (stderr nudge only).
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_teammate "lane-a" "idle"
printf '[spawn]\ncoordinate_drive_guard = "warn"\n' > .claude/shepherd.toml
out=$(printf '{"hook_event_name":"Stop","session_id":"s8"}' | bash "$SCRIPT" 2>/dev/null)
if ! is_block "$out"; then pass "config warn: no block"; else fail "config warn: no block" "out=$out"; fi
printf '' > .claude/shepherd.toml

echo "—— $((total-fails))/$total passed ——"
exit "$fails"
