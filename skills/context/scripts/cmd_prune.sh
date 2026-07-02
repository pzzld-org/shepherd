#!/usr/bin/env bash
# shctx prune [--confirm] [--vacuum] [--json] [--logs-days=N] [--dispatch-days=N] [--snapshots-keep=N]
#
# Outcome-safe workdir + registry GC (v6.2.5, first-cut). See doctrines/workdir-prune.md.
#
# --dry-run is the DEFAULT: nothing is removed; the plan is printed and written
# to /tmp/shepherd-prune-<epoch>/plan.csv. --confirm executes the ON-DISK sweeps
# by MOVING targets into that /tmp run dir, which MIRRORS the workdir tree
# (reversible — the snapshot IS the move; `mv <run>/<rel-path> <workdir>/<rel-path>`
# to restore). Preserving the relative path keeps subdir files (e.g. logs/hooks/)
# from colliding on basename and makes the restore mechanical.
#
# Fence (ALL of): the item's sprint/branch != the CURRENT git branch, a terminal
# state, and age >= floor. NEVER touches index_releases, the current sprint's
# focus, sprint_metrics, pinned/doctrine memory, unresolved escalations, pending
# deliverables, active locks (released_at IS NULL), or active loops.
#
# On-disk sweeps EXECUTE now (with --confirm):
#   - dispatch/<sprint>/ dirs where sprint != current branch, older than dispatch_days
#   - logs/events-*.jsonl + logs/hooks/*.jsonl older than logs_days
#   - memory/snapshots/precompact-*.json beyond snapshots_keep (newest-first)
# DB-row sweeps are PREVIEW-ONLY in v6.2.5 (eligible counts printed, nothing
# deleted) — enabled incrementally in a later patch, each DELETE table-guarded
# (this DB may lack migrations 8-18). "start now, finish over time."
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

confirm=0; vacuum=0; json=0
logs_days=""; dispatch_days=""; snapshots_keep=""
for a in "$@"; do
  case "$a" in
    --confirm) confirm=1 ;;
    --vacuum)  vacuum=1 ;;
    --json)    json=1 ;;
    --dry-run) confirm=0 ;;
    --logs-days=*)      logs_days="${a#--logs-days=}" ;;
    --dispatch-days=*)  dispatch_days="${a#--dispatch-days=}" ;;
    --snapshots-keep=*) snapshots_keep="${a#--snapshots-keep=}" ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *) echo "ERROR: unknown arg: $a" >&2; exit 2 ;;
  esac
done

# Retention windows: flag > [prune] config > built-in default.
[[ -n "$logs_days" ]]      || logs_days="$(cfg_section_get prune logs_days)";          [[ -n "$logs_days" ]]      || logs_days=60
[[ -n "$dispatch_days" ]]  || dispatch_days="$(cfg_section_get prune dispatch_days)";   [[ -n "$dispatch_days" ]]  || dispatch_days=30
[[ -n "$snapshots_keep" ]] || snapshots_keep="$(cfg_section_get prune snapshots_keep)"; [[ -n "$snapshots_keep" ]] || snapshots_keep=20

wd="$(shctx_artifacts_root)"
branch="$(current_sprint)"
db="$(shctx_db_path)"
run="/tmp/shepherd-prune-$(shctx_now)"
csv="$run/plan.csv"
mkdir -p "$run"
printf 'category,path_or_table,detail,action\n' > "$csv"

mode="dry-run"; [[ "$confirm" == "1" ]] && mode="confirm"

add_csv() { printf '%s,%s,%s,%s\n' "$1" "$2" "$3" "$4" >> "$csv"; }

# Record + (with --confirm) MOVE a path into $run, PRESERVING its workdir-relative
# path so subdir files (logs/hooks/, memory/snapshots/) keep their structure and
# never collide on basename — restore is `mv $run/<rel> $wd/<rel>`.
sweep_path() {
  local cat="$1" path="$2" detail="$3"
  if [[ "$confirm" == "1" ]]; then
    local rel="${path#"$wd"/}"                      # workdir-relative path
    mkdir -p "$run/$(dirname "$rel")"
    if mv "$path" "$run/$rel" 2>/dev/null; then add_csv "$cat" "$path" "$detail" "moved"
    else add_csv "$cat" "$path" "$detail" "move-failed"; fi
  else
    add_csv "$cat" "$path" "$detail" "would-move"
  fi
}

n_dispatch=0; n_logs=0; n_snaps=0

# dispatch dirs (non-current branch, aged)
disp="$wd/dispatch"
if [[ -d "$disp" ]]; then
  for d in "$disp"/*/; do
    [[ -d "$d" ]] || continue
    name="$(basename "$d")"
    [[ "$name" == "$branch" ]] && continue
    if find "$d" -maxdepth 0 -type d -mtime +"$dispatch_days" 2>/dev/null | grep -q .; then
      sweep_path dispatch "${d%/}" "sprint=$name age>${dispatch_days}d"
      n_dispatch=$((n_dispatch+1))
    fi
  done
fi

# aged logs
logsdir="$wd/logs"
if [[ -d "$logsdir" ]]; then
  while IFS= read -r f; do
    [[ -n "$f" ]] || continue
    sweep_path logs "$f" "age>${logs_days}d"
    n_logs=$((n_logs+1))
  done < <(find "$logsdir" -type f \( -name 'events-*.jsonl' -o -path '*/hooks/*.jsonl' \) -mtime +"$logs_days" 2>/dev/null || true)
fi

# precompact snapshots beyond newest-N
snapdir="$wd/memory/snapshots"
if [[ -d "$snapdir" ]]; then
  i=0
  while IFS= read -r f; do
    [[ -n "$f" ]] || continue
    i=$((i+1))
    [[ $i -le $snapshots_keep ]] && continue
    sweep_path snapshots "$f" "beyond newest-${snapshots_keep}"
    n_snaps=$((n_snaps+1))
  done < <(ls -t "$snapdir"/precompact-*.json 2>/dev/null || true)
fi

# --- DB-row eligibility (PREVIEW ONLY in v6.2.5) ---
db_present=0
db_rows=""
if [[ -f "$db" ]]; then
  db_present=1
  cur_esc="${branch//\'/\'\'}"
  now_s="$(shctx_now)"
  count_pre() {   # <label> <table> <where> <criterion-desc>
    local label="$1" table="$2" where="$3" desc="$4" exists n
    exists="$(shctx_sql "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='$table';" 2>/dev/null || echo 0)"
    if [[ "$exists" != "1" ]]; then
      add_csv "db:$label" "$table" "$desc" "skip:table-absent"
      db_rows="${db_rows}${label}"$'\t'"n/a"$'\t'"$desc (table absent)"$'\n'
      return 0
    fi
    n="$(shctx_sql "SELECT count(*) FROM $table WHERE $where;" 2>/dev/null || echo '?')"
    add_csv "db:$label" "$table" "$desc" "preview:$n"
    db_rows="${db_rows}${label}"$'\t'"$n"$'\t'"$desc"$'\n'
  }
  count_pre logs_events    logs_events        "ts < $now_s - $logs_days*86400"                                                  "observability rows older than ${logs_days}d"
  count_pre crashed_hb     heartbeats         "teammate_id IN (SELECT id FROM teammates WHERE status IN ('crashed','retired'))" "heartbeats for crashed/retired teammates"
  count_pre acked_mail     mailbox            "acked_at IS NOT NULL OR (expires_at IS NOT NULL AND expires_at < strftime('%s','now')*1000)" "mailbox acked or expired"
  count_pre closed_disc    discovery_findings "sprint_branch IS NOT NULL AND sprint_branch != '$cur_esc'"                       "discovery findings from non-current sprints"
  count_pre closed_audit   audit_findings     "sprint_branch IS NOT NULL AND sprint_branch != '$cur_esc'"                       "audit findings from non-current sprints"
  count_pre released_locks locks_history      "released_at IS NOT NULL"                                                         "released locks"
fi

total_disk=$((n_dispatch+n_logs+n_snaps))

if [[ "$json" == "1" ]]; then
  python3 - "$mode" "$wd" "$branch" "$run" "$csv" "$db_present" "$n_dispatch" "$n_logs" "$n_snaps" <<'PY'
import csv as _csv, json, sys
mode, wd, branch, run, csvp, db_present, nd, nl, ns = sys.argv[1:10]
rows = list(_csv.DictReader(open(csvp)))
disk = [r for r in rows if not r["category"].startswith("db:")]
dbp  = [r for r in rows if r["category"].startswith("db:")]
print(json.dumps({
  "mode": mode, "workdir": wd, "branch": branch, "run_dir": run, "csv": csvp,
  "db_present": db_present == "1",
  "on_disk": {"dispatch": int(nd), "logs": int(nl), "snapshots": int(ns),
              "items": [{"category": r["category"], "path": r["path_or_table"],
                         "detail": r["detail"], "action": r["action"]} for r in disk]},
  "db_preview": [{"name": r["category"][3:], "table": r["path_or_table"],
                  "detail": r["detail"], "action": r["action"]} for r in dbp],
}, indent=2))
PY
else
  echo "shctx prune — $mode (workdir=$wd, branch=$branch)"
  echo
  echo "on-disk (executes with --confirm):"
  printf '  dispatch dirs (non-current, >%sd):   %s\n' "$dispatch_days" "$n_dispatch"
  printf '  log files (>%sd):                    %s\n' "$logs_days" "$n_logs"
  printf '  precompact snapshots (beyond %s):     %s\n' "$snapshots_keep" "$n_snaps"
  echo
  if [[ "$db_present" == "1" ]]; then
    echo "registry rows (PREVIEW ONLY in v6.2.5 — nothing deleted):"
    printf '%s' "$db_rows" | while IFS="$(printf '\t')" read -r label n desc; do
      [[ -n "$label" ]] || continue
      printf '  %-16s %6s   %s\n' "$label" "$n" "$desc"
    done
    echo
  else
    echo "registry DB: none at $db (skipped)"
    echo
  fi
  if [[ "$confirm" == "1" ]]; then
    echo "MOVED $total_disk on-disk item(s) into $run (mirrors the workdir tree; mv a path back to restore)."
  else
    echo "DRY-RUN: nothing removed. Re-run with --confirm to move the $total_disk on-disk item(s) to /tmp."
  fi
  echo "plan CSV: $csv"
fi

# Optional space reclaim (needs exclusive DB access).
if [[ "$vacuum" == "1" && "$db_present" == "1" ]]; then
  if [[ "$confirm" == "1" ]]; then
    if shctx_sql "PRAGMA wal_checkpoint(TRUNCATE); VACUUM;" >/dev/null 2>&1; then
      echo "vacuum: WAL checkpointed + VACUUM ok"
    else
      echo "vacuum: skipped (DB busy/locked; retry when no shepherd process holds it)" >&2
    fi
  else
    echo "vacuum: --vacuum requires --confirm (skipped in dry-run)"
  fi
fi

exit 0
