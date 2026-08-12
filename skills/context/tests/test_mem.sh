#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init

id=$("$SHCTX" mem add --kind=note --title="t" --body="b")
[[ "$id" =~ ^[0-9a-f-]+$ ]] || { echo "FAIL: id format: $id"; exit 1; }
out=$("$SHCTX" mem list)
assert_contains "list" "$out" "t"
"$SHCTX" mem pin "$id"
n=$(sqlite3 "$SHCTX_TEST_TMP/.shepherd/shepherd.db" "SELECT pinned FROM mem_entries WHERE id='$id';")
assert_eq "pinned" "$n" "1"
"$SHCTX" mem unpin "$id"
n=$(sqlite3 "$SHCTX_TEST_TMP/.shepherd/shepherd.db" "SELECT pinned FROM mem_entries WHERE id='$id';")
assert_eq "unpinned" "$n" "0"
out=$("$SHCTX" mem search --q=t)
assert_contains "search" "$out" "t"
