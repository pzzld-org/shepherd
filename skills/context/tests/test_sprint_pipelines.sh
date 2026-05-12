#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"

"$SHCTX" init >/dev/null

# sprint open
out=$("$SHCTX" sprint open v0.0.1-dev.0 2>&1 || true)
assert_contains "sprint open emits header"   "$out" "shctx sprint open v0.0.1-dev.0"
assert_contains "sprint open shows lock"     "$out" "  lock:"
assert_contains "sprint open shows refresh"  "$out" "  refresh:"
assert_contains "sprint open shows lint"     "$out" "  lint:"

# sprint wave
out=$("$SHCTX" sprint wave 1 2>&1 || true)
assert_contains "sprint wave emits header"   "$out" "shctx sprint wave 1: scope=github,artifacts"
assert_contains "sprint wave shows refresh"  "$out" "  refresh:"
out=$("$SHCTX" sprint wave 1 --all 2>&1 || true)
assert_contains "sprint wave --all forwards scope" "$out" "scope=all"

# sprint close — release the lock first by running close
out=$("$SHCTX" sprint close v0.0.1-dev.0 2>&1 || true)
assert_contains "sprint close emits header"  "$out" "shctx sprint close v0.0.1-dev.0"
assert_contains "sprint close shows handoff" "$out" "  handoff:"
assert_contains "sprint close shows gc"      "$out" "  gc:"
assert_contains "sprint close shows lock release" "$out" "  lock:"

echo "PASS: sprint pipelines"
