#!/usr/bin/env bash
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

sub="${1:-show}"; shift || true
lock="$(shctx_lock_path)"
project_id=$(shctx_project_id)
now=$(shctx_now)

parse_kv() {
  MODE="context"; SESS=""
  for a in "$@"; do
    case "$a" in
      --mode=*)    MODE="${a#--mode=}" ;;
      --session=*) SESS="${a#--session=}" ;;
    esac
  done
}

case "$sub" in
  show)
    if [[ -f "$lock" ]]; then
      echo "lock: held"; jq . "$lock"
    else
      echo "lock: free"
    fi
    ;;
  acquire)
    parse_kv "$@"
    [[ -n "$SESS" ]] || SESS=$(shctx_uuid7)
    if [[ -f "$lock" ]]; then
      echo "ERROR: lock already held" >&2; exit 1
    fi
    jq -nc --arg s "$SESS" --arg m "$MODE" --argjson p "$$" --argjson at "$now" \
      '{holder_session_id:$s, mode:$m, acquired_at:$at, pid:$p, children:[]}' > "$lock"
    # $SESS (--session=) and $MODE (--mode=, no enum here) are free-text CLI
    # flags and were interpolated raw with zero escaping.
    shctx_sql "INSERT INTO locks_history (project_id, session_id, mode, acquired_at)
               VALUES ('$(esc "$project_id")', '$(esc "$SESS")', '$(esc "$MODE")', $now);"
    echo "lock: acquired ($SESS, $MODE)"
    ;;
  release)
    force=0
    for a in "$@"; do
      case "$a" in --force|--all) force=1 ;; esac
    done
    if (( force )); then
      # v5.0.4 — --force / --all aliases reap (no liveness check).
      [[ -f "$lock" ]] || { echo "lock: free"; exit 0; }
      sess=$(jq -r .holder_session_id "$lock" 2>/dev/null || echo "")
      rm -f "$lock"
      shctx_sql "UPDATE locks_history SET released_at=$now, released_by='force' WHERE session_id='$(esc "$sess")' AND released_at IS NULL;"
      echo "lock: released (force)"
      exit 0
    fi
    [[ -f "$lock" ]] || { echo "lock: free"; exit 0; }
    sess=$(jq -r .holder_session_id "$lock")
    rm -f "$lock"
    shctx_sql "UPDATE locks_history SET released_at=$now, released_by='normal' WHERE session_id='$(esc "$sess")' AND released_at IS NULL;"
    echo "lock: released"
    ;;
  reap)
    [[ -f "$lock" ]] || { echo "lock: free"; exit 0; }
    pid=$(jq -r .pid "$lock"); at=$(jq -r .acquired_at "$lock"); sess=$(jq -r .holder_session_id "$lock")
    age_min=$(( (now - at) / 60 ))
    if ! kill -0 "$pid" 2>/dev/null || (( age_min > 60 )); then
      rm -f "$lock"
      shctx_sql "UPDATE locks_history SET released_at=$now, released_by='reap' WHERE session_id='$(esc "$sess")' AND released_at IS NULL;"
      echo "lock: reaped (pid=$pid, age=${age_min}m)"
    else
      echo "lock: held by live pid $pid (age ${age_min}m); not reaping"
      exit 1
    fi
    ;;
  *) echo "ERROR: usage: shctx lock <show|acquire|release|reap>" >&2; exit 1 ;;
esac
