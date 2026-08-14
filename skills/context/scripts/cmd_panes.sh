#!/usr/bin/env bash
# shctx panes — in-session observability over teammate tmux panes.
#
# Claude Code owns the panes in teammateMode=tmux|auto (it opens one per teammate).
# shctx does NOT lay them out. This command is the OBSERVABILITY + CLEANUP layer that
# reads the teammates.tmux_pane_id column (written by `shctx teammate register --pane`)
# — the column's first and only consumer.
#
#   status [--stale-mins=N]      per-lane dashboard: liveness + last heartbeat + pane
#   capture [--lines=N]          snapshot each live teammate's pane -> <ns>/logs/panes/<lane>.log
#   tail <lane> [--lines=N]      print the tail of a captured lane log
#   prune [--closed-only]        kill orphan panes (closed teammates; or worktree-gone panes)
#
# All subcommands are read-mostly except `prune` (kills dead panes only — never a live one).
# Pane logs live under <ns>/logs/ (gitignored). bash-3.2-safe; degrades cleanly without tmux.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/_lib.sh"
DB="${SHCTX_DB:-$(shctx_db_path)}"
[[ -f "$DB" ]] || { echo "ERR: registry DB not found at $DB (run 'shctx init')" >&2; exit 1; }
# Schema self-heal (v6.3.3 #200): panes reads declared_state (0019); heal a behind
# DB to HEAD before the query so it can't crash on the missing column. Fail-soft.
shctx_ensure_migrated

NS="$(resolve_workdir)"
PANE_LOG_DIR="$NS/logs/panes"

have_tmux() { command -v tmux >/dev/null 2>&1; }
pane_alive() { tmux display -p -t "$1" '#{pane_id}' >/dev/null 2>&1; }
# Filename-safe lane label (teammate_name may contain slashes/spaces).
safe_name() { printf '%s' "$1" | tr -c 'A-Za-z0-9._-' '_'; }

usage() {
  cat <<'USAGE'
shctx panes status [--stale-mins=N]   per-lane dashboard (liveness + heartbeat + pane id)
shctx panes capture [--lines=N]       snapshot each live teammate pane to <ns>/logs/panes/<lane>.log
shctx panes tail <lane> [--lines=N]   print the tail of a captured lane log
shctx panes prune [--closed-only]     kill orphan panes (closed teammates; else also worktree-gone)
USAGE
}

sub="${1:-}"; shift || true
case "$sub" in
  status|dash)
    stale=5
    while [[ $# -gt 0 ]]; do case "$1" in
      --stale-mins=*) stale="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    # $threshold_ms lands bare (unquoted) in the SQL text below — validate.
    [[ "$stale" =~ ^[0-9]+$ ]] || { echo "ERR: --stale-mins must be a non-negative integer (got '$stale')" >&2; exit 2; }
    threshold_ms=$((stale * 60 * 1000))
    # #200 backstop: if the self-heal could not add declared_state (read-only/locked
    # DB), degrade to a timing-only verdict rather than crash on the missing column.
    if [[ -n "$(sqlite3 "$DB" "SELECT 1 FROM pragma_table_info('teammates') WHERE name='declared_state' LIMIT 1;" 2>/dev/null)" ]]; then
      declared_col="COALESCE(v.declared_state,'-')"
      verdict_case="CASE
               WHEN v.declared_state = 'in-progress' THEN 'ok'
               WHEN v.declared_state = 'error'       THEN 'error'
               WHEN v.declared_state = 'complete'    THEN 'complete'
               WHEN v.declared_state = 'idle'        THEN 'idle'
               WHEN v.ms_since_seen > $threshold_ms AND v.status IN ('booting','active')
                    THEN 'presumed-crashed' ELSE 'ok' END"
    else
      declared_col="'-'"
      verdict_case="CASE WHEN v.ms_since_seen > $threshold_ms AND v.status IN ('booting','active')
                    THEN 'presumed-crashed' ELSE 'ok' END"
    fi
    sqlite3 -header -column "$DB" "
      SELECT v.teammate_name                         AS lane,
             v.agent_type                            AS role,
             v.status                                AS status,
             $declared_col                           AS declared,
             v.ms_since_seen/1000                    AS idle_s,
             COALESCE(v.tmux_pane_id,'-')            AS pane,
             COALESCE(h.phase,'-')                   AS phase,
             $verdict_case                           AS verdict
      FROM v_teammates_live v
      LEFT JOIN heartbeats h
        ON h.teammate_id = v.id
       AND h.ts = (SELECT max(ts) FROM heartbeats WHERE teammate_id = v.id)
      ORDER BY v.status, v.teammate_name;"
    echo ""
    echo "pane logs: $PANE_LOG_DIR/<lane>.log   (refresh: shctx panes capture; watch: /loop 30s shctx panes status)"
    ;;

  capture)
    lines=200
    while [[ $# -gt 0 ]]; do case "$1" in
      --lines=*) lines="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    have_tmux || { echo "tmux not available — nothing to capture (teammateMode is in-process?)"; exit 0; }
    mkdir -p "$PANE_LOG_DIR"
    n=0
    while IFS='|' read -r name pane; do
      [[ -n "$pane" ]] || continue
      pane_alive "$pane" || continue
      tmux capture-pane -p -t "$pane" -S -"$lines" > "$PANE_LOG_DIR/$(safe_name "$name").log" 2>/dev/null || continue
      n=$((n + 1))
    done < <(sqlite3 "$DB" "SELECT teammate_name, tmux_pane_id FROM teammates WHERE tmux_pane_id IS NOT NULL AND status IN ('booting','active','idle');")
    echo "captured $n live pane(s) → $PANE_LOG_DIR/"
    ;;

  tail)
    lane="${1:-}"; shift || true
    lines=40
    while [[ $# -gt 0 ]]; do case "$1" in
      --lines=*) lines="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    [[ -n "$lane" ]] || { echo "usage: shctx panes tail <lane> [--lines=N]" >&2; exit 2; }
    f="$PANE_LOG_DIR/$(safe_name "$lane").log"
    if [[ -f "$f" ]]; then tail -n "$lines" "$f"; else
      echo "no capture for '$lane' yet — run: shctx panes capture" >&2; exit 1
    fi
    ;;

  prune)
    closed_only=0
    while [[ $# -gt 0 ]]; do case "$1" in
      --closed-only) closed_only=1;;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    have_tmux || { echo "tmux not available — no panes to prune"; exit 0; }
    killed=0
    # Candidates: any teammate row carrying a pane id.
    while IFS='|' read -r name pane status; do
      [[ -n "$pane" ]] || continue
      pane_alive "$pane" || continue          # pane already gone — nothing to do
      orphan=0
      case "$status" in
        crashed|retired) orphan=1 ;;          # closed teammate → its pane is an orphan
        *)
          if [[ "$closed_only" -eq 0 ]]; then
            # worktree-gone heuristic: pane cwd is a .worktrees/ path that no longer exists
            cwd="$(tmux display -p -t "$pane" '#{pane_current_path}' 2>/dev/null || true)"
            case "$cwd" in
              */.worktrees/*) [[ -d "$cwd" ]] || orphan=1 ;;
            esac
          fi
          ;;
      esac
      if [[ "$orphan" -eq 1 ]]; then
        tmux kill-pane -t "$pane" 2>/dev/null && killed=$((killed + 1)) && echo "killed orphan pane $pane ($name, status=$status)"
      fi
    done < <(sqlite3 "$DB" "SELECT teammate_name, tmux_pane_id, status FROM teammates WHERE tmux_pane_id IS NOT NULL;")
    echo "pruned $killed orphan pane(s)"
    ;;

  ""|help|--help|-h) usage;;
  *) echo "unknown subcommand: $sub" >&2; usage; exit 2;;
esac
