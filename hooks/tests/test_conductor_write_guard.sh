#!/usr/bin/env bash
# hooks/tests/test_conductor_write_guard.sh — tests for conductor_write_guard.sh
#
# Covers the PreToolUse(Edit|Write|Bash) conductor artifact/registry-write guard
# (v6.2.7 #180; git carve-back v6.3.1 — the conductor owns git directly):
#   1. No shepherd.toml → PASS.
#   2. Sprint branch + Edit → DENY CONDUCTOR-WRITE-DENIED.
#   3. Sprint branch + Write → DENY CONDUCTOR-WRITE-DENIED.
#   4. Sprint branch + Bash git commit → PASS (git is the conductor's now, v6.3.1).
#   5. Sprint branch + Bash git rebase → PASS.
#   6. Sprint branch + Bash git push → PASS.
#   7. Sprint branch + Bash git worktree remove → PASS.
#   8. Sprint branch + Bash rm -rf → DENY CONDUCTOR-WRITE-DENIED (FS mutation).
#   9. Sprint branch + Bash shctx seed verify → PASS (read-only shctx verb).
#  10. Sprint branch + Bash shctx close-lane → DENY CONDUCTOR-WRITE-DENIED (mutating shctx).
#  10b-c. Sprint branch + git checkout / git switch → PASS (git is the conductor's).
#  10d. Sprint branch + git branch --show-current → PASS (read-only).
#  11. Sprint branch + Bash git log → PASS (read-only).
#  12. Sprint branch + Bash git status → PASS (read-only).
#  13. Non-sprint branch, non-teammate + Edit → PASS (no conductor session open).
#  14. Sprint branch + tagged @coder dispatch + Edit → PASS (not the conductor's turn).
#  15. Teammate session (non-sprint branch) + Edit → DENY (leg 2 via teammates row).
#  16. Retired teammate, non-sprint branch + Edit → PASS.
#  17-21. v6.5.0 lane-plan custody exemption (seed decision 6): a teammate-
#      conductor whose session-tier marker (stamped by user_prompt_submit.sh
#      from the boot prompt's `Lane plan (YOURS):` path) names a lane may
#      Edit/Write inside ITS OWN runs/{run}/lanes/{lane}/ dir — relative or
#      absolute target shapes. A sibling lane's dir, the master runs plan, and
#      a marker-less (solo) conductor keep the full deny.

set -eu -o pipefail
cd "$(dirname "$0")"
HOOKS_DIR="$(cd .. && pwd)/scripts"
SCRIPT="$HOOKS_DIR/conductor_write_guard.sh"

fails=0
total=0
pass()  { printf '  PASS  %s\n' "$1"; }
fail()  { printf '  FAIL  %s — %s\n' "$1" "$2"; fails=$((fails+1)); }

is_deny()  { printf '%s' "$1" | grep -q '"permissionDecision"[[:space:]]*:[[:space:]]*"deny"'; }
has_code() { printf '%s' "$1" | grep -q "$2"; }

run_hook() { printf '%s' "$1" | bash "$SCRIPT" 2>/dev/null; return 0; }

P_EDIT()  { printf '{"session_id":"%s","tool_use_id":"%s","tool_name":"Edit","tool_input":{"file_path":"docs/foo.md","old_string":"a","new_string":"b"}}' "$1" "${2:-}"; }
P_EDIT_AT() { printf '{"session_id":"%s","tool_use_id":"%s","tool_name":"Edit","tool_input":{"file_path":"%s","old_string":"a","new_string":"b"}}' "$1" "${2:-}" "$3"; }
P_WRITE() { printf '{"session_id":"%s","tool_use_id":"%s","tool_name":"Write","tool_input":{"file_path":"docs/foo.md","content":"x"}}' "$1" "${2:-}"; }
P_BASH()  { printf '{"session_id":"%s","tool_use_id":"%s","tool_name":"Bash","tool_input":{"command":"%s"}}' "$1" "${2:-}" "$3"; }

# ---------------------------------------------------------------------------
# 1. No shepherd.toml → PASS.
# ---------------------------------------------------------------------------
total=$((total+1))
tmp_bare=$(mktemp -d -t shep-cwg-bare.XXXXXX)
(
  cd "$tmp_bare"
  git init -q . && git config user.email t@t && git config user.name t
  git checkout -q -b v1.0.0-dev.0
  git -c commit.gpgsign=false commit -q --allow-empty -m init
  out=$(printf '%s' "$(P_EDIT sess-bare tu-1)" | bash "$SCRIPT" 2>/dev/null) || true
  if ! is_deny "$out"; then
    printf '  PASS  no-shepherd-toml: PASS\n'
  else
    printf '  FAIL  no-shepherd-toml: PASS — got deny: %s\n' "${out:0:80}"
    exit 1
  fi
) || fails=$((fails+1))
rm -rf "$tmp_bare"

if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "  SKIP  DB-dependent cases — sqlite3 binary missing"
  echo "—— $((total-fails))/$total passed ——"
  exit "$fails"
fi

# ---------------------------------------------------------------------------
# Shared ephemeral shepherd-flagged repo on a sprint branch.
# ---------------------------------------------------------------------------
tmp=$(mktemp -d -t shep-cwg-test.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q .
git config user.email t@t
git config user.name t
git -c commit.gpgsign=false commit -q --allow-empty -m init
git checkout -q -b v1.0.0-dev.0
mkdir -p .claude .artifacts
touch .claude/shepherd.toml
DB=".artifacts/root.db"
NOW=$(( $(date +%s) * 1000 ))

sqlite3 "$DB" <<'SQL' >/dev/null 2>&1
CREATE TABLE teammates (
  id TEXT PRIMARY KEY, team_name TEXT, teammate_name TEXT, agent_type TEXT,
  session_id TEXT, spawned_at INTEGER, last_seen_at INTEGER, status TEXT
);
SQL

TM_SESSION="sess-tm-01"
TM_RETIRED="sess-tm-retired"
sqlite3 "$DB" "INSERT INTO teammates VALUES ('tm-1','team','lane-a','conductor','${TM_SESSION}',${NOW},${NOW},'active');" >/dev/null 2>&1
sqlite3 "$DB" "INSERT INTO teammates VALUES ('tm-ret','team','lane-ret','conductor','${TM_RETIRED}',${NOW},${NOW},'retired');" >/dev/null 2>&1

# ---------------------------------------------------------------------------
# 2. Sprint branch + Edit → DENY.
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(run_hook "$(P_EDIT sess-solo tu-2)")
if is_deny "$out" && has_code "$out" "CONDUCTOR-WRITE-DENIED"; then
  pass "sprint-branch + Edit: DENY CONDUCTOR-WRITE-DENIED"
else
  fail "sprint-branch + Edit: DENY CONDUCTOR-WRITE-DENIED" "out=${out:0:150}"
fi

# ---------------------------------------------------------------------------
# 3. Sprint branch + Write → DENY.
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(run_hook "$(P_WRITE sess-solo tu-3)")
if is_deny "$out" && has_code "$out" "CONDUCTOR-WRITE-DENIED"; then
  pass "sprint-branch + Write: DENY CONDUCTOR-WRITE-DENIED"
else
  fail "sprint-branch + Write: DENY CONDUCTOR-WRITE-DENIED" "out=${out:0:150}"
fi

# ---------------------------------------------------------------------------
# 4-7. Sprint branch + Bash git commit/rebase/push/worktree → PASS (git carve-back
# v6.3.1: the conductor owns git directly — no @worker for routine git).
# ---------------------------------------------------------------------------
for verb_case in "git commit -m 'fix'" 'git rebase v1.0.0' 'git push origin v1.0.0-dev.0' 'git worktree remove --force .worktrees/x'; do
  total=$((total+1))
  out=$(run_hook "$(P_BASH sess-solo tu-4 "$verb_case")")
  if ! is_deny "$out"; then
    pass "sprint-branch + Bash '$verb_case': PASS (conductor git direct, v6.3.1)"
  else
    fail "sprint-branch + Bash '$verb_case': PASS" "unexpected deny: ${out:0:150}"
  fi
done

# ---------------------------------------------------------------------------
# 8. Sprint branch + rm -rf → DENY CONDUCTOR-WRITE-DENIED (FS mutation stays dispatched).
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(run_hook "$(P_BASH sess-solo tu-8 'rm -rf .worktrees/x')")
if is_deny "$out" && has_code "$out" "CONDUCTOR-WRITE-DENIED"; then
  pass "sprint-branch + rm -rf: DENY CONDUCTOR-WRITE-DENIED"
else
  fail "sprint-branch + rm -rf: DENY" "out=${out:0:150}"
fi

# ---------------------------------------------------------------------------
# 9. Sprint branch + shctx seed verify → PASS (read-only verb).
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(run_hook "$(P_BASH sess-solo tu-9 './shctx seed verify plans/x.seed.md')")
if ! is_deny "$out"; then
  pass "sprint-branch + shctx seed verify: PASS (read-only)"
else
  fail "sprint-branch + shctx seed verify: PASS" "unexpected deny: ${out:0:150}"
fi

# ---------------------------------------------------------------------------
# 10. Sprint branch + shctx close-lane → DENY (mutating verb).
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(run_hook "$(P_BASH sess-solo tu-10 './shctx close-lane lane-a --sprint=v1.0.0-dev.0')")
if is_deny "$out" && has_code "$out" "CONDUCTOR-WRITE-DENIED"; then
  pass "sprint-branch + shctx close-lane: DENY CONDUCTOR-WRITE-DENIED (mutating)"
else
  fail "sprint-branch + shctx close-lane: DENY" "out=${out:0:150}"
fi

# ---------------------------------------------------------------------------
# 10b-10c. Sprint branch + git checkout / git switch → PASS (git carve-back
# v6.3.1: git is the conductor's; §Ban 2 keeps it off agent/lane branches by
# doctrine + bash_guard Check 1, not this guard).
# ---------------------------------------------------------------------------
for hd_case in 'git checkout v1.0.0-dev.0' 'git switch v1.0.0-dev.0'; do
  total=$((total+1))
  out=$(run_hook "$(P_BASH sess-solo tu-10b "$hd_case")")
  if ! is_deny "$out"; then
    pass "sprint-branch + Bash '$hd_case': PASS (conductor git direct)"
  else
    fail "sprint-branch + Bash '$hd_case': PASS" "unexpected deny: ${out:0:150}"
  fi
done

# ---------------------------------------------------------------------------
# 10d. Sprint branch + git branch --show-current → PASS (read-only, not -d/-D).
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(run_hook "$(P_BASH sess-solo tu-10d 'git branch --show-current')")
if ! is_deny "$out"; then
  pass "sprint-branch + git branch --show-current: PASS (read-only)"
else
  fail "sprint-branch + git branch --show-current: PASS" "unexpected deny: ${out:0:150}"
fi

# ---------------------------------------------------------------------------
# 11-12. Sprint branch + git log / git status → PASS.
# ---------------------------------------------------------------------------
for ro_case in 'git log --oneline -20' 'git status'; do
  total=$((total+1))
  out=$(run_hook "$(P_BASH sess-solo tu-11 "$ro_case")")
  if ! is_deny "$out"; then
    pass "sprint-branch + Bash '$ro_case': PASS (read-only)"
  else
    fail "sprint-branch + Bash '$ro_case': PASS" "unexpected deny: ${out:0:150}"
  fi
done

# ---------------------------------------------------------------------------
# 13. Non-sprint branch, non-teammate session + Edit → PASS (no conductor open).
# ---------------------------------------------------------------------------
total=$((total+1))
git checkout -q -b main-ish 2>/dev/null || git checkout -q main-ish
out=$(run_hook "$(P_EDIT sess-plain tu-13)")
if ! is_deny "$out"; then
  pass "non-sprint-branch + plain session + Edit: PASS (no active conductor)"
else
  fail "non-sprint-branch + plain session + Edit: PASS" "unexpected deny: ${out:0:150}"
fi

# ---------------------------------------------------------------------------
# 14. Sprint branch + tagged @coder dispatch + Edit → PASS (not conductor's turn).
# ---------------------------------------------------------------------------
git checkout -q v1.0.0-dev.0
total=$((total+1))
mkdir -p .artifacts/dispatch/v1.0.0-dev.0
echo '{"agent_role":"coder"}' > .artifacts/dispatch/v1.0.0-dev.0/tu-14.json
out=$(run_hook "$(P_EDIT sess-solo tu-14)")
if ! is_deny "$out"; then
  pass "sprint-branch + tagged @coder + Edit: PASS (not conductor)"
else
  fail "sprint-branch + tagged @coder + Edit: PASS" "unexpected deny: ${out:0:150}"
fi

# ---------------------------------------------------------------------------
# 15. Teammate session on a non-sprint-shaped branch + Edit → DENY (leg 2 via DB row).
# ---------------------------------------------------------------------------
git checkout -q main-ish
total=$((total+1))
out=$(run_hook "$(P_EDIT "$TM_SESSION" tu-15)")
if is_deny "$out" && has_code "$out" "CONDUCTOR-WRITE-DENIED"; then
  pass "teammate session + Edit (non-sprint-branch cwd): DENY"
else
  fail "teammate session + Edit (non-sprint-branch cwd): DENY" "out=${out:0:150}"
fi

# ---------------------------------------------------------------------------
# 16. Retired teammate, non-sprint branch + Edit → PASS.
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(run_hook "$(P_EDIT "$TM_RETIRED" tu-16)")
if ! is_deny "$out"; then
  pass "retired teammate + Edit (non-sprint-branch cwd): PASS"
else
  fail "retired teammate + Edit (non-sprint-branch cwd): PASS" "unexpected deny: ${out:0:150}"
fi

# ---------------------------------------------------------------------------
# 17-20. v6.5.0 lane-plan custody exemption. Stamp the teammate's session-tier
# marker through the REAL stamper (user_prompt_submit.sh over a rendered boot
# prompt carrying `Lane plan (YOURS):`), then drive the guard.
# ---------------------------------------------------------------------------
LANE_PLAN_REL=".shepherd/runs/v100-dev0/lanes/lane-a/plan.md"
BOOT='You are a spawned teammate-conductor.\n  Lane plan (YOURS):    .shepherd/runs/v100-dev0/lanes/lane-a/plan.md\nROOT-SESSION-NAME: shepherd-root @ abc\nINVOCATION-CONTEXT:\n  dispatcher: teammate-conductor\n'
printf '{"session_id":"%s","hook_event_name":"UserPromptSubmit","prompt":"%s"}' "$TM_SESSION" "$BOOT" \
  | bash "$HOOKS_DIR/user_prompt_submit.sh" >/dev/null 2>&1 || true

# 17. Own lane plan, repo-relative target → PASS.
total=$((total+1))
out=$(run_hook "$(P_EDIT_AT "$TM_SESSION" tu-17 "$LANE_PLAN_REL")")
if ! is_deny "$out"; then
  pass "teammate + marker + own lane plan (relative): PASS (lane custody)"
else
  fail "teammate + marker + own lane plan (relative): PASS" "unexpected deny: ${out:0:150}"
fi

# 18. Another file in the SAME lane dir, absolute target → PASS.
total=$((total+1))
out=$(run_hook "$(P_EDIT_AT "$TM_SESSION" tu-18 "$tmp/.shepherd/runs/v100-dev0/lanes/lane-a/notes.md")")
if ! is_deny "$out"; then
  pass "teammate + marker + own lane dir file (absolute): PASS (lane custody)"
else
  fail "teammate + marker + own lane dir file (absolute): PASS" "unexpected deny: ${out:0:150}"
fi

# 19. A SIBLING lane's plan → DENY (custody is scoped to the OWN lane only).
total=$((total+1))
out=$(run_hook "$(P_EDIT_AT "$TM_SESSION" tu-19 ".shepherd/runs/v100-dev0/lanes/lane-b/plan.md")")
if is_deny "$out" && has_code "$out" "CONDUCTOR-WRITE-DENIED"; then
  pass "teammate + marker + sibling lane plan: DENY"
else
  fail "teammate + marker + sibling lane plan: DENY" "out=${out:0:150}"
fi

# 20. The run's MASTER plan.md → DENY (root/engineer territory, not lane custody).
total=$((total+1))
out=$(run_hook "$(P_EDIT_AT "$TM_SESSION" tu-20 ".shepherd/runs/v100-dev0/plan.md")")
if is_deny "$out" && has_code "$out" "CONDUCTOR-WRITE-DENIED"; then
  pass "teammate + marker + master runs plan.md: DENY"
else
  fail "teammate + marker + master runs plan.md: DENY" "out=${out:0:150}"
fi

# ---------------------------------------------------------------------------
# 21. SOLO conductor (sprint branch, NO marker) editing a lane path → DENY —
#     the exemption requires the boot-stamped marker; root materializes lane
#     plans via dispatch/CLI, never Edit/Write.
# ---------------------------------------------------------------------------
git checkout -q v1.0.0-dev.0
total=$((total+1))
out=$(run_hook "$(P_EDIT_AT sess-solo tu-21 "$LANE_PLAN_REL")")
if is_deny "$out" && has_code "$out" "CONDUCTOR-WRITE-DENIED"; then
  pass "solo conductor (no marker) + lane path: DENY"
else
  fail "solo conductor (no marker) + lane path: DENY" "out=${out:0:150}"
fi

echo "—— $((total-fails))/$total passed ——"
exit "$fails"
