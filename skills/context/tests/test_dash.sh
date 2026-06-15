#!/usr/bin/env bash
# shctx dash — one-glance sprint dashboard composition (v6.1.5 #13).
# Verifies: runs on a fresh DB, renders every section, degrades on empty state,
# and surfaces a seeded focus objective + active loop.
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init >/dev/null
"$SHCTX" migrate >/dev/null

db="$SHCTX_TEST_TMP/.shepherd/shepherd.db"
branch="$(git rev-parse --abbrev-ref HEAD)"

# ---- empty-state: all sections present, graceful degrade --------------------
out="$("$SHCTX" dash)"
for section in "SHEPHERD DASH" "SPRINT" "GRAPH" "TEAMMATES" "MAILBOX" "ESCALATION" "LOOPS" "STALE"; do
  assert_contains "dash.$section" "$out" "$section"
done
assert_contains "dash.no-graph"   "$out" "no stage-graph state"
assert_contains "dash.no-team"    "$out" "none live"
assert_contains "dash.mail-clear" "$out" "all read"
assert_contains "dash.no-esc"     "$out" "none open"
assert_contains "dash.no-loop"    "$out" "none active"

# ---- seeded focus objective surfaces in the FOCUS line ----------------------
sqlite3 "$db" "INSERT INTO focus(sprint,objective,updated_at)
               VALUES('$branch','north-star-objective-token',$(date +%s));"
out="$("$SHCTX" dash)"
assert_contains "dash.focus" "$out" "north-star-objective-token"

# ---- seeded active loop surfaces with iteration progress --------------------
pid="$(sqlite3 "$db" 'SELECT id FROM projects LIMIT 1;')"
sqlite3 "$db" "INSERT INTO loops(id,project_id,kind,task,agent,max_iterations,until_field,status,created_at)
               VALUES('LOOP1','$pid','focus','t','orchestrator',8,'new_findings','active',$(date +%s));"
sqlite3 "$db" "INSERT INTO loop_iterations(loop_id,iteration,new_findings,summary,recorded_at)
               VALUES('LOOP1',3,1,'s',$(date +%s));"
out="$("$SHCTX" dash)"
assert_contains "dash.loop-active"   "$out" "active"
assert_contains "dash.loop-progress" "$out" "focus 3/8"

# ---- DB-less degrade --------------------------------------------------------
TMP2="$(mktemp -d)"; ( cd "$TMP2" && git init -q . \
  && out2="$("$SHCTX" dash)" \
  && grep -q "no registry DB" <<< "$out2" ) \
  || { echo "FAIL: dash did not degrade gracefully without a DB"; rm -rf "$TMP2"; exit 1; }
rm -rf "$TMP2"
