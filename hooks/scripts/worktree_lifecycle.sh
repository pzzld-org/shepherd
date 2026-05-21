#!/usr/bin/env bash
# shepherd hook — WorktreeCreate / WorktreeRemove lifecycle (v5.1.8).
#
# Closes GitHub issue #22 — zombie worktree refs accumulate after force-remove
# with no cleanup step.
#
# Single script bound to BOTH events. Branches on $hook_event_name:
#
#   • WorktreeCreate — record path + branch + tool_use_id + ts in the
#     SQLite `worktrees` table (status='active').
#
#   • WorktreeRemove — UPDATE the matching row to status='removed' +
#     removed_at=<epoch_ms>; then sweep `worktree-agent-*` refs and prune
#     any whose `git rev-parse --verify` fails (no commit / dangling ref).
#
# Discipline:
#   • Never block.    Exit 0 unconditionally; DB/IO/git failures swallowed.
#   • Idempotent.     Re-running on the same payload is a no-op (UPDATE
#                     filters on status='active'; branch -D is git-no-op
#                     if the ref already vanished).
#   • Quiet.          No stdout; stderr only on real zombie cleanup.
#
# Input  (stdin): WorktreeCreate / WorktreeRemove JSON. Per Claude Code docs
# (https://code.claude.com/docs/en/hooks), the canonical hook envelope carries
# `session_id`, `hook_event_name`, `tool_use_id` at the top level. The
# worktree-specific fields are NOT formally documented as of 2026-05; this
# hook reads `.worktree.path` and `.worktree.branch` defensively and falls
# back to `.path` / `.branch` / pwd / current HEAD if absent. Schema drift
# surfaces in the log_event payload — operators can audit jsonl entries to
# correct the field paths.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=_lib.sh
source "$HERE/_lib.sh"

INPUT="$(cat || true)"
[[ -z "$INPUT" ]] && exit 0

event=$(json_field "$INPUT" '.hook_event_name')
case "$event" in
  WorktreeCreate|WorktreeRemove) ;;
  *) exit 0 ;;
esac

# DB gate: a missing DB or sqlite3 binary is a no-op (idempotent silent skip).
ns=$(resolve_namespace)
DB="$ns/root.db"
[[ -f "$DB" ]] || exit 0
command -v sqlite3 >/dev/null 2>&1 || exit 0

# Confirm the `worktrees` table exists (migration 0008 may not have been
# applied yet on this project). If absent, exit 0 silently.
has_table=$(sqlite3 "$DB" \
  "SELECT name FROM sqlite_master WHERE type='table' AND name='worktrees';" \
  2>/dev/null || true)
[[ "$has_table" = "worktrees" ]] || exit 0

# Parse payload fields defensively. Try .worktree.<f> first, then top-level.
wt_path=$(json_field "$INPUT" '.worktree.path')
[[ -z "$wt_path" ]] && wt_path=$(json_field "$INPUT" '.path')
wt_branch=$(json_field "$INPUT" '.worktree.branch')
[[ -z "$wt_branch" ]] && wt_branch=$(json_field "$INPUT" '.branch')
tool_use_id=$(json_field "$INPUT" '.tool_use_id')
session=$(json_field "$INPUT" '.session_id')

# Fallbacks for create-side: pwd + current HEAD ref.
if [[ "$event" = "WorktreeCreate" ]]; then
  [[ -z "$wt_path" ]] && wt_path=$(pwd 2>/dev/null || echo "")
  [[ -z "$wt_branch" ]] && wt_branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
fi

# Epoch milliseconds (matching v5.1.7 ms convention in teammates/deliverables).
NOW_MS=$(( $(date +%s) * 1000 ))

sprint=$(current_sprint 2>/dev/null || echo "")
agent_role=$(current_role "$tool_use_id" "$sprint" 2>/dev/null || echo "unknown")

# SQL-escape single quotes the cheap-and-correct way (sqlite3 doubles them).
sqlq() { printf '%s' "${1:-}" | sed "s/'/''/g"; }
qp=$(sqlq "$wt_path")
qb=$(sqlq "$wt_branch")
qt=$(sqlq "$tool_use_id")
qr=$(sqlq "$agent_role")
qs=$(sqlq "$sprint")

case "$event" in
  WorktreeCreate)
    sqlite3 "$DB" <<SQL 2>/dev/null || true
INSERT INTO worktrees (path, branch, tool_use_id, agent_role, sprint, created_at, status)
VALUES ('$qp', '$qb', '$qt', '$qr', '$qs', $NOW_MS, 'active');
SQL
    log_event "worktree_lifecycle" "create" "Worktree" "$agent_role" "$session" \
      "$(emit_json_obj path "$wt_path" branch "$wt_branch" tool_use_id "$tool_use_id")"
    ;;

  WorktreeRemove)
    # Mark the row removed (only active rows; idempotent on replay).
    sqlite3 "$DB" <<SQL 2>/dev/null || true
UPDATE worktrees
   SET status='removed', removed_at=$NOW_MS
 WHERE path='$qp' AND status='active';
SQL

    # Sweep zombie `worktree-agent-*` refs. A zombie is a branch ref whose
    # `git rev-parse --verify` fails (dangling ref / no HEAD / no commit).
    # `git branch -D` is idempotent — non-existent refs report stderr but
    # do not change exit semantics for us (we swallow all errors).
    pruned=0
    if command -v git >/dev/null 2>&1; then
      # List local refs matching the pattern; check each for liveness.
      while IFS= read -r ref; do
        [[ -z "$ref" ]] && continue
        # `git branch --list` lines start with "  " or "* "; strip both.
        ref="${ref#\*}"
        ref="${ref# }"
        ref="${ref# }"
        [[ -z "$ref" ]] && continue
        if ! git rev-parse --verify --quiet "refs/heads/$ref" >/dev/null 2>&1; then
          git branch -D "$ref" >/dev/null 2>&1 && pruned=$((pruned+1)) || true
        fi
      done < <(git branch --list 'worktree-agent-*' 2>/dev/null || true)
    fi

    if [[ "$pruned" -gt 0 ]]; then
      echo "[shctx] worktree_lifecycle: pruned $pruned zombie worktree-agent-* ref(s)" >&2
    fi

    log_event "worktree_lifecycle" "remove" "Worktree" "$agent_role" "$session" \
      "$(emit_json_obj path "$wt_path" pruned "$pruned")"
    ;;
esac

exit 0
