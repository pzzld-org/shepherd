#!/usr/bin/env bash
# shepherd hook — PreToolUse(Edit|Write|Bash): conductor read+dispatch-only guard
# (v6.2.7, #180 — "the conductor may read and dispatch; nothing else").
#
# WHY: agents/conductor.md prose has always said the conductor writes only
# `.md` (v6.1.x) or, as of v6.2.7, writes NOTHING at all — every artifact
# (plan/report/handoff/ledger/CLAUDE.md patch) and every git-write operation
# (gate commit, rebase-merge, branch cut/delete, worktree lifecycle, release
# pipeline) is composed by the conductor and DISPATCHED to `@worker` as a
# deterministic brief (exact content, exact command sequence). A prose-only
# contract is exactly the failure mode teammate_git_guard.sh already exists to
# close for git-integration verbs; this hook closes the same hole for the
# FULL write surface (Edit, Write, and Bash-as-a-write-vehicle), in BOTH SOLO
# and TEAMMATE conductor modes.
#
# The conductor's ONE permitted external mutation is opening/closing GitHub
# issues via `mcp__plugin_github_github__issue_write` — an MCP tool call, not
# Edit/Write/Bash, so it is never touched by this hook.
#
# EVENT: PreToolUse(Edit), PreToolUse(Write), PreToolUse(Bash)
# STDIN: { session_id, tool_name, tool_input.{file_path|command}, tool_use_id }
# OUTPUT:
#   {"permissionDecision":"deny","message":"..."}  — conductor write blocked
#   silent exit 0                                  — not a conductor turn, or
#                                                     no sprint currently open,
#                                                     or a read-safe command
#
# DETECTION (two independent legs, either satisfies "this is a conductor turn"):
#   1. `current_role` (hooks/scripts/_lib.sh) resolves "conductor" for any tool
#      call NOT tagged as an in-flight `@coder`/`@auditor`/`@worker`/`@discovery`/
#      `@engineer`/`@critic` dispatch by agent_invocation_tagger.sh — i.e. every
#      direct tool call the top-level session makes IS the conductor's, in both
#      SOLO (main chat running `/shepherd:start`) and TEAMMATE
#      (`/shepherd:start --teammate`) mode. This mirrors the documented
#      current_role fallback contract verbatim.
#   2. "Is a sprint actually open" — checked so this guard never fires on a
#      plain operator session that merely happens to sit in a shepherd-managed
#      repo but is not running `/shepherd:start` at all: HEAD matches the sprint
#      branch pattern `v{X}.{Y}.{Z}-dev.{N}` (mirrors session_open.sh's own
#      plan-validity check), OR this session_id is a registered non-retired
#      teammate row (mirrors teammate_git_guard.sh's exact query).
#
# Both legs pass (in-flight dispatch role OR no active sprint) → exit 0 silent.
#
# Edit / Write: ALWAYS denied when both legs above hold. No carve-out — "read
# and dispatch, nothing more, nothing less" per the operator directive. Route
# the content through a `@worker` dispatch instead.
#
# Bash: DENY-LIST of write-shaped commands (git integration/history-mutating
# verbs, filesystem mutation, in-place edits, shell redirection into a file,
# and the `shctx` subcommands that mutate registry/state). Everything else
# (git log/status/diff/show/branch/rev-parse/ls-remote/worktree list/fetch,
# `gh` read calls, `shctx query/search/status/doctor/dash/inject/toolkit
# list|show|md/models show/refresh/lint/seed verify/plan verify/plan hash/
# graph compile --verify`) passes through unmatched — deny-list, not
# allow-list, so an unanticipated read-only command is never falsely blocked
# (same philosophy as teammate_git_guard.sh's fail-open default).
#
# CAVEAT: heuristic regex pass over the command string, not a parsed argument
# tree — the same acknowledged limitation teammate_git_guard.sh documents.
#
# HALT CODES: CONDUCTOR-WRITE-DENIED (Edit/Write), CONDUCTOR-GIT-WRITE-DENIED
# (Bash) — both registered in agents/conductor.md §Halt codes.

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$HERE/_lib.sh" 2>/dev/null || exit 0

PAYLOAD="$(cat 2>/dev/null || true)"

# --- is_shepherd_project guard -------------------------------------------
is_shepherd_project || exit 0

TOOL="$(json_field "$PAYLOAD" '.tool_name' 2>/dev/null || true)"
case "$TOOL" in
  Edit|Write|Bash) ;;
  *) exit 0 ;;
esac

SESSION="$(json_field "$PAYLOAD" '.session_id' 2>/dev/null || true)"
[[ -n "$SESSION" ]] || SESSION="nosession"
TOOL_USE_ID="$(json_field "$PAYLOAD" '.tool_use_id' 2>/dev/null || true)"

# --- Leg 1: is this the conductor's own turn (not a tagged flock dispatch)? ---
SPRINT="$(current_sprint)"
ROLE="$(current_role "$TOOL_USE_ID" "$SPRINT" 2>/dev/null || echo conductor)"
[[ "$ROLE" == "conductor" ]] || exit 0

# --- Leg 2: is a sprint actually open? -----------------------------------
SPRINT_OPEN=0
if [[ "$SPRINT" =~ ^v[0-9]+\.[0-9]+\.[0-9]+-dev\.[0-9]+$ ]]; then
  SPRINT_OPEN=1
elif command -v sqlite3 >/dev/null 2>&1; then
  NS="$(resolve_namespace 2>/dev/null || echo .shepherd)"
  DB="$(hook_db_path "$NS")"
  if [[ -f "$DB" ]]; then
    TEAMMATE_COUNT="$(sqlite3 "$DB" \
      "SELECT count(*) FROM teammates WHERE session_id='${SESSION//\'/\'\'}' AND status NOT IN ('retired','crashed');" \
      2>/dev/null || echo 0)"
    [[ "$TEAMMATE_COUNT" =~ ^[0-9]+$ ]] || TEAMMATE_COUNT=0
    [[ "$TEAMMATE_COUNT" -gt 0 ]] && SPRINT_OPEN=1
  fi
fi
[[ "$SPRINT_OPEN" -eq 1 ]] || exit 0

# ---------------------------------------------------------------------------
# Edit / Write — always denied, no carve-out.
# ---------------------------------------------------------------------------
if [[ "$TOOL" == "Edit" || "$TOOL" == "Write" ]]; then
  FILE_PATH="$(json_field "$PAYLOAD" '.tool_input.file_path' 2>/dev/null || true)"
  MSG="[shepherd] CONDUCTOR-WRITE-DENIED — conductor is read+dispatch only (v6.2.7)."$'\n'
  MSG+="  Tool       : $TOOL"$'\n'
  MSG+="  Target     : ${FILE_PATH:-unknown}"$'\n'
  MSG+="The conductor never Edits or Writes a file, in EITHER mode — no '.md-only'"$'\n'
  MSG+="carve-out remains. Compose the exact content in your own reasoning and hand"$'\n'
  MSG+="it to a @worker dispatch as a deterministic write-brief (exact path + exact"$'\n'
  MSG+="content); read the worker's report back. The conductor's ONLY direct external"$'\n'
  MSG+="mutation is opening/closing GitHub issues via"$'\n'
  MSG+="mcp__plugin_github_github__issue_write. See agents/conductor.md"$'\n'
  MSG+="§Hard prohibitions + §Side-effect boundary."
  emit_deny "$MSG" "conductor_write_guard" "$TOOL" "conductor" "$SESSION"
fi

# ---------------------------------------------------------------------------
# Bash — deny-list of write-shaped commands.
# ---------------------------------------------------------------------------
CMD="$(json_field "$PAYLOAD" '.tool_input.command' 2>/dev/null || true)"
[[ -n "$CMD" ]] || exit 0

# git verbs that mutate history/refs/remote/worktrees.
GIT_WRITE_PATTERN='(^|[[:space:];|&])git[[:space:]]+(commit|push|merge|rebase|cherry-pick|reset|tag|switch|checkout|branch[[:space:]]+-[dD])([[:space:]]|$)'
GIT_WORKTREE_WRITE_PATTERN='(^|[[:space:];|&])git[[:space:]]+worktree[[:space:]]+(add|remove|prune)([[:space:]]|$)'
# filesystem mutation / in-place edit.
FS_WRITE_PATTERN='(^|[[:space:];|&])(rm|mv|sed[[:space:]]+-i|touch)([[:space:]]|$)'
# shell redirection into a file (heuristic — a bare `>`/`>>` not part of a
# comparison operator; excludes /dev/null and process-substitution `>()`).
REDIRECT_PATTERN='[^<>]>[[:space:]]*[^&|[:space:](][^[:space:]]*'
# shctx subcommands that mutate registry/state rather than read it.
SHCTX_WRITE_PATTERN='shctx[[:space:]]+(seed|plan[[:space:]]+record-critique|close-lane|adapt[[:space:]]+(roll|reflect)|loop[[:space:]]+(init|record|close|native-cmd)|loop[[:space:]]+focus[[:space:]]+upsert|mem[[:space:]]+(add|pin|unpin|rm|delete)|lock[[:space:]]+(acquire|release)|worktree[[:space:]]+(create-batch|merge|gc)|config[[:space:]]+(init|claude-md)|migrate|prune[[:space:]].*--confirm|release|dups[[:space:]]+registry|escalate|handoff|export|profile[[:space:]]+sync|style[[:space:]]+(init|edit))([[:space:]]|$)'
# `shctx seed verify` is read-only validation, not authorship — strip any such
# occurrence from the test copy before running the mutating-verb match above,
# so it doesn't false-positive on the bare "seed" alternative.
CMD_FOR_SHCTX_CHECK="$(printf '%s' "$CMD" | sed -E 's/shctx[[:space:]]+seed[[:space:]]+verify/shctx __seed_verify_exempt__/g')"

MATCHED=""
for pat_name in GIT_WRITE_PATTERN GIT_WORKTREE_WRITE_PATTERN FS_WRITE_PATTERN REDIRECT_PATTERN; do
  pat="${!pat_name}"
  if printf '%s' "$CMD" | grep -qE "$pat" 2>/dev/null; then
    MATCHED="${MATCHED:+$MATCHED, }${pat_name%_PATTERN}"
  fi
done
if printf '%s' "$CMD_FOR_SHCTX_CHECK" | grep -qE "$SHCTX_WRITE_PATTERN" 2>/dev/null; then
  MATCHED="${MATCHED:+$MATCHED, }SHCTX_WRITE"
fi

if [[ -z "$MATCHED" ]]; then
  pass_silent "conductor_write_guard" "Bash" "conductor" "$SESSION"
fi

MSG="[shepherd] CONDUCTOR-GIT-WRITE-DENIED — conductor is read+dispatch only (v6.2.7)."$'\n'
MSG+="  Command    : ${CMD:0:200}"$'\n'
MSG+="  Matched    : ${MATCHED}"$'\n'
MSG+="Gate commits, rebase-merges, branch cuts/deletes, worktree create/remove,"$'\n'
MSG+="filesystem mutation, and any shctx write verb are @worker territory now —"$'\n'
MSG+="compose the EXACT command sequence and dispatch it to @worker with a"$'\n'
MSG+="deterministic brief (no judgment left to worker beyond running the given"$'\n'
MSG+="commands and reporting output). Read-only Bash (git log/status/diff/show/"$'\n'
MSG+="branch/worktree list, gh read calls, shctx query/search/status/doctor/dash/"$'\n'
MSG+="inject/toolkit/models show/refresh/lint/seed verify/plan verify/graph"$'\n'
MSG+="compile --verify) remains yours. See agents/conductor.md §Hard prohibitions"$'\n'
MSG+="+ §Side-effect boundary."

emit_deny "$MSG" "conductor_write_guard" "Bash" "conductor" "$SESSION"
