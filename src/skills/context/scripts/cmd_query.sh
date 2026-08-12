#!/usr/bin/env bash
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

name="${1:-}"; shift || true
[[ -n "$name" ]] || { echo "ERROR: usage: shctx query <name> [--json|--md] [--key=val ...]" >&2; exit 1; }

fmt="md"
bind_keys=()
bind_vals=()
for a in "$@"; do
  case "$a" in
    --json) fmt=json ;;
    --md)   fmt=md ;;
    --*=*)
      k=${a%%=*}; k=${k#--}; v=${a#*=}
      bind_keys+=("$k")
      bind_vals+=("$v")
      ;;
    *) echo "ERROR: bad arg: $a" >&2; exit 1 ;;
  esac
done

f="$(shctx_skill_root)/queries/$name.sql"
[[ -f "$f" ]] || { echo "ERROR: query not found: $name" >&2; exit 1; }

project_id=$(shctx_project_id)
sql=$(cat "$f")
sql=${sql//:project_id/\'$project_id\'}
i=0
while [[ $i -lt ${#bind_keys[@]} ]]; do
  k=${bind_keys[$i]}
  v=${bind_vals[$i]}
  v=${v//\'/''}
  sql=${sql//:$k/\'$v\'}
  i=$((i + 1))
done
# Replace any remaining :param tokens (optional params not supplied by the
# caller) with NULL so that IS-NULL predicates evaluate to match-all.
sql=$(printf '%s' "$sql" | sed 's/:[a-z_][a-z_0-9]*/NULL/g')

db="$(shctx_db_path)"
case "$fmt" in
  json) printf '%s\n' "$sql" | sqlite3 -bail -json "$db" ;;
  md)
    printf '%s\n' "$sql" | sqlite3 -bail -header -markdown "$db" 2>/dev/null \
      || printf '%s\n' "$sql" | sqlite3 -bail -header -column "$db"
    ;;
esac
