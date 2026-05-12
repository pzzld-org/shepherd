#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init >/dev/null

# Make a handful of commits + memories + artifacts so the auto-populated metrics are non-zero.
echo "alpha" > a.txt && git add a.txt && git commit -qm "feat: alpha"
echo "beta"  > b.txt && git add b.txt && git commit -qm "feat: beta"
"$SHCTX" mem add --kind=note --title="ship-it" --body="hello" >/dev/null
"$SHCTX" lock acquire --mode=context >/dev/null
"$SHCTX" lock release >/dev/null

# ---- create ----
out=$("$SHCTX" handoff create --branch=v0.0.1-dev.0 2>&1)
file=$(printf '%s\n' "$out" | tail -1)
assert_file "$file"
content=$(cat "$file")
assert_contains "branch substitution"  "$content" "Sprint handoff — v0.0.1-dev.0"
assert_contains "commits captured"     "$content" "feat: alpha"
assert_contains "north-star fillin"    "$content" "[FILL IN]"
assert_contains "carry-fwd fillin"     "$content" "## Carry-forwards"
# mem entries should be at least 1.
assert_contains "metrics rendered"     "$content" "Memory entries written | 1"
# locks at least 1.
assert_contains "lock metric"          "$content" "Lock acquisitions | 1"

# Path shape (assert via case to avoid grep flag-parsing on the leading '-v').
case "$file" in
  *-v0.0.1-dev.0-close-handoff.md) : ;;
  *) echo "FAIL: filename shape: $file" >&2; exit 1 ;;
esac

# ---- list ----
list=$("$SHCTX" handoff list 2>&1)
assert_contains "list contains file" "$list" "v0.0.1-dev.0-close-handoff.md"

# ---- show (no arg) ----
shown=$("$SHCTX" handoff show 2>&1)
assert_contains "show emits content" "$shown" "Sprint handoff — v0.0.1-dev.0"

# ---- show with substring match ----
shown2=$("$SHCTX" handoff show v0.0.1-dev.0 2>&1)
assert_contains "show matches branch" "$shown2" "Sprint handoff — v0.0.1-dev.0"

# ---- show with no match returns clear message ----
nm=$("$SHCTX" handoff show v999 2>&1 || true)
assert_contains "show no-match" "$nm" "no handoff matching"
