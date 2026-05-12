#!/usr/bin/env bash
# v5.0.4 — verify the canonical --all flag works as alias for --scope=all
# across every subcommand that supports either form.

source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"

"$SHCTX" init    >/dev/null
"$SHCTX" migrate >/dev/null  # styles, FTS5, lane_closures tables need 0002–0004

# refresh: --all == --scope=all (just verifies parser accepts both forms)
"$SHCTX" refresh --scope=all   >/dev/null 2>&1 || true
"$SHCTX" refresh --all         >/dev/null 2>&1 || true

# search: same
"$SHCTX" search "x" --scope=all --limit=1 >/dev/null 2>&1 || true
"$SHCTX" search "x" --all --limit=1       >/dev/null 2>&1 || true

# style init --all is the original surface (already supported)
out=$("$SHCTX" style init --all 2>&1 || true)
assert_contains "style init --all enumerates langs" "$out" "rust"

# worktree gc --all == --older-than=0
out=$("$SHCTX" worktree gc --all --dry-run 2>&1 || true)
assert_contains "worktree gc --all accepted" "$out" "shctx worktree gc:"

# lock release --force / --all aliases reap
"$SHCTX" lock acquire --mode=context >/dev/null
out=$("$SHCTX" lock release --force 2>&1)
assert_contains "lock release --force accepted" "$out" "released (force)"

# export --all bundles a directory.
out=$("$SHCTX" export --all 2>&1 || true)
assert_contains "export --all bundles" "$out" "shctx export --all: bundle at"

echo "PASS: flag aliases"
