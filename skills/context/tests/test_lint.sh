#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init
"$SHCTX" lint  # empty tree → ok
echo "x" > .shepherd/plans/badname.md
if "$SHCTX" lint 2>/dev/null; then echo "FAIL: lint should reject badname.md" >&2; exit 1; fi
rm .shepherd/plans/badname.md
"$SHCTX" lint
echo "PASS: test_lint.sh"
