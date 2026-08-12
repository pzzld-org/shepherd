#!/usr/bin/env bash
# hooks/tests/test_close_finalize_check.sh — tests for close_finalize_check.sh
#
# Covers the Stop-hook deterministic close-finalize detector (v6.0.7, GH #127):
#
#   Fast-paths (all must exit 0, no block):
#     1. Non-sprint branch (main, v0.3.5, feature/foo)
#     2. Subworktree (pwd != git show-toplevel)
#     3. Sprint branch + no close report committed (normal mid-sprint state)
#     4. Sprint branch + planter-mesh committed (fire #17 variant — plant-mode)
#     4b. PRIOR-sprint close report in HEAD + current LIVE branch (GH #122 — slug scope)
#     5. Sprint branch + close report + branch GONE from origin (already finalized)
#     6. Invalid slug form — branch unparseable → fail-open
#
#   Block path:
#     7. Sprint branch + committed close report + branch still on origin → BLOCK

set -eu -o pipefail
cd "$(dirname "$0")"
HOOKS_DIR="$(cd .. && pwd)/scripts"
SCRIPT="$HOOKS_DIR/close_finalize_check.sh"

fails=0
total=0
pass()  { printf '  PASS  %s\n' "$1"; }
fail()  { printf '  FAIL  %s — %s\n' "$1" "$2"; fails=$((fails+1)); }

is_block() { printf '%s' "$1" | grep -q '"decision"[[:space:]]*:[[:space:]]*"block"'; }
run_check() { printf '{}' | bash "$SCRIPT" 2>/dev/null; }

# Shared ephemeral repo + bare origin
tmp=$(mktemp -d -t shep-cfc-test.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
ORIGIN="$tmp/origin.git"
git init --bare -q "$ORIGIN"
mkdir -p "$tmp/repo"
cd "$tmp/repo"
git init -q .
git config user.email t@t
git config user.name t
git config commit.gpgsign false
git remote add origin "$ORIGIN"
git -c commit.gpgsign=false commit -q --allow-empty -m "init"
mkdir -p .claude .artifacts/reports
touch .claude/shepherd.toml
git push -q origin HEAD:main 2>/dev/null || true   # seed origin

# Helper: commit a named file into .artifacts/reports/ on the current branch
commit_report() {
  local filename="$1" msg="${2:-add report}"
  mkdir -p .artifacts/reports
  touch ".artifacts/reports/$filename"
  git add ".artifacts/reports/$filename"
  git -c commit.gpgsign=false commit -q -m "$msg"
}

# ---------------------------------------------------------------------------
# 1. Non-sprint branch (main) → fast-path, no block.
# ---------------------------------------------------------------------------
total=$((total+1))
# We start on main (or whatever the init branch is); just ensure not a dev branch.
CURRENT=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
if [[ "$CURRENT" =~ -dev\.[0-9]+$ ]]; then
  fail "non-sprint-branch: fast-path" "starting branch is unexpectedly a dev branch: $CURRENT"
else
  out=$(run_check)
  if ! is_block "$out"; then pass "non-sprint-branch: fast-path, no block"; else fail "non-sprint-branch: fast-path" "out=$out"; fi
fi

# ---------------------------------------------------------------------------
# 2. Subworktree: pwd != git show-toplevel → fast-path, no block.
# ---------------------------------------------------------------------------
total=$((total+1))
git checkout -q -b v0.3.5-dev.0 2>/dev/null || git checkout -q v0.3.5-dev.0
mkdir -p .worktrees/lane-a
out=$(cd .worktrees/lane-a && printf '{}' | bash "$SCRIPT" 2>/dev/null)
if ! is_block "$out"; then pass "subworktree: fast-path, no block"; else fail "subworktree: fast-path" "out=$out"; fi
git checkout -q v0.3.5-dev.0 2>/dev/null   # back to sprint branch

# ---------------------------------------------------------------------------
# 3. Sprint branch + no close report committed → fast-path, no block.
#    (Normal mid-sprint state — Signal A empty.)
# ---------------------------------------------------------------------------
total=$((total+1))
# v0.3.5-dev.0 just cut from init; no close report commits.
out=$(run_check)
if ! is_block "$out"; then pass "no-close-report: fast-path, no block"; else fail "no-close-report: fast-path" "out=$out"; fi

# ---------------------------------------------------------------------------
# 4. Sprint branch + planter-mesh committed → fast-path, no block.
#    (Fire #17 variant: planter commits to .artifacts/reports/ but it's not
#     a *-v{slug}-close.md file.)
# ---------------------------------------------------------------------------
total=$((total+1))
commit_report "2026-06-04-planter-mesh.md" "chore(plant): mesh report for v0.3.5-dev.0"
out=$(run_check)
if ! is_block "$out"; then
  pass "planter-mesh: fast-path, no block (fire#17 variant)"
else
  fail "planter-mesh: fast-path, no block" "planter-mesh.md should not match slug-close pattern; out=$out"
fi

# Also test other plant-mode adjacent names that should not match:
for name in "2026-06-04-phase0-discovery.md" "v035-dev0.seed.md" "2026-06-04-v035-dev0-handoff.md"; do
  total=$((total+1))
  commit_report "$name" "chore(plant): $name"
  out=$(run_check)
  if ! is_block "$out"; then
    pass "non-close-artifact ($name): no block"
  else
    fail "non-close-artifact ($name): no block" "should not match slug-close pattern; out=$out"
  fi
done

# ---------------------------------------------------------------------------
# 4b. GH #122 REGRESSION — PRIOR-sprint close report in HEAD + current LIVE
#     sprint branch on origin → must NOT block.
#     Scenario: v0.3.4-dev.8 closed (its close report committed), then
#     v0.3.4-dev.9 was cut FROM dev.8 (so dev.8's close report is reachable
#     from dev.9 HEAD) and pushed LIVE. The old `-newer .git/HEAD` detector
#     matched the prior slug and instructed deleting the LIVE dev.9 branch.
#     Slug-scoping (Signal A = *-v035-dev9-close.md, derived from the CURRENT
#     branch) must make dev.8's report invisible → fast-path, no block.
# ---------------------------------------------------------------------------
total=$((total+1))
git checkout -q v0.3.5-dev.0
git checkout -q -b v0.3.5-dev.1                       # prior sprint
commit_report "2026-06-03-v035-dev1-close.md" "close(v0.3.5-dev.1): prior sprint"
git checkout -q -b v0.3.5-dev.2                       # current sprint, cut FROM dev.1
git push -q origin v0.3.5-dev.2 2>/dev/null           # dev.2 is LIVE on origin
out=$(run_check)
if ! is_block "$out"; then
  pass "prior-sprint-close-report + live-current-branch: no block (#122)"
else
  fail "prior-sprint-close-report + live-current-branch: no block (#122)" "dev.1 close report must not match dev.2 slug; out=$out"
fi
git checkout -q v0.3.5-dev.0

# ---------------------------------------------------------------------------
# 5. Sprint branch + committed close report + branch GONE from origin.
#    (Finalize complete → fast-path, no block.)
#    We don't push this branch to origin, so ls-remote returns empty.
# ---------------------------------------------------------------------------
total=$((total+1))
commit_report "2026-06-04-v035-dev0-close.md" "close(v0.3.5-dev.0): sprint close report"
# v0.3.5-dev.0 is NOT on origin (never pushed) → Signal B empty → fast-path.
out=$(run_check)
if ! is_block "$out"; then
  pass "close-report-branch-not-on-origin: fast-path, no block"
else
  fail "close-report-branch-not-on-origin: fast-path" "Signal B should be empty when branch not on origin; out=$out"
fi

# ---------------------------------------------------------------------------
# 6. Invalid slug: branch name that doesn't parse to digits-devN → fail-open.
# ---------------------------------------------------------------------------
total=$((total+1))
git checkout -q -b feature/weird-branch 2>/dev/null
out=$(run_check)
if ! is_block "$out"; then pass "invalid-slug: fail-open, no block"; else fail "invalid-slug: fail-open" "out=$out"; fi
git checkout -q v0.3.5-dev.0

# ---------------------------------------------------------------------------
# 7. Sprint branch + committed close report + branch STILL on origin → BLOCK.
#    (Both signals positive — the only legitimate block path.)
# ---------------------------------------------------------------------------
total=$((total+1))
# Push v0.3.5-dev.0 (with the close report commit from step 5) to origin.
git push -q origin v0.3.5-dev.0 2>/dev/null
out=$(run_check)
if is_block "$out"; then
  pass "close-report-and-branch-on-origin: BLOCK"
else
  fail "close-report-and-branch-on-origin: BLOCK" "both signals should be positive; out=$out"
fi

# Confirm the block reason does NOT instruct running --delete (fire #127 original defect).
# The old agent prompt emitted: "git push origin --delete <branch>" as a remediation command.
# Acceptable: prohibitions mentioning the flag; Unacceptable: prescribing the command.
total=$((total+1))
if printf '%s' "$out" | grep -qE 'git push origin --delete|push.*--delete.*sprint'; then
  fail "block-reason: no destructive --delete instruction" "found push --delete command in reason; out=$out"
else
  pass "block-reason: no destructive --delete instruction"
fi

# ---------------------------------------------------------------------------
# 9. (#154) Runaway bound — the SAME committed state must not re-block forever.
#    Clear the per-state counter, then CAP=2 blocks, the 3rd fails OPEN.
# ---------------------------------------------------------------------------
total=$((total+1))
rm -f .artifacts/tmp/close_finalize_check.*.count 2>/dev/null || true
b1=$(run_check); b2=$(run_check); b3=$(run_check)
if is_block "$b1" && is_block "$b2" && ! is_block "$b3"; then
  pass "#154 runaway bound: block,block,fail-open on same HEAD"
else
  fail "#154 runaway bound" "b1=$(is_block "$b1" && echo B || echo -) b2=$(is_block "$b2" && echo B || echo -) b3=$(is_block "$b3" && echo B || echo -)"
fi

# ---------------------------------------------------------------------------
# 10. (#154) A NEW commit (HEAD changes) legitimately re-warns once — a real new
#     close report is never masked by the bound.
# ---------------------------------------------------------------------------
total=$((total+1))
commit_report "2026-06-05-v035-dev0-close.md" "close(v0.3.5-dev.0): amended report"
git push -q origin v0.3.5-dev.0 2>/dev/null
out=$(run_check)
if is_block "$out"; then pass "#154 new HEAD re-warns once"; else fail "#154 new HEAD re-warns" "out=$out"; fi

# ---------------------------------------------------------------------------
# 11. (#154) Operator hold: [close].finalize_hold = "true" silences the block
#     while the dev→patch merge is intentionally deferred.
# ---------------------------------------------------------------------------
total=$((total+1))
printf '[close]\nfinalize_hold = "true"\n' > .claude/shepherd.toml
out=$(run_check)
if ! is_block "$out"; then pass "#154 finalize_hold escape: no block"; else fail "#154 finalize_hold escape" "out=$out"; fi
printf '' > .claude/shepherd.toml

echo "—— $((total-fails))/$total passed ——"
exit "$fails"
