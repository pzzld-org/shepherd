#!/usr/bin/env bash
# shctx signal — dedicated CROSS-SESSION handoff channel (v6.3.7, #206).
#
# SCOPE — READ THIS FIRST. This is ONLY for two INDEPENDENT sessions that share a
# repo but no team graph (today: the `--staged` plant->spawn `seed-ready` nudge,
# spawn-flags.md §--staged). It is NOT a teammate<->lead inbox. Intra-session
# coordination — a teammate reporting to its lead, root draining teammate status —
# uses the harness-native `SendMessage` tool; root's canonical inbox is that
# native queue, never a table. Do not reach for `signal` to talk to a teammate.
#
# Deliberately narrow: send + poll(+--consume). No ack / read / stale tri-state
# (that ambiguity was the retired mailbox's, and its desync with SendMessage was
# #206). Nothing "drains" this channel and no Stop hook reads it, so it can never
# manufacture a phantom-unread. The committed artifact (e.g. the verified seed
# file) remains the source of truth — a signal is only a nudge.
#
#   shctx signal send --to=<recipient> --kind=<k> <<<'<payload-json>'   -> prints id
#   shctx signal poll --as=<recipient> [--kind=<k>] [--consume] [--json]
#
# Exit: 0 ok; 1 runtime error (bad JSON, missing DB); 2 usage error.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$HERE/_lib.sh"
DB="${SHCTX_DB:-$(shctx_db_path)}"
[[ -f "$DB" ]] || { echo "ERR: registry DB not found at $DB" >&2; exit 1; }
now_ms() { echo $(($(date +%s) * 1000)); }
project_id() { sqlite3 "$DB" "SELECT id FROM projects LIMIT 1;"; }

usage() { cat <<'U'
shctx signal send --to=<recipient> --kind=<kind> <<<payload-json   (prints new id)
shctx signal poll --as=<recipient> [--kind=<kind>] [--consume] [--json]

CROSS-SESSION ONLY. Intra-session teammate<->lead messaging uses native SendMessage.
U
}

sub="${1:-}"; shift || true
case "$sub" in
  send)
    to=""; kind=""
    while [[ $# -gt 0 ]]; do case "$1" in
      --to=*)   to="${1#*=}";;
      --kind=*) kind="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    [[ -n "$to" && -n "$kind" ]] || { usage >&2; exit 2; }
    payload="$(cat)"
    echo "$payload" | python3 -c 'import sys,json;json.loads(sys.stdin.read())' >/dev/null 2>&1 \
      || { echo "ERR: payload not valid JSON" >&2; exit 1; }
    pid="$(project_id)"
    [[ -n "$pid" ]] || { echo "ERR: no project registered (run 'shctx init')" >&2; exit 1; }
    sender="${CLAUDE_TEAMMATE_NAME:-${SHEPHERD_SESSION_ID:-root}}"
    ts="$(now_ms)"
    safe_payload="$(esc "$payload")"
    # $to/$kind (free-text CLI flags) and $sender/$pid were interpolated raw
    # with no escaping in THIS INSERT — inconsistent with `poll` below, which
    # already escaped the same $kind value correctly.
    id=$(sqlite3 "$DB" "INSERT INTO session_signals (project_id, sender, recipient, kind, payload, sent_at) VALUES ('$(esc "$pid")','$(esc "$sender")','$(esc "$to")','$(esc "$kind")','$safe_payload',$ts) RETURNING id;")
    echo "$id"
    ;;
  poll)
    as=""; kind=""; consume=0; json=0
    while [[ $# -gt 0 ]]; do case "$1" in
      --as=*)    as="${1#*=}";;
      --kind=*)  kind="${1#*=}";;
      --consume) consume=1;;
      --json)    json=1;;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    [[ -n "$as" ]] || { usage >&2; exit 2; }
    where="recipient='$(esc "$as")' AND consumed_at IS NULL"
    [[ -n "$kind" ]] && where="$where AND kind='$(esc "$kind")'"
    if [[ "$json" == "1" ]]; then
      sqlite3 -json "$DB" "SELECT * FROM session_signals WHERE $where ORDER BY sent_at;"
    else
      sqlite3 "$DB" "SELECT id||' '||kind||' '||payload FROM session_signals WHERE $where ORDER BY sent_at;"
    fi
    if [[ "$consume" == "1" ]]; then
      sqlite3 "$DB" "UPDATE session_signals SET consumed_at=$(now_ms) WHERE $where;"
    fi
    ;;
  ""|help|--help|-h) usage;;
  *) echo "unknown subcommand: $sub" >&2; usage >&2; exit 2;;
esac
