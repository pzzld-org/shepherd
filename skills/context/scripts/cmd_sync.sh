#!/usr/bin/env bash
# shctx sync — one-shot context refresh pipeline (v5.0.4)
#
#   refresh  →  lint  →  status
#
# Idempotent. Emits a 5-line summary by default; --verbose forwards
# stage output. Honors --scope=… and --all in line with cmd_refresh.

set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

scope="all"
verbose=0
for arg in "$@"; do
  case "$arg" in
    --scope=*) scope="${arg#--scope=}" ;;
    --all)     scope="all" ;;
    --verbose|-v) verbose=1 ;;
    -h|--help)
      cat <<'EOF'
shctx sync [--scope=symbols|github|artifacts|all] [--all] [--verbose]

  refresh → lint → status — one-shot context update pipeline.
  --all is the canonical "all targets" alias (= --scope=all).
EOF
      exit 0 ;;
    *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
  esac
done

run_stage() {
  local name="$1"; shift
  if (( verbose )); then
    echo "─── $name ───"
    "$@" || return $?
  else
    "$@" >/dev/null 2>&1 || return $?
  fi
}

t0=$(shctx_now)
rc_refresh=0; rc_lint=0; rc_status=0
run_stage refresh bash "$HERE/cmd_refresh.sh" "--scope=$scope" || rc_refresh=$?
run_stage lint    bash "$HERE/cmd_lint.sh"                      || rc_lint=$?
run_stage status  bash "$HERE/cmd_status.sh"                    || rc_status=$?
elapsed=$(( $(shctx_now) - t0 ))

echo "shctx sync: scope=$scope  elapsed=${elapsed}s"
echo "  refresh: $([[ $rc_refresh -eq 0 ]] && echo ok || echo "fail (rc=$rc_refresh)")"
echo "  lint:    $([[ $rc_lint    -eq 0 ]] && echo ok || echo "fail (rc=$rc_lint)")"
echo "  status:  $([[ $rc_status  -eq 0 ]] && echo ok || echo "fail (rc=$rc_status)")"

if (( rc_refresh != 0 || rc_lint != 0 || rc_status != 0 )); then exit 1; fi
exit 0
