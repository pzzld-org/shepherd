#!/usr/bin/env bash
# shctx dash — one-glance sprint dashboard (v6.1.5 #13).
#
# A thin COMPOSITION of primitives that already exist — no new table, no new
# subsystem. Every row is read from a view or file another command already owns:
#   SPRINT/FOCUS  focus table (v6.0.9)           — north-star + cursor
#   GRAPH         graph/state.json (cmd_graph)    — completion %, ready/in-flight
#   TEAMMATES     v_teammates_live (0007)         — live lanes + idle time
#   MAILBOX       v_mailbox_unread_per_recipient  — unread fan-in
#   ESCALATION    v_escalations_open              — open escalations + oldest
#   LOOPS         v_loops_active (0012)           — focus/convergence progress
#   STALE         index_issues/index_prs          — GitHub cache freshness
#
# Built to be looped at a cadence:  /shepherd:loop <interval> shctx dash
# Read-only. bash-3.2-safe; degrades cleanly on missing DB / graph state / tmux.
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

# Human age from epoch-seconds ("-"/0/empty → "-").
_age() {
  local then="${1:-}" now d
  [[ -z "$then" || "$then" == "0" || "$then" == "-" ]] && { echo "-"; return 0; }
  now="$(shctx_now)"; d=$(( now - then ))
  (( d < 0 )) && d=0
  if   (( d < 90 ));     then echo "${d}s"
  elif (( d < 5400 ));   then echo "$(( d/60 ))m"
  elif (( d < 172800 )); then echo "$(( d/3600 ))h"
  else                        echo "$(( d/86400 ))d"; fi
}

db="$(shctx_db_path)"
branch="$(current_sprint)"
proj="$(basename "$(shctx_repo_root)")"
ts="$(date '+%H:%M:%S' 2>/dev/null || echo '--:--:--')"

printf '═══ SHEPHERD DASH ═══  %s  @%s  %s\n' "$proj" "$branch" "$ts"

# --- DB-less degrade ---------------------------------------------------------
if [[ ! -f "$db" ]]; then
  echo "  (no registry DB — run 'shctx init'; dashboard limited to git state)"
  exit 0
fi

# SPRINT: schema + lock; FOCUS: north-star objective (truncated, newline-stripped).
schema="$(shctx_sql 'SELECT MAX(version) FROM schema_versions;' 2>/dev/null || echo '?')"
lock="$(shctx_lock_path)"; lockstate="free"; [[ -f "$lock" ]] && lockstate="HELD"
printf 'SPRINT      schema=v%s  lock=%s\n' "${schema:-?}" "$lockstate"
obj="$(shctx_sql "SELECT COALESCE(substr(replace(replace(objective,char(10),' '),char(13),' '),1,76),'') FROM focus WHERE sprint='$branch' LIMIT 1;" 2>/dev/null || true)"
[[ -n "$obj" ]] && printf 'FOCUS       %s…\n' "$obj"

# GRAPH: delegate to the graph-status renderer when stage-graph state exists.
gstate="$(shctx_artifacts_root)/graph/state.json"
if [[ -f "$gstate" ]]; then
  echo "GRAPH"
  bash "$HERE/cmd_graph.sh" status 2>/dev/null | sed 's/^/  /' || echo "  (graph status error)"
else
  echo "GRAPH       (no stage-graph state — solo / pre-extract)"
fi

# TEAMMATES: live count + compact roster (lane:role:status:idle).
tline="$(shctx_sql "
  SELECT teammate_name||':'||COALESCE(agent_type,'?')||':'||status||':'||(ms_since_seen/1000)||'s'
  FROM v_teammates_live ORDER BY teammate_name;" 2>/dev/null || true)"
if [[ -n "$tline" ]]; then
  n="$(printf '%s\n' "$tline" | grep -c . || true)"
  printf 'TEAMMATES   %s live\n' "$n"
  printf '%s\n' "$tline" | sed 's/^/              /'
else
  echo "TEAMMATES   none live"
fi

# MAILBOX: unread fan-in per recipient (only when something is unread).
mline="$(shctx_sql "SELECT recipient_name||': '||unread_count FROM v_mailbox_unread_per_recipient ORDER BY unread_count DESC;" 2>/dev/null || true)"
if [[ -n "$mline" ]]; then
  echo "MAILBOX     unread"
  printf '%s\n' "$mline" | sed 's/^/              /'
else
  echo "MAILBOX     all read"
fi

# ESCALATION: open count + oldest age.
ec="$(shctx_sql 'SELECT COUNT(*) FROM v_escalations_open;' 2>/dev/null || echo 0)"
if [[ "${ec:-0}" -gt 0 ]]; then
  eo="$(shctx_sql 'SELECT MIN(raised_at) FROM v_escalations_open;' 2>/dev/null || echo 0)"
  printf 'ESCALATION  %s open (oldest %s)\n' "$ec" "$(_age "$eo")"
else
  echo "ESCALATION  none open"
fi

# LOOPS: active focus/convergence/watch loops with iteration progress.
lline="$(shctx_sql "
  SELECT COALESCE(kind,'loop')||' '||COALESCE(latest_iteration,0)||'/'||max_iterations||
         ' (find='||COALESCE(total_findings,0)||')'
  FROM v_loops_active ORDER BY created_at;" 2>/dev/null || true)"
if [[ -n "$lline" ]]; then
  echo "LOOPS       active"
  printf '%s\n' "$lline" | sed 's/^/              /'
else
  echo "LOOPS       none active"
fi

# STALE: GitHub cache freshness (issues + PRs).
gi="$(shctx_sql 'SELECT COALESCE(MAX(refreshed_at),0) FROM index_issues;' 2>/dev/null || echo 0)"
gp="$(shctx_sql 'SELECT COALESCE(MAX(refreshed_at),0) FROM index_prs;'    2>/dev/null || echo 0)"
printf 'STALE       issues=%s  prs=%s\n' "$(_age "$gi")" "$(_age "$gp")"
