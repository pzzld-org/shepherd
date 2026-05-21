#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB="${SHCTX_DB:-$(git rev-parse --show-toplevel 2>/dev/null)/.artifacts/root.db}"
[[ -f "$DB" ]] || { echo "ERR: registry DB not found at $DB" >&2; exit 1; }
now_ms() { echo $(($(date +%s) * 1000)); }
project_id() { sqlite3 "$DB" "SELECT id FROM projects LIMIT 1;"; }

usage() { cat <<'U'
shctx escalate --role=<r> --question=<q> [--blocking] [--phase=<p>] [--context=<json>]
shctx escalate list [--open-only]
shctx escalate resolve <id> --reply=<text>
U
}

sub="${1:-}"
# If sub is a known subcommand, shift; otherwise treat top-level as create.
case "$sub" in
  list|resolve|help|--help|-h|"") shift || true ;;
  *) sub="create" ;;  # top-level create form
esac

case "$sub" in
  create)
    role=""; q=""; blocking=1; phase=""; ctx=""
    while [[ $# -gt 0 ]]; do case "$1" in
      --role=*)     role="${1#*=}";;
      --question=*) q="${1#*=}";;
      --blocking)   blocking=1;;
      --phase=*)    phase="${1#*=}";;
      --context=*)  ctx="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    [[ -n "$role" && -n "$q" ]] || { usage; exit 2; }
    [[ -n "$ctx" ]] && echo "$ctx" | python3 -c 'import sys,json;json.loads(sys.stdin.read())' >/dev/null 2>&1 || ctx=""
    pid="$(project_id)"
    tname="${CLAUDE_TEAMMATE_NAME:-}"
    tid=""
    [[ -n "$tname" ]] && tid=$(sqlite3 "$DB" "SELECT id FROM teammates WHERE teammate_name='$tname' ORDER BY spawned_at DESC LIMIT 1;")
    ts="$(now_ms)"
    safe_q="${q//\'/''}"; safe_ctx="${ctx//\'/''}"
    id=$(sqlite3 "$DB" "INSERT INTO escalations (project_id, teammate_id, role, phase, question, blocking, context_refs, raised_at) VALUES ('$pid', NULLIF('$tid',''), '$role', NULLIF('$phase',''), '$safe_q', $blocking, NULLIF('$safe_ctx',''), $ts) RETURNING id;")
    echo "$id"
    ;;
  list)
    open_only=0
    while [[ $# -gt 0 ]]; do case "$1" in
      --open-only) open_only=1;;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    if [[ "$open_only" == "1" ]]; then
      sqlite3 -header -column "$DB" "SELECT * FROM v_escalations_open;"
    else
      sqlite3 -header -column "$DB" "SELECT id, role, phase, blocking, raised_at, resolved_at FROM escalations ORDER BY raised_at DESC;"
    fi
    ;;
  resolve)
    id="$1"; shift
    [[ "$id" =~ ^[0-9]+$ ]] || { echo "ERR: id must be numeric" >&2; exit 2; }
    reply=""
    while [[ $# -gt 0 ]]; do case "$1" in
      --reply=*) reply="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    [[ -n "$reply" ]] || { echo "ERR: --reply required" >&2; exit 2; }
    safe="${reply//\'/''}"
    sqlite3 "$DB" "UPDATE escalations SET resolved_at=$(now_ms), resolution='$safe' WHERE id=$id;"
    ;;
  ""|help|--help|-h) usage;;
esac
