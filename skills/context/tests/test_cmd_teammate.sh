#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"

TMPDIR_T="$(mktemp -d -t shepherd-test-teammate.XXXXXX)"
trap "rm -rf $TMPDIR_T" EXIT
export SHCTX_DB="$TMPDIR_T/shepherd.db"

# Bootstrap schema
for f in "$ROOT/skills/context/schema/0001_init.sql" \
         "$ROOT/skills/context/schema/migrations/"*.sql \
         "$ROOT/skills/context/schema/migrations/0007_canonical_state.sql"; do
  sqlite3 "$SHCTX_DB" < "$f"
done
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

echo "PASS: test_cmd_teammate"
