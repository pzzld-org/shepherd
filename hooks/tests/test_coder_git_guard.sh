#!/usr/bin/env bash
# hooks/tests/test_coder_git_guard.sh — tests for coder_git_guard.sh (v6.3.0,
# #187; rebuilt DF-77).
#
# WHY REBUILT: every prior DENY case fed the guard a HAND-WRITTEN dispatch
# record (`{"agent_role":"coder"}`) at a filename chosen to equal the Bash
# call's own tool_use_id — a payload shape that never occurs in production
# (agent_invocation_tagger.sh derives agent_role, it is never handed one
# directly; and a dispatch record is keyed by the DISPATCHING Agent() call's
# own tool_use_id, never the id of a LATER Bash call). The suite passed
# 31/31 while the real guard denied nothing in this repository — proving the
# fixture, not the mechanism (the exact DF-19 pattern). This rebuild runs the
# REAL agent_invocation_tagger.sh, fed a REALISTIC
# tool_input.subagent_type-bearing PreToolUse(Agent) payload, to PRODUCE every
# dispatch record the guard cases below consume — so a passing DENY case now
# proves FIX 1 (role derivation) and coder_git_guard.sh's deny logic work
# TOGETHER, end to end, through both real hook scripts.
#
# ONE assertion matters most: "coder + git commit → DENY (real tagger,
# real guard)" below — a dispatch tagged shepherd:coder attempting `git
# commit` is denied end to end. Everything else is the regression matrix
# around it, plus the FIX-2/FIX-3 controls the DF-77 brief calls out
# explicitly:
#   - a coder's `git status` passes (read-only)
#   - root — a Bash call with NO matching dispatch record at all — is NOT
#     denied for a git write (current_role() resolves "unknown", never
#     escalates to "conductor"; coder_git_guard.sh warns, never denies, on
#     "unknown" — see _lib.sh current_role() + coder_git_guard.sh headers for
#     why: root's own direct git writes resolve to the identical "unknown"
#     value, so a blanket deny would block root too)
#   - that same "unknown role + git write" case emits a LOUD warn
#     (additionalContext), never a silent pass — DF-77's own root cause was a
#     guard nobody could see was doing nothing
#
#   1. No shepherd.toml                                → PASS (not a shepherd project)
#   2. tagger: subagent_type=shepherd:coder             → writes agent_role="coder" (FIX 1, real)
#   3. coder + git commit → DENY (real tagger, real guard) *** the ONE assertion ***
#   4. coder + git add <file>                           → DENY
#   5. coder + git add -A                                → DENY
#   6. coder + git reset --hard                          → DENY
#   7. coder + git checkout main                         → DENY
#   8. coder + git stash                                 → DENY
#   9. coder + git push                                  → DENY
#  10. coder + git worktree add                          → DENY
#  11. coder + git branch -D foo                         → DENY
#  12. coder + git -C <path> commit (global opt)         → DENY
#  13. coder + git status && git commit (mixed)          → DENY
#  14. coder + git status                                → PASS (read-only)
#  15. coder + git diff                                  → PASS
#  16. coder + git log --oneline -5                      → PASS
#  17. coder + git show HEAD                              → PASS
#  18. coder + git rev-parse HEAD (Step 0.5)              → PASS
#  19. coder + rg pattern (no git)                        → PASS
#  20. auditor (real tagger) + git commit                 → PASS (guard only polices coder)
#  21. untagged/unresolved + git commit                   → PASS but WARN (FIX 2/3 — root not denied)
#  22. untagged/unresolved + git status                   → PASS, no warn (ordinary read, no noise)

set -uo pipefail
cd "$(dirname "$0")"
SCRIPT="$(cd .. && pwd)/scripts/coder_git_guard.sh"
TAGGER="$(cd .. && pwd)/scripts/agent_invocation_tagger.sh"

fails=0; total=0
pass()  { printf '  PASS  %s\n' "$1"; }
fail()  { printf '  FAIL  %s — %s\n' "$1" "$2"; fails=$((fails+1)); }
is_deny()  { printf '%s' "$1" | grep -q '"permissionDecision"[[:space:]]*:[[:space:]]*"deny"'; }
has_code() { printf '%s' "$1" | grep -q "CODER-GIT-WRITE"; }
is_warn()  { printf '%s' "$1" | grep -q '"additionalContext"'; }
run_hook() { printf '%s' "$1" | bash "$SCRIPT" 2>/dev/null; return 0; }

# current_role needs jq or python3 to read the dispatch record; without either
# the role resolves to "unknown" and every coder case would false-warn instead
# of denying (see coder_git_guard.sh's own ROLE-DETECTION header).
if ! command -v jq >/dev/null 2>&1 && ! command -v python3 >/dev/null 2>&1; then
  printf '  SKIP  all cases — neither jq nor python3 available for role resolution\n'
  exit 0
fi
if ! command -v python3 >/dev/null 2>&1; then
  printf '  SKIP  all cases — python3 required to build realistic Agent()/Bash() payloads\n'
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

# --- shared ephemeral shepherd repo ---------------------------------------
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

# --- Agent() payload builder + REAL tagger invocation ---------------------
# Mirrors a real PreToolUse(Agent) hook payload: tool_input.subagent_type is
# the dispatch-law-mandated field FIX 1 reads. Runs the REAL
# agent_invocation_tagger.sh so the dispatch record consumed below is
# genuinely produced by the fix under test, not hand-authored.
AGENT_PAYLOAD() { # <tool_use_id> <subagent_type e.g. shepherd:coder>
  python3 -c 'import json,sys; print(json.dumps({"session_id":"s","tool_name":"Agent","tool_use_id":sys.argv[1],"tool_input":{"subagent_type":sys.argv[2],"model":"claude-sonnet-5","prompt":"do the work"}}))' "$1" "$2"
}
tag_dispatch() { # <tool_use_id> <subagent_type>
  printf '%s' "$(AGENT_PAYLOAD "$1" "$2")" | bash "$TAGGER" >/dev/null 2>&1 || true
}

tag_dispatch coder1 shepherd:coder
tag_dispatch aud1   shepherd:auditor

# --- case 2: tagger writes agent_role from subagent_type (FIX 1, real) ----
total=$((total+1))
record_file=".shepherd/dispatch/$sprint/coder1.json"
if [[ -f "$record_file" ]] && grep -q '"agent_role"[[:space:]]*:[[:space:]]*"coder"' "$record_file"; then
  pass "tagger: subagent_type=shepherd:coder -> agent_role=coder (FIX 1)"
else
  fail "tagger: subagent_type=shepherd:coder -> agent_role=coder (FIX 1)" \
    "record missing or wrong role: $(cat "$record_file" 2>/dev/null || echo '<no file>')"
fi

# payload builder: <tool_use_id> <command> — JSON-escape the command (it may
# contain embedded quotes, e.g. bash -c "git commit").
P() {
  python3 -c 'import json,sys; print(json.dumps({"session_id":"s","tool_name":"Bash","tool_use_id":sys.argv[1],"tool_input":{"command":sys.argv[2]}}))' "$1" "$2"
}

deny_case() { # <label> <tool_use_id> <cmd>
  total=$((total+1)); local out; out=$(run_hook "$(P "$2" "$3")")
  if is_deny "$out" && has_code "$out"; then pass "$1"; else fail "$1" "expected deny+CODER-GIT-WRITE, got: ${out:0:100}"; fi
}
pass_case() { # <label> <tool_use_id> <cmd>
  total=$((total+1)); local out; out=$(run_hook "$(P "$2" "$3")")
  if ! is_deny "$out"; then pass "$1"; else fail "$1" "unexpected deny: ${out:0:100}"; fi
}

# --- case 3: THE ONE ASSERTION THAT MATTERS -------------------------------
deny_case "*** coder + git commit -> DENY (real tagger, real guard) ***" coder1 'git commit -m feat'

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
pass_case "auditor (real tagger) + git commit → PASS" aud1   'git commit -m x'

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

# --- DF-77 FIX 2/3 controls: untagged tool_use_id (root, or an unresolved
# dispatch — mechanically identical to current_role(), which is the honest
# point: neither can be distinguished from the other today) -----------------
total=$((total+1))
out=$(run_hook "$(P nodisp-untagged 'git commit -m x')")
if is_deny "$out"; then
  fail "untagged + git commit → NOT denied (root not blocked, DF-77 FIX 2)" "unexpected deny: ${out:0:100}"
elif ! is_warn "$out"; then
  fail "untagged + git commit → NOT denied (root not blocked, DF-77 FIX 2)" "expected a warn (additionalContext), got: ${out:0:100}"
else
  pass "untagged + git commit → NOT denied, but WARNS (DF-77 FIX 2/3 — root not blocked, gap stays visible)"
fi

total=$((total+1))
out=$(run_hook "$(P nodisp-untagged2 'git status')")
if is_deny "$out"; then
  fail "untagged + git status → PASS, no noise" "unexpected deny: ${out:0:100}"
elif is_warn "$out"; then
  fail "untagged + git status → PASS, no noise" "unexpected warn on an ordinary read: ${out:0:100}"
else
  pass "untagged + git status → PASS, no noise (ordinary read stays quiet)"
fi

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
