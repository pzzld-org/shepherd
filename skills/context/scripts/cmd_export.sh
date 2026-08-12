#!/usr/bin/env bash
# shctx export <kind> [--out=<path>] [--all]
#
# v5.0.4 — adds --all (bundles every export kind to a directory).

set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

kind="${1:-}"
all=0
out=""

# v5.0.4 — `export --all` is shorthand for `export all-bundle --out=...`
if [[ "$kind" == "--all" ]]; then
  all=1; kind="all"; shift
elif [[ "$kind" == "all" ]]; then
  all=1; shift
else
  shift || true
fi

for a in "$@"; do
  case "$a" in
    --out=*) out="${a#--out=}" ;;
    --all)   all=1; kind="all" ;;
    -h|--help)
      cat <<'EOF'
shctx export <kind> [--out=<path>]
shctx export --all   [--out=<dir>]
shctx export all     [--out=<dir>]

  <kind>     canonical-types | open-issues | open-prs | recent-releases
             | drift-risk | search-symbols | mem
  --out      output path (file for single kind, dir for --all)
  --all      bundle every supported export kind to a directory
EOF
      exit 0 ;;
  esac
done

emit_one() {
  local k="$1"
  case "$k" in
    canonical-types)  bash "$HERE/cmd_query.sh" canonical-types --md ;;
    open-issues)      bash "$HERE/cmd_query.sh" open-issues --md ;;
    open-prs)         bash "$HERE/cmd_query.sh" open-prs --md 2>/dev/null || echo "# (open-prs query unavailable)" ;;
    recent-releases)  bash "$HERE/cmd_query.sh" recent-releases --md 2>/dev/null || echo "# (recent-releases query unavailable)" ;;
    drift-risk)       bash "$HERE/cmd_query.sh" drift-risk --md 2>/dev/null || echo "# (drift-risk query unavailable)" ;;
    mem)              bash "$HERE/cmd_mem.sh" list 2>/dev/null || echo "# (no memories)" ;;
    *) echo "ERROR: unknown export kind: $k" >&2; return 1 ;;
  esac
}

if (( all )); then
  bundle_dir="${out:-$(shctx_artifacts_root)/exports/$(date +%Y-%m-%dT%H-%M-%S)}"
  mkdir -p "$bundle_dir"
  for k in canonical-types open-issues open-prs recent-releases drift-risk mem; do
    f="$bundle_dir/${k}.md"
    if emit_one "$k" > "$f" 2>/dev/null; then
      echo "wrote $f"
    else
      rm -f "$f"
      echo "skip $k (unavailable)"
    fi
  done
  echo "shctx export --all: bundle at $bundle_dir"
else
  [[ -n "$kind" ]] || { echo "ERROR: kind required (or pass --all)" >&2; exit 1; }
  data=$(emit_one "$kind") || exit 1
  if [[ -n "$out" ]]; then
    printf '%s\n' "$data" > "$out"
    echo "wrote $out"
  else
    printf '%s\n' "$data"
  fi
fi
