#!/usr/bin/env bash
# shctx search <text> [--scope=symbols|artifacts|all] [--limit=N] [--md|--json]
#
# v5.0.3 — FTS5 fast-path over symbols and artifacts. Falls back gracefully
# if migration 0004_fts_search.sql hasn't been applied yet (instructs the
# user to run `shctx migrate`).

set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

scope="all"
limit=20
fmt="md"
text=""

usage() {
  cat <<'EOF'
shctx search <text> [--scope=symbols|artifacts|all] [--limit=N] [--md|--json]

FTS5 search over the project's symbol index and artifact content. Requires
schema migration 0004 (run `shctx migrate` if it errors with "no such table").

  text          search text — passes to FTS5 (`name AND signature` etc OK)
  --scope       symbols | artifacts | all (default: all)
  --all         alias for --scope=all (canonical universal flag, v5.0.4)
  --limit       max results per scope (default: 20)
  --md | --json output format (default: md)

Examples:
  shctx search "BookSnapshot"
  shctx search "QuestDB ILP" --scope=artifacts
  shctx search "candle OR ohlc" --scope=symbols --limit=10 --json
EOF
}

while (( $# > 0 )); do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --scope=*) scope="${1#*=}" ;;
    --all)     scope="all" ;;  # canonical alias (v5.0.4)
    --limit=*) limit="${1#*=}" ;;
    --md)      fmt="md" ;;
    --json)    fmt="json" ;;
    --*)       echo "ERROR: unknown flag: $1" >&2; usage >&2; exit 1 ;;
    *)         text+="${text:+ }$1" ;;
  esac
  shift
done

[[ -n "$text" ]] || { echo "ERROR: search text required" >&2; usage >&2; exit 1; }
case "$scope" in symbols|artifacts|all) ;; *) echo "ERROR: --scope must be symbols|artifacts|all" >&2; exit 1 ;; esac
case "$fmt"  in md|json) ;;             *) echo "ERROR: format must be --md or --json" >&2; exit 1 ;; esac

project_id=$(shctx_project_id)
db="$(shctx_db_path)"

# Verify FTS tables exist (migration 0004 applied).
if ! shctx_sql "SELECT 1 FROM sqlite_master WHERE type='table' AND name='index_fts_symbols';" | grep -q 1; then
  echo "ERROR: FTS tables missing. Run \`shctx migrate\` to apply 0004_fts_search.sql." >&2
  exit 2
fi

# SQL-escape the search expression.
q_esc=$(printf '%s' "$text" | sed "s/'/''/g")
pid_esc=$(printf '%s' "$project_id" | sed "s/'/''/g")
limit_n=$((limit + 0))

run_symbols() {
  sqlite3 "$db" <<SQL
.mode list
.separator '|'
SELECT s.package, s.kind, s.name, s.signature, s.file_path, s.line,
       printf('%.4f', bm25(index_fts_symbols)) AS rank
FROM index_fts_symbols
JOIN index_symbols s ON s.rowid = index_fts_symbols.rowid
WHERE index_fts_symbols MATCH '$q_esc'
  AND s.project_id = '$pid_esc'
ORDER BY rank
LIMIT $limit_n;
SQL
}

run_artifacts() {
  # Replace newlines in the snippet output with spaces so each result is a single line.
  sqlite3 "$db" <<SQL
.mode list
.separator |
SELECT a.kind, a.path, COALESCE(a.title,''), COALESCE(a.sprint_branch,''),
       replace(replace(snippet(index_fts_artifacts, 2, '«', '»', ' … ', 12), char(10), ' '), char(13), ' ') AS ctx,
       printf('%.4f', bm25(index_fts_artifacts)) AS rank
FROM index_fts_artifacts
JOIN artifacts a ON a.rowid = index_fts_artifacts.rowid
WHERE index_fts_artifacts MATCH '$q_esc'
  AND a.project_id = '$pid_esc'
ORDER BY rank
LIMIT $limit_n;
SQL
}

emit_md() {
  echo "# shctx search — \`$text\`"
  echo
  if [[ "$scope" == symbols || "$scope" == all ]]; then
    echo "## Symbols"
    echo
    echo "| package | kind | name | file:line | rank |"
    echo "|---|---|---|---|---|"
    while IFS='|' read -r pkg kind name sig path line rank; do
      [[ -z "$name" ]] && continue
      echo "| \`$pkg\` | $kind | \`$name\` | \`$path:$line\` | $rank |"
    done < <(run_symbols)
    echo
  fi
  if [[ "$scope" == artifacts || "$scope" == all ]]; then
    echo "## Artifacts"
    echo
    while IFS='|' read -r kind path title branch ctx rank; do
      [[ -z "$path" ]] && continue
      echo "- **$kind** · \`$path\`${branch:+ · branch \`$branch\`} · rank $rank"
      echo "  - $title"
      [[ -n "$ctx" ]] && echo "  - $ctx"
    done < <(run_artifacts)
  fi
}

emit_json() {
  echo '{'
  if [[ "$scope" == symbols || "$scope" == all ]]; then
    echo '  "symbols": ['
    first=1
    while IFS='|' read -r pkg kind name sig path line rank; do
      [[ -z "$name" ]] && continue
      (( first )) || echo ','
      first=0
      printf '    {"package":"%s","kind":"%s","name":"%s","file":"%s","line":%s,"rank":%s}' \
        "$pkg" "$kind" "$name" "$path" "${line:-null}" "$rank"
    done < <(run_symbols)
    echo
    echo '  ]'
  fi
  if [[ "$scope" == all ]]; then echo '  ,'; fi
  if [[ "$scope" == artifacts || "$scope" == all ]]; then
    echo '  "artifacts": ['
    first=1
    while IFS='|' read -r kind path title branch ctx rank; do
      [[ -z "$path" ]] && continue
      (( first )) || echo ','
      first=0
      ctx_esc=$(printf '%s' "$ctx"   | sed 's/"/\\"/g')
      ttl_esc=$(printf '%s' "$title" | sed 's/"/\\"/g')
      printf '    {"kind":"%s","path":"%s","title":"%s","branch":"%s","context":"%s","rank":%s}' \
        "$kind" "$path" "$ttl_esc" "$branch" "$ctx_esc" "$rank"
    done < <(run_artifacts)
    echo
    echo '  ]'
  fi
  echo '}'
}

case "$fmt" in
  md)   emit_md ;;
  json) emit_json ;;
esac
