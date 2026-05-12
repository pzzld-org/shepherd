#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"

# Init first.
"$SHCTX" init >/dev/null

# `sync --all` should run cleanly (artifacts refresh works on empty repo,
# symbols may run, github will skip if gh missing — all should yield exit 0
# or 1 only if a real failure occurred).
out=$("$SHCTX" sync --all 2>&1 || true)
assert_contains "sync emits scope summary" "$out" "shctx sync: scope=all"
assert_contains "sync emits per-stage status" "$out" "  refresh:"
assert_contains "sync emits lint status"      "$out" "  lint:"
assert_contains "sync emits status status"    "$out" "  status:"

# Help text honors --all.
help=$("$SHCTX" sync --help 2>&1)
assert_contains "sync help advertises --all" "$help" "--all"
echo "PASS: sync"
