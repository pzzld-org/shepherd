#!/usr/bin/env bash
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

db="$(shctx_db_path)"
[[ -f "$db" ]] || { echo "ERROR: no DB at $db — run 'shctx init'" >&2; exit 1; }

echo "Schema version: $(shctx_sql 'SELECT MAX(version) FROM schema_versions;')"
echo
echo "Tables (rows):"
for t in projects sessions profiles_defs mem_entries \
         index_symbols index_concepts index_issues index_prs \
         index_releases index_milestones logs_events artifacts \
         locks_history; do
  n=$(shctx_sql "SELECT COUNT(*) FROM $t;")
  printf "  %-20s %s\n" "$t" "$n"
done
echo
echo "Refresh staleness:"
for t in index_symbols index_issues index_prs index_releases index_milestones; do
  last=$(shctx_sql "SELECT COALESCE(MAX(refreshed_at),0) FROM $t;")
  if [[ "$last" -eq 0 ]]; then
    age="never"
  else
    age="$(( ($(shctx_now) - last) / 60 )) min ago"
  fi
  printf "  %-20s %s\n" "$t" "$age"
done
echo
lock="$(shctx_lock_path)"
if [[ -f "$lock" ]]; then
  echo "Lock: held"
  jq . "$lock"
else
  echo "Lock: free"
fi
