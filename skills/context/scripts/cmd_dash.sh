#!/usr/bin/env bash
# shctx dash — one-glance sprint dashboard (v6.1.5 #13).
#
# A thin COMPOSITION of primitives that already exist — no new table, no new
# subsystem. Every row is read from a view or file another command already owns:
#   SPRINT/FOCUS  focus table (v6.0.9)           — north-star + cursor
#   GRAPH         graph/state.json (cmd_graph)    — completion %, ready/in-flight
#   TEAMMATES     v_teammates_live (0007)         — live lanes + idle time
#   SIGNALS       session_signals (0020)          — pending cross-session nudges
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

# SIGNALS: pending (unconsumed) cross-session nudges per recipient (v6.3.7 #206).
# The dedicated inter-session channel — NOT a teammate inbox (that is native
# SendMessage). Shown only when something is waiting to be polled.
sline="$(shctx_sql "SELECT recipient||': '||COUNT(*) FROM session_signals WHERE consumed_at IS NULL GROUP BY recipient ORDER BY COUNT(*) DESC;" 2>/dev/null || true)"
if [[ -n "$sline" ]]; then
  echo "SIGNALS     pending"
  printf '%s\n' "$sline" | sed 's/^/              /'
else
  echo "SIGNALS     none pending"
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

# ADAPT: self-improvement registry — measured averages + harvested priors +
# latest lesson. Cheap reads only (the full trend scan lives in the SessionStart
# banner + close report); makes the loop visible at the same glance as lanes.
apid="$(shctx_project_id 2>/dev/null || true)"
if [[ -n "$apid" ]]; then
  arow="$(shctx_sql "SELECT n||'|'||CAST(ROUND(COALESCE(avg_lane_count,0)) AS INTEGER)||'|'||CAST(ROUND(COALESCE(avg_wall_minutes,0)) AS INTEGER) FROM v_sprint_metrics_avg WHERE project_id='$apid';" 2>/dev/null || true)"
  pri="$(shctx_sql "SELECT count(*) FROM mem_entries WHERE project_id='$apid' AND kind='prior';" 2>/dev/null || echo 0)"
  an="${arow%%|*}"
  if [[ -n "$an" && "$an" != "0" ]]; then
    IFS='|' read -r an al aw <<< "$arow"
    printf 'ADAPT       %s sprint(s)  lanes~%s  wall~%sm  priors=%s\n' "$an" "$al" "$aw" "${pri:-0}"
    lesson="$(shctx_sql "SELECT substr(replace(title,'prior: ',''),1,58) FROM mem_entries WHERE project_id='$apid' AND kind='prior' ORDER BY created_at DESC, id DESC LIMIT 1;" 2>/dev/null || true)"
    [[ -n "$lesson" ]] && printf '              latest: %s\n' "$lesson"
  elif [[ "${pri:-0}" -gt 0 ]]; then
    printf 'ADAPT       priors=%s (no sprint metrics yet)\n' "$pri"
  else
    echo "ADAPT       no history yet (first cycle lands at close)"
  fi
fi

# EVAL: latest recorded quality verdict for a latent output (v6.2.3 eval harness).
# Omit-if-empty: only surfaces once something has been `shctx eval … --record`ed.
if [[ -n "${apid:-}" ]] && [[ -n "$(shctx_sql "SELECT 1 FROM sqlite_master WHERE type='table' AND name='eval_runs' LIMIT 1;" 2>/dev/null || true)" ]]; then
  erow="$(shctx_sql "SELECT kind||' '||COALESCE(subject_ref,'·')||' '||score||'/'||threshold||' '||CASE passed WHEN 1 THEN 'PASS' ELSE 'FAIL' END
                     FROM v_eval_latest WHERE project_id='$apid' ORDER BY created_at DESC, id DESC LIMIT 1;" 2>/dev/null || true)"
  if [[ -n "$erow" ]]; then
    ecount="$(shctx_sql "SELECT count(*) FROM v_eval_latest WHERE project_id='$apid';" 2>/dev/null || echo 0)"
    printf 'EVAL        latest: %s  (%s scored)\n' "$erow" "$ecount"
  fi
fi

# STALE: GitHub cache freshness (issues + PRs).
gi="$(shctx_sql 'SELECT COALESCE(MAX(refreshed_at),0) FROM index_issues;' 2>/dev/null || echo 0)"
gp="$(shctx_sql 'SELECT COALESCE(MAX(refreshed_at),0) FROM index_prs;'    2>/dev/null || echo 0)"
printf 'STALE       issues=%s  prs=%s\n' "$(_age "$gi")" "$(_age "$gp")"
