#!/usr/bin/env bash
# shctx ready — first-time consumer-project bootstrap (v5.0.4)
#
#   init (idempotent)  →  migrate  →  refresh --all  →  lint  →  doctor
#
# Safe to run on already-initialized projects: each stage no-ops if
# already complete.

set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

verbose=0
init_flags=()
for arg in "$@"; do
  case "$arg" in
    --verbose|-v) verbose=1 ;;
    --shepherd|--artifacts) init_flags+=("$arg") ;;
    -h|--help)
      cat <<'EOF'
shctx ready [--shepherd|--artifacts] [--verbose]

  init → migrate → refresh --all → lint → doctor

First-time bootstrap. Pass --artifacts for legacy `.artifacts/` namespace
(default is `.shepherd/`). Idempotent.
EOF
      exit 0 ;;
    *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
  esac
done

run_stage() {
  local name="$1"; shift
  if (( verbose )); then echo "─── $name ───"; "$@"
  else "$@" >/dev/null 2>&1 || return $?
  fi
}

t0=$(shctx_now)

# 1. init — only if no namespace dir exists yet
root="$(shctx_artifacts_root)"
if [[ ! -f "$(shctx_project_id_path)" ]]; then
  if (( verbose )); then echo "─── init ───"; fi
  bash "$HERE/cmd_init.sh" "${init_flags[@]+"${init_flags[@]}"}" >/dev/null
  did_init=1
else
  did_init=0
fi

# 2. migrate
rc_migrate=0
run_stage migrate bash "$HERE/cmd_migrate.sh" || rc_migrate=$?

# 3. refresh --all
rc_refresh=0
run_stage refresh bash "$HERE/cmd_refresh.sh" --scope=all || rc_refresh=$?

# 4. lint
rc_lint=0
run_stage lint bash "$HERE/cmd_lint.sh" || rc_lint=$?

# 5. doctor — emit at end as the user-visible summary
echo
bash "$HERE/cmd_doctor.sh"
rc_doctor=$?

elapsed=$(( $(shctx_now) - t0 ))
echo
echo "shctx ready: bootstrap done (elapsed=${elapsed}s)"
echo "  init:    $([[ $did_init -eq 1 ]] && echo "performed" || echo "skipped (already initialized)")"
echo "  migrate: $([[ $rc_migrate -eq 0 ]] && echo ok || echo "fail (rc=$rc_migrate)")"
echo "  refresh: $([[ $rc_refresh -eq 0 ]] && echo ok || echo "fail (rc=$rc_refresh)")"
echo "  lint:    $([[ $rc_lint    -eq 0 ]] && echo ok || echo "fail (rc=$rc_lint)")"
echo "  doctor:  $([[ $rc_doctor  -eq 0 ]] && echo ok || ([[ $rc_doctor -eq 2 ]] && echo "warn" || echo "fail (rc=$rc_doctor)"))"

if (( rc_migrate != 0 || rc_refresh != 0 || rc_lint != 0 )); then exit 1; fi
exit 0
