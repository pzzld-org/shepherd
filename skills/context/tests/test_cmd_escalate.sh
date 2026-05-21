#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
TMPDIR_T="$(mktemp -d -t shepherd-test-escalate.XXXXXX)"
trap "rm -rf $TMPDIR_T" EXIT
export SHCTX_DB="$TMPDIR_T/root.db"
for f in "$ROOT/skills/context/schema/0001_init.sql" \
         "$ROOT/skills/context/schema/migrations/"*.sql \
         "$ROOT/skills/context/schema/0007_canonical_state.sql"; do
  sqlite3 "$SHCTX_DB" < "$f"
done
sqlite3 "$SHCTX_DB" "INSERT INTO projects (id, name, created_at, updated_at) VALUES ('p', 't', 1, 1);"

CMD="bash $ROOT/skills/context/scripts/cmd_escalate.sh"

id=$($CMD --role=engineer --question='serde rotation needs operator call' --blocking)
[[ -n "$id" ]] || { echo "FAIL: escalate create returned no id"; exit 1; }

$CMD list --open-only | grep -c "engineer" >/dev/null || { echo "FAIL: list --open-only missing role"; exit 1; }

$CMD resolve $id --reply='use serde 1.0.220'
resolved=$(sqlite3 "$SHCTX_DB" "SELECT resolved_at FROM escalations WHERE id=$id;")
[[ -n "$resolved" && "$resolved" != "" ]] || { echo "FAIL: resolved_at not set"; exit 1; }

echo "PASS: test_cmd_escalate"
