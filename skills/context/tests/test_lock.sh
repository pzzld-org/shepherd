#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init

"$SHCTX" lock acquire --mode=context --session=test1
out=$("$SHCTX" lock show)
assert_contains "show.held" "$out" "test1"
"$SHCTX" lock release
out=$("$SHCTX" lock show)
assert_contains "show.free" "$out" "free"

# Stale lock reaping.
echo '{"holder_session_id":"dead","mode":"context","acquired_at":1,"pid":99999999,"children":[]}' > .shepherd/shepherd.lock
"$SHCTX" lock reap
[[ ! -f .shepherd/shepherd.lock ]] || { echo "FAIL: stale lock not reaped" >&2; exit 1; }
