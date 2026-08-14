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
    body_esc=$(esc "$BODY")
    title_esc=$(esc "$TITLE")
    # $KIND (--kind=, default "note") and $TAGS (--tags=, a JSON array string)
    # were interpolated raw with no escaping at all.
    kind_esc=$(esc "$KIND")
    tags_esc=$(esc "$TAGS")
    shctx_sql "INSERT INTO mem_entries (id,project_id,kind,title,body,tags,pinned,created_at,updated_at)
               VALUES ('$id','$(esc "$project_id")','$kind_esc','$title_esc','$body_esc','$tags_esc',0,$now,$now);"
    echo "$id"
    ;;
  list)
    shctx_sql -header -column \
      "SELECT id, kind, title, pinned, created_at FROM mem_entries WHERE project_id='$(esc "$project_id")' ORDER BY pinned DESC, created_at DESC;"
    ;;
  search)
    Q=""; parse_kv "$@"
    [[ -n "$Q" ]] || { echo "ERROR: --q=<text> required for mem search" >&2; exit 1; }
    q_esc="%$(esc "$Q")%"
    shctx_sql -header -column \
      "SELECT id, kind, title, pinned FROM mem_entries WHERE project_id='$(esc "$project_id")' AND (title LIKE '$q_esc' OR body LIKE '$q_esc') ORDER BY pinned DESC, created_at DESC;"
    ;;
  pin|unpin)
    id="${1:-}"; [[ -n "$id" ]] || { echo "ERROR: usage: shctx mem $sub <id>" >&2; exit 1; }
    val=$([[ "$sub" == "pin" ]] && echo 1 || echo 0)
    # $id is a bare CLI positional — the same WHERE-bypass/mass-UPDATE class
    # as GH #295 (cmd_teammate.sh retire/status) if left unescaped.
    shctx_sql "UPDATE mem_entries SET pinned=$val, updated_at=$now WHERE id='$(esc "$id")' AND project_id='$(esc "$project_id")';"
    ;;
  show)
    id="${1:-}"; [[ -n "$id" ]] || { echo "ERROR: usage: shctx mem show <id>" >&2; exit 1; }
    shctx_sql -header -column \
      "SELECT id, kind, title, body, tags, pinned, created_at, updated_at
         FROM mem_entries WHERE project_id='$(esc "$project_id")' AND id='$(esc "$id")';"
    ;;
  rm|delete)
    id="${1:-}"; [[ -n "$id" ]] || { echo "ERROR: usage: shctx mem rm <id>" >&2; exit 1; }
    # Same WHERE-bypass class as #295: a crafted <id> (e.g. `' OR '1'='1`)
    # unescaped would DELETE every mem_entries row for this project, not
    # just the named one.
    shctx_sql "DELETE FROM mem_entries WHERE project_id='$(esc "$project_id")' AND id='$(esc "$id")';"
    echo "shctx mem rm: removed $id"
    ;;
  *) echo "ERROR: usage: shctx mem <add|list|search|show|pin|unpin|rm>" >&2; exit 1 ;;
esac
