#!/usr/bin/env bash
# shepherd hook — PreToolUse(Edit|Write|Bash): conductor artifact/registry-write
# guard (v6.2.7 #180; git carve-back v6.3.1 — "the conductor owns git + reads;
# artifact + registry writes are dispatched").
#
# WHY: agents/conductor.md keeps the conductor from AUTHORING artifacts
# (plan/report/handoff/ledger/CLAUDE.md patch) directly — a teammate returns
# structured payloads and ROOT materializes them — so Edit/Write, non-git tree
# mutation (rm/mv/sed -i/touch, redirection into a file), and mutating `shctx`
# state verbs stay @worker/root territory. This hook is that mechanical backstop.
#
# GIT CARVE-BACK (v6.3.1): the v6.2.7 model also routed every git-write through
# @worker, which made the conductor spawn a worker just to run two git commands
# — wasteful. Coders/workers own NO git (#187), so the CONDUCTOR commits its
# lane's coder output DIRECTLY (and at root/solo tier pushes + rebases too);
# @worker is dispatched only for a BULK git batch. Cross-lane INTEGRATION onto
# the dev branch stays root-exclusive for a TEAMMATE-conductor, but that seam is
# teammate_git_guard.sh's job (TEAMMATE-GIT-WRITE), not this hook's. So this
# guard no longer denies any git command.
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
# `gh` read calls, `shctx query/search/status/doctor/dash/inject/models show/
# refresh/lint/seed verify/plan verify/plan hash/
# graph compile --verify`) passes through unmatched — deny-list, not
# allow-list, so an unanticipated read-only command is never falsely blocked
# (same philosophy as teammate_git_guard.sh's fail-open default).
#
# CAVEAT: heuristic regex pass over the command string, not a parsed argument
# tree — the same acknowledged limitation teammate_git_guard.sh documents.
#
# HALT CODE: CONDUCTOR-WRITE-DENIED — Edit/Write, or a Bash FS/registry-write
# (git is NOT denied here, v6.3.1) — registered in agents/conductor.md §Halt codes.

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

# v6.3.1: git is NO LONGER blocked here. The conductor manages its worktree,
# commits (its own lane's coder output — coders own no git, #187), pushes, and
# rebases DIRECTLY — dispatching @worker for two git commands is wasteful; only
# a BULK git batch earns a @worker. Cross-lane INTEGRATION onto the dev branch
# stays root-exclusive for a TEAMMATE-conductor, but that seam is enforced by
# teammate_git_guard.sh (TEAMMATE-GIT-WRITE), not here. So GIT_WRITE_PATTERN and
# GIT_WORKTREE_WRITE_PATTERN are retired from this guard's deny-list.
# filesystem mutation / in-place edit (non-git tree mutation stays dispatched).
FS_WRITE_PATTERN='(^|[[:space:];|&])(rm|mv|sed[[:space:]]+-i|touch)([[:space:]]|$)'
# shell redirection into a file (heuristic — a bare `>`/`>>` not part of a
# comparison operator; excludes /dev/null and process-substitution `>()`).
REDIRECT_PATTERN='[^<>]>[[:space:]]*[^&|[:space:](][^[:space:]]*'
# shctx subcommands that mutate registry/state rather than read it.
SHCTX_WRITE_PATTERN='shctx[[:space:]]+(seed|plan[[:space:]]+record-critique|close-lane|adapt[[:space:]]+(roll|reflect)|loop[[:space:]]+(init|record|close|native-cmd)|loop[[:space:]]+focus[[:space:]]+upsert|mem[[:space:]]+(add|pin|unpin|rm|delete)|lock[[:space:]]+(acquire|release)|worktree[[:space:]]+(create-batch|merge|gc)|config[[:space:]]+(init|claude-md)|migrate|prune[[:space:]].*--confirm|release|dups[[:space:]]+registry|handoff|export|style[[:space:]]+(init|edit))([[:space:]]|$)'
# `shctx seed verify` is read-only validation, not authorship — strip any such
# occurrence from the test copy before running the mutating-verb match above,
# so it doesn't false-positive on the bare "seed" alternative.
CMD_FOR_SHCTX_CHECK="$(printf '%s' "$CMD" | sed -E 's/shctx[[:space:]]+seed[[:space:]]+verify/shctx __seed_verify_exempt__/g')"

MATCHED=""
for pat_name in FS_WRITE_PATTERN REDIRECT_PATTERN; do
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

MSG="[shepherd] CONDUCTOR-WRITE-DENIED — filesystem/registry mutation is @worker's (v6.3.1)."$'\n'
MSG+="  Command    : ${CMD:0:200}"$'\n'
MSG+="  Matched    : ${MATCHED}"$'\n'
MSG+="Git is NOT blocked here — commit your lane DIRECTLY (root/solo also pushes +"$'\n'
MSG+="rebases; a teammate's cross-lane integration stays root's via"$'\n'
MSG+="teammate_git_guard). @worker only for a BULK git batch. But non-git tree"$'\n'
MSG+="mutation (rm/mv/sed -i/touch, shell redirection into a file) and mutating"$'\n'
MSG+="shctx state verbs (seed/close-lane/loop/mem/lock/migrate/…) stay @worker"$'\n'
MSG+="territory — compose the EXACT command and dispatch it with a deterministic"$'\n'
MSG+="brief. Read-only Bash + all git remain yours. See agents/conductor.md"$'\n'
MSG+="§Hard prohibitions + §Side-effect boundary."

emit_deny "$MSG" "conductor_write_guard" "Bash" "conductor" "$SESSION"
