#!/usr/bin/env bash
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

scope="all"
for arg in "$@"; do
  case "$arg" in
    --scope=*) scope="${arg#--scope=}" ;;
    --all)     scope="all" ;;  # canonical "all targets" alias (v5.0.4)
    -h|--help)
      cat <<'EOF'
shctx refresh [--scope=symbols|github|artifacts|all] [--all]

  --scope=NAME  refresh a single zone (symbols | github | artifacts | all)
  --all         alias for --scope=all (canonical universal flag, v5.0.4)
EOF
      exit 0 ;;
    *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
  esac
done

case "$scope" in
  symbols)   bash "$HERE/refresh-symbols.sh" ;;
  github)    bash "$HERE/refresh-github.sh" ;;
  artifacts) bash "$HERE/refresh-artifacts.sh" ;;
  all)
    # Each scope is isolated — one zone's failure must not block the others.
    bash "$HERE/refresh-symbols.sh"   || echo "shctx: symbols refresh failed (continuing)"   >&2
    bash "$HERE/refresh-github.sh"    || echo "shctx: github refresh failed (continuing)"    >&2
    bash "$HERE/refresh-artifacts.sh" || echo "shctx: artifacts refresh failed (continuing)" >&2
    ;;
  *) echo "ERROR: unknown --scope: $scope" >&2; exit 1 ;;
esac
