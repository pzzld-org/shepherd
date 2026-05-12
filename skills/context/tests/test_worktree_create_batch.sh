#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"

# Make a sprint branch with one commit so HEAD is well-defined.
git checkout -q -b v0.0.1-dev.0
echo "sprint" > sprint.txt && git add sprint.txt && git commit -qm "sprint commit"
sprint_sha=$(git rev-parse HEAD)

"$SHCTX" init >/dev/null

# Pre-create three worktrees for lanes 1/2/3 from sprint HEAD.
out=$("$SHCTX" worktree create-batch lane-1 lane-2 lane-3 --from v0.0.1-dev.0 2>&1)
assert_contains "create-batch reports created" "$out" "created agent-lane-1"
assert_contains "create-batch reports BASE-COMMIT-EXPECTED" "$out" "[BASE-COMMIT-EXPECTED]"
assert_contains "create-batch echoes sprint sha" "$out" "$sprint_sha"

# Verify each worktree exists at the expected SHA.
for lane in lane-1 lane-2 lane-3; do
  wt=".claude/worktrees/agent-${lane}"
  [[ -d "$wt" ]] || { echo "FAIL: worktree missing: $wt" >&2; exit 1; }
  wt_sha=$(git -C "$wt" rev-parse HEAD)
  assert_eq "worktree $lane HEAD matches sprint" "$wt_sha" "$sprint_sha"
done

# Idempotency: re-running skips existing worktrees.
out=$("$SHCTX" worktree create-batch lane-1 --from v0.0.1-dev.0 2>&1)
assert_contains "create-batch is idempotent" "$out" "skip agent-lane-1"

# gc --all (== --older-than=0) clears all agent worktrees regardless of age.
out=$("$SHCTX" worktree gc --all 2>&1)
assert_contains "gc --all prunes" "$out" "pruned"

echo "PASS: worktree create-batch"
