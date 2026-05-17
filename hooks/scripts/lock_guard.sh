#!/usr/bin/env bash
# shepherd hook — Write/Edit path-policy + sprint lock guard (v5.1.2)
#
# Fires at PreToolUse(Write|Edit). Three checks (first-match-wins):
#
# 1. role-based write-path BLOCK — @discovery / @auditor / @coder Writes outside their authorized path
# 2. sprint lock WARN            — different session holds .shepherd/shepherd.lock
# 3. otherwise pass
#
# Role-write-path policy:
#   @discovery — Write only to {paths.reports}/<date>-discovery-*.md
#   @auditor   — Write only to {paths.reports}/<date>-{intro-,}audit-*.md
#   @coder     — Write only inside [WORKTREE].Path (recorded at dispatch by agent_invocation_tagger)
#   others     — passthrough (no constraint enforced at hook layer)
#
# Input  (stdin): PreToolUse JSON { tool_name, tool_input, tool_use_id, session_id, ... }
# Output (stdout):
#   {"permissionDecision":"deny","message":"..."}    — Check 1
#   {"additionalContext":"..."}                       — Check 2
#   exit 0 silently otherwise.

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

input=$(cat)
is_shepherd_project || exit 0

tool=$(json_field "$input" '.tool_name')
case "$tool" in Write|Edit) ;; *) exit 0 ;; esac

tool_use_id=$(json_field "$input" '.tool_use_id')
session=$(json_field "$input" '.session_id')
sprint=$(current_sprint)
role=$(current_role "$tool_use_id" "$sprint")

# Extract the file path the tool is writing/editing.
file_path=$(json_field "$input" '.tool_input.file_path')
[[ -z "$file_path" ]] && file_path=$(json_field "$input" '.tool_input.path')

# ---------------------------------------------------------------------------
# Check 1 — role-based write-path enforcement (BLOCK)
# ---------------------------------------------------------------------------
case "$role" in
  discovery)
    # Allow only {paths.reports}/<date>-discovery-*.md
    if ! printf '%s' "$file_path" | grep -qE '/reports/[0-9]{4}-[0-9]{2}-[0-9]{2}-discovery-.+\.md$'; then
      msg="[shepherd] DISCOVERY-WRITE-PATH BLOCKED — @discovery may only Write to {paths.reports}/<date>-discovery-<id>.md"$'\n'
      msg+="  Attempted:  $file_path"$'\n'
      msg+="  Role:       discovery (from dispatch tag $tool_use_id)"$'\n'
      msg+="See doctrines/discovery-readonly.md §Hard prohibitions."
      emit_deny "$msg" "lock_guard" "$tool" "$role" "$session"
    fi
    ;;
  auditor)
    # Allow {paths.reports}/<date>-{audit,intro-audit}-<concern>.md
    if ! printf '%s' "$file_path" | grep -qE '/reports/[0-9]{4}-[0-9]{2}-[0-9]{2}-(intro-)?audit-.+\.md$'; then
      msg="[shepherd] AUDITOR-WRITE-PATH BLOCKED — @auditor may only Write to {paths.reports}/<date>-(intro-)audit-<concern>.md"$'\n'
      msg+="  Attempted:  $file_path"$'\n'
      msg+="  Role:       auditor (from dispatch tag $tool_use_id)"$'\n'
      msg+="See doctrines/auditor-readonly.md §What auditors DO NOT."
      emit_deny "$msg" "lock_guard" "$tool" "$role" "$session"
    fi
    ;;
  coder)
    # Coder must Write inside its worktree. Look up the recorded [WORKTREE].Path
    # from the dispatch tag (agent_invocation_tagger writes this when present).
    ns=$(resolve_namespace)
    dispatch_file="$ns/dispatch/$sprint/${tool_use_id}.json"
    worktree_path=""
    if [[ -f "$dispatch_file" ]] && command -v jq &>/dev/null; then
      worktree_path=$(jq -r '.worktree_path // empty' "$dispatch_file" 2>/dev/null || true)
    fi
    # If we don't have a recorded worktree_path, allow (best-effort — don't
    # block the operator's manual conductor edits via main chat).
    if [[ -n "$worktree_path" ]]; then
      # Resolve to absolute paths for comparison
      abs_file=$(cd "$(dirname "$file_path")" 2>/dev/null && pwd)/$(basename "$file_path") || abs_file="$file_path"
      case "$abs_file" in
        "$worktree_path"/*) ;;  # OK — inside worktree
        *)
          msg="[shepherd] CODER-WORKTREE-CONFINEMENT BLOCKED — @coder Write outside [WORKTREE].Path"$'\n'
          msg+="  Attempted:    $file_path"$'\n'
          msg+="  Worktree:     $worktree_path"$'\n'
          msg+="  Role:         coder (from dispatch tag $tool_use_id)"$'\n'
          msg+="Writes outside the worktree are silently dropped from cherry-pick."$'\n'
          msg+="See doctrines/worktree-confinement.md."
          emit_deny "$msg" "lock_guard" "$tool" "$role" "$session"
          ;;
      esac
    fi
    ;;
  *)
    # conductor / engineer / critic / worker / unknown — no write-path constraint at hook layer
    ;;
esac

# ---------------------------------------------------------------------------
# Check 2 — sprint lock conflict (WARN, do not block)
# ---------------------------------------------------------------------------
ns=$(resolve_namespace)
lock_file=""
for candidate in "$ns/shepherd.lock" ".artifacts/shepherd.lock" ".shepherd/shepherd.lock"; do
  [[ -f "$candidate" ]] && { lock_file="$candidate"; break; }
done
if [[ -n "$lock_file" ]]; then
  if command -v jq &>/dev/null; then
    lock_session=$(jq -r '.session_id // empty' "$lock_file" 2>/dev/null || true)
    lock_sprint=$(jq -r '.sprint // empty' "$lock_file" 2>/dev/null || true)
  else
    lock_session=$(python3 -c "import json; d=json.load(open('$lock_file')); print(d.get('session_id',''))" 2>/dev/null || true)
    lock_sprint=$(python3 -c "import json; d=json.load(open('$lock_file')); print(d.get('sprint',''))" 2>/dev/null || true)
  fi
  if [[ -n "$lock_session" && "$lock_session" != "$session" ]]; then
    sprint_hint=""
    [[ -n "$lock_sprint" ]] && sprint_hint=" (sprint: $lock_sprint)"
    msg="[shepherd] sprint lock conflict: $lock_file is held by session ${lock_session}${sprint_hint}."$'\n'
    msg+="A concurrent conductor session may be active. Verify before writing."$'\n'
    msg+="If the prior session is dead, delete $lock_file to release the lock."
    emit_context "$msg" "lock_guard" "$tool" "$role" "$session"
  fi
fi

pass_silent "lock_guard" "$tool" "$role" "$session"
