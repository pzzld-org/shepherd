#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
db=$(shctx_test_db)

# All v5.0.0 tables must exist.
for t in projects sessions profiles_defs mem_entries \
         index_symbols index_concepts index_issues index_prs \
         index_releases index_milestones logs_events artifacts \
         locks_history schema_versions; do
  assert_table "$db" "$t"
done

# All views must exist.
for v in v_open_issues v_canonical_types v_drift_risk v_mem_recent_7d v_active_locks; do
  sqlite3 "$db" "SELECT 1 FROM $v LIMIT 1;" >/dev/null \
    || { echo "FAIL: view missing or broken: $v" >&2; exit 1; }
done

# WAL journal mode + foreign keys ON.
mode=$(sqlite3 "$db" "PRAGMA journal_mode;")
assert_eq "journal_mode" "$mode" "wal"
fk=$(sqlite3 "$db" "PRAGMA foreign_keys = ON; PRAGMA foreign_keys;")
assert_eq "foreign_keys" "$fk" "1"

# JSON CHECK constraints reject invalid JSON.
if sqlite3 "$db" "INSERT INTO projects (id,name,scope,tags,created_at,updated_at) VALUES ('x','t','not-json','[]',0,0);" 2>/dev/null; then
  echo "FAIL: invalid JSON accepted in projects.scope" >&2; exit 1
fi

# Schema-version row written.
v=$(sqlite3 "$db" "SELECT version FROM schema_versions ORDER BY version DESC LIMIT 1;")
assert_eq "schema_version" "$v" "1"
