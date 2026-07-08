#!/usr/bin/env bash
# hooks/tests/test_coder_git_guard.sh — tests for coder_git_guard.sh (v6.3.0, #187).
#
# Covers the PreToolUse(Bash) @coder git-write guard: git custody is never the
# coder's, so every git write/mutating verb is denied for a @coder dispatch
# while read-only inspection (status/diff/log/show/rev-parse) passes. Role is
# resolved via the dispatch record agent_invocation_tagger.sh writes (same path
# bash_guard.sh uses for @auditor/@discovery), simulated here as
# .shepherd/dispatch/<sprint>/<tool_use_id>.json.
#
#   1. No shepherd.toml                         → PASS (not a shepherd project)
#   2. coder + git commit                       → DENY + CODER-GIT-WRITE
#   3. coder + git add <file>                   → DENY
#   4. coder + git add -A                        → DENY
#   5. coder + git reset --hard                  → DENY
#   6. coder + git checkout main                 → DENY
#   7. coder + git stash                         → DENY
#   8. coder + git push                          → DENY
#   9. coder + git worktree add                  → DENY
#  10. coder + git branch -D foo                 → DENY
#  11. coder + git -C <path> commit (global opt) → DENY
#  12. coder + git status && git commit (mixed)  → DENY
#  13. coder + git status                        → PASS (read-only)
#  14. coder + git diff                          → PASS
#  15. coder + git log --oneline -5              → PASS
#  16. coder + git show HEAD                     → PASS
#  17. coder + git rev-parse HEAD (Step 0.5)     → PASS
#  18. coder + rg pattern (no git)               → PASS
#  19. auditor + git commit (non-coder role)     → PASS (guard only polices coder)
#  20. untagged turn + git commit (role≠coder)   → PASS

set -uo pipefail
cd "$(dirname "$0")"
SCRIPT="$(cd .. && pwd)/scripts/coder_git_guard.sh"

fails=0; total=0
pass()  { printf '  PASS  %s\n' "$1"; }
fail()  { printf '  FAIL  %s — %s\n' "$1" "$2"; fails=$((fails+1)); }
is_deny()  { printf '%s' "$1" | grep -q '"permissionDecision"[[:space:]]*:[[:space:]]*"deny"'; }
has_code() { printf '%s' "$1" | grep -q "CODER-GIT-WRITE"; }
run_hook() { printf '%s' "$1" | bash "$SCRIPT" 2>/dev/null; return 0; }

# current_role needs jq or python3 to read the dispatch record; without either
# the role resolves to "conductor" and every coder case would false-pass.
if ! command -v jq >/dev/null 2>&1 && ! command -v python3 >/dev/null 2>&1; then
  printf '  SKIP  all cases — neither jq nor python3 available for role resolution\n'
  exit 0
fi

# --- case 1: no shepherd.toml → PASS -------------------------------------
total=$((total+1))
bare=$(mktemp -d -t shep-cgg-bare.XXXXXX)
(
  cd "$bare"; git init -q .; git config user.email t@t; git config user.name t
  git -c commit.gpgsign=false commit -q --allow-empty -m init
  out=$(printf '{"session_id":"s","tool_name":"Bash","tool_use_id":"x","tool_input":{"command":"git commit -m y"}}' | bash "$SCRIPT" 2>/dev/null) || true
  is_deny "$out" && { printf '  FAIL  no-shepherd-toml: PASS — got deny\n'; exit 1; } || printf '  PASS  no-shepherd-toml: PASS\n'
) || fails=$((fails+1))
rm -rf "$bare"

# --- shared ephemeral shepherd repo + dispatch records -------------------
tmp=$(mktemp -d -t shep-cgg.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q .; git config user.email t@t; git config user.name t
mkdir -p .claude; touch .claude/shepherd.toml
# COMMIT the shepherd.toml so a linked worktree checkout also carries it (the
# cross-worktree case below needs is_shepherd_project to pass from the worktree).
git add .claude/shepherd.toml
git -c commit.gpgsign=false commit -q -m init
sprint=$(git rev-parse --abbrev-ref HEAD)
mkdir -p ".shepherd/dispatch/$sprint"
printf '{"agent_role":"coder"}'   > ".shepherd/dispatch/$sprint/coder1.json"
printf '{"agent_role":"auditor"}' > ".shepherd/dispatch/$sprint/aud1.json"

# payload builder: <tool_use_id> <command> — JSON-escape the command (it may
# contain embedded quotes, e.g. bash -c "git commit").
P() {
  if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import json,sys; print(json.dumps({"session_id":"s","tool_name":"Bash","tool_use_id":sys.argv[1],"tool_input":{"command":sys.argv[2]}}))' "$1" "$2"
  else
    printf '{"session_id":"s","tool_name":"Bash","tool_use_id":"%s","tool_input":{"command":"%s"}}' "$1" "$2"
  fi
}

deny_case() { # <label> <tool_use_id> <cmd>
  total=$((total+1)); local out; out=$(run_hook "$(P "$2" "$3")")
  if is_deny "$out" && has_code "$out"; then pass "$1"; else fail "$1" "expected deny+CODER-GIT-WRITE, got: ${out:0:100}"; fi
}
pass_case() { # <label> <tool_use_id> <cmd>
  total=$((total+1)); local out; out=$(run_hook "$(P "$2" "$3")")
  if ! is_deny "$out"; then pass "$1"; else fail "$1" "unexpected deny: ${out:0:100}"; fi
}

deny_case "coder + git commit → DENY"                 coder1 'git commit -m feat'
deny_case "coder + git add <file> → DENY"             coder1 'git add src/lib.rs'
deny_case "coder + git add -A → DENY"                 coder1 'git add -A'
deny_case "coder + git reset --hard → DENY"           coder1 'git reset --hard HEAD'
deny_case "coder + git checkout main → DENY"          coder1 'git checkout main'
deny_case "coder + git stash → DENY"                  coder1 'git stash'
deny_case "coder + git push → DENY"                   coder1 'git push origin lane'
deny_case "coder + git worktree add → DENY"           coder1 'git worktree add ../x main'
deny_case "coder + git branch -D → DENY"              coder1 'git branch -D foo'
deny_case "coder + git -C <path> commit → DENY"       coder1 'git -C /repo commit -m x'
deny_case "coder + git status && git commit → DENY"   coder1 'git status && git commit -m x'

pass_case "coder + git status → PASS"                 coder1 'git status'
pass_case "coder + git diff → PASS"                   coder1 'git diff HEAD'
pass_case "coder + git log → PASS"                    coder1 'git log --oneline -5'
pass_case "coder + git show → PASS"                   coder1 'git show HEAD'
pass_case "coder + git rev-parse → PASS (Step 0.5)"   coder1 'git rev-parse HEAD'
pass_case "coder + rg (no git) → PASS"                coder1 'rg -n pattern src/'
pass_case "auditor + git commit → PASS (non-coder)"   aud1   'git commit -m x'
pass_case "untagged + git commit → PASS (role≠coder)" nodisp 'git commit -m x'

# --- bypass regressions (review CRITICAL #2/#3, MEDIUM #8) ----------------
deny_case "coder + bash -c \"git commit\" → DENY"     coder1 'bash -c "git commit -am x"'
deny_case "coder + git status && bash -c git write"   coder1 'git status && bash -c "git commit -am x"'
deny_case "coder + eval \"git reset --hard\" → DENY"  coder1 'eval "git reset --hard HEAD"'
deny_case "coder + git read-tree (plumbing) → DENY"   coder1 'git read-tree --reset -u HEAD'
deny_case "coder + git reflog expire → DENY"          coder1 'git reflog expire --all'
deny_case "coder + glued git status;git commit → DENY" coder1 'git status;git commit -am x'
deny_case "coder + sh -c git checkout → DENY"         coder1 'sh -c "git checkout -- ."'
pass_case "coder + glued git status;git log → PASS"   coder1 'git status;git log --oneline'
pass_case "coder + git status;echo ok → PASS"         coder1 'git status;echo ok'

# --- cross-worktree role detection (review CRITICAL #1, _lib.sh current_role) ---
# The coder's Bash runs from its OWN linked worktree (a different branch AND
# toplevel than the sprint root where the dispatch record was written). The guard
# must still resolve role=coder from there — else it silently no-ops, the exact
# field bug. Reproduces by running the hook from inside a real linked worktree.
if git -C "$tmp" worktree add -q -b agent-lane-x "$tmp/wt-x" "$sprint" 2>/dev/null; then
  total=$((total+1))
  out=$( cd "$tmp/wt-x" && printf '%s' "$(P coder1 'git commit -am x')" | bash "$SCRIPT" 2>/dev/null || true )
  if is_deny "$out" && has_code "$out"; then pass "cross-worktree coder commit → DENY (current_role #1)"
  else fail "cross-worktree commit" "guard no-op from worktree: ${out:0:80}"; fi
  total=$((total+1))
  out=$( cd "$tmp/wt-x" && printf '%s' "$(P coder1 'git status')" | bash "$SCRIPT" 2>/dev/null || true )
  if ! is_deny "$out"; then pass "cross-worktree coder read → PASS"
  else fail "cross-worktree read" "unexpected deny: ${out:0:80}"; fi
  git -C "$tmp" worktree remove --force "$tmp/wt-x" 2>/dev/null || true
else
  printf '  SKIP  cross-worktree cases — git worktree add unavailable\n'
fi

echo "—— $((total-fails))/$total passed ——"
exit "$fails"
