#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"

TMPDIR_T="$(mktemp -d -t shepherd-test-teammate.XXXXXX)"
trap "rm -rf $TMPDIR_T" EXIT
export SHCTX_DB="$TMPDIR_T/shepherd.db"

# Bootstrap schema the way the real system does — seed 0001 then run the
# version-gated migrate so schema_versions is ACCURATE. v6.3.3 #200: liveness now
# self-heals a behind DB; an accurate schema_versions means that self-heal is a
# no-op here (not a needless re-apply of migration DDL). shctx resolves the
# migrations dir from its own location; SHCTX_DB (honored by shctx_db_path) targets
# this temp DB.
sqlite3 "$SHCTX_DB" < "$ROOT/skills/context/schema/0001_init.sql"
SHCTX_DB="$SHCTX_DB" bash "$ROOT/skills/context/scripts/shctx" migrate >/dev/null
sqlite3 "$SHCTX_DB" "INSERT INTO projects (id, name, created_at, updated_at) VALUES ('test-proj', 'test', $(date +%s)000, $(date +%s)000);"

CMD="bash $ROOT/skills/context/scripts/cmd_teammate.sh"

# register
id=$($CMD register conductor-test --team=team-a --type=conductor --pane='%5')
[[ -n "$id" ]] || { echo "FAIL: register returned empty id"; exit 1; }

# heartbeat moves status booting → active
$CMD heartbeat conductor-test --phase=wave-1 --tool=Read
status=$(sqlite3 "$SHCTX_DB" "SELECT status FROM teammates WHERE id='$id';")
[[ "$status" == "active" ]] || { echo "FAIL: status after heartbeat: $status"; exit 1; }

# heartbeat row inserted
hb=$(sqlite3 "$SHCTX_DB" "SELECT count(*) FROM heartbeats WHERE teammate_id='$id';")
[[ "$hb" == "1" ]] || { echo "FAIL: heartbeat row count: $hb"; exit 1; }

# #234 regression: a --note / --phase carrying an apostrophe must persist, not
# break the SQL (the heartbeat path interpolated user text unescaped, so a
# conductor's engagement note like "lane-config's plan" threw unrecognized token).
$CMD heartbeat conductor-test --phase="wave's-2" --note="reconciling lane-config's plan steps"
note234=$(sqlite3 "$SHCTX_DB" "SELECT note FROM heartbeats WHERE teammate_id='$id' ORDER BY rowid DESC LIMIT 1;")
[[ "$note234" == "reconciling lane-config's plan steps" ]] || { echo "FAIL: #234 apostrophe note not persisted: [$note234]"; exit 1; }

# liveness shows table
$CMD liveness --stale-mins=10 | grep -c "conductor-test" >/dev/null || { echo "FAIL: liveness missing conductor-test"; exit 1; }

# status returns JSON
$CMD status conductor-test | grep -c '"teammate_name":"conductor-test"' >/dev/null || { echo "FAIL: status JSON shape"; exit 1; }

# retire sets status
$CMD retire conductor-test
status=$(sqlite3 "$SHCTX_DB" "SELECT status FROM teammates WHERE id='$id';")
[[ "$status" == "retired" ]] || { echo "FAIL: status after retire: $status"; exit 1; }

# prune --confirm --name removes
$CMD prune --confirm --name=conductor-test | grep -c "pruned 1" >/dev/null || { echo "FAIL: prune output"; exit 1; }
remaining=$(sqlite3 "$SHCTX_DB" "SELECT count(*) FROM teammates;")
[[ "$remaining" == "0" ]] || { echo "FAIL: rows remain: $remaining"; exit 1; }

# prune refuses without --confirm
if $CMD prune --crashed 2>/dev/null; then
  echo "FAIL: prune ran without --confirm"; exit 1
fi

# ---------------------------------------------------------------------------
# declared_state (0019, #193/#194/#195/#98): explicit progress declaration and
# its effect on the liveness verdict + prune --crashed. Registry now empty.
# ---------------------------------------------------------------------------
id2=$($CMD register eng-decl --team=team-b --type=engineer --session=sess-eng)
[[ -n "$id2" ]] || { echo "FAIL: register eng-decl returned empty id"; exit 1; }

# state --set declares; bare `state <name>` reads it back
[[ "$($CMD state eng-decl --set=in-progress)" == "in-progress" ]] || { echo "FAIL: state --set/read"; exit 1; }
[[ "$(sqlite3 "$SHCTX_DB" "SELECT declared_state FROM teammates WHERE id='$id2';")" == "in-progress" ]] || { echo "FAIL: declared_state not persisted"; exit 1; }

# invalid state rejected (exit non-zero), stored value unchanged
if $CMD state eng-decl --set=bogus 2>/dev/null; then echo "FAIL: invalid state accepted"; exit 1; fi
[[ "$(sqlite3 "$SHCTX_DB" "SELECT declared_state FROM teammates WHERE id='$id2';")" == "in-progress" ]] || { echo "FAIL: invalid state mutated the value"; exit 1; }

# heartbeat --state declares in a single call
$CMD heartbeat eng-decl --state=idle
[[ "$(sqlite3 "$SHCTX_DB" "SELECT declared_state FROM teammates WHERE id='$id2';")" == "idle" ]] || { echo "FAIL: heartbeat --state did not declare"; exit 1; }

# liveness: an explicit in-progress on a STALE row reads 'ok', not presumed-crashed (#193)
$CMD state eng-decl --set=in-progress >/dev/null
sqlite3 "$SHCTX_DB" "UPDATE teammates SET last_seen_at=(strftime('%s','now')-600)*1000, status='active' WHERE id='$id2';"
$CMD liveness | grep eng-decl | grep -q 'ok' || { echo "FAIL: stale in-progress should read ok"; exit 1; }
if $CMD liveness | grep eng-decl | grep -q 'presumed-crashed'; then echo "FAIL: declared in-progress read presumed-crashed (#193)"; exit 1; fi

# clear the declaration → the same stale row now reads presumed-crashed (pre-0019 behavior)
sqlite3 "$SHCTX_DB" "UPDATE teammates SET declared_state=NULL WHERE id='$id2';"
$CMD liveness | grep eng-decl | grep -q 'presumed-crashed' || { echo "FAIL: undeclared stale row should read presumed-crashed"; exit 1; }

# prune --crashed matches that DERIVED verdict, not the never-written status='crashed' (#194)
p=$($CMD prune --confirm --crashed | grep -oE '[0-9]+' | head -1)
[[ "$p" == "1" ]] || { echo "FAIL: prune --crashed should match derived ghost, got: $p"; exit 1; }
[[ "$(sqlite3 "$SHCTX_DB" "SELECT count(*) FROM teammates;")" == "0" ]] || { echo "FAIL: crashed ghost not pruned"; exit 1; }

echo "PASS: test_cmd_teammate"
