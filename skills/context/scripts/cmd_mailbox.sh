#!/usr/bin/env bash
# shctx mailbox — send/recv/ack/stale
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB="${SHCTX_DB:-$(git rev-parse --show-toplevel 2>/dev/null)/.artifacts/root.db}"
[[ -f "$DB" ]] || { echo "ERR: registry DB not found at $DB" >&2; exit 1; }
now_ms() { echo $(($(date +%s) * 1000)); }
project_id() { sqlite3 "$DB" "SELECT id FROM projects LIMIT 1;"; }

usage() { cat <<'U'
shctx mailbox send --to=<name> --kind=<k> [--target-file=<p>] [--requires-ack] <<<payload-json
shctx mailbox recv --as=<name> [--unread-only] [--mark-read]
shctx mailbox ack <id>
shctx mailbox stale [--mins=<n>]
U
}

sub="${1:-}"; shift || true
case "$sub" in
  send)
    to=""; kind="generic"; target=""; ack=0
    while [[ $# -gt 0 ]]; do case "$1" in
      --to=*)          to="${1#*=}";;
      --kind=*)        kind="${1#*=}";;
      --target-file=*) target="${1#*=}";;
      --requires-ack)  ack=1;;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    [[ -n "$to" ]] || { usage; exit 2; }
    payload="$(cat)"
    # Validate payload JSON
    echo "$payload" | python3 -c 'import sys,json;json.loads(sys.stdin.read())' >/dev/null 2>&1 \
      || { echo "ERR: payload not valid JSON" >&2; exit 1; }
    pid="$(project_id)"
    sender="${CLAUDE_TEAMMATE_NAME:-root}"
    ts="$(now_ms)"
    # Escape single quotes in payload
    safe_payload="${payload//\'/''}"
    safe_target="${target//\'/''}"
    id=$(sqlite3 "$DB" "INSERT INTO mailbox (project_id, sender_id, recipient_name, kind, payload, target_file, requires_ack, sent_at) VALUES ('$pid','$sender','$to','$kind','$safe_payload',NULLIF('$safe_target',''),$ack,$ts) RETURNING id;")
    echo "$id"
    ;;
  recv)
    as=""; unread=0; mark=0
    while [[ $# -gt 0 ]]; do case "$1" in
      --as=*)        as="${1#*=}";;
      --unread-only) unread=1;;
      --mark-read)   mark=1;;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    [[ -n "$as" ]] || { usage; exit 2; }
    where="recipient_name='$as'"
    [[ "$unread" == "1" ]] && where="$where AND read_at IS NULL"
    sqlite3 -json "$DB" "SELECT * FROM mailbox WHERE $where ORDER BY sent_at;"
    if [[ "$mark" == "1" ]]; then
      sqlite3 "$DB" "UPDATE mailbox SET read_at=$(now_ms) WHERE $where AND read_at IS NULL;"
    fi
    ;;
  ack)
    id="$1"
    [[ "$id" =~ ^[0-9]+$ ]] || { echo "ERR: id must be numeric" >&2; exit 2; }
    sqlite3 "$DB" "UPDATE mailbox SET acked_at=$(now_ms) WHERE id=$id;"
    ;;
  stale)
    mins=30
    while [[ $# -gt 0 ]]; do case "$1" in
      --mins=*) mins="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    cutoff=$(( $(now_ms) - mins*60*1000 ))
    sqlite3 -header -column "$DB" "SELECT id, recipient_name, kind, sent_at FROM mailbox WHERE requires_ack=1 AND acked_at IS NULL AND sent_at < $cutoff ORDER BY sent_at;"
    ;;
  ""|help|--help|-h) usage;;
  *) echo "unknown subcommand: $sub" >&2; usage; exit 2;;
esac
