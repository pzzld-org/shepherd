#!/usr/bin/env bash
# hooks/tests/test_teammate_git_guard.sh — tests for teammate_git_guard.sh
#
# Covers the PreToolUse(Bash) teammate git integration guard (v6.0.9, Item E, #99;
# hardened v6.4.5 DF-71 CRITICAL).
#
# STRUCTURE (DF-71): the PRIMARY block below runs against an UNSEEDED database —
# a `teammates` row whose `session_id` column is EMPTY, exactly the state DF-71
# measured for all six live teammates in production (`teammates.session_id` is
# populated only via `shctx teammate register --session=...`, which was optional
# and universally omitted). Before v6.4.5 the guard's `WHERE session_id=...`
# lookup matched ZERO rows against that state — the branch every real teammate
# actually hit, every command, all sprint — and silently allowed. The OLD suite
# never exercised that branch: it SEEDED `teammates.session_id` to exactly equal
# the payload's session_id, which manufactures a DB state that has never existed
# in production. That fixture is kept below as the SECONDARY block (still a valid
# regression check of the guard's verb/pattern logic), but it no longer stands in
# for "does the guard actually fire for a real teammate" — the PRIMARY block does.
#
# PRIMARY (unseeded database — the production-representative case):
#   P1.  Unregistered + unmarked session + git merge         → PASS  (residual gap,
#        documented: an unidentifiable caller stays fail-open — root/bystanders)
#   P2.  Unseeded row + session-tier MARKER + git merge      → DENY + TEAMMATE-GIT-WRITE
#        (THE DF-71 regression test — see the falsifiability note below)
#   P3.  Marker + git rebase                                  → DENY
#   P4.  Marker + git cherry-pick                              → DENY
#   P5.  Marker + git push (own lane branch, #222)             → PASS
#   P6.  Marker + git worktree add                             → DENY
#   P7.  Marker + git worktree remove                          → DENY
#   P8.  Marker + git worktree prune                           → DENY
#   P9.  Marker + git worktree list                            → PASS (read-only)
#   P10. Marker + git branch -d <name>                         → DENY  (DF-71 part b)
#   P11. Marker + git branch -D <name>                         → DENY  (DF-71 part b)
#   P12. Marker + git branch --delete <name>                   → DENY  (widened form)
#   P13. Marker + git branch <name> (create, no delete flag)   → PASS
#   P14. Marker + bare git branch (list, no delete flag)       → PASS
#   P15. Marker + git add / git commit / git log / git status  → PASS (in-worktree/read-only)
#   P16. Retired row + STALE marker (shutdown-lag edge case)   → DENY (accepted
#        fail-closed trade-off — see the comment at that test)
#   P17. Genuine root session (no row, no marker)               → PASS (root's own
#        git is never blocked — the exact false-positive DF-71 warns against)
#   P18. Non-Bash tool + marker present                         → PASS (ignored)
#   P19. Root session + MARKER whose dispatcher is root-shepherd
#        (root authored/quoted a lane boot brief) + git merge   → PASS  (v6.4.5
#        rework, adversarial-review defect (b) — marker CONTENT, not existence,
#        must gate the fallback; see the falsifiability note below)
#   P20. Teammate MARKER + git merge, with the DB FILE ABSENT
#        (a fresh lane worktree's shape — no root.db/shepherd.db yet) → DENY
#        (v6.4.5 rework, adversarial-review defect (a) — the marker check must
#        run BEFORE both DB gates; see the falsifiability note below)
#
# SECONDARY (legacy seeded-session_id fixture — kept for regression coverage of
# the verb/pattern matching itself, not for guard-activation coverage):
#   S1-S17: as the pre-v6.4.5 suite (root pass, teammate merge/rebase/push/
#   cherry-pick/add/commit/log/status, non-bash, retired, worktree add/remove/
#   prune/list, non-teammate worktree).
#
# FALSIFIABILITY (brief requirement — "prove your fix falsifiable, show the
# assertion failing before the fix and passing after"): P2 is that proof. Revert
# hooks/scripts/teammate_git_guard.sh's DF-71-part-(c) marker fallback (the block
# reading `MARKER_FALLBACK=... session_tier_marker ...`) and P2 FAILS — with no
# DB row and no fallback, TEAMMATE_COUNT stays 0 and the guard silently passes
# the merge, exactly DF-71's measured production defect. Restore the fallback and
# P2 PASSES. This was verified empirically against the pre-fix
# `git show HEAD:hooks/scripts/teammate_git_guard.sh` content while authoring
# this fix (see coder-W8-L1.md for the transcript).
#
# P19/P20 are the SAME kind of proof for the two defects an adversarial review
# found in that W8-L1 fix AFTER the wave auditor had already passed it:
#   (b) P19 — against the pre-rework guard (the one this suite's own P1-P18
#       exercised), the marker fallback tested ONLY `[[ -f "$(session_tier_
#       marker ...)" ]]` — existence, never content. A marker stamped with
#       `dispatcher: root-shepherd` (exactly what `user_prompt_submit.sh`
#       writes when ROOT authors/quotes a lane boot brief — that brief reads
#       "dispatcher: root-shepherd" because ROOT is the one dispatching) still
#       satisfied the existence check, so the pre-rework guard DENIED root's
#       own `git merge` — P19 asserting PASS FAILS against that code. Reading
#       `.dispatcher` and gating on `== "teammate-conductor"` (this fix) makes
#       P19 PASS.
#   (a) P20 — against the pre-rework guard, `command -v sqlite3 || exit 0` and
#       `[[ -f "$DB" ]] || exit 0` sat ABOVE the marker check and unconditionally
#       exited the entire script — with the DB file absent, the guard returned
#       PASS (no deny) even for a session carrying a valid teammate-conductor
#       marker. P20 asserting DENY FAILS against that code. Moving the marker
#       check above both DB gates (this fix) makes P20 DENY correctly, deriving
#       identity from the marker alone when the registry is unavailable.
# Both were traced line-by-line against the exact pre-rework source (read in
# full at the start of this fix) rather than executed against a reverted copy
# — resource-discipline for this rework forbids local test runs; the central
# auditor's own mutate-run-restore pass (the same method it already used for
# W8-L1's P2) is the fast, authoritative way to confirm both empirically.

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
  printf '{"session_id":"%s","tool_name":"Edit","tool_input":{"file_path":"foo.rs","old_string":"x","new_string":"y"}}' "$1"
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
  skip "DB-dependent cases (PRIMARY + SECONDARY)" "sqlite3 binary missing"
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

# Reuse the SAME namespace/marker helpers the guard itself uses (session_tier_
# marker, resolve_namespace) rather than re-deriving the escaping/path scheme —
# a second, hand-rolled implementation could silently drift from the guard's.
# shellcheck source=/dev/null
source "$HOOKS_DIR/_lib.sh"
NS="$(resolve_namespace)"   # resolves to "$tmp/.artifacts" (the only ns dir present)

stamp_marker() {
  # Usage: stamp_marker <session_id> [dispatcher]
  local sess="$1" disp="${2:-teammate-conductor}" marker
  marker="$(session_tier_marker "$NS" "$sess")"
  mkdir -p "$(dirname "$marker")"
  printf '{"tier":"teammate","dispatcher":"%s","lane_plan":"","stamped_at":0}\n' "$disp" > "$marker"
}

ROOT_SESSION="sess-root-01"
TM_SESSION="sess-tm-01"
TM_SESSION_RETIRED="sess-tm-retired"

# ===========================================================================
# PRIMARY — unseeded database (production-representative, DF-71).
# ===========================================================================

# Two rows, matching the EXACT production shape DF-71 measured: registered,
# ACTIVE (or retired), session_id EMPTY. Neither row's session_id will ever
# match a payload's session_id — that IS the defect this suite now proves
# the guard survives.
sqlite3 "$DB" "INSERT INTO teammates (id,team_name,teammate_name,agent_type,session_id,spawned_at,last_seen_at,status) VALUES ('tm-unseeded','team','lane-a','conductor','',${NOW},${NOW},'active');" >/dev/null 2>&1
sqlite3 "$DB" "INSERT INTO teammates (id,team_name,teammate_name,agent_type,session_id,spawned_at,last_seen_at,status) VALUES ('tm-unseeded-ret','team','lane-ret','conductor','',${NOW},${NOW},'retired');" >/dev/null 2>&1

# ---------------------------------------------------------------------------
# P1. Unregistered + UNMARKED session + git merge → PASS (documented residual
#     gap: with no DB match and no boot-time marker, the guard cannot prove
#     this caller is a teammate — same population as root/a bystander).
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(run_hook "$(P_BASH_CMD "sess-unmarked-01" 'git merge origin/dev')")
if ! is_deny "$out"; then
  pass "P1 unmarked+unseeded + git merge: PASS (residual gap, documented)"
else
  fail "P1 unmarked+unseeded + git merge: PASS" "unexpected deny: ${out:0:80}"
fi

# ---------------------------------------------------------------------------
# P2. Unseeded row + session-tier MARKER + git merge → DENY. THE DF-71
#     regression test — see the falsifiability note in the file header.
# ---------------------------------------------------------------------------
stamp_marker "$TM_SESSION"
total=$((total+1))
out=$(run_hook "$(P_BASH_CMD "$TM_SESSION" 'git merge origin/dev')")
if is_deny "$out" && has_code "$out"; then
  pass "P2 marker+unseeded + git merge: DENY + TEAMMATE-GIT-WRITE"
else
  fail "P2 marker+unseeded + git merge: DENY + TEAMMATE-GIT-WRITE" "out=${out:0:160}"
fi
total=$((total+1))
if printf '%s' "$out" | grep -q 'session-tier marker'; then
  pass "P2b deny message names the marker-fallback identity path"
else
  fail "P2b deny message names the marker-fallback identity path" "out=${out:0:200}"
fi

# ---------------------------------------------------------------------------
# P3. Marker + git rebase → DENY.
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(run_hook "$(P_BASH_CMD "$TM_SESSION" 'git rebase origin/dev')")
if is_deny "$out" && has_code "$out"; then
  pass "P3 marker + git rebase: DENY"
else
  fail "P3 marker + git rebase: DENY" "out=${out:0:120}"
fi

# ---------------------------------------------------------------------------
# P4. Marker + git cherry-pick → DENY.
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(run_hook "$(P_BASH_CMD "$TM_SESSION" 'git cherry-pick abc1234')")
if is_deny "$out" && has_code "$out"; then
  pass "P4 marker + git cherry-pick: DENY"
else
  fail "P4 marker + git cherry-pick: DENY" "out=${out:0:120}"
fi

# ---------------------------------------------------------------------------
# P5. Marker + git push (own lane branch, #222) → PASS.
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(run_hook "$(P_BASH_CMD "$TM_SESSION" 'git push origin lane-a')")
if ! is_deny "$out"; then
  pass "P5 marker + git push: PASS (lane-branch publish — #222)"
else
  fail "P5 marker + git push: PASS" "unexpected deny: ${out:0:120}"
fi

# ---------------------------------------------------------------------------
# P6-P8. Marker + git worktree add/remove/prune → DENY.
# ---------------------------------------------------------------------------
for wt in add remove prune; do
  total=$((total+1))
  case "$wt" in
    add)    cmd='git worktree add .worktrees/y main' ;;
    remove) cmd='git worktree remove --force .worktrees/x' ;;
    prune)  cmd='git worktree prune' ;;
  esac
  out=$(run_hook "$(P_BASH_CMD "$TM_SESSION" "$cmd")")
  if is_deny "$out" && has_code "$out"; then
    pass "P6-8 marker + git worktree $wt: DENY"
  else
    fail "P6-8 marker + git worktree $wt: DENY" "out=${out:0:120}"
  fi
done

# ---------------------------------------------------------------------------
# P9. Marker + git worktree list → PASS (read-only subcommand).
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(run_hook "$(P_BASH_CMD "$TM_SESSION" 'git worktree list')")
if ! is_deny "$out"; then
  pass "P9 marker + git worktree list: PASS (read-only)"
else
  fail "P9 marker + git worktree list: PASS" "unexpected deny: ${out:0:80}"
fi

# ---------------------------------------------------------------------------
# P10-P12. Marker + git branch -d / -D / --delete → DENY (DF-71 part b: the
#          guard's FORBIDDEN_PATTERN never matched branch-delete before this
#          fix — worktree add/remove/prune was ALREADY wired, contrary to
#          DF-71's own text; branch-delete was the genuine gap).
# ---------------------------------------------------------------------------
for flag in '-d' '-D' '--delete'; do
  total=$((total+1))
  out=$(run_hook "$(P_BASH_CMD "$TM_SESSION" "git branch $flag stale-lane")")
  if is_deny "$out" && has_code "$out"; then
    pass "P10-12 marker + git branch $flag: DENY"
  else
    fail "P10-12 marker + git branch $flag: DENY" "out=${out:0:120}"
  fi
done

# ---------------------------------------------------------------------------
# P13. Marker + git branch <name> (create, no delete flag) → PASS.
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(run_hook "$(P_BASH_CMD "$TM_SESSION" 'git branch new-lane-branch')")
if ! is_deny "$out"; then
  pass "P13 marker + git branch <name> (create): PASS"
else
  fail "P13 marker + git branch <name> (create): PASS" "unexpected deny: ${out:0:80}"
fi

# ---------------------------------------------------------------------------
# P14. Marker + bare git branch (list) → PASS.
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(run_hook "$(P_BASH_CMD "$TM_SESSION" 'git branch')")
if ! is_deny "$out"; then
  pass "P14 marker + bare git branch (list): PASS"
else
  fail "P14 marker + bare git branch (list): PASS" "unexpected deny: ${out:0:80}"
fi

# ---------------------------------------------------------------------------
# P15. Marker + git add / commit / log / status → PASS.
# ---------------------------------------------------------------------------
for cmd in 'git add src/lib.rs' 'git commit -m "feat: x"' 'git log --oneline -5' 'git status'; do
  total=$((total+1))
  out=$(run_hook "$(P_BASH_CMD "$TM_SESSION" "$cmd")")
  if ! is_deny "$out"; then
    pass "P15 marker + '$cmd': PASS"
  else
    fail "P15 marker + '$cmd': PASS" "unexpected deny: ${out:0:80}"
  fi
done

# ---------------------------------------------------------------------------
# P16. Retired row + STALE marker (shutdown-lag edge case) → DENY. Accepted
#      fail-closed trade-off, not a bug: the marker is stamped ONCE at boot
#      and this guard has no session_id-independent way to see a LATER
#      `shctx teammate retire` (that update is keyed by teammate_name, never
#      observable from a bare session_id at PreToolUse). A stray git call
#      from a session mid-teardown (harness shutdown is documented SLOW —
#      skills/harness/SKILL.md) gets DENIED and surfaced to root rather than
#      silently allowed — the safer failure direction DF-71 explicitly asks
#      for ("cannot prove this is safe — deny and surface").
# ---------------------------------------------------------------------------
stamp_marker "$TM_SESSION_RETIRED"
total=$((total+1))
out=$(run_hook "$(P_BASH_CMD "$TM_SESSION_RETIRED" 'git merge origin/dev')")
if is_deny "$out" && has_code "$out"; then
  pass "P16 retired-row + stale marker + git merge: DENY (accepted fail-closed trade-off)"
else
  fail "P16 retired-row + stale marker + git merge: DENY" "out=${out:0:120}"
fi

# ---------------------------------------------------------------------------
# P17. Genuine root session (no row, no marker) + git merge → PASS. Root's
#      own git is never blocked — the exact false-positive DF-71 warns
#      against a naive "zero rows → deny" flip would create.
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(run_hook "$(P_BASH_CMD "$ROOT_SESSION" 'git merge origin/dev')")
if ! is_deny "$out"; then
  pass "P17 root-session + git merge: PASS"
else
  fail "P17 root-session + git merge: PASS" "unexpected deny: ${out:0:80}"
fi
total=$((total+1))
out=$(run_hook "$(P_BASH_CMD "$ROOT_SESSION" 'git worktree remove --force .worktrees/x')")
if ! is_deny "$out"; then
  pass "P17b root-session + git worktree remove: PASS"
else
  fail "P17b root-session + git worktree remove: PASS" "unexpected deny: ${out:0:80}"
fi
total=$((total+1))
out=$(run_hook "$(P_BASH_CMD "$ROOT_SESSION" 'git branch -D stale-lane')")
if ! is_deny "$out"; then
  pass "P17c root-session + git branch -D: PASS"
else
  fail "P17c root-session + git branch -D: PASS" "unexpected deny: ${out:0:80}"
fi

# ---------------------------------------------------------------------------
# P18. Non-Bash tool + marker present → PASS (guard only ever looks at Bash).
# ---------------------------------------------------------------------------
total=$((total+1))
out=$(run_hook "$(P_NON_BASH "$TM_SESSION")")
if ! is_deny "$out"; then
  pass "P18 marker + non-bash tool: PASS (Edit tool ignored)"
else
  fail "P18 marker + non-bash tool: PASS" "unexpected deny: ${out:0:80}"
fi

# ---------------------------------------------------------------------------
# P19. Root session + MARKER whose dispatcher is root-shepherd + git merge →
#      PASS. v6.4.5 rework, adversarial-review defect (b): the pre-rework
#      guard trusted the marker's mere EXISTENCE, never its `dispatcher`
#      field. `user_prompt_submit.sh` stamps this exact marker shape for a
#      ROOT session that merely authors/quotes a lane boot brief (that brief
#      itself reads "dispatcher: root-shepherd" because ROOT is doing the
#      dispatching) — routine while composing a spawn in this very sprint.
#      Against the pre-rework guard this session would have been DENIED its
#      own `git merge` for the rest of the session, no override. See the file
#      header's falsifiability note for the line-by-line trace.
# ---------------------------------------------------------------------------
stamp_marker "$ROOT_SESSION" "root-shepherd"
total=$((total+1))
out=$(run_hook "$(P_BASH_CMD "$ROOT_SESSION" 'git merge origin/dev')")
if ! is_deny "$out"; then
  pass "P19 root-session + marker(dispatcher=root-shepherd) + git merge: PASS (defect b)"
else
  fail "P19 root-session + marker(dispatcher=root-shepherd) + git merge: PASS" "unexpected deny: ${out:0:160}"
fi

# ---------------------------------------------------------------------------
# P20. Teammate MARKER + git merge, DB FILE ABSENT (a fresh lane worktree's
#      shape — no root.db/shepherd.db yet) → DENY. v6.4.5 rework,
#      adversarial-review defect (a): the pre-rework guard's
#      `command -v sqlite3 || exit 0` and `[[ -f "$DB" ]] || exit 0` sat
#      ABOVE the marker check and exited the ENTIRE script before the marker
#      was ever consulted — fail-closed was unreachable in exactly the state
#      a freshly spawned lane worktree boots into. See the file header's
#      falsifiability note for the line-by-line trace.
# ---------------------------------------------------------------------------
total=$((total+1))
mv "$DB" "${DB}.hidden"
out=$(run_hook "$(P_BASH_CMD "$TM_SESSION" 'git merge origin/dev')")
mv "${DB}.hidden" "$DB"
if is_deny "$out" && has_code "$out"; then
  pass "P20 marker + NO DB FILE (fresh worktree) + git merge: DENY (defect a, ordering)"
else
  fail "P20 marker + NO DB FILE (fresh worktree) + git merge: DENY" "out=${out:0:160}"
fi

# ===========================================================================
# SECONDARY — legacy seeded-session_id fixture (kept for verb/pattern
# regression coverage; NOT production-representative — see the file header).
# ===========================================================================
SEED_DB=".artifacts/root-seeded.db"
sqlite3 "$SEED_DB" <<'SQL' >/dev/null 2>&1
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
sqlite3 "$SEED_DB" "INSERT INTO teammates (id,team_name,teammate_name,agent_type,session_id,spawned_at,last_seen_at,status) VALUES ('tm-1','team','lane-a','conductor','${TM_SESSION}',${NOW},${NOW},'active');" >/dev/null 2>&1
sqlite3 "$SEED_DB" "INSERT INTO teammates (id,team_name,teammate_name,agent_type,session_id,spawned_at,last_seen_at,status) VALUES ('tm-ret','team','lane-ret','conductor','${TM_SESSION_RETIRED}',${NOW},${NOW},'retired');" >/dev/null 2>&1

run_seeded_hook() {
  # Swap in the seeded DB for the duration of one call, matching hook_db_path's
  # "shepherd.db, else root.db" precedence: the unseeded root.db from the
  # PRIMARY block above must be out of the way for this block's assertions.
  local payload="$1"
  mv "$DB" "${DB}.primary"
  mv "$SEED_DB" "$DB"
  local out
  out=$(printf '%s' "$payload" | bash "$SCRIPT" 2>/dev/null) || true
  mv "$DB" "$SEED_DB"
  mv "${DB}.primary" "$DB"
  printf '%s' "$out"
}

total=$((total+1))
out=$(run_seeded_hook "$(P_BASH_CMD "$ROOT_SESSION" 'git merge origin/dev')")
if ! is_deny "$out"; then
  pass "S1 seeded: root-session + git merge: PASS"
else
  fail "S1 seeded: root-session + git merge: PASS" "unexpected deny: ${out:0:80}"
fi

total=$((total+1))
out=$(run_seeded_hook "$(P_BASH_CMD "$TM_SESSION" 'git merge origin/dev')")
if is_deny "$out" && has_code "$out"; then
  pass "S2 seeded: teammate + git merge: DENY + TEAMMATE-GIT-WRITE"
else
  fail "S2 seeded: teammate + git merge: DENY + TEAMMATE-GIT-WRITE" "out=${out:0:120}"
fi

total=$((total+1))
out=$(run_seeded_hook "$(P_BASH_CMD "$TM_SESSION" 'git rebase origin/dev')")
if is_deny "$out" && has_code "$out"; then
  pass "S3 seeded: teammate + git rebase: DENY + TEAMMATE-GIT-WRITE"
else
  fail "S3 seeded: teammate + git rebase: DENY + TEAMMATE-GIT-WRITE" "out=${out:0:120}"
fi

total=$((total+1))
out=$(run_seeded_hook "$(P_BASH_CMD "$TM_SESSION" 'git push origin lane-a')")
if ! is_deny "$out"; then
  pass "S4 seeded: teammate + git push: PASS (lane-branch publish — #222)"
else
  fail "S4 seeded: teammate + git push: PASS" "unexpected deny: ${out:0:120}"
fi

total=$((total+1))
out=$(run_seeded_hook "$(P_BASH_CMD "$TM_SESSION" 'git cherry-pick abc1234')")
if is_deny "$out" && has_code "$out"; then
  pass "S5 seeded: teammate + git cherry-pick: DENY + TEAMMATE-GIT-WRITE"
else
  fail "S5 seeded: teammate + git cherry-pick: DENY + TEAMMATE-GIT-WRITE" "out=${out:0:120}"
fi

total=$((total+1))
out=$(run_seeded_hook "$(P_BASH_CMD "$TM_SESSION" 'git add src/lib.rs')")
if ! is_deny "$out"; then
  pass "S6 seeded: teammate + git add: PASS (in-worktree allowed)"
else
  fail "S6 seeded: teammate + git add: PASS" "unexpected deny: ${out:0:80}"
fi

total=$((total+1))
out=$(run_seeded_hook "$(P_BASH_CMD "$TM_SESSION" 'git commit -m "feat: implement foo"')")
if ! is_deny "$out"; then
  pass "S7 seeded: teammate + git commit: PASS (in-worktree allowed)"
else
  fail "S7 seeded: teammate + git commit: PASS" "unexpected deny: ${out:0:80}"
fi

total=$((total+1))
out=$(run_seeded_hook "$(P_BASH_CMD "$TM_SESSION" 'git log --oneline -20')")
if ! is_deny "$out"; then
  pass "S8 seeded: teammate + git log: PASS (read-only)"
else
  fail "S8 seeded: teammate + git log: PASS" "unexpected deny: ${out:0:80}"
fi

total=$((total+1))
out=$(run_seeded_hook "$(P_BASH_CMD "$TM_SESSION" 'git status')")
if ! is_deny "$out"; then
  pass "S9 seeded: teammate + git status: PASS (read-only)"
else
  fail "S9 seeded: teammate + git status: PASS" "unexpected deny: ${out:0:80}"
fi

total=$((total+1))
out=$(run_seeded_hook "$(P_NON_BASH "$TM_SESSION")")
if ! is_deny "$out"; then
  pass "S10 seeded: non-bash tool: PASS (Edit tool ignored)"
else
  fail "S10 seeded: non-bash tool: PASS" "unexpected deny: ${out:0:80}"
fi

total=$((total+1))
out=$(run_seeded_hook "$(P_BASH_CMD "$TM_SESSION_RETIRED" 'git merge origin/dev')")
if ! is_deny "$out"; then
  pass "S11 seeded: retired-teammate + git merge: PASS"
else
  fail "S11 seeded: retired-teammate + git merge: PASS" "unexpected deny: ${out:0:80}"
fi

total=$((total+1))
out=$(run_seeded_hook "$(P_BASH_CMD "$TM_SESSION" 'git worktree remove --force .worktrees/x')")
if is_deny "$out" && has_code "$out"; then
  pass "S12 seeded: teammate + git worktree remove: DENY + TEAMMATE-GIT-WRITE"
else
  fail "S12 seeded: teammate + git worktree remove: DENY + TEAMMATE-GIT-WRITE" "out=${out:0:120}"
fi

total=$((total+1))
out=$(run_seeded_hook "$(P_BASH_CMD "$TM_SESSION" 'git worktree prune')")
if is_deny "$out" && has_code "$out"; then
  pass "S13 seeded: teammate + git worktree prune: DENY + TEAMMATE-GIT-WRITE"
else
  fail "S13 seeded: teammate + git worktree prune: DENY + TEAMMATE-GIT-WRITE" "out=${out:0:120}"
fi

total=$((total+1))
out=$(run_seeded_hook "$(P_BASH_CMD "$TM_SESSION" 'git worktree add .worktrees/y main')")
if is_deny "$out" && has_code "$out"; then
  pass "S14 seeded: teammate + git worktree add: DENY + TEAMMATE-GIT-WRITE"
else
  fail "S14 seeded: teammate + git worktree add: DENY + TEAMMATE-GIT-WRITE" "out=${out:0:120}"
fi

total=$((total+1))
out=$(run_seeded_hook "$(P_BASH_CMD "$TM_SESSION" 'git worktree list')")
if ! is_deny "$out"; then
  pass "S15 seeded: teammate + git worktree list: PASS (read-only)"
else
  fail "S15 seeded: teammate + git worktree list: PASS" "unexpected deny: ${out:0:80}"
fi

total=$((total+1))
out=$(run_seeded_hook "$(P_BASH_CMD "$ROOT_SESSION" 'git worktree remove --force .worktrees/x')")
if ! is_deny "$out"; then
  pass "S16 seeded: root-session + git worktree remove: PASS (not a teammate)"
else
  fail "S16 seeded: root-session + git worktree remove: PASS" "unexpected deny: ${out:0:80}"
fi

total=$((total+1))
out=$(run_seeded_hook "$(P_BASH_CMD "$TM_SESSION" 'git branch -d stale-lane')")
if is_deny "$out" && has_code "$out"; then
  pass "S17 seeded: teammate + git branch -d: DENY + TEAMMATE-GIT-WRITE"
else
  fail "S17 seeded: teammate + git branch -d: DENY + TEAMMATE-GIT-WRITE" "out=${out:0:120}"
fi

echo "—— $((total-fails))/$total passed ——"
exit "$fails"
