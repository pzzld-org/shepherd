#!/usr/bin/env bash
# shctx sprint <open|wave|close> [args] — sprint-cycle pipelines (v5.0.4)
#
#   sprint open <branch>     lock acquire → refresh --all → lint → status
#   sprint wave <wave-id>    refresh --scope=github,artifacts → lint
#                            (replaces auto_refresh = ["on-wave-gate"])
#   sprint close <branch>    close-lane (each known) → handoff → worktree gc → lock release
#
# All stages idempotent; failures emit fix lines and a non-zero exit.

set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

sub="${1:-}"; shift || true

usage() {
  cat <<'EOF'
shctx sprint <open|wave|close> [args]

  open <branch>           kickoff: lock acquire → refresh --all → lint → status
  wave <wave-id> [--all]  wave-gate: refresh --scope=github,artifacts → lint
                          --all forwards --scope=all to refresh
  close <branch>          finale: close-lane (each) → handoff → worktree gc → lock release

All pipelines emit a per-stage summary; --verbose forwards stage output.
EOF
}

verbose=0
for arg in "$@"; do
  case "$arg" in --verbose|-v) verbose=1 ;; esac
done

run_stage() {
  local name="$1"; shift
  if (( verbose )); then echo "─── $name ───"; "$@"
  else "$@" >/dev/null 2>&1 || return $?
  fi
}

case "$sub" in
  open)
    branch="${1:-}"
    [[ -n "$branch" ]] || { echo "ERROR: usage: shctx sprint open <branch>" >&2; exit 1; }
    t0=$(shctx_now)
    rc_lock=0; rc_refresh=0; rc_lint=0; rc_status=0
    run_stage "lock acquire" bash "$HERE/cmd_lock.sh" acquire --mode=sprint || rc_lock=$?
    run_stage "refresh --all" bash "$HERE/cmd_refresh.sh" --scope=all       || rc_refresh=$?
    run_stage lint           bash "$HERE/cmd_lint.sh"                       || rc_lint=$?
    run_stage status         bash "$HERE/cmd_status.sh"                     || rc_status=$?
    elapsed=$(( $(shctx_now) - t0 ))
    echo "shctx sprint open $branch: elapsed=${elapsed}s"
    echo "  lock:    $([[ $rc_lock    -eq 0 ]] && echo acquired || echo "fail (rc=$rc_lock)")"
    echo "  refresh: $([[ $rc_refresh -eq 0 ]] && echo ok       || echo "fail (rc=$rc_refresh)")"
    echo "  lint:    $([[ $rc_lint    -eq 0 ]] && echo ok       || echo "fail (rc=$rc_lint)")"
    echo "  status:  $([[ $rc_status  -eq 0 ]] && echo ok       || echo "fail (rc=$rc_status)")"
    (( rc_lock == 0 && rc_refresh == 0 && rc_lint == 0 && rc_status == 0 ))
    ;;

  wave)
    wave="${1:-}"
    [[ -n "$wave" ]] || { echo "ERROR: usage: shctx sprint wave <wave-id>" >&2; exit 1; }
    shift
    scope="github,artifacts"
    for arg in "$@"; do
      case "$arg" in --all) scope="all" ;; esac
    done
    t0=$(shctx_now)
    rc_g=0; rc_a=0; rc_lint=0
    if [[ "$scope" == "all" ]]; then
      run_stage "refresh --all" bash "$HERE/cmd_refresh.sh" --scope=all || rc_g=$?
    else
      run_stage "refresh github"    bash "$HERE/cmd_refresh.sh" --scope=github    || rc_g=$?
      run_stage "refresh artifacts" bash "$HERE/cmd_refresh.sh" --scope=artifacts || rc_a=$?
    fi
    run_stage lint bash "$HERE/cmd_lint.sh" || rc_lint=$?
    elapsed=$(( $(shctx_now) - t0 ))
    echo "shctx sprint wave $wave: scope=$scope elapsed=${elapsed}s"
    echo "  refresh: $([[ $rc_g -eq 0 && $rc_a -eq 0 ]] && echo ok || echo "fail (g=$rc_g a=$rc_a)")"
    echo "  lint:    $([[ $rc_lint -eq 0 ]] && echo ok || echo "fail (rc=$rc_lint)")"
    (( rc_g == 0 && rc_a == 0 && rc_lint == 0 ))
    ;;

  close)
    branch="${1:-}"
    [[ -n "$branch" ]] || { echo "ERROR: usage: shctx sprint close <branch>" >&2; exit 1; }
    t0=$(shctx_now)
    # 1. Close each known lane that's tied to this sprint.
    project_id=$(shctx_project_id 2>/dev/null || echo "")
    closed=0; lane_failed=0
    if [[ -n "$project_id" ]] && shctx_sql "SELECT 1 FROM sqlite_master WHERE type='table' AND name='lane_closures';" | grep -q 1; then
      while read -r lane; do
        [[ -n "$lane" ]] || continue
        if bash "$HERE/cmd_close-lane.sh" "$lane" --sprint="$branch" --status=clean >/dev/null 2>&1; then
          closed=$((closed + 1))
        else
          lane_failed=$((lane_failed + 1))
        fi
      done < <(shctx_sql "SELECT lane_id FROM lane_closures WHERE project_id='$project_id' AND sprint_branch='$branch' AND closed_at IS NULL ORDER BY lane_id;")
    fi
    # 2. Handoff
    rc_h=0
    run_stage handoff bash "$HERE/cmd_handoff.sh" create --branch="$branch" || rc_h=$?
    # 3. Worktree gc
    rc_gc=0
    run_stage "worktree gc" bash "$HERE/cmd_worktree.sh" gc || rc_gc=$?
    # 4. Lock release
    rc_l=0
    run_stage "lock release" bash "$HERE/cmd_lock.sh" release || rc_l=$?
    elapsed=$(( $(shctx_now) - t0 ))
    echo "shctx sprint close $branch: elapsed=${elapsed}s"
    echo "  lanes:   closed=$closed failed=$lane_failed"
    echo "  handoff: $([[ $rc_h -eq 0 ]] && echo ok || echo "fail (rc=$rc_h)")"
    echo "  gc:      $([[ $rc_gc -eq 0 ]] && echo ok || echo "fail (rc=$rc_gc)")"
    echo "  lock:    $([[ $rc_l -eq 0 ]] && echo released || echo "fail (rc=$rc_l)")"
    (( rc_h == 0 && rc_gc == 0 && rc_l == 0 && lane_failed == 0 ))
    ;;

  ""|-h|--help|help) usage ;;
  *) echo "ERROR: unknown subcommand: $sub" >&2; usage >&2; exit 1 ;;
esac
