#!/usr/bin/env bash
# hooks/tests/test_teammate_heartbeat.sh — tests for teammate_heartbeat.sh (v6.3.3 #193).
#
# The PreToolUse auto-heartbeat advances a REGISTERED teammate's last_seen_at (and
# flips booting → active) on every tool call, so liveness is trustworthy for roles
# that never call `shctx teammate heartbeat` (the self-contained @engineer). It is
# observational: it never blocks a tool, and fails open on any missing precondition.
#
# Covers: registered teammate advances + revives; non-teammate session is a no-op;
# terminal (retired/crashed) teammate untouched; missing DB fails open; [hooks].
# teammate_heartbeat=off disables it; an 'active' teammate keeps status active;
# v6.4.1 #229 liveness scoping — the stamp is refused for rows whose team is
# not the CURRENT session's (newest-registration) team, so a prior team's row
# carrying the same session_id can never be kept artificially "alive".
# Conventions mirror hooks/tests/test_coordinate_drive_guard.sh.

set -eu -o pipefail
cd "$(dirname "$0")"
SCRIPT="$(cd .. && pwd)/scripts/teammate_heartbeat.sh"

fails=0; total=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s — %s\n' "$1" "$2"; fails=$((fails+1)); }
skip() { printf '  SKIP  %s — %s\n' "$1" "$2"; }

# no-payload invocation is a clean exit 0
total=$((total+1))
if : | bash "$SCRIPT" >/dev/null 2>&1; then pass "no-payload: exit 0"; else fail "no-payload: exit 0" "non-zero"; fi

if ! command -v sqlite3 >/dev/null 2>&1; then
  skip "DB-dependent cases" "sqlite3 missing"; echo "—— $((total-fails))/$total passed ——"; exit "$fails"
fi

tmp=$(mktemp -d -t shep-hb-test.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q .; git config user.email t@t; git config user.name t
git -c commit.gpgsign=false commit -q --allow-empty -m init
mkdir -p .claude .shepherd
touch .claude/shepherd.toml
DB=".shepherd/shepherd.db"
NOW=$(( $(date +%s) * 1000 ))
OLD=$(( NOW - 600000 ))   # 10 min ago

sqlite3 "$DB" <<SQL >/dev/null 2>&1
CREATE TABLE teammates (
  id TEXT PRIMARY KEY, team_name TEXT, teammate_name TEXT, agent_type TEXT,
  session_id TEXT, tmux_pane_id TEXT, spawned_at INTEGER, last_seen_at INTEGER, status TEXT
);
SQL

reset_row() { # reset_row <status> <session_id>
  sqlite3 "$DB" "DELETE FROM teammates;
    INSERT INTO teammates (id,team_name,teammate_name,agent_type,session_id,spawned_at,last_seen_at,status)
    VALUES ('t1','team','eng-1','engineer','$2',$OLD,$OLD,'$1');" >/dev/null 2>&1
}
seen()   { sqlite3 "$DB" "SELECT last_seen_at FROM teammates WHERE id='t1';" 2>/dev/null || echo 0; }
status() { sqlite3 "$DB" "SELECT status FROM teammates WHERE id='t1';" 2>/dev/null || echo '?'; }
fire()   { printf '{"hook_event_name":"PreToolUse","session_id":"%s","tool_name":"Bash","tool_input":{"command":"ls"}}' "$1" | bash "$SCRIPT" >/dev/null 2>&1; }

# 1. Registered teammate: last_seen_at advances past OLD + status booting → active.
total=$((total+1)); reset_row booting S1; fire S1
if [[ "$(seen)" -gt "$OLD" && "$(status)" == "active" ]]; then pass "registered teammate: last_seen advanced + revived to active"
else fail "registered teammate advance/revive" "seen=$(seen) OLD=$OLD status=$(status)"; fi

# 2. Non-teammate session: teammate row is untouched (no-op).
total=$((total+1)); reset_row booting S1; fire SOMEONE-ELSE
if [[ "$(seen)" == "$OLD" && "$(status)" == "booting" ]]; then pass "non-teammate session: no-op"
else fail "non-teammate session: no-op" "seen=$(seen) status=$(status)"; fi

# 3. Terminal (retired) teammate: untouched even on its own session.
total=$((total+1)); reset_row retired S1; fire S1
if [[ "$(seen)" == "$OLD" && "$(status)" == "retired" ]]; then pass "retired teammate: untouched"
else fail "retired teammate: untouched" "seen=$(seen) status=$(status)"; fi

# 4. 'active' teammate stays active (status not churned) but last_seen advances.
total=$((total+1)); reset_row active S1; fire S1
if [[ "$(seen)" -gt "$OLD" && "$(status)" == "active" ]]; then pass "active teammate: advanced, stays active"
else fail "active teammate advance" "seen=$(seen) status=$(status)"; fi

# 5. Toggle off → no-op.
total=$((total+1)); reset_row booting S1
printf '[hooks]\nteammate_heartbeat = off\n' > .claude/shepherd.toml
fire S1
if [[ "$(seen)" == "$OLD" && "$(status)" == "booting" ]]; then pass "[hooks].teammate_heartbeat=off: no-op"
else fail "toggle off: no-op" "seen=$(seen) status=$(status)"; fi
printf '' > .claude/shepherd.toml  # restore: CLEAR the off-toggle (touch alone left it set — empty toml still flags a shepherd project)

# 6. (#229) Same session_id registered in TWO teams: only the row in the
#    session's CURRENT team (the newest registration) is stamped; the prior
#    team's row is REFUSED — left frozen so that team's liveness/drive counts
#    never read a dead lane as alive. (It ages out via the #229 reboot sweep.)
total=$((total+1))
sqlite3 "$DB" "DELETE FROM teammates;
  INSERT INTO teammates (id,team_name,teammate_name,agent_type,session_id,spawned_at,last_seen_at,status)
  VALUES ('t-old','team-old','eng-1','engineer','S1',$OLD,$OLD,'active'),
         ('t-new','team-new','eng-1','engineer','S1',$(( OLD + 1000 )),$OLD,'active');" >/dev/null 2>&1
fire S1
SEEN_OLD=$(sqlite3 "$DB" "SELECT last_seen_at FROM teammates WHERE id='t-old';" 2>/dev/null || echo 0)
SEEN_NEW=$(sqlite3 "$DB" "SELECT last_seen_at FROM teammates WHERE id='t-new';" 2>/dev/null || echo 0)
if [[ "$SEEN_NEW" -gt "$OLD" && "$SEEN_OLD" == "$OLD" ]]; then
  pass "#229 team scoping: current team stamped, prior team's row refused"
else
  fail "#229 team scoping" "old=$SEEN_OLD new=$SEEN_NEW OLD=$OLD"
fi

# 7. Missing DB → fail open (exit 0, no crash).
total=$((total+1)); rm -f "$DB"
if fire S1; then pass "missing DB: fail-open exit 0"; else fail "missing DB: fail-open" "non-zero"; fi

echo "—— $((total-fails))/$total passed ——"
exit "$fails"
