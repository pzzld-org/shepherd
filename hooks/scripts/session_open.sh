#!/usr/bin/env bash
# shepherd hook — session-open hygiene (v5.1.2)
#
# Fires at SessionStart. Implements:
#   1. Three-anchor verification (conductor-cwd.md §Mandatory verification)
#   2. Orphan worktree detection
#   3. Sprint-patterns.md existence surface (adaptation-loop.md)
#   4. Plan validity check (v5.1.2 — sprint pattern branch must have a plan)
#
# Output: JSON additionalContext injected into Claude's context when any
# warning fires; silent exit 0 when all checks pass.

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

# Consume stdin (SessionStart payload — not needed for these checks)
cat > /dev/null

is_shepherd_project || exit 0

warnings=()

# --- Anchor 1: HEAD must not be an agent/lane branch ---
branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
if [[ "$branch" =~ ^(agent-|lane-) ]]; then
  warnings+=("HEAD is on agent lane '$branch' (not sprint branch). Recover: git checkout <sprint_branch>  [conductor-cwd.md §Ban 2]")
fi

# --- Anchor 2: cwd must be the primary worktree (not a sub-worktree) ---
if in_subworktree; then
  sr=$(sprint_root)
  warnings+=("cwd is inside a sub-worktree. Sprint root: $sr — recover: cd $sr  [conductor-cwd.md §Ban 1]")
fi

# --- Anchor 3: orphan worktrees from prior sprints (informational) ---
wt_count=$(git worktree list --porcelain 2>/dev/null | grep -c "^worktree " || true)
if [[ "${wt_count:-0}" -gt 1 ]]; then
  warnings+=("$((wt_count - 1)) sub-worktree(s) active. Run 'git worktree list' to inspect; prune orphans with 'git worktree remove <path>'.")
fi

# --- Sprint-patterns.md check (adaptation-loop.md) ---
ns=$(resolve_namespace)
ctx_path=""
for candidate in "$ns/ctx" ".artifacts/ctx" ".shepherd/ctx"; do
  if [[ -d "$candidate" ]]; then
    ctx_path="$candidate"
    break
  fi
done
if [[ -n "$ctx_path" && ! -f "$ctx_path/sprint-patterns.md" ]]; then
  warnings+=("sprint-patterns.md absent at $ctx_path/sprint-patterns.md — no pattern history yet. First adaptation cycle records at this sprint's CLOSE-SWARM.  [adaptation-loop.md]")
fi

# --- Plan validity check (v5.1.2) ---
# If the current branch matches sprint_branch_pattern, plan.md should exist.
# This is a heuristic — we don't parse shepherd.toml here, just look for the
# v{X}.{Y}.{Z}-dev.{N} pattern as the default sprint shape.
if [[ "$branch" =~ ^v[0-9]+\.[0-9]+\.[0-9]+-dev\.[0-9]+$ ]]; then
  plan_dotted="$ns/plans/${branch}.plan.md"
  # Also check slug form (v5.1.1 sprint-slug naming convention)
  slug=$(printf '%s' "$branch" | sed -E 's/^v([0-9]+)\.([0-9]+)\.([0-9]+)-dev\.([0-9]+)$/v\1\2\3-dev\4/')
  plan_slug="$ns/plans/${slug}.plan.md"
  if [[ ! -f "$plan_dotted" && ! -f "$plan_slug" ]]; then
    warnings+=("Sprint branch '$branch' has no plan.md at ${plan_dotted#$(pwd)/} or ${plan_slug#$(pwd)/}. Engineer dispatch pending? [pipeline.md §I INTRO]")
  fi
fi

# --- Build output ---
session=$(cat 2>/dev/null || true)  # already consumed; placeholder
[[ ${#warnings[@]} -eq 0 ]] && pass_silent "session_open" "Session" "conductor" ""

msg="[shepherd] Session-open hygiene (v5.1.2):"$'\n'
for w in "${warnings[@]}"; do
  msg+="  • $w"$'\n'
done
msg+="Run 'shctx doctor' for a full pre-flight check."

log_event "session_open" "warn" "Session" "conductor" "" "$(emit_json_obj warnings_count "${#warnings[@]}")"
emit_json_obj additionalContext "$msg"
