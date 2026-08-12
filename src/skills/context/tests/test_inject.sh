#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init
for r in engineer coder auditor; do
  out=$("$SHCTX" inject "$r")
  assert_contains "$r" "$out" "[DB-CONTEXT]"
  assert_contains "$r.close" "$out" "[/DB-CONTEXT]"
done
echo "PASS: test_inject.sh"
