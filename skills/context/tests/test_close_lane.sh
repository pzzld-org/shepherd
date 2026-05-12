#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init >/dev/null
"$SHCTX" migrate >/dev/null

# close-lane without gh CLI should still record the closure (treats issues as still-open).
out=$("$SHCTX" close-lane lane-3 --sprint=v0.3.0-dev.4 --issues=#999,#1000 --status=clean 2>&1)
echo "$out" | grep -q "carry-forward patch" || { echo "FAIL: missing markdown patch" >&2; echo "$out"; exit 1; }

# Verify a row was inserted.
n=$(sqlite3 .shepherd/root.db "SELECT COUNT(*) FROM lane_closures WHERE lane_id='lane-3' AND sprint_branch='v0.3.0-dev.4';")
[[ "$n" == "1" ]] || { echo "FAIL: expected 1 lane_closure row, got $n" >&2; exit 1; }

# Verify status enum is honored. Disable set -e so we can capture the rc.
set +e
"$SHCTX" close-lane lane-4 --sprint=v0.3.0-dev.4 --status=invalid >/dev/null 2>&1
rc=$?
set -e
[[ "$rc" -ne 0 ]] || { echo "FAIL: invalid status should error" >&2; exit 1; }

# Idempotency: calling close-lane twice updates same row.
"$SHCTX" close-lane lane-3 --sprint=v0.3.0-dev.4 --status=partial >/dev/null
n=$(sqlite3 .shepherd/root.db "SELECT COUNT(*) FROM lane_closures WHERE lane_id='lane-3' AND sprint_branch='v0.3.0-dev.4';")
[[ "$n" == "1" ]] || { echo "FAIL: expected 1 row after re-close (UPSERT), got $n" >&2; exit 1; }
status=$(sqlite3 .shepherd/root.db "SELECT status FROM lane_closures WHERE lane_id='lane-3';")
[[ "$status" == "partial" ]] || { echo "FAIL: expected status=partial after update, got $status" >&2; exit 1; }

echo "PASS: test_close_lane.sh"
