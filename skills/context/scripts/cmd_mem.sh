#!/usr/bin/env bash
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

sub="${1:-}"; shift || true
project_id=$(shctx_project_id)
now=$(shctx_now)

parse_kv() {
  for a in "$@"; do
    case "$a" in
      --kind=*)  KIND="${a#--kind=}" ;;
      --title=*) TITLE="${a#--title=}" ;;
      --body=*)  BODY="${a#--body=}" ;;
      --tags=*)  TAGS="${a#--tags=}" ;;
      --q=*)     Q="${a#--q=}" ;;
    esac
  done
}

case "$sub" in
  add)
    KIND="note"; TITLE=""; BODY=""; TAGS="[]"; parse_kv "$@"
    [[ -n "$TITLE" ]] || { echo "ERROR: --title required" >&2; exit 1; }
    id=$(shctx_uuid7)
    body_esc=${BODY//\'/\'\'}
    title_esc=${TITLE//\'/\'\'}
    shctx_sql "INSERT INTO mem_entries (id,project_id,kind,title,body,tags,pinned,created_at,updated_at)
               VALUES ('$id','$project_id','$KIND','$title_esc','$body_esc','$TAGS',0,$now,$now);"
    echo "$id"
    ;;
  list)
    shctx_sql -header -column \
      "SELECT id, kind, title, pinned, created_at FROM mem_entries WHERE project_id='$project_id' ORDER BY pinned DESC, created_at DESC;"
    ;;
  search)
    Q=""; parse_kv "$@"
    [[ -n "$Q" ]] || { echo "ERROR: --q=<text> required for mem search" >&2; exit 1; }
    q_esc="%${Q//\'/\'\'}%"
    shctx_sql -header -column \
      "SELECT id, kind, title, pinned FROM mem_entries WHERE project_id='$project_id' AND (title LIKE '$q_esc' OR body LIKE '$q_esc') ORDER BY pinned DESC, created_at DESC;"
    ;;
  pin|unpin)
    id="${1:-}"; [[ -n "$id" ]] || { echo "ERROR: usage: shctx mem $sub <id>" >&2; exit 1; }
    val=$([[ "$sub" == "pin" ]] && echo 1 || echo 0)
    shctx_sql "UPDATE mem_entries SET pinned=$val, updated_at=$now WHERE id='$id' AND project_id='$project_id';"
    ;;
  show)
    id="${1:-}"; [[ -n "$id" ]] || { echo "ERROR: usage: shctx mem show <id>" >&2; exit 1; }
    shctx_sql -header -column \
      "SELECT id, kind, title, body, tags, pinned, created_at, updated_at
         FROM mem_entries WHERE project_id='$project_id' AND id='$id';"
    ;;
  rm|delete)
    id="${1:-}"; [[ -n "$id" ]] || { echo "ERROR: usage: shctx mem rm <id>" >&2; exit 1; }
    shctx_sql "DELETE FROM mem_entries WHERE project_id='$project_id' AND id='$id';"
    echo "shctx mem rm: removed $id"
    ;;
  *) echo "ERROR: usage: shctx mem <add|list|search|show|pin|unpin|rm>" >&2; exit 1 ;;
esac
