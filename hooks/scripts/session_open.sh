#!/usr/bin/env bash
# shepherd hook — session-open hygiene (v5.1.8)
#
# Fires at SessionStart. Implements:
#   1. Three-anchor verification (conductor-cwd.md §Mandatory verification)
#   2. Orphan worktree detection
#   3. Sprint-patterns.md existence surface (adaptation-loop.md)
#   4. Plan validity check (v5.1.2 — sprint pattern branch must have a plan)
#   5. Agent-branch stray-commit survey (v5.1.8 — issue #24)
#   6. Multi-plan.md reconciliation surface (v5.1.8 — issue #26)
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

# --- Adaptation registry check (adaptation-loop.md, v6.0.4 SQLite-canonical) ---
ns=$(resolve_namespace)
db="$(hook_db_path "$ns")"
if [[ -f "$db" ]] && command -v sqlite3 >/dev/null 2>&1; then
  n=$(sqlite3 "$db" "SELECT count(*) FROM sprint_metrics;" 2>/dev/null || echo 0)
  if [[ "${n:-0}" == "0" ]]; then
    warnings+=("adaptation registry empty — no pattern history yet. First cycle records at CLOSE-FINALIZE via 'shctx adapt roll'.  [adaptation-loop.md]")
  fi
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

# --- Anchor 5: agent-branch stray-commit survey (v5.1.8 — issue #24) ---
# Scan local agent-* branches for unique commits not reachable from the sprint
# HEAD. Catches lost work from context-truncated prior sessions BEFORE the
# conductor reads the handoff and trusts a "complete" claim. Complements the
# v5.1.8 WAVE-GATE Stop hook (which catches strays during the current session).
if [[ "$branch" != "unknown" ]] && ! [[ "$branch" =~ ^(agent-|lane-) ]]; then
  stray_branches=()
  while IFS= read -r br; do
    [[ -z "$br" ]] && continue
    br=$(echo "$br" | sed 's/^[[:space:]]*//')
    ahead=$(git rev-list --right-only --count "$branch...$br" 2>/dev/null || echo 0)
    if [[ "${ahead:-0}" -gt 0 ]]; then
      stray_branches+=("$br ($ahead)")
    fi
  done < <(git branch 2>/dev/null | grep '^  agent-' || true)
  if [[ ${#stray_branches[@]} -gt 0 ]]; then
    stray_list=$(IFS=', '; echo "${stray_branches[*]}")
    warnings+=("$( printf '%s' "${#stray_branches[@]} agent branch(es) have stray commits NOT in '$branch': $stray_list. Cherry-pick or drop before dispatching — silent data-loss risk if next session inherits 'complete' from handoff. [issue #24]" )")
  fi
fi

# --- Anchor 6: multiple plan.md files for current sprint (v5.1.8 — issue #26) ---
# When a sprint has an addendum plan (dev.1.plan.md + dev.1b.plan.md), the
# second is invisible to Step 0 by default. Surface the file list so the
# conductor reads ALL of them, not just one.
if [[ "$branch" =~ ^v[0-9]+\.[0-9]+\.[0-9]+-dev\.[0-9]+$ ]] && [[ -d "$ns/plans" ]]; then
  # Match base sprint prefix; the dot-or-letter suffix allows addendum forms
  # (dev.1.plan.md, dev.1b.plan.md, dev.1.b.plan.md).
  plan_matches=()
  while IFS= read -r f; do
    [[ -n "$f" ]] && plan_matches+=("$f")
  done < <(ls -1 "$ns/plans/" 2>/dev/null | grep -E "^${branch}([.-][a-z0-9]+)?\.plan\.md$" || true)
  if [[ ${#plan_matches[@]} -gt 1 ]]; then
    plan_list=$(IFS=', '; echo "${plan_matches[*]}")
    warnings+=("$( printf '%s' "${#plan_matches[@]} plan files for sprint '$branch': $plan_list — reconcile ALL (addendum plans may carry orphaned lanes). Read each in chronological order. [issue #26]" )")
  fi
fi

# --- shctx CLI locator (v6.1.8) — kill the "shctx absent" false negative ------
# shctx is plugin-local and NEVER on $PATH; `command -v shctx` / `which shctx`
# returns absent BY DESIGN. A session that probes it that way (or whose shell
# never received $CLAUDE_PLUGIN_ROOT) wrongly concludes shctx is missing. Resolve
# the absolute path from THIS hook's OWN location (hooks/scripts → ../.. = the
# installed plugin root) — correct regardless of whether $CLAUDE_PLUGIN_ROOT
# reached the agent's Bash env — and surface it so every session has a working
# invocation. Config-gated: [context].announce_shctx_path = on (default) | off.
shctx_line=""
if [[ "$(cfg_get announce_shctx_path)" != "off" ]]; then
  plugin_root="$(cd "$HERE/../.." 2>/dev/null && pwd || true)"
  shctx_path="$plugin_root/skills/context/scripts/shctx"
  if [[ -f "$shctx_path" ]]; then
    [[ -n "${CLAUDE_PLUGIN_ROOT:-}" ]] && cpr="set" || cpr="UNSET"
    shctx_line="shctx CLI → $shctx_path"$'\n'
    shctx_line+="  (plugin-local; NOT on \$PATH — 'command -v shctx' / 'which shctx' returns absent BY DESIGN, NOT evidence of absence. Invoke by this absolute path. \$CLAUDE_PLUGIN_ROOT is $cpr in this shell.)"
  fi
fi

# --- Build output ---
# Emit if there's a locator line OR any hygiene warning; else stay silent.
if [[ -z "$shctx_line" && ${#warnings[@]} -eq 0 ]]; then
  pass_silent "session_open" "Session" "conductor" ""
fi

msg="[shepherd] Session orientation:"$'\n'
[[ -n "$shctx_line" ]] && msg+="$shctx_line"$'\n'
if [[ ${#warnings[@]} -gt 0 ]]; then
  msg+="Session-open hygiene (v5.1.8):"$'\n'
  for w in "${warnings[@]}"; do
    msg+="  • $w"$'\n'
  done
  msg+="Run 'shctx doctor' for a full pre-flight check."
fi

# v5.1.8: route through emit_context so [hooks].quiet_warnings opt-out applies.
# emit_context already calls log_event under the hood.
emit_context "$msg" "session_open" "Session" "conductor" ""
