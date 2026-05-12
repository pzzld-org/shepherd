#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init

out=$("$SHCTX" status)
for tok in "Schema version" "Tables" "projects" "index_symbols" "Lock"; do
  assert_contains "status.$tok" "$out" "$tok"
done
