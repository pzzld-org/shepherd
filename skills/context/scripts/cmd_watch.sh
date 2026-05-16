#!/usr/bin/env bash
# shctx watch — directory/file content hash watcher (v5.1.1)
#
# Lets agents + sessions cache "I've already read this path; its hash was X"
# so they can skip re-reading when the path is unchanged.
#
# Subcommands:
#   add <path> [--label=<name>] [--source=git|fs]   Register a watched path
#   mark <path> [--by=<role>]                       Record current hash as "seen"
#   status [--path=<path>] [--json|--md]            Show current vs marked hash; changed/unchanged
#   list [--json|--md]                              All watched paths
#   remove <path>                                    Stop watching
#   help                                             This help
#
# Hash sources:
#   git — `git rev-parse HEAD:<path>` (instant; for tracked content)
#   fs  — `find ... -type f -exec sha256sum {} + | sort | sha256sum` (for untracked)

set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

DB=$(shctx_db_path)
sub="${1:-help}"
shift || true

usage() {
  cat <<'EOF'
shctx watch — directory/file content hash watcher

USAGE
  shctx watch add <path> [--label=<name>] [--source=git|fs]
  shctx watch mark <path> [--by=<role>]
  shctx watch status [--path=<path>] [--json|--md]
  shctx watch list [--json|--md]
  shctx watch remove <path>

EXAMPLES
  shctx watch add .shepherd/ctx --label=canonical-types
  shctx watch mark .shepherd/ctx --by=engineer
  shctx watch status .shepherd/ctx
  shctx watch list --md
EOF
}

# ----- helpers -----

# Echo the content hash of <path> using the registered source.
# git: tree hash via rev-parse. fs: sorted sha256 of all regular files within.
compute_hash() {
  local path="$1" source="$2"
  if [[ "$source" == "git" ]]; then
    git rev-parse "HEAD:$path" 2>/dev/null || echo "MISSING"
  else
    if [[ -d "$path" ]]; then
      find "$path" -type f -print0 2>/dev/null \
        | sort -z \
        | xargs -0 shasum -a 256 2>/dev/null \
        | shasum -a 256 \
        | awk '{print $1}'
    elif [[ -f "$path" ]]; then
      shasum -a 256 "$path" 2>/dev/null | awk '{print $1}'
    else
      echo "MISSING"
    fi
  fi
}

# Auto-detect source: if path is tracked in git, use 'git'; else 'fs'.
auto_source() {
  local path="$1"
  if git ls-files --error-unmatch "$path" >/dev/null 2>&1; then
    echo "git"
  else
    echo "fs"
  fi
}

# Resolve a path argument to a normalized form relative to repo root.
normalize_path() {
  local path="$1"
  local repo_root
  repo_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
  # Strip leading repo_root if absolute, otherwise leave as-is
  case "$path" in
    "$repo_root"/*) printf '%s' "${path#$repo_root/}" ;;
    /*)             printf '%s' "$path" ;;
    *)              printf '%s' "$path" ;;
  esac
}

# ----- subcommands -----

cmd_add() {
  local path="" label="" source=""
  for arg in "$@"; do
    case "$arg" in
      --label=*)  label="${arg#--label=}" ;;
      --source=*) source="${arg#--source=}" ;;
      *)          [[ -z "$path" ]] && path="$arg" ;;
    esac
  done
  [[ -z "$path" ]] && { echo "ERROR: shctx watch add <path>" >&2; exit 1; }
  path=$(normalize_path "$path")
  [[ -z "$source" ]] && source=$(auto_source "$path")
  [[ "$source" =~ ^(git|fs)$ ]] || { echo "ERROR: source must be git|fs" >&2; exit 1; }

  local current
  current=$(compute_hash "$path" "$source")

  sqlite3 "$DB" <<SQL
INSERT INTO watch_paths (path, label, source, current_hash)
VALUES ('$path', $(if [[ -n "$label" ]]; then echo "'$label'"; else echo NULL; fi), '$source', '$current')
ON CONFLICT(path) DO UPDATE SET
  label = $(if [[ -n "$label" ]]; then echo "'$label'"; else echo "watch_paths.label"; fi),
  source = '$source',
  current_hash = '$current';
SQL
  echo "[shctx watch] added: $path  (source=$source, hash=${current:0:12}...)"
}

cmd_mark() {
  local path="" by=""
  for arg in "$@"; do
    case "$arg" in
      --by=*) by="${arg#--by=}" ;;
      *)      [[ -z "$path" ]] && path="$arg" ;;
    esac
  done
  [[ -z "$path" ]] && { echo "ERROR: shctx watch mark <path>" >&2; exit 1; }
  path=$(normalize_path "$path")

  local row source current
  row=$(sqlite3 "$DB" "SELECT source FROM watch_paths WHERE path = '$path';" 2>/dev/null || true)
  if [[ -z "$row" ]]; then
    echo "[shctx watch] '$path' not registered. Run: shctx watch add $path" >&2
    exit 1
  fi
  source="$row"
  current=$(compute_hash "$path" "$source")

  sqlite3 "$DB" <<SQL
UPDATE watch_paths
SET current_hash = '$current',
    last_marked_hash = '$current',
    last_marked_at = strftime('%s', 'now'),
    last_marked_by = $(if [[ -n "$by" ]]; then echo "'$by'"; else echo NULL; fi)
WHERE path = '$path';
SQL
  echo "[shctx watch] marked: $path  (hash=${current:0:12}...)"
}

cmd_status() {
  local path="" fmt="md"
  for arg in "$@"; do
    case "$arg" in
      --path=*) path="${arg#--path=}" ;;
      --json)   fmt="json" ;;
      --md)     fmt="md" ;;
      *)        [[ -z "$path" ]] && path="$arg" ;;
    esac
  done

  local where="1=1"
  if [[ -n "$path" ]]; then
    path=$(normalize_path "$path")
    where="path = '$path'"
  fi

  # Read all matching rows; recompute current hash for each
  local rows
  rows=$(sqlite3 -separator '|' "$DB" "SELECT path, source, last_marked_hash, last_marked_at, label FROM watch_paths WHERE $where ORDER BY path;" 2>/dev/null || true)

  if [[ -z "$rows" ]]; then
    [[ -n "$path" ]] && echo "[shctx watch] '$path' not registered" >&2 && exit 1
    echo "[shctx watch] no watched paths"
    exit 0
  fi

  if [[ "$fmt" == "json" ]]; then
    echo "["
    local first=1
    while IFS='|' read -r p src marked marked_at label; do
      [[ -z "$p" ]] && continue
      local cur=$(compute_hash "$p" "$src")
      local changed="false"
      [[ -n "$marked" && "$cur" != "$marked" ]] && changed="true"
      [[ -z "$marked" ]] && changed="unmarked"
      [[ $first -eq 0 ]] && echo ","
      first=0
      printf '  {"path":"%s","source":"%s","current":"%s","marked":"%s","changed":"%s","label":"%s","marked_at":%s}' \
        "$p" "$src" "$cur" "$marked" "$changed" "$label" "${marked_at:-null}"
    done <<<"$rows"
    echo ""
    echo "]"
  else
    echo "| path | source | changed | current | marked | label |"
    echo "|---|---|---|---|---|---|"
    while IFS='|' read -r p src marked marked_at label; do
      [[ -z "$p" ]] && continue
      local cur=$(compute_hash "$p" "$src")
      local marker="—"
      if [[ -z "$marked" ]]; then
        marker="**UNMARKED**"
      elif [[ "$cur" != "$marked" ]]; then
        marker="**CHANGED**"
      else
        marker="unchanged"
      fi
      echo "| \`$p\` | $src | $marker | \`${cur:0:12}\` | \`${marked:0:12}\` | ${label:-} |"
    done <<<"$rows"
  fi
}

cmd_list() {
  local fmt="md"
  for arg in "$@"; do
    case "$arg" in --json) fmt="json" ;; --md) fmt="md" ;; esac
  done
  cmd_status "--$fmt"
}

cmd_remove() {
  local path="${1:-}"
  [[ -z "$path" ]] && { echo "ERROR: shctx watch remove <path>" >&2; exit 1; }
  path=$(normalize_path "$path")
  sqlite3 "$DB" "DELETE FROM watch_paths WHERE path = '$path';"
  echo "[shctx watch] removed: $path"
}

case "$sub" in
  help|-h|--help) usage ;;
  add)            cmd_add "$@" ;;
  mark)           cmd_mark "$@" ;;
  status)         cmd_status "$@" ;;
  list)           cmd_list "$@" ;;
  remove|rm)      cmd_remove "$@" ;;
  *) echo "ERROR: unknown shctx watch subcommand: $sub" >&2; usage >&2; exit 1 ;;
esac
