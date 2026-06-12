#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init
"$SHCTX" migrate

"$SHCTX" style init rust
assert_file "$SHCTX_TEST_TMP/.shepherd/styles/rust.md"

# Idempotent — second init does not overwrite custom edits.
echo "# CUSTOMIZED" >> "$SHCTX_TEST_TMP/.shepherd/styles/rust.md"
"$SHCTX" style init rust
grep -q CUSTOMIZED "$SHCTX_TEST_TMP/.shepherd/styles/rust.md" || { echo "FAIL: init clobbered custom edits"; exit 1; }

# init --all bootstraps every bundled language.
"$SHCTX" style init --all
for l in rust python typescript go shell sql; do
  assert_file "$SHCTX_TEST_TMP/.shepherd/styles/$l.md"
done

# `list` enumerates files.
out=$("$SHCTX" style list)
assert_contains "list" "$out" "rust.md"

# DB row created for each language.
n=$(sqlite3 "$SHCTX_TEST_TMP/.shepherd/shepherd.db" "SELECT COUNT(*) FROM styles;")
[[ "$n" -ge 6 ]] || { echo "FAIL: expected >=6 styles rows, got $n"; exit 1; }
