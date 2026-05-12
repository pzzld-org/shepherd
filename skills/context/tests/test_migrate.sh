#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init

# Apply any bundled migrations (e.g. real 0002_styles.sql) so we reach a clean head.
"$SHCTX" migrate >/dev/null

# At head → migrate is a no-op.
out=$("$SHCTX" migrate)
assert_contains "noop" "$out" "no migrations pending"

# Drop a fake 0099.sql; migrate applies it.
mig="$SHCTX_SKILL_ROOT/schema/migrations/0099_test.sql"
trap 'rm -f "$mig"' EXIT
cat > "$mig" <<'SQL'
CREATE TABLE _migrate_probe (id INTEGER PRIMARY KEY);
SQL

out=$("$SHCTX" migrate)
assert_contains "applied" "$out" "0099"

v=$(sqlite3 "$SHCTX_TEST_TMP/.shepherd/root.db" "SELECT MAX(version) FROM schema_versions;")
assert_eq "max_version" "$v" "99"

# Idempotent: re-run is a no-op.
out=$("$SHCTX" migrate)
assert_contains "noop2" "$out" "no migrations pending"
