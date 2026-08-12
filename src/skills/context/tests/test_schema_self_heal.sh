#!/usr/bin/env bash
# test_schema_self_heal.sh — v6.3.3 #200 regression.
#
# A DB left BEHIND the shipped schema (an older plugin, or a half-applied migrate)
# must NOT crash `shctx teammate liveness` / `shctx panes` with
# "no such column: declared_state". Two guarantees:
#   A. Stateful commands SELF-HEAL: shctx_ensure_migrated brings the DB to HEAD
#      before the query, so the missing column is created on demand.
#   B. If healing is IMPOSSIBLE (migrations unreachable — read-only/locked/missing),
#      the command DEGRADES to the timing-only verdict instead of crashing.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
SCHEMA="$ROOT/skills/context/schema"
TEAMMATE="$ROOT/skills/context/scripts/cmd_teammate.sh"

TMP="$(mktemp -d -t shepherd-selfheal.XXXXXX)"
trap "rm -rf $TMP" EXIT
fails=0
now_ms=$(( $(date +%s) * 1000 ))

# Build a DB at "version 18" — every migration below 0019 applied AND recorded in
# schema_versions, but 0019 (declared_state) absent. This is exactly an older-plugin
# DB: the teammates table exists, declared_state does not.
build_behind_db() {
  local db="$1"
  sqlite3 "$db" < "$SCHEMA/0001_init.sql"
  local f v
  for f in "$SCHEMA/migrations/"*.sql; do
    v=$(basename "$f" | grep -oE '^[0-9]+'); v=$((10#$v))
    [[ "$v" -ge 19 ]] && continue          # simulate a plugin that predates 0019
    sqlite3 "$db" < "$f"
    sqlite3 "$db" "INSERT INTO schema_versions(version,applied_at,checksum) VALUES($v,$(date +%s),'seed');"
  done
  sqlite3 "$db" "INSERT INTO projects(id,name,created_at,updated_at) VALUES('p','proj',$(date +%s),$(date +%s));"
}
has_declared() { [[ -n "$(sqlite3 "$1" "SELECT 1 FROM pragma_table_info('teammates') WHERE name='declared_state' LIMIT 1;" 2>/dev/null)" ]]; }

# ── Case A: liveness SELF-HEALS a behind DB ────────────────────────────────────
DB="$TMP/behind.db"; export SHCTX_DB="$DB"
build_behind_db "$DB"

# precondition: the crash condition is real — declared_state absent, raw query errors.
has_declared "$DB" && { echo "FAIL: precondition — declared_state should be ABSENT on the behind DB"; fails=$((fails+1)); }
if sqlite3 "$DB" "SELECT declared_state FROM teammates LIMIT 1;" >/dev/null 2>&1; then
  echo "FAIL: precondition — a raw declared_state query should error on the behind DB"; fails=$((fails+1))
fi

sqlite3 "$DB" "INSERT INTO teammates(id,project_id,team_name,teammate_name,agent_type,spawned_at,last_seen_at,status)
               VALUES('t1','p','team-a','eng-1','engineer',$now_ms,$now_ms,'active');"

out="$("$TEAMMATE" liveness 2>"$TMP/a.err")" || { echo "FAIL: liveness exited non-zero on behind DB"; cat "$TMP/a.err"; fails=$((fails+1)); }
echo "$out" | grep -q "eng-1" || { echo "FAIL: liveness did not list eng-1 after self-heal"; fails=$((fails+1)); }
has_declared "$DB" || { echo "FAIL: declared_state still absent after liveness self-heal"; fails=$((fails+1)); }
mx=$(sqlite3 "$DB" "SELECT MAX(version) FROM schema_versions;")
[[ "${mx:-0}" -ge 19 ]] || { echo "FAIL: schema_versions max=$mx (<19) after self-heal"; fails=$((fails+1)); }

# a declared row on the healed DB reads through the verdict logic (#193 parity)
sqlite3 "$DB" "UPDATE teammates SET declared_state='in-progress', last_seen_at=$(( now_ms - 600000 )) WHERE id='t1';"
"$TEAMMATE" liveness | grep eng-1 | grep -q 'ok' || { echo "FAIL: declared in-progress on a stale row should read ok"; fails=$((fails+1)); }

# ── Case B: healing IMPOSSIBLE → degrade, never crash ──────────────────────────
DB2="$TMP/behind2.db"; export SHCTX_DB="$DB2"
build_behind_db "$DB2"
sqlite3 "$DB2" "INSERT INTO teammates(id,project_id,team_name,teammate_name,agent_type,spawned_at,last_seen_at,status)
                VALUES('t2','p','team-a','eng-2','engineer',$now_ms,$now_ms,'active');"
# Point the skill root at a dir with no migrations → ensure_migrated can't heal.
EMPTY="$TMP/noskill"; mkdir -p "$EMPTY"
out2="$(SHCTX_SKILL_ROOT="$EMPTY" "$TEAMMATE" liveness 2>"$TMP/b.err")" \
  || { echo "FAIL: liveness crashed when healing impossible (should degrade)"; cat "$TMP/b.err"; fails=$((fails+1)); }
echo "$out2" | grep -q "eng-2" || { echo "FAIL: degraded liveness did not list eng-2"; fails=$((fails+1)); }
has_declared "$DB2" && { echo "FAIL: Case B unexpectedly healed (skill root was empty)"; fails=$((fails+1)); }

if [[ "$fails" -gt 0 ]]; then echo "FAIL: test_schema_self_heal ($fails failure(s))"; exit 1; fi
echo "PASS: test_schema_self_heal"
