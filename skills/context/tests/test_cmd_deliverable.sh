#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
TMPDIR_T="$(mktemp -d -t shepherd-test-deliverable.XXXXXX)"
trap "rm -rf $TMPDIR_T" EXIT
export SHCTX_DB="$TMPDIR_T/root.db"
for f in "$ROOT/skills/context/schema/0001_init.sql" \
         "$ROOT/skills/context/schema/migrations/"*.sql \
         "$ROOT/skills/context/schema/0007_canonical_state.sql"; do
  sqlite3 "$SHCTX_DB" < "$f"
done
sqlite3 "$SHCTX_DB" "INSERT INTO projects (id, name, created_at, updated_at) VALUES ('p', 't', 1, 1);"
CMD="bash $ROOT/skills/context/scripts/cmd_deliverable.sh"

id=$(CLAUDE_AGENT_ROLE=critic CLAUDE_SESSION_ID=sess1 $CMD promise --kind=row --target='audit_findings:code-quality')
[[ -n "$id" ]] || { echo "FAIL: promise returned no id"; exit 1; }

st=$(sqlite3 "$SHCTX_DB" "SELECT status FROM deliverables WHERE id=$id;")
[[ "$st" == "pending" ]] || { echo "FAIL: status not pending"; exit 1; }

$CMD complete $id
st=$(sqlite3 "$SHCTX_DB" "SELECT status FROM deliverables WHERE id=$id;")
[[ "$st" == "delivered" ]] || { echo "FAIL: status not delivered"; exit 1; }

echo "PASS: test_cmd_deliverable"
