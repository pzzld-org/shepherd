#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/_lib.sh"
DB="${SHCTX_DB:-$(shctx_db_path)}"
[[ -f "$DB" ]] || { echo "ERR: registry DB not found at $DB" >&2; exit 1; }
now_ms() { echo $(($(date +%s) * 1000)); }
project_id() { sqlite3 "$DB" "SELECT id FROM projects LIMIT 1;"; }

usage() { cat <<'U'
shctx deliverable promise --kind=<k> --target=<ref> [--role=<r>]
shctx deliverable complete <id>
shctx deliverable stalled [--since-mins=<n>]
U
}

sub="${1:-}"; shift || true
case "$sub" in
  promise)
    kind=""; target=""; role=""
    while [[ $# -gt 0 ]]; do case "$1" in
      --kind=*)   kind="${1#*=}";;
      --target=*) target="${1#*=}";;
      --role=*)   role="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    [[ -n "$kind" && -n "$target" ]] || { usage; exit 2; }
    pid="$(project_id)"
    session="${CLAUDE_SESSION_ID:-unknown}"
    role="${role:-${CLAUDE_AGENT_ROLE:-unknown}}"
    ts="$(now_ms)"
    safe_t="${target//\'/''}"
    id=$(sqlite3 "$DB" "INSERT INTO deliverables (project_id, agent_session, agent_role, kind, target_ref, promised_at, status) VALUES ('$pid','$session','$role','$kind','$safe_t',$ts,'pending') RETURNING id;")
    echo "$id"
    ;;
  complete)
    id="$1"
    [[ "$id" =~ ^[0-9]+$ ]] || { echo "ERR: id must be numeric" >&2; exit 2; }
    sqlite3 "$DB" "UPDATE deliverables SET status='delivered', delivered_at=$(now_ms) WHERE id=$id;"
    ;;
  stalled)
    since=10
    while [[ $# -gt 0 ]]; do case "$1" in
      --since-mins=*) since="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    cutoff=$(( $(now_ms) - since*60*1000 ))
    sqlite3 -header -column "$DB" "SELECT id, agent_role, kind, target_ref, promised_at FROM deliverables WHERE status='pending' AND promised_at < $cutoff ORDER BY promised_at;"
    ;;
  ""|help|--help|-h) usage;;
  *) echo "unknown subcommand: $sub" >&2; usage; exit 2;;
esac
