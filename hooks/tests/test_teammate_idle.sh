#!/usr/bin/env bash
# hooks/tests/test_teammate_idle.sh — tests for teammate_idle.sh (v6.3.0, #183).
#
# The TeammateIdle hook runs in the LEAD's context when a teammate idles. It
# must flip the teammate's status to 'idle' in the canonical store by NAME
# (the key named-Agent teammates register under — not the teammate's own
# session id), reading the name from whichever identity field the payload
# carries, and it must NOT flood the lead with "no row matched" noise when no
# spawn is actually live (the #183 flood that masked real stalls).
#
#   1. registered name (teammate_name) idles      → status flips to 'idle', silent
#   2. registered name via .agent_id field        → status flips to 'idle'
#   3. unregistered name, OTHER live teammates     → warns "no teammates row matched"
#   4. unregistered name, NO live teammates        → SILENT (no flood)
#   5. crashed/retired teammate idles              → not flipped, silent (terminal)
#   6. empty payload                               → exit 0, silent
#   7. session_id fallback (no name in payload)    → flips by session_id

set -uo pipefail
cd "$(dirname "$0")"
SCRIPT="$(cd .. && pwd)/scripts/teammate_idle.sh"

fails=0; total=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s — %s\n' "$1" "$2"; fails=$((fails+1)); }

if ! command -v sqlite3 >/dev/null 2>&1; then
  printf '  SKIP  all cases — sqlite3 binary missing\n'; exit 0
fi
if ! command -v jq >/dev/null 2>&1 && ! command -v python3 >/dev/null 2>&1; then
  printf '  SKIP  all cases — neither jq nor python3 for payload parse\n'; exit 0
fi

tmp=$(mktemp -d -t shep-idle.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q .; git config user.email t@t; git config user.name t
git -c commit.gpgsign=false commit -q --allow-empty -m init
mkdir -p .claude .shepherd; touch .claude/shepherd.toml
DB=".shepherd/shepherd.db"
export SHCTX_DB="$PWD/$DB"

# Minimal canonical tables (schema-independent — avoids the full migration chain).
sqlite3 "$DB" "CREATE TABLE teammates (id TEXT PRIMARY KEY, project_id TEXT, team_name TEXT, teammate_name TEXT, agent_type TEXT, session_id TEXT, tmux_pane_id TEXT, spawned_at INTEGER, last_seen_at INTEGER, status TEXT, UNIQUE(project_id,team_name,teammate_name));"
sqlite3 "$DB" "CREATE TABLE heartbeats (teammate_id TEXT, ts INTEGER, phase TEXT, tool_name TEXT, note TEXT);"
NOW=$(( $(date +%s) * 1000 ))
ins() { # ins <id> <name> <session> <status>
  sqlite3 "$DB" "INSERT INTO teammates (id,project_id,team_name,teammate_name,agent_type,session_id,spawned_at,last_seen_at,status) VALUES ('$1','p','team','$2','conductor',$([[ -n "$3" ]] && echo "'$3'" || echo NULL),$NOW,$NOW,'$4');"
}
status_of() { sqlite3 "$DB" "SELECT status FROM teammates WHERE teammate_name='$1';"; }
run_err() { printf '%s' "$1" | bash "$SCRIPT" 2>&1 >/dev/null; }  # capture stderr only

# --- 1. registered name idles → flips, silent ----------------------------
total=$((total+1)); ins t1 lane-a sess-a active
err=$(run_err '{"hook_event_name":"TeammateIdle","teammate_name":"lane-a","session_id":"sess-a"}')
st=$(status_of lane-a)
if [[ "$st" == "idle" ]] && ! printf '%s' "$err" | grep -q "no teammates row matched"; then
  pass "registered name idles → flips to idle, silent"
else fail "registered name idles" "status=$st err=${err:0:80}"; fi

# --- 2. registered name via .agent_id field → flips ----------------------
total=$((total+1)); ins t2 lane-b '' active
run_err '{"hook_event_name":"TeammateIdle","agent_id":"lane-b"}' >/dev/null
st=$(status_of lane-b)
[[ "$st" == "idle" ]] && pass "name via .agent_id → flips to idle" || fail "agent_id field" "status=$st"

# --- 3. unregistered name, OTHER live teammates → warns ------------------
total=$((total+1))   # lane-a/lane-b are live → table non-empty
err=$(run_err '{"hook_event_name":"TeammateIdle","teammate_name":"ghost","session_id":"nope"}')
if printf '%s' "$err" | grep -q "no teammates row matched"; then
  pass "unregistered name + live teammates → warns"
else fail "unregistered+live warns" "err=${err:0:80}"; fi

# --- 4. unregistered name, NO live teammates → SILENT (no flood) ---------
total=$((total+1))
db2=".shepherd/empty.db"; export SHCTX_DB="$PWD/$db2"
sqlite3 "$db2" "CREATE TABLE teammates (id TEXT PRIMARY KEY, project_id TEXT, team_name TEXT, teammate_name TEXT, agent_type TEXT, session_id TEXT, tmux_pane_id TEXT, spawned_at INTEGER, last_seen_at INTEGER, status TEXT, UNIQUE(project_id,team_name,teammate_name));"
sqlite3 "$db2" "CREATE TABLE heartbeats (teammate_id TEXT, ts INTEGER, phase TEXT, tool_name TEXT, note TEXT);"
sqlite3 "$db2" "INSERT INTO teammates (id,project_id,team_name,teammate_name,agent_type,session_id,spawned_at,last_seen_at,status) VALUES ('r','p','team','gone','conductor',NULL,$NOW,$NOW,'retired');"
# point resolve_namespace's DB at empty.db by making it the shepherd.db
cp "$db2" "$DB"; export SHCTX_DB="$PWD/$DB"
err=$(run_err '{"hook_event_name":"TeammateIdle","teammate_name":"ghost2"}')
if ! printf '%s' "$err" | grep -q "no teammates row matched"; then
  pass "unregistered name + no live teammates → silent (no flood)"
else fail "no-live silent" "unexpected warn: ${err:0:80}"; fi

# --- 5. crashed teammate idles → not flipped, silent --------------------
total=$((total+1))
# rebuild DB with a single crashed row
sqlite3 "$DB" "DELETE FROM teammates;"
sqlite3 "$DB" "INSERT INTO teammates (id,project_id,team_name,teammate_name,agent_type,session_id,spawned_at,last_seen_at,status) VALUES ('c','p','team','lane-x','conductor','sx',$NOW,$NOW,'crashed');"
err=$(run_err '{"hook_event_name":"TeammateIdle","teammate_name":"lane-x"}')
st=$(status_of lane-x)
if [[ "$st" == "crashed" ]] && ! printf '%s' "$err" | grep -q "no teammates row matched"; then
  pass "crashed teammate → not flipped, silent"
else fail "crashed not flipped" "status=$st err=${err:0:80}"; fi

# --- 6. empty payload → exit 0, silent ----------------------------------
total=$((total+1))
if printf '' | bash "$SCRIPT" >/dev/null 2>&1; then pass "empty payload → exit 0"; else fail "empty payload" "non-zero exit"; fi

# --- 7. session_id fallback (no name field) → flips by session ----------
total=$((total+1))
sqlite3 "$DB" "DELETE FROM teammates;"
sqlite3 "$DB" "INSERT INTO teammates (id,project_id,team_name,teammate_name,agent_type,session_id,spawned_at,last_seen_at,status) VALUES ('s','p','team','lane-s','conductor','sess-77',$NOW,$NOW,'active');"
run_err '{"hook_event_name":"TeammateIdle","session_id":"sess-77"}' >/dev/null
st=$(status_of lane-s)
[[ "$st" == "idle" ]] && pass "session_id fallback → flips to idle" || fail "session fallback" "status=$st"

echo "—— $((total-fails))/$total passed ——"
exit "$fails"
