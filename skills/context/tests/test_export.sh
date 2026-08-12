#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init
"$SHCTX" export canonical-types --out="$SHCTX_TEST_TMP/out.md"
assert_file "$SHCTX_TEST_TMP/out.md"
echo "PASS: test_export.sh"
