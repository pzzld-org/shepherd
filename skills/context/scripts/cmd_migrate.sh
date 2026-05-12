#!/usr/bin/env bash
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

migdir="$(shctx_skill_root)/schema/migrations"
[[ -d "$migdir" ]] || { echo "no migrations dir"; exit 0; }

current=$(shctx_sql "SELECT COALESCE(MAX(version),0) FROM schema_versions;")
applied=0
shopt -s nullglob
for f in "$migdir"/[0-9][0-9][0-9][0-9]_*.sql; do
  fname=$(basename "$f")
  num=${fname:0:4}
  v=$((10#$num))
  (( v > current )) || continue
  echo "shctx migrate: applying $fname"
  sum=$(shasum -a 256 "$f" | awk '{print $1}')
  sqlite3 "$(shctx_db_path)" < "$f"
  shctx_sql "INSERT INTO schema_versions (version, applied_at, checksum)
             VALUES ($v, $(shctx_now), '$sum');"
  applied=$((applied+1))
done
if (( applied == 0 )); then
  echo "shctx migrate: no migrations pending (at version $current)"
else
  echo "shctx migrate: applied $applied migration(s)"
fi
