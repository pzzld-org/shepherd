#!/usr/bin/env bash
# shepherd hook — session-open hygiene (v5.0.9)
#
# Fires at SessionStart. Implements:
#   1. Three-anchor verification (conductor-cwd.md §Mandatory verification)
#   2. Orphan worktree detection
#   3. Sprint-patterns.md existence surface (adaptation-loop.md §IX v5.0.9)
#
# Output: JSON additionalContext injected into Claude's context when any
# warning fires; silent exit 0 when all checks pass.

set -euo pipefail

# Consume stdin (SessionStart payload — not needed for these checks)
cat > /dev/null

# Skip entirely if this project isn't running shepherd
[[ -f ".claude/shepherd.toml" ]] || exit 0

warnings=()

# --- Anchor 1: HEAD must not be an agent/lane branch ---
branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
if [[ "$branch" =~ ^(agent-|lane-) ]]; then
  warnings+=("HEAD is on agent lane '$branch' (not sprint branch). Recover: git checkout <sprint_branch>  [conductor-cwd.md §Ban 2]")
fi

# --- Anchor 2: cwd must be the primary worktree (not a sub-worktree) ---
git_dir=$(git rev-parse --git-dir 2>/dev/null || echo "")
git_common=$(git rev-parse --git-common-dir 2>/dev/null || echo "")
if [[ -n "$git_dir" && "$git_dir" != "$git_common" ]]; then
  sprint_root=$(git rev-parse --git-common-dir 2>/dev/null | sed 's|/\.git$||; s|/.git$||' || echo "unknown")
  warnings+=("cwd is inside a sub-worktree. Sprint root: $sprint_root — recover: cd $sprint_root  [conductor-cwd.md §Ban 1]")
fi

# --- Anchor 3: orphan worktrees from prior sprints (informational) ---
wt_count=$(git worktree list --porcelain 2>/dev/null | grep -c "^worktree " || true)
if [[ "${wt_count:-0}" -gt 1 ]]; then
  warnings+=("$((wt_count - 1)) sub-worktree(s) active. Run 'git worktree list' to inspect; prune orphans with 'git worktree remove <path>'.")
fi

# --- Sprint-patterns.md check (adaptation-loop.md — v5.0.9) ---
repo_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
ctx_path=""
for candidate in "$repo_root/.shepherd/ctx" "$repo_root/.artifacts/ctx"; do
  if [[ -d "$candidate" ]]; then
    ctx_path="$candidate"
    break
  fi
done
if [[ -n "$ctx_path" && ! -f "$ctx_path/sprint-patterns.md" ]]; then
  warnings+=("sprint-patterns.md absent at $ctx_path/sprint-patterns.md — no pattern history yet. First adaptation cycle records at this sprint's CLOSE-SWARM.  [adaptation-loop.md]")
fi

# --- Build output ---
[[ ${#warnings[@]} -eq 0 ]] && exit 0

msg="[shepherd] Session-open hygiene (v5.0.9):"$'\n'
for w in "${warnings[@]}"; do
  msg+="  • $w"$'\n'
done
msg+="Run 'shctx doctor' for a full pre-flight check."

if command -v jq &>/dev/null; then
  jq -n --arg ctx "$msg" '{"additionalContext": $ctx}'
else
  python3 -c "import json,sys; print(json.dumps({'additionalContext': sys.argv[1]}))" "$msg"
fi
