#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init
out=$("$SHCTX" query open-issues --json)
assert_eq "empty_json" "$out" ""

# Insert a row directly and query it.
db="$SHCTX_TEST_TMP/.shepherd/root.db"
pid=$(jq -r .id "$SHCTX_TEST_TMP/.shepherd/project.json")
sqlite3 "$db" "INSERT INTO index_issues VALUES ('x','$pid','github',1,'t','open','[]',NULL,'[]','b','u',1,1,1);"
out=$("$SHCTX" query open-issues --json)
assert_contains "json.t" "$out" '"title":"t"'
echo "PASS: test_query.sh"
