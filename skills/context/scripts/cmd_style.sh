#!/usr/bin/env bash
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

sub="${1:-list}"; shift || true
project_id=$(shctx_project_id)
now=$(shctx_now)
src_dir="$(shctx_skill_root)/styles"
dst_dir="$(shctx_artifacts_root)/styles"
mkdir -p "$dst_dir"

upsert_row() {
  local lang="$1" path="$2" uid; uid=$(shctx_uuid7)
  shctx_sql "INSERT INTO styles (id,project_id,language,source_path,active,created_at,updated_at)
             VALUES ('$uid','$project_id','$lang','$path',1,$now,$now)
             ON CONFLICT(project_id,language) DO UPDATE SET source_path=excluded.source_path, updated_at=excluded.updated_at;"
}

init_one() {
  local lang="$1"
  local src="$src_dir/$lang.md"
  local dst="$dst_dir/$lang.md"
  [[ -f "$src" ]] || { echo "ERROR: no bundled style for $lang" >&2; return 1; }
  if [[ -f "$dst" ]]; then
    echo "shctx style: $dst already exists (preserving)"
  else
    cp "$src" "$dst"
    echo "shctx style: wrote $dst"
  fi
  upsert_row "$lang" "$dst"
}

case "$sub" in
  init)
    arg="${1:-}"; [[ -n "$arg" ]] || { echo "ERROR: usage: shctx style init <lang|--all>" >&2; exit 1; }
    if [[ "$arg" == "--all" ]]; then
      for f in "$src_dir"/*.md; do init_one "$(basename "$f" .md)"; done
    else
      init_one "$arg"
    fi
    ;;
  show)
    arg="${1:-}"; [[ -n "$arg" ]] || { echo "ERROR: usage: shctx style show <lang>" >&2; exit 1; }
    cat "$dst_dir/$arg.md"
    ;;
  list)
    if [[ -d "$dst_dir" ]]; then ls "$dst_dir"; else echo "(no styles initialized)"; fi
    ;;
  edit)
    arg="${1:-}"; [[ -n "$arg" ]] || { echo "ERROR: usage: shctx style edit <lang>" >&2; exit 1; }
    [[ -f "$dst_dir/$arg.md" ]] || init_one "$arg"
    "${EDITOR:-vi}" "$dst_dir/$arg.md"
    ;;
  *) echo "ERROR: usage: shctx style <init|show|list|edit>" >&2; exit 1 ;;
esac
