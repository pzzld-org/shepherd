#!/usr/bin/env bash
# Test: 0007 migration applies clean and creates all 7 tables + 3 views.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"

TMPDB="$(mktemp -t shepherd-test-0007.XXXXXX.db)"
trap "rm -f $TMPDB ${TMPDB}-wal ${TMPDB}-shm" EXIT

# Bootstrap with all prior migrations (mirror cmd_init.sh ordering)
for f in "$ROOT/skills/context/schema/0001_init.sql" \
         "$ROOT/skills/context/schema/migrations/"*.sql; do
  sqlite3 "$TMPDB" < "$f"
done

# Apply 0007
sqlite3 "$TMPDB" < "$ROOT/skills/context/schema/0007_canonical_state.sql"

# Assert tables present
for t in teammates heartbeats mailbox escalations deliverables \
         discovery_findings audit_findings; do
  count=$(sqlite3 "$TMPDB" "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='$t';")
  [[ "$count" == "1" ]] || { echo "FAIL: table $t missing"; exit 1; }
done

# Assert views present
for v in v_teammates_live v_mailbox_unread_per_recipient v_escalations_open; do
  count=$(sqlite3 "$TMPDB" "SELECT count(*) FROM sqlite_master WHERE type='view' AND name='$v';")
  [[ "$count" == "1" ]] || { echo "FAIL: view $v missing"; exit 1; }
done

# Assert schema_versions row
ver=$(sqlite3 "$TMPDB" "SELECT version FROM schema_versions ORDER BY version DESC LIMIT 1;")
[[ "$ver" == "7" ]] || { echo "FAIL: schema_versions max != 7 (got: $ver)"; exit 1; }

# Assert WAL still on
mode=$(sqlite3 "$TMPDB" "PRAGMA journal_mode;")
[[ "$mode" == "wal" ]] || { echo "FAIL: journal_mode not wal (got: $mode)"; exit 1; }

# Assert json_valid CHECK on metadata enforced
if sqlite3 "$TMPDB" "INSERT INTO teammates (id, project_id, team_name, teammate_name, agent_type, spawned_at, last_seen_at, status, metadata) VALUES ('t1','p1','team','name','type',1,1,'active','not-json');" 2>/dev/null; then
  echo "FAIL: bad JSON in teammates.metadata was accepted"; exit 1
fi

echo "PASS: test_schema_0007"
