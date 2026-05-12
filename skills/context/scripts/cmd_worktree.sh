#!/usr/bin/env bash
# shctx worktree <subcommand> [args]
#
# v5.0.3 — worktree hygiene helpers. Field origin: v5.0.1 conductor feedback
# §4 Priority 3 (stale-worktree pruner + cherry-pick UX).
# v5.0.4 — adds `create-batch` to pre-create N agent worktrees from the
# sprint HEAD, eliminating the `Agent({isolation:"worktree"})` BASE-DRIFT
# pattern documented in v5.0.3 feedback §1.
#
# Subcommands:
#   list
#       Print all known worktrees with branch + last-commit + age.
#
#   create-batch <lane-id…> [--from=<branch>] [--prefix=agent-]
#       Pre-create one worktree per lane-id at .claude/worktrees/<prefix><id>
#       checked out at HEAD of --from (default: current branch). Coder briefs
#       then receive [WORKTREE-PATH] = <abs path> and never invoke
#       `Agent({isolation:"worktree"})` (which races to a wrong base).
#
#   gc [--older-than=<hours>] [--dry-run] [--all]
#       Prune `.claude/worktrees/agent-*` entries whose last-commit timestamp
#       is older than --older-than (default 24h). --all == --older-than=0,
#       i.e. prune every agent worktree regardless of age. Unlike
#       `git worktree prune`, this also removes the directory.
#
#   merge <agent-id> [--strategy=theirs|prompt] [--no-cleanup]
#       Cherry-pick the worktree's HEAD onto the current sprint branch. On
#       conflict: --strategy=theirs takes the worktree's version automatically;
#       --strategy=prompt halts so the operator resolves manually (default).
#       After successful pick, removes the worktree (unless --no-cleanup).
#
# IMPORTANT: per `doctrines/conductor-cwd.md`, the conductor MUST NOT `cd`
# into a worktree. This script uses `git -C <path>` and stays at sprint root.

set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

sub="${1:-list}"; shift || true
repo="$(shctx_repo_root)"

age_hours() {
  # Print integer hours since the given epoch.
  local then="$1" now
  now=$(shctx_now)
  echo $(( (now - then) / 3600 ))
}

list_worktrees() {
  # Returns lines: <abs-path>|<branch>|<head-sha>|<last-commit-epoch>
  git -C "$repo" worktree list --porcelain | awk '
    /^worktree / { wt=$2 }
    /^branch /   { br=$2 }
    /^HEAD /     { sha=$2 }
    /^$/ {
      if (wt && wt != "" && wt != ENVIRON["REPO"]) {
        print wt"|"br"|"sha
      }
      wt=""; br=""; sha=""
    }
  ' REPO="$repo" | while IFS='|' read -r wt br sha; do
    [[ -n "$wt" ]] || continue
    if [[ -d "$wt" ]]; then
      ts=$(git -C "$wt" log -1 --format=%ct 2>/dev/null || echo 0)
    else
      ts=0
    fi
    echo "$wt|${br#refs/heads/}|$sha|$ts"
  done
}

case "$sub" in
  create-batch)
    from_branch=""
    prefix="agent-"
    lanes=()
    while (( $# > 0 )); do
      case "$1" in
        --from=*)   from_branch="${1#*=}" ;;
        --from)     shift; from_branch="${1:-}" ;;
        --prefix=*) prefix="${1#*=}" ;;
        --prefix)   shift; prefix="${1:-}" ;;
        -h|--help)
          echo "shctx worktree create-batch <lane-id…> [--from=<branch>] [--prefix=agent-]" >&2
          echo "  Pre-creates one worktree per lane-id at .claude/worktrees/<prefix><id>" >&2
          echo "  rooted at the HEAD of --from (default: current branch)." >&2
          exit 0 ;;
        --*) echo "ERROR: unknown flag: $1" >&2; exit 1 ;;
        *)   lanes+=("$1") ;;
      esac
      shift
    done
    [[ ${#lanes[@]} -gt 0 ]] || { echo "ERROR: at least one lane-id required" >&2; exit 1; }
    if [[ -z "$from_branch" ]]; then
      from_branch=$(git -C "$repo" symbolic-ref --short HEAD 2>/dev/null || true)
      [[ -n "$from_branch" ]] || { echo "ERROR: detached HEAD; pass --from=<branch>" >&2; exit 1; }
    fi
    git -C "$repo" rev-parse --verify "$from_branch" >/dev/null 2>&1 \
      || { echo "ERROR: --from=$from_branch does not exist" >&2; exit 1; }
    base_sha=$(git -C "$repo" rev-parse "$from_branch")
    mkdir -p "$repo/.claude/worktrees"
    created=0
    for lane in "${lanes[@]}"; do
      wt_path="$repo/.claude/worktrees/${prefix}${lane}"
      wt_branch="${prefix}${lane}"
      if [[ -d "$wt_path" ]]; then
        echo "skip ${prefix}${lane}: $wt_path already exists"
        continue
      fi
      if git -C "$repo" rev-parse --verify "$wt_branch" >/dev/null 2>&1; then
        # Branch exists; reuse it but verify it points at the expected base.
        existing_sha=$(git -C "$repo" rev-parse "$wt_branch")
        if [[ "$existing_sha" != "$base_sha" ]]; then
          echo "WARN ${prefix}${lane}: branch exists at $existing_sha (expected $base_sha)"
        fi
        git -C "$repo" worktree add "$wt_path" "$wt_branch"
      else
        git -C "$repo" worktree add -b "$wt_branch" "$wt_path" "$from_branch"
      fi
      echo "created ${prefix}${lane}: $wt_path (base=${base_sha:0:10})"
      created=$((created + 1))
    done
    echo "shctx worktree create-batch: created $created worktrees from $from_branch (${base_sha:0:10})"
    echo "[BASE-COMMIT-EXPECTED] for coder briefs: $base_sha"
    ;;

  list)
    printf '%-60s %-30s %-12s %s\n' PATH BRANCH HEAD AGE
    while IFS='|' read -r wt br sha ts; do
      [[ -n "$wt" ]] || continue
      ah=$(age_hours "$ts")
      printf '%-60s %-30s %-12s %sh\n' "${wt#$repo/}" "$br" "${sha:0:10}" "$ah"
    done < <(list_worktrees)
    ;;

  gc)
    older=24
    dry=0
    for arg in "$@"; do
      case "$arg" in
        --older-than=*) older="${arg#*=}" ;;
        --all)          older=0 ;;
        --dry-run)      dry=1 ;;
        -h|--help)
          echo "shctx worktree gc [--older-than=<hours> | --all] [--dry-run]" >&2; exit 0 ;;
        *) echo "ERROR: unknown flag: $arg" >&2; exit 1 ;;
      esac
    done
    threshold=$(( $(shctx_now) - older * 3600 ))
    pruned=0
    while IFS='|' read -r wt br sha ts; do
      [[ -n "$wt" ]] || continue
      [[ "$wt" == *"/.claude/worktrees/agent-"* ]] || continue
      (( ts < threshold )) || continue
      if (( dry )); then
        echo "[dry-run] would prune $wt (branch=$br, age=$(age_hours "$ts")h)"
      else
        echo "pruning $wt (branch=$br, age=$(age_hours "$ts")h)"
        git -C "$repo" worktree remove --force "$wt" 2>/dev/null || rm -rf "$wt"
        # Best-effort: drop the agent branch if no other worktree refers to it.
        if [[ -n "$br" ]] && ! git -C "$repo" worktree list | grep -q "$br"; then
          git -C "$repo" branch -D "$br" 2>/dev/null || true
        fi
      fi
      pruned=$((pruned + 1))
    done < <(list_worktrees)
    git -C "$repo" worktree prune
    echo "shctx worktree gc: pruned $pruned (threshold ${older}h)"
    ;;

  merge)
    agent=""
    strategy="prompt"
    cleanup=1
    while (( $# > 0 )); do
      case "$1" in
        --strategy=*) strategy="${1#*=}" ;;
        --no-cleanup) cleanup=0 ;;
        -h|--help)
          echo "shctx worktree merge <agent-id> [--strategy=theirs|prompt] [--no-cleanup]" >&2; exit 0 ;;
        --*) echo "ERROR: unknown flag: $1" >&2; exit 1 ;;
        *)   agent="$1" ;;
      esac
      shift
    done
    [[ -n "$agent" ]] || { echo "ERROR: agent-id required" >&2; exit 1; }
    case "$strategy" in theirs|prompt) ;; *) echo "ERROR: --strategy must be theirs|prompt" >&2; exit 1 ;; esac

    # Find the worktree path for the given agent id.
    wt=""
    while IFS='|' read -r path br sha ts; do
      [[ "$path" == *"agent-${agent}"* ]] && { wt="$path"; break; }
    done < <(list_worktrees)
    [[ -n "$wt" ]] || { echo "ERROR: no worktree matching agent-id '$agent'" >&2; exit 1; }
    [[ -d "$wt" ]] || { echo "ERROR: worktree path missing: $wt" >&2; exit 1; }

    head_sha=$(git -C "$wt" rev-parse HEAD)
    echo "shctx worktree merge: cherry-picking $head_sha from $wt"

    set +e
    if [[ "$strategy" == "theirs" ]]; then
      git -C "$repo" cherry-pick -X theirs "$head_sha"
      rc=$?
    else
      git -C "$repo" cherry-pick "$head_sha"
      rc=$?
    fi
    set -e

    if (( rc != 0 )); then
      echo "shctx worktree merge: cherry-pick had conflicts (rc=$rc). Resolve, then run \`git cherry-pick --continue\`." >&2
      echo "                       Worktree NOT cleaned up; re-run \`shctx worktree merge $agent --no-cleanup\` after resolution if needed." >&2
      exit "$rc"
    fi

    if (( cleanup )); then
      echo "shctx worktree merge: cleanup — removing $wt"
      git -C "$repo" worktree remove --force "$wt" 2>/dev/null || rm -rf "$wt"
    fi
    echo "shctx worktree merge: ok"
    ;;

  -h|--help|help)
    cat <<'EOF'
shctx worktree <subcommand>

  list                                                   list worktrees with branch + age
  create-batch <lane-id…> [--from=<branch>] [--prefix=]  pre-create per-lane worktrees from sprint HEAD
  gc   [--older-than=<hours> | --all] [--dry-run]        prune stale agent worktrees (default 24h)
  merge <agent-id> [--strategy=...] [--no-cleanup]       cherry-pick + cleanup

Per doctrines/conductor-cwd.md the conductor never `cd`'s into a worktree —
this command uses `git -C <path>` and stays at sprint root.
EOF
    ;;
  *)
    echo "ERROR: unknown subcommand: $sub" >&2; exit 1 ;;
esac
