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
# RULE: A teammate session MAY (within its OWN lane worktree/branch):
#   • git add, git commit (in-worktree local commits — legitimate lane commits)
#   • git push (publish its OWN lane branch so root harvests a clean, final
#     product — v6.3.9 #222: a conductor is a detached manager that commits AND
#     pushes its lane after impl + adversarial-review waves, then reports to root;
#     cross-lane integration onto the shared dev branch stays root's, below)
#   • git log, git status, git diff, git branch, git fetch (read-only)
#   • git worktree list (read-only worktree subcommand — allowed)
#
# A teammate session MUST NOT (these are ROOT's LANE-INTEGRATE seam):
#   • git merge (onto any branch, but especially dev/main)
#   • git rebase (onto a shared/dev branch)
#   • git cherry-pick (onto dev — indicates integration intent)
#   • git worktree add (spawns a new worktree — root-exclusive)
#   • git worktree remove (destroys a worktree — root-exclusive)
#   • git worktree prune (prunes stale worktree refs — root-exclusive)
#   • git branch -d / -D / --delete (deletes a branch — root-exclusive; plain
#     `git branch` list/create/read stays allowed, only deletion is blocked)
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
# DB unavailable (no sqlite3, or no root.db/shepherd.db yet — a fresh lane
# worktree) → the registry lookup is skipped, not the whole guard; identity
# falls through to the marker fallback below.
#
# FAIL-CLOSED FALLBACK (DF-71 part c, v6.4.5): that DB row has been EMPTY for
# every registered teammate all sprint (`teammates.session_id` is populated
# only via `shctx teammate register --session=...`, which was optional and
# universally omitted — DF-71/DF-12), so the query above matched ZERO rows
# for every teammate, every time, and this guard fired for NOBODY. A zero-row
# lookup does NOT mean "not a teammate" — it also means "genuinely unknown"
# (root, a bystander) OR "a real teammate the registry cannot yet identify".
# Those are NOT the same and must not collapse to one verdict: a naive
# fail-closed on every zero-row lookup denies root's own git. The guard now
# falls back to the POSITIVE session-tier marker `user_prompt_submit.sh`
# stamps at <ns>/tmp/session-tier-<session> (`hooks/scripts/_lib.sh
# session_tier_marker()`) the moment ANY native teammate-spawn delivers its
# boot brief as that session's first user turn — root's own top-level session
# never receives this marker (its first turn is operator-typed, never a
# machine-rendered INVOCATION-CONTEXT boot block); see that hook's own
# comment. `coordinate_drive_guard.sh` and `conductor_write_guard.sh` already
# trust this exact marker for the identical root-vs-teammate question, so
# this reuses a proven, already-live runtime signal rather than inventing
# one.
#
# MARKER CONTENT, NOT JUST EXISTENCE (v6.4.5 rework, adversarial review after
# the wave auditor passed W8-L1): the marker's own `dispatcher` field is what
# gates the fallback now, not the marker's mere presence. `user_prompt_submit.sh`
# stamps the identical marker SHAPE for three distinct `dispatcher` values —
# `teammate-conductor`, `root-shepherd`, `engineer-self-contained` — and fires
# on ANY prompt (not only a genuine first turn) that contains a recognized
# INVOCATION-CONTEXT/`dispatcher:` line. ROOT routinely authors or quotes a
# LANE boot brief while composing one — that brief itself reads
# "dispatcher: root-shepherd" because ROOT is the one doing the dispatching —
# so an exists-only check reclassified ROOT's own persistent session as a
# teammate for the rest of the session, permanently losing merge/worktree/
# branch -d with no override. Only `dispatcher == "teammate-conductor"`
# governs here (this guard's whole concern, per its header above, is
# agents/conductor.md TEAMMATE mode); `root-shepherd` and
# `engineer-self-contained` never do, marker or not.
#
# ORDERING (v6.4.5 rework, same adversarial-review pass): the marker check
# now runs BEFORE both the `sqlite3` availability check and the DB-file-
# existence check, not after. Previously either gate `exit 0`'d the ENTIRE
# guard before the marker was ever consulted — on a checkout with no
# root.db/shepherd.db yet (exactly the state a freshly spawned lane worktree
# is in), a positively-identified teammate's forbidden git verb passed
# silently, fail-CLOSED being unreachable by construction. The registry
# lookup is now a best-effort ADDITION on top of the marker, never a
# precondition for consulting it.
#
# Marker present + dispatcher == teammate-conductor + DB row absent →
# treated as a teammate (fail CLOSED). Marker absent, or dispatcher not
# teammate-conductor → unchanged fail-open (root, or a genuine bystander).
# RESIDUAL GAP, stated plainly: a teammate whose first prompt did not match
# `user_prompt_submit.sh`'s TIER_DISP_RE (a malformed/unrecognized
# `dispatcher:` value) is neither DB-registered nor marker-stamped and still
# falls through to allow — no further signal distinguishes that case from a
# single PreToolUse(Bash) hook; closing it needs the dispatch path itself to
# guarantee the marker, which is outside this file.
#
# INTEGRATION-COMMAND DETECTION:
#   Blocked: git merge, git rebase, git cherry-pick,
#            git worktree add, git worktree remove, git worktree prune,
#            git branch -d / -D / --delete
#   Allowed: git add, git commit, git push, git log, git status, git diff,
#            git fetch, git branch (list/create — no delete flag), git show,
#            git stash, git tag (local/publish), git worktree list (read-only)
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
# Three patterns cover the three blocked command shapes:
#   FORBIDDEN_PATTERN              — single-token verbs: merge, rebase, cherry-pick
#                                     (push is DELIBERATELY absent — a teammate
#                                     publishing its own lane branch is allowed,
#                                     #222 / .shepherd/dispatcher-patches/v645-pc-1.md)
#   FORBIDDEN_WORKTREE_PATTERN     — two-token: git worktree (add|remove|prune)
#                                     Note: git worktree list is read-only and ALLOWED.
#   FORBIDDEN_BRANCH_DELETE_PATTERN — two-token: git branch (-d|-D|--delete)
#                                     Note: plain `git branch` (list/create) is
#                                     read/safe and ALLOWED; only deletion blocks.
FORBIDDEN_PATTERN='(^|[[:space:];|&])git[[:space:]]+(merge|rebase|cherry-pick)[[:space:]]?'
FORBIDDEN_WORKTREE_PATTERN='(^|[[:space:];|&])git[[:space:]]+worktree[[:space:]]+(add|remove|prune)([[:space:]]|$)'
FORBIDDEN_BRANCH_DELETE_PATTERN='(^|[[:space:];|&])git[[:space:]]+branch[[:space:]]+(-d|-D|--delete)([[:space:]]|$)'
if ! printf '%s' "$CMD" | grep -qE "$FORBIDDEN_PATTERN" 2>/dev/null && \
   ! printf '%s' "$CMD" | grep -qE "$FORBIDDEN_WORKTREE_PATTERN" 2>/dev/null && \
   ! printf '%s' "$CMD" | grep -qE "$FORBIDDEN_BRANCH_DELETE_PATTERN" 2>/dev/null; then
  # No forbidden verb present — pass without DB lookup.
  exit 0
fi

# --- positive teammate identity: session-tier marker, CHECKED FIRST -----
# (v6.4.5 rework — see the ORDERING + MARKER CONTENT header comments above.)
# Resolving the marker needs neither sqlite3 nor a DB file, so this MUST run
# before either DB gate below — a fresh lane worktree (no root.db/shepherd.db
# yet) must still be governed by a positively-identified teammate.
NS="$(resolve_namespace 2>/dev/null || echo .shepherd)"

MARKER_TEAMMATE=0
MARKER_PATH="$(session_tier_marker "$NS" "$SESSION")"
if [[ -f "$MARKER_PATH" ]]; then
  # Content, not existence: only a marker whose OWN `dispatcher` field reads
  # "teammate-conductor" identifies this guard's concern. `root-shepherd` and
  # `engineer-self-contained` (the marker's two other possible values) are
  # left at 0 — deliberately: a ROOT session that merely authored or quoted a
  # lane boot brief (which itself reads "dispatcher: root-shepherd") must
  # never be governed as a teammate.
  MARKER_DISPATCHER="$(json_field "$(cat "$MARKER_PATH" 2>/dev/null || true)" '.dispatcher' 2>/dev/null || true)"
  [[ "$MARKER_DISPATCHER" == "teammate-conductor" ]] && MARKER_TEAMMATE=1
fi

# --- registry lookup: best-effort, DB may not exist yet ------------------
TEAMMATE_COUNT=0
KNOWN_RETIRED=0
DB="$(hook_db_path "$NS")"
if command -v sqlite3 >/dev/null 2>&1 && [[ -f "$DB" ]]; then
  # --- is this session a non-retired teammate? ----------------------------
  # If the teammates table does not exist yet, sqlite3 will error → count 0.
  TEAMMATE_COUNT="$(sqlite3 "$DB" \
    "SELECT count(*) FROM teammates WHERE session_id='${SESSION//\'/\'\'}' AND status NOT IN ('retired','crashed');" \
    2>/dev/null || echo 0)"
  [[ "$TEAMMATE_COUNT" =~ ^[0-9]+$ ]] || TEAMMATE_COUNT=0

  # --- DF-71 part (c): fail CLOSED on a zero-row lookup that is really a
  # teammate (see the FAIL-CLOSED FALLBACK header comment above for the full
  # rationale). Before trusting the weaker marker signal, prefer STRONGER
  # registry knowledge when it exists: if a row's session_id exactly matches
  # this payload (so the registry genuinely KNOWS this session) and it was
  # excluded only by status (retired/crashed), that is definitive proof this
  # session is not this guard's concern — never override it with the marker
  # fallback below.
  KNOWN_RETIRED="$(sqlite3 "$DB" \
    "SELECT count(*) FROM teammates WHERE session_id='${SESSION//\'/\'\'}' AND status IN ('retired','crashed');" \
    2>/dev/null || echo 0)"
  [[ "$KNOWN_RETIRED" =~ ^[0-9]+$ ]] || KNOWN_RETIRED=0
fi

MARKER_FALLBACK=0
if [[ "$TEAMMATE_COUNT" -eq 0 ]] && [[ "$KNOWN_RETIRED" -eq 0 ]] \
   && [[ "$MARKER_TEAMMATE" -eq 1 ]]; then
  TEAMMATE_COUNT=1
  MARKER_FALLBACK=1
fi

if [[ "$TEAMMATE_COUNT" -eq 0 ]]; then
  # Not a registered teammate and not a marked teammate session (or a KNOWN
  # retired/crashed one) → not this guard's concern (root, or a bystander).
  pass_silent "teammate_git_guard" "Bash" "conductor-root" "$SESSION"
fi

# --- this IS a teammate and the command contains a forbidden git verb ---
# (We already confirmed at least one forbidden pattern is present above.)

# Identify which forbidden verb(s) are present for the deny message.
VERBS=""
for verb in merge rebase cherry-pick; do
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
# Two-token branch-delete flags (-d/-D/--delete) — checked separately for the
# same reason: the flag follows "git branch", not "git" directly.
for bd_flag in -d -D --delete; do
  if printf '%s' "$CMD" | grep -qE "(^|[[:space:];|&])git[[:space:]]+branch[[:space:]]+${bd_flag}([[:space:]]|$)"; then
    VERBS="${VERBS:+$VERBS, }git branch ${bd_flag}"
  fi
done
[[ -n "$VERBS" ]] || VERBS="forbidden git integration command"

MSG="[shepherd] TEAMMATE-GIT-WRITE — teammate may not integrate to the dev branch."$'\n'
MSG+="  Session    : ${SESSION}"$'\n'
if [[ "$MARKER_FALLBACK" -eq 1 ]]; then
  MSG+="  Identity   : session-tier marker (teammates.session_id not yet populated — DF-71)"$'\n'
fi
MSG+="  Command    : ${CMD:0:200}"$'\n'
MSG+="  Verb(s)    : ${VERBS}"$'\n'
MSG+="Integration is ROOT-EXCLUSIVE (LANE-INTEGRATE seam). Teammate-conductors own"$'\n'
MSG+="their lane worktree: git add + git commit + git push (their OWN lane branch)."$'\n'
MSG+="Merging, rebasing, cherry-picking onto dev, worktree add/remove/prune, and"$'\n'
MSG+="branch -d/-D/--delete are root-tier decisions — they require a diff review or"$'\n'
MSG+="explicit root orchestration."$'\n'
MSG+="Action: surface SendMessage(to: lead, halt_code: TEAMMATE-GIT-WRITE) and"$'\n'
MSG+="describe the integration you need. Root will execute LANE-INTEGRATE."$'\n'
MSG+="See skills/shepherd/references/pipeline.md §CLOSE-FINALIZE + agents/shepherd.md LANE-INTEGRATE."

emit_deny "$MSG" "teammate_git_guard" "Bash" "conductor-teammate" "$SESSION"
