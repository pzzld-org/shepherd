#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init >/dev/null

# Seed the workspace with the version files so the bump-plan output exercises every format.
mkdir -p .claude-plugin skills/shepherd skills/context
echo '{"version":"0.0.0"}' > .claude-plugin/plugin.json
echo '{"version":"0.0.0"}' > .claude-plugin/marketplace.json
printf -- '---\nname: x\nslug: x\nversion: 0.0.0\n---\n' \
  | tee skills/shepherd/SKILL.md \
        skills/context/SKILL.md >/dev/null
printf '# README\n\nCurrent version: **0.0.0**\n' > README.md
git add . && git commit -qm "seed version files"

# ---- Mode A: lighter-pattern (patch branch, e.g. v5.0.0) ----
# Initial branch is whatever git init produced (master/main). Cut a v5.0.0 patch branch.
git checkout -q -b v5.0.0
out=$("$SHCTX" release --dry-run 2>&1 || true)
# Confirm mode detection.
assert_contains "release mode detect" "$out" "lighter-pattern mode: patch 5.0.0 ready for release"
# Confirm core cascade plan steps appear.
assert_contains "plan squash"    "$out" "git merge --squash v5.0.0"
assert_contains "plan tag patch" "$out" "git tag -a v5.0.0"
assert_contains "plan tag minor" "$out" "git tag -f v5.0"
assert_contains "plan tag major" "$out" "git tag -f v5"
assert_contains "plan gh"        "$out" "gh release create v5.0.0"
# Cascade: 5.0.0 → 5.0.1 (Z<9 increments Z).
assert_contains "plan next patch branch" "$out" "git checkout -b v5.0.1"
assert_contains "plan next dev branch"   "$out" "git checkout -b v5.0.1-dev.0"
assert_contains "plan version bump"      "$out" "bump (json) .claude-plugin/plugin.json"
assert_contains "plan readme bump"       "$out" "bump (readme) README.md"
assert_contains "plan complete"          "$out" "release pipeline complete: v5.0.0 released"

# ---- Mode B: sprint-end mode, mid-patch (dev.5 of v0.2.9 — sprints_per_patch=10, last=9) ----
git checkout -q -b v0.2.9
git checkout -q -b v0.2.9-dev.5
out=$("$SHCTX" release --dry-run 2>&1 || true)
assert_contains "sprint mode detect"     "$out" "sprint-end mode: dev.5 of patch 0.2.9"
assert_contains "sprint mid-patch close" "$out" "mid-patch sprint close: rebase dev.5"
assert_contains "sprint rebase"          "$out" "git rebase v0.2.9-dev.5"
assert_contains "sprint cut next"        "$out" "git checkout -b v0.2.9-dev.6 v0.2.9"
# Mid-patch should NOT do the full cascade.
if grep -qF "git tag -a v0.2.9" <<< "$out"; then
  echo "FAIL: mid-patch sprint should not tag" >&2; exit 1
fi
if grep -qF "gh release create v0.2.9" <<< "$out"; then
  echo "FAIL: mid-patch sprint should not gh-release" >&2; exit 1
fi

# ---- Mode C: sprint-end mode, end of patch (dev.9 of v0.2.9 → cascade fires) ----
git checkout -q -b v0.2.9-dev.9
out=$("$SHCTX" release --dry-run 2>&1 || true)
assert_contains "sprint patch-end detect"     "$out" "sprint-end mode: dev.9 of patch 0.2.9"
assert_contains "sprint patch-end fall-thru"  "$out" "patch-end sprint: rebase dev.9 → v0.2.9, then run full cascade"
# After the rebase fall-through, the cascade should fire (Z=9, Y=2 → Y+1=3, Z=0).
assert_contains "sprint cascade tag"          "$out" "git tag -a v0.2.9"
assert_contains "sprint cascade next patch"   "$out" "git checkout -b v0.3.0"
assert_contains "sprint cascade next dev"     "$out" "git checkout -b v0.3.0-dev.0"

# ---- Mode D: cascade boundary (Z=9, Y=9 → major bump) ----
git checkout -q -b v1.9.9
out=$("$SHCTX" release --dry-run 2>&1 || true)
assert_contains "major-bump cascade" "$out" "git checkout -b v2.0.0"

# ---- skip flags work ----
git checkout -q -b v3.0.0
out=$("$SHCTX" release --dry-run --skip=tag,gh,bump,push 2>&1 || true)
assert_contains "skip tag" "$out" "skip tag (--skip=tag): v3.0.0"
assert_contains "skip gh"  "$out" "skip gh release (--skip=gh): v3.0.0"
assert_contains "skip bump" "$out" "skip version bump (--skip=bump)"

# ---- unknown branch shape errors clearly ----
git checkout -q -b not-a-version
out=$("$SHCTX" release --dry-run 2>&1 || true)
assert_contains "unknown-branch error" "$out" "does not match a known release pattern"
