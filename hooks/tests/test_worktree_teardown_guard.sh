#!/usr/bin/env bash
# hooks/tests/test_worktree_teardown_guard.sh — tests for worktree_teardown_guard.sh
#
# Covers the PreToolUse(Bash) blanket worktree teardown guard (v6.1.0, #141):
#   1. Live teammate + `git worktree prune`                        → DENY
#   2. Live teammate + blanket list|remove pipeline               → DENY
#   3. Live teammate + scoped single-lane remove (.worktrees/…)   → PASS
#   4. ZERO live teammates + blanket teardown                     → PASS
#   5. Non-worktree git command (`git status`)                    → PASS
#   6. Config `off`                                               → PASS even with live + blanket
#   7. Config `warn`                                              → PASS (stderr only, no deny)
#   8. No .claude/shepherd.toml                                   → PASS (not a shepherd project)

set -eu -o pipefail
cd "$(dirname "$0")"
HOOKS_DIR="$(cd .. && pwd)/scripts"
SCRIPT="$HOOKS_DIR/worktree_teardown_guard.sh"

fails=0
total=0
pass()  { printf '  PASS  %s\n' "$1"; }
fail()  { printf '  FAIL  %s — %s\n' "$1" "$2"; fails=$((fails+1)); }
skip()  { printf '  SKIP  %s — %s\n' "$1" "$2"; }

is_deny()     { printf '%s' "$1" | grep -q '"permissionDecision"[[:space:]]*:[[:space:]]*"deny"'; }
has_haltcode(){ printf '%s' "$1" | grep -q 'WORKTREE-TEARDOWN-LIVE'; }

run_hook() {
  local payload="$1"
  printf '%s' "$payload" | bash "$SCRIPT" 2>/dev/null
  return 0
}

P_BASH_CMD() {
  printf '{"session_id":"%s","tool_name":"Bash","tool_input":{"command":"%s"}}' "$1" "$2"
}

# ---------------------------------------------------------------------------
# 1. No shepherd.toml → PASS (not a shepherd project; guard fast-paths).
# ---------------------------------------------------------------------------
total=$((total+1))
tmp_bare=$(mktemp -d -t shep-wtg-bare.XXXXXX)
(
  cd "$tmp_bare"
  git init -q . && git config user.email t@t && git config user.name t
  git -c commit.gpgsign=false commit -q --allow-empty -m init
  out=$(printf '%s' "$(P_BASH_CMD sess-bare 'git worktree prune')" | bash "$SCRIPT" 2>/dev/null) || true
  if ! is_deny "$out"; then
    printf '  PASS  no-shepherd-toml: PASS\n'
  else
    printf '  FAIL  no-shepherd-toml: PASS — unexpected deny: %s\n' "${out:0:80}"
    exit 1
  fi
) || fails=$((fails+1))
rm -rf "$tmp_bare"

# ---------------------------------------------------------------------------
# Skip DB-dependent tests when sqlite3 is unavailable.
# ---------------------------------------------------------------------------
if ! command -v sqlite3 >/dev/null 2>&1; then
  skip "DB-dependent cases (2-8)" "sqlite3 binary missing"
  echo "—— $((total-fails))/$total passed ——"
  exit "$fails"
fi

# ---------------------------------------------------------------------------
# Ephemeral shepherd-flagged repo + minimal DB with teammates + v_teammates_live.
# Schema mirrors test_coordinate_drive_guard.sh (migration 0007 subset).
# ---------------------------------------------------------------------------
tmp=$(mktemp -d -t shep-wtg-test.XXXXXX)
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

sqlite3 "$DB" <<SQL >/dev/null 2>&1
CREATE TABLE teammates (
  id TEXT PRIMARY KEY, team_name TEXT, teammate_name TEXT,
  agent_type TEXT, spawned_at INTEGER, last_seen_at INTEGER, status TEXT
);
CREATE VIEW v_teammates_live AS
  SELECT t.*, (strftime('%s','now')*1000 - t.last_seen_at) AS ms_since_seen
  FROM teammates t WHERE t.status NOT IN ('crashed','retired');
SQL

reset_db()        { sqlite3 "$DB" "DELETE FROM teammates;" >/dev/null 2>&1; }
add_live()        { sqlite3 "$DB" "INSERT INTO teammates (id,team_name,teammate_name,agent_type,spawned_at,last_seen_at,status) VALUES ('$1','team','$1','conductor',$NOW,$NOW,'active');" >/dev/null 2>&1; }
add_retired()     { sqlite3 "$DB" "INSERT INTO teammates (id,team_name,teammate_name,agent_type,spawned_at,last_seen_at,status) VALUES ('$1','team','$1','conductor',$NOW,$NOW,'retired');" >/dev/null 2>&1; }

# ---------------------------------------------------------------------------
# 2. Live teammate + `git worktree prune` → DENY + WORKTREE-TEARDOWN-LIVE.
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_live "lane-a"
out=$(run_hook "$(P_BASH_CMD "s2" 'git worktree prune')")
if is_deny "$out" && has_haltcode "$out"; then
  pass "live + git worktree prune: DENY + WORKTREE-TEARDOWN-LIVE"
else
  fail "live + git worktree prune: DENY" "out=${out:0:120}"
fi

# ---------------------------------------------------------------------------
# 3. Live teammate + blanket list|remove pipeline → DENY.
# Build payload with python3 to avoid JSON quoting hazards in the command.
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_live "lane-a"
BLANKET_PAYLOAD="$(python3 -c '
import json
cmd = "git worktree list | grep agent- | while read p rest; do git worktree remove --force \"$p\"; done"
print(json.dumps({"session_id":"s3","tool_name":"Bash","tool_input":{"command":cmd}}))
')"
out=$(printf '%s' "$BLANKET_PAYLOAD" | bash "$SCRIPT" 2>/dev/null) || true
if is_deny "$out" && has_haltcode "$out"; then
  pass "live + blanket list|remove: DENY + WORKTREE-TEARDOWN-LIVE"
else
  fail "live + blanket list|remove: DENY" "out=${out:0:120}"
fi

# ---------------------------------------------------------------------------
# 4. Live teammate + scoped single-lane remove (.worktrees/…) → PASS.
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_live "lane-a"
out=$(run_hook "$(P_BASH_CMD "s4" 'git worktree remove --force .worktrees/v610-dev0-A')")
if ! is_deny "$out"; then
  pass "live + scoped single-lane remove: PASS"
else
  fail "live + scoped single-lane remove: PASS" "unexpected deny: ${out:0:120}"
fi

# ---------------------------------------------------------------------------
# 5. ZERO live teammates + blanket teardown → PASS (teardown at CLOSE is OK).
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_retired "lane-a"
out=$(run_hook "$(P_BASH_CMD "s5" 'git worktree prune')")
if ! is_deny "$out"; then
  pass "no live teammates + prune: PASS (CLOSE teardown allowed)"
else
  fail "no live teammates + prune: PASS" "unexpected deny: ${out:0:120}"
fi

# ---------------------------------------------------------------------------
# 6. Non-worktree git command → PASS.
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_live "lane-a"
out=$(run_hook "$(P_BASH_CMD "s6" 'git status')")
if ! is_deny "$out"; then
  pass "non-worktree git command: PASS"
else
  fail "non-worktree git command: PASS" "unexpected deny: ${out:0:120}"
fi

# ---------------------------------------------------------------------------
# 7. Config `off` → PASS even with live teammate + blanket teardown.
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_live "lane-a"
printf '[spawn]\nworktree_teardown_guard = "off"\n' > .claude/shepherd.toml
out=$(run_hook "$(P_BASH_CMD "s7" 'git worktree prune')")
if ! is_deny "$out"; then
  pass "config off: PASS (guard disabled)"
else
  fail "config off: PASS" "unexpected deny: ${out:0:120}"
fi
printf '' > .claude/shepherd.toml

# ---------------------------------------------------------------------------
# 8. Config `warn` → PASS (stderr note, no deny JSON) with live + blanket.
# ---------------------------------------------------------------------------
total=$((total+1)); reset_db; add_live "lane-a"
printf '[spawn]\nworktree_teardown_guard = "warn"\n' > .claude/shepherd.toml
out=$(printf '%s' "$(P_BASH_CMD "s8" 'git worktree prune')" | bash "$SCRIPT" 2>/dev/null)
if ! is_deny "$out"; then
  pass "config warn: PASS (no deny; warn mode)"
else
  fail "config warn: PASS" "unexpected deny: ${out:0:120}"
fi
printf '' > .claude/shepherd.toml

echo "—— $((total-fails))/$total passed ——"
exit "$fails"
