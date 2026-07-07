#!/usr/bin/env bash
# shepherd hook — PreToolUse(Bash): teammate git integration guard (v6.0.9, #99).
#
# ENFORCES: skills/shepherd/references/pipeline.md §CLOSE-FINALIZE + agents/shepherd.md
# root-only LANE-INTEGRATE seam.
#
# PROBLEM: Teammates are told in their profile (agents/conductor.md TEAMMATE
# mode) never to write to the dev branch, but #99 observed a teammate
# attempting a rebase onto dev. The profile is prose; this hook is the
# mechanical gate.
#
# RULE: A teammate session MAY:
#   • git add, git commit (in-worktree local commits — these are legitimate
#     lane commits, never blocked)
#   • git log, git status, git diff, git branch, git fetch (read-only)
#   • git worktree list (read-only worktree subcommand — allowed)
#
# A teammate session MUST NOT:
#   • git merge (onto any branch, but especially dev/main)
#   • git rebase (onto a shared/dev branch)
#   • git push (any remote write)
#   • git cherry-pick (onto dev — indicates integration intent)
#   • git worktree add (spawns a new worktree — root-exclusive)
#   • git worktree remove (destroys a worktree — root-exclusive)
#   • git worktree prune (prunes stale worktree refs — root-exclusive)
#
# These integration commands are ROOT-EXCLUSIVE via the LANE-INTEGRATE seam.
# When denied, route to root via TEAMMATE-GIT-WRITE halt code.
#
# EVENT: PreToolUse(Bash)
# STDIN: { session_id, tool_name, tool_input.command, tool_use_id, ... }
# OUTPUT:
#   {"permissionDecision":"deny","message":"..."}  — teammate git integration blocked
#   silent exit 0 — not a teammate, or allowed git command
#
# HALT CODE: TEAMMATE-GIT-WRITE (registered in agents/conductor.md + shepherd.md)
#
# TEAMMATE DETECTION: the guard queries the `teammates` table in root.db for
# a row matching the current session_id with status NOT IN ('retired','crashed').
# If sqlite3 / root.db unavailable → pass (fail-open).
#
# INTEGRATION-COMMAND DETECTION:
#   Blocked: git merge, git rebase, git push, git cherry-pick,
#            git worktree add, git worktree remove, git worktree prune
#   Allowed: git add, git commit, git log, git status, git diff, git fetch,
#            git branch, git show, git stash, git tag (read-only / local),
#            git worktree list (read-only)
#
# CAVEAT: This is a heuristic regex pass — it does not parse git argument trees
# fully. It matches any `git <forbidden-verb>` or `git worktree <forbidden-subverb>`
# occurrence in the command string. No attempt is made to detect "rebase onto THIS
# branch" vs "rebase onto a safe branch" — any git rebase from a teammate session
# is blocked because integration direction is not knowable at the PreToolUse layer
# without parsing the full command tree. This is the conservative, safe default.

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$HERE/_lib.sh" 2>/dev/null || exit 0

PAYLOAD="$(cat 2>/dev/null || true)"

# --- is_shepherd_project guard -------------------------------------------
is_shepherd_project || exit 0

# --- tool filter: only Bash ----------------------------------------------
TOOL="$(json_field "$PAYLOAD" '.tool_name' 2>/dev/null || true)"
[[ "$TOOL" == "Bash" ]] || exit 0

CMD="$(json_field "$PAYLOAD" '.tool_input.command' 2>/dev/null || true)"
SESSION="$(json_field "$PAYLOAD" '.session_id' 2>/dev/null || true)"
[[ -n "$SESSION" ]] || SESSION="nosession"
TOOL_USE_ID="$(json_field "$PAYLOAD" '.tool_use_id' 2>/dev/null || true)"

# --- fast-path: no git command at all ------------------------------------
printf '%s' "$CMD" | grep -qE '(^|[[:space:];|&])git[[:space:]]' 2>/dev/null || exit 0

# --- fast-path: explicitly allowed in-worktree git commands --------------
# git add and git commit are always permitted (local, in-worktree commits).
# Check these first to avoid false-positive on legitimate lane commits.
# Strategy: if the ONLY git verbs in the command are from the allowed set,
# skip the DB lookup entirely.
#
# Two patterns cover the two blocked command shapes:
#   FORBIDDEN_PATTERN         — single-token verbs: merge, rebase, push, cherry-pick
#   FORBIDDEN_WORKTREE_PATTERN — two-token: git worktree (add|remove|prune)
#                                Note: git worktree list is read-only and ALLOWED.
FORBIDDEN_PATTERN='(^|[[:space:];|&])git[[:space:]]+(merge|rebase|push|cherry-pick)[[:space:]]?'
FORBIDDEN_WORKTREE_PATTERN='(^|[[:space:];|&])git[[:space:]]+worktree[[:space:]]+(add|remove|prune)([[:space:]]|$)'
if ! printf '%s' "$CMD" | grep -qE "$FORBIDDEN_PATTERN" 2>/dev/null && \
   ! printf '%s' "$CMD" | grep -qE "$FORBIDDEN_WORKTREE_PATTERN" 2>/dev/null; then
  # No forbidden verb present — pass without DB lookup.
  exit 0
fi

# --- check sqlite3 availability and DB presence -------------------------
command -v sqlite3 >/dev/null 2>&1 || exit 0
NS="$(resolve_namespace 2>/dev/null || echo .shepherd)"
DB="$(hook_db_path "$NS")"
[[ -f "$DB" ]] || exit 0

# --- is this session a non-retired teammate? ----------------------------
# If the teammates table does not exist yet, sqlite3 will error → exit 0 (pass).
TEAMMATE_COUNT="$(sqlite3 "$DB" \
  "SELECT count(*) FROM teammates WHERE session_id='${SESSION//\'/\'\'}' AND status NOT IN ('retired','crashed');" \
  2>/dev/null || echo 0)"
[[ "$TEAMMATE_COUNT" =~ ^[0-9]+$ ]] || TEAMMATE_COUNT=0

if [[ "$TEAMMATE_COUNT" -eq 0 ]]; then
  # Not a registered teammate → not this guard's concern.
  pass_silent "teammate_git_guard" "Bash" "conductor-root" "$SESSION"
fi

# --- this IS a teammate and the command contains a forbidden git verb ---
# (We already confirmed at least one forbidden pattern is present above.)

# Identify which forbidden verb(s) are present for the deny message.
VERBS=""
for verb in merge rebase push cherry-pick; do
  if printf '%s' "$CMD" | grep -qE "(^|[[:space:];|&])git[[:space:]]+${verb}([[:space:]]|$)"; then
    VERBS="${VERBS:+$VERBS, }git ${verb}"
  fi
done
# Two-token worktree subcommands (add/remove/prune) — check separately because
# the subverb follows "git worktree", not "git" directly.
for wt_subverb in add remove prune; do
  if printf '%s' "$CMD" | grep -qE "(^|[[:space:];|&])git[[:space:]]+worktree[[:space:]]+${wt_subverb}([[:space:]]|$)"; then
    VERBS="${VERBS:+$VERBS, }git worktree ${wt_subverb}"
  fi
done
[[ -n "$VERBS" ]] || VERBS="forbidden git integration command"

MSG="[shepherd] TEAMMATE-GIT-WRITE — teammate may not integrate to the dev branch."$'\n'
MSG+="  Session    : ${SESSION}"$'\n'
MSG+="  Command    : ${CMD:0:200}"$'\n'
MSG+="  Verb(s)    : ${VERBS}"$'\n'
MSG+="Integration is ROOT-EXCLUSIVE (LANE-INTEGRATE seam). Teammate-conductors own"$'\n'
MSG+="in-worktree commits (git add + git commit) only. Merging, rebasing, pushing,"$'\n'
MSG+="cherry-picking onto dev, and worktree add/remove/prune are root-tier decisions"$'\n'
MSG+="— they require a diff review or explicit root orchestration before execution."$'\n'
MSG+="Action: surface SendMessage(to: lead, halt_code: TEAMMATE-GIT-WRITE) and"$'\n'
MSG+="describe the integration you need. Root will execute LANE-INTEGRATE."$'\n'
MSG+="See skills/shepherd/references/pipeline.md §CLOSE-FINALIZE + agents/shepherd.md LANE-INTEGRATE."

emit_deny "$MSG" "teammate_git_guard" "Bash" "conductor-teammate" "$SESSION"
