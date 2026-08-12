#!/usr/bin/env bash
# hooks/tests/teammate_git_guard_test.sh — tests for teammate_git_guard.sh
#
# Covers the PreToolUse(Bash) teammate git integration guard (v6.0.9, Item E, #99):
#   1. No shepherd.toml → PASS (not a shepherd project).
#   2. No sqlite3 → PASS (fail-open; guard cannot check teammates table).
#   3. Root session (not in teammates table) → PASS for git merge.
#   4. Teammate session + git merge → DENY with TEAMMATE-GIT-WRITE.
#   5. Teammate session + git rebase → DENY with TEAMMATE-GIT-WRITE.
#   6. Teammate session + git push → PASS (publishes its OWN lane branch — #222).
#   7. Teammate session + git cherry-pick → DENY with TEAMMATE-GIT-WRITE.
#   8. Teammate session + git add → PASS (in-worktree local commit — allowed).
#   9. Teammate session + git commit → PASS (in-worktree local commit — allowed).
#  10. Teammate session + git log → PASS (read-only).
#  11. Teammate session + git status → PASS (read-only).
#  12. Non-Bash tool → PASS (guard ignores Edit, Agent, etc).
#  13. Retired teammate + git merge → PASS (status=retired, guard does not block).
#  14. Teammate + git worktree remove → DENY with TEAMMATE-GIT-WRITE.
#  15. Teammate + git worktree prune → DENY with TEAMMATE-GIT-WRITE.
#  16. Teammate + git worktree add → DENY with TEAMMATE-GIT-WRITE.
#  17. Teammate + git worktree list → PASS (read-only subcommand).
#  18. Non-teammate + git worktree remove → PASS (not this guard's concern).

set -eu -o pipefail
cd "$(dirname "$0")"
HOOKS_DIR="$(cd .. && pwd)/scripts"
SCRIPT="$HOOKS_DIR/teammate_git_guard.sh"

fails=0
total=0
pass()  { printf '  PASS  %s\n' "$1"; }
fail()  { printf '  FAIL  %s — %s\n' "$1" "$2"; fails=$((fails+1)); }
skip()  { printf '  SKIP  %s — %s\n' "$1" "$2"; }

is_deny()  { printf '%s' "$1" | grep -q '"permissionDecision"[[:space:]]*:[[:space:]]*"deny"'; }
has_code() { printf '%s' "$1" | grep -q "TEAMMATE-GIT-WRITE"; }

run_hook() {
  local payload="$1"
  printf '%s' "$payload" | bash "$SCRIPT" 2>/dev/null
  return 0
}

# Payload builders.
P_BASH_CMD() {
  # Usage: P_BASH_CMD <session_id> <command>
  printf '{"session_id":"%s","tool_name":"Bash","tool_input":{"command":"%s"}}' "$1" "$2"
}
P_NON_BASH() {
  printf '{"session_id":"s1","tool_name":"Edit","tool_input":{"file_path":"foo.rs","old_string":"x","new_string":"y"}}'
}

# ---------------------------------------------------------------------------
# 1. No shepherd.toml → PASS.
# ---------------------------------------------------------------------------
total=$((total+1))
tmp_bare=$(mktemp -d -t shep-tgg-bare.XXXXXX)
(
  cd "$tmp_bare"
  git init -q . && git config user.email t@t && git config user.name t
  git -c commit.gpgsign=false commit -q --allow-empty -m init
  out=$(printf '%s' "$(P_BASH_CMD sess-bare 'git merge origin/dev')" | bash "$SCRIPT" 2>/dev/null) || true
  if ! is_deny "$out"; then
    printf '  PASS  no-shepherd-toml: PASS\n'
  else
    printf '  FAIL  no-shepherd-toml: PASS — got deny: %s\n' "${out:0:80}"
    exit 1
  fi
) || fails=$((fails+1))
rm -rf "$tmp_bare"

# ---------------------------------------------------------------------------
# Skip all DB-dependent tests if sqlite3 is unavailable.
# ---------------------------------------------------------------------------
if ! command -v sqlite3 >/dev/null 2>&1; then
  skip "DB-dependent cases (2-13)" "sqlite3 binary missing"
  echo "—— $((total-fails))/$total passed ——"
  exit "$fails"
fi

# ---------------------------------------------------------------------------
# Shared ephemeral shepherd-flagged repo + minimal teammates table.
# ---------------------------------------------------------------------------
tmp=$(mktemp -d -t shep-tgg-test.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q .
git config user.email t@t
git config user.name t
git -c commit.gpgsign=false commit -q --allow-empty -m init
mkdir -p .claude .artifacts
touch .claude/shepherd.toml
DB=".artifacts/root.db"
NOW=$(( $(date +%s) * 1000 ))

sqlite3 "$DB" <<'SQL' >/dev/null 2>&1
CREATE TABLE teammates (
  id TEXT PRIMARY KEY,
  team_name TEXT,
  teammate_name TEXT,
  agent_type TEXT,
  session_id TEXT,
  spawned_at INTEGER,
  last_seen_at INTEGER,
  status TEXT
);
SQL

ROOT_SESSION="sess-root-01"
TM_SESSION="sess-tm-01"
TM_SESSION_RETIRED="sess-tm-retired"

# Insert a live teammate row.
sqlite3 "$DB" "INSERT INTO teammates (id,team_name,teammate_name,agent_type,session_id,spawned_at,last_seen_at,status) VALUES ('tm-1','team','lane-a','conductor','${TM_SESSION}',${NOW},${NOW},'active');" >/dev/null 2>&1
# Insert a retired teammate row.
sqlite3 "$DB" "INSERT INTO teammates (id,team_name,teammate_name,agent_type,session_id,spawned_at,last_seen_at,status) VALUES ('tm-ret','team','lane-ret','conductor','${TM_SESSION_RETIRED}',${NOW},${NOW},'retired');" >/dev/null 2>&1

# ---------------------------------------------------------------------------
# 2. Root session (not in teammates table) + git merge → PASS.
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(run_hook "$(P_BASH_CMD "$ROOT_SESSION" 'git merge origin/dev')")
if ! is_deny "$out"; then
  pass "root-session + git merge: PASS"
else
  fail "root-session + git merge: PASS" "unexpected deny: ${out:0:80}"
fi

# ---------------------------------------------------------------------------
# 3. Teammate + git merge → DENY + TEAMMATE-GIT-WRITE.
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(run_hook "$(P_BASH_CMD "$TM_SESSION" 'git merge origin/dev')")
if is_deny "$out" && has_code "$out"; then
  pass "teammate + git merge: DENY + TEAMMATE-GIT-WRITE"
else
  fail "teammate + git merge: DENY + TEAMMATE-GIT-WRITE" "out=${out:0:120}"
fi

# ---------------------------------------------------------------------------
# 4. Teammate + git rebase → DENY.
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(run_hook "$(P_BASH_CMD "$TM_SESSION" 'git rebase origin/dev')")
if is_deny "$out" && has_code "$out"; then
  pass "teammate + git rebase: DENY + TEAMMATE-GIT-WRITE"
else
  fail "teammate + git rebase: DENY + TEAMMATE-GIT-WRITE" "out=${out:0:120}"
fi

# ---------------------------------------------------------------------------
# 5. Teammate + git push → PASS (v6.3.9 #222 — a conductor is a detached manager
#    that commits AND pushes its OWN lane branch so root harvests a clean, final
#    product; only integration onto dev (merge/rebase/cherry-pick) and worktree
#    lifecycle stay root's LANE-INTEGRATE seam).
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(run_hook "$(P_BASH_CMD "$TM_SESSION" 'git push origin lane-a')")
if ! is_deny "$out"; then
  pass "teammate + git push: PASS (lane-branch publish — #222)"
else
  fail "teammate + git push: PASS (lane-branch publish — #222)" "unexpected deny: ${out:0:120}"
fi

# ---------------------------------------------------------------------------
# 6. Teammate + git cherry-pick → DENY.
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(run_hook "$(P_BASH_CMD "$TM_SESSION" 'git cherry-pick abc1234')")
if is_deny "$out" && has_code "$out"; then
  pass "teammate + git cherry-pick: DENY + TEAMMATE-GIT-WRITE"
else
  fail "teammate + git cherry-pick: DENY + TEAMMATE-GIT-WRITE" "out=${out:0:120}"
fi

# ---------------------------------------------------------------------------
# 7. Teammate + git add → PASS (in-worktree allowed).
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(run_hook "$(P_BASH_CMD "$TM_SESSION" 'git add src/lib.rs')")
if ! is_deny "$out"; then
  pass "teammate + git add: PASS (in-worktree allowed)"
else
  fail "teammate + git add: PASS" "unexpected deny: ${out:0:80}"
fi

# ---------------------------------------------------------------------------
# 8. Teammate + git commit → PASS (in-worktree allowed).
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(run_hook "$(P_BASH_CMD "$TM_SESSION" 'git commit -m "feat: implement foo"')")
if ! is_deny "$out"; then
  pass "teammate + git commit: PASS (in-worktree allowed)"
else
  fail "teammate + git commit: PASS" "unexpected deny: ${out:0:80}"
fi

# ---------------------------------------------------------------------------
# 9. Teammate + git log → PASS (read-only).
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(run_hook "$(P_BASH_CMD "$TM_SESSION" 'git log --oneline -20')")
if ! is_deny "$out"; then
  pass "teammate + git log: PASS (read-only)"
else
  fail "teammate + git log: PASS" "unexpected deny: ${out:0:80}"
fi

# ---------------------------------------------------------------------------
# 10. Teammate + git status → PASS (read-only).
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(run_hook "$(P_BASH_CMD "$TM_SESSION" 'git status')")
if ! is_deny "$out"; then
  pass "teammate + git status: PASS (read-only)"
else
  fail "teammate + git status: PASS" "unexpected deny: ${out:0:80}"
fi

# ---------------------------------------------------------------------------
# 11. Non-Bash tool → PASS.
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(run_hook "$(P_NON_BASH)")
if ! is_deny "$out"; then
  pass "non-bash tool: PASS (Edit tool ignored)"
else
  fail "non-bash tool: PASS" "unexpected deny: ${out:0:80}"
fi

# ---------------------------------------------------------------------------
# 12. Retired teammate + git merge → PASS (status=retired, not active).
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(run_hook "$(P_BASH_CMD "$TM_SESSION_RETIRED" 'git merge origin/dev')")
if ! is_deny "$out"; then
  pass "retired-teammate + git merge: PASS"
else
  fail "retired-teammate + git merge: PASS" "unexpected deny: ${out:0:80}"
fi

# ---------------------------------------------------------------------------
# 14. Teammate + git worktree remove → DENY + TEAMMATE-GIT-WRITE.
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(run_hook "$(P_BASH_CMD "$TM_SESSION" 'git worktree remove --force .worktrees/x')")
if is_deny "$out" && has_code "$out"; then
  pass "teammate + git worktree remove: DENY + TEAMMATE-GIT-WRITE"
else
  fail "teammate + git worktree remove: DENY + TEAMMATE-GIT-WRITE" "out=${out:0:120}"
fi

# ---------------------------------------------------------------------------
# 15. Teammate + git worktree prune → DENY + TEAMMATE-GIT-WRITE.
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(run_hook "$(P_BASH_CMD "$TM_SESSION" 'git worktree prune')")
if is_deny "$out" && has_code "$out"; then
  pass "teammate + git worktree prune: DENY + TEAMMATE-GIT-WRITE"
else
  fail "teammate + git worktree prune: DENY + TEAMMATE-GIT-WRITE" "out=${out:0:120}"
fi

# ---------------------------------------------------------------------------
# 16. Teammate + git worktree add → DENY + TEAMMATE-GIT-WRITE.
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(run_hook "$(P_BASH_CMD "$TM_SESSION" 'git worktree add .worktrees/y main')")
if is_deny "$out" && has_code "$out"; then
  pass "teammate + git worktree add: DENY + TEAMMATE-GIT-WRITE"
else
  fail "teammate + git worktree add: DENY + TEAMMATE-GIT-WRITE" "out=${out:0:120}"
fi

# ---------------------------------------------------------------------------
# 17. Teammate + git worktree list → PASS (read-only subcommand).
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(run_hook "$(P_BASH_CMD "$TM_SESSION" 'git worktree list')")
if ! is_deny "$out"; then
  pass "teammate + git worktree list: PASS (read-only)"
else
  fail "teammate + git worktree list: PASS" "unexpected deny: ${out:0:80}"
fi

# ---------------------------------------------------------------------------
# 18. Non-teammate + git worktree remove → PASS (root session; not blocked).
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(run_hook "$(P_BASH_CMD "$ROOT_SESSION" 'git worktree remove --force .worktrees/x')")
if ! is_deny "$out"; then
  pass "root-session + git worktree remove: PASS (not a teammate)"
else
  fail "root-session + git worktree remove: PASS" "unexpected deny: ${out:0:80}"
fi

echo "—— $((total-fails))/$total passed ——"
exit "$fails"
