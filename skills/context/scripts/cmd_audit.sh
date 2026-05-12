#!/usr/bin/env bash
# shctx audit — read-only validation pipeline (v5.0.4)
#
#   lint  →  doctor  →  status
#
# No writes. Used by the conductor as a pre-dispatch sanity check, and
# by CI for "is this project's context registry healthy?".

set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

verbose=0
for arg in "$@"; do
  case "$arg" in
    --verbose|-v) verbose=1 ;;
    -h|--help)
      cat <<'EOF'
shctx audit [--verbose]

Read-only validation: lint → doctor → status.
Exits 0 if all green, 1 if any FAIL, 2 if only WARNs (matches doctor).
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

rc_lint=0; rc_doctor=0; rc_status=0
run_stage lint   bash "$HERE/cmd_lint.sh"   || rc_lint=$?
bash "$HERE/cmd_doctor.sh" >/dev/null 2>&1 || rc_doctor=$?
run_stage status bash "$HERE/cmd_status.sh" || rc_status=$?

# Always print doctor at end (it's the user-relevant signal).
bash "$HERE/cmd_doctor.sh"

echo
echo "shctx audit:"
echo "  lint:   $([[ $rc_lint   -eq 0 ]] && echo ok || echo "fail (rc=$rc_lint)")"
echo "  doctor: $([[ $rc_doctor -eq 0 ]] && echo ok || ([[ $rc_doctor -eq 2 ]] && echo "warn" || echo "fail (rc=$rc_doctor)"))"
echo "  status: $([[ $rc_status -eq 0 ]] && echo ok || echo "fail (rc=$rc_status)")"

if (( rc_lint != 0 || rc_doctor == 1 || rc_status != 0 )); then exit 1; fi
if (( rc_doctor == 2 )); then exit 2; fi
exit 0
