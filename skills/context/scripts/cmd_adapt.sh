#!/usr/bin/env bash
# shctx adapt <roll|priors|report> [args]   (v6.0.4 #94/#95)
#
# The SQLite-canonical adaptation loop. Replaces the advisory markdown
# sprint-patterns.md registry (see doctrines/adaptation-loop.md).
#
#   roll --sprint=<branch> [--grade= --size= --lanes= --waves=
#                           --loc-add= --loc-del= --wall-min= --api=]
#       Write one sprint_metrics row at CLOSE-FINALIZE (idempotent on
#       UNIQUE(project,sprint_branch)) AND harvest this sprint's HIGH/CRITICAL
#       audit_findings into mem_entries(kind='prior') lessons (deduped by title).
#
#   priors [--metrics|--lessons|--all] [--json|--md]
#       Read priors at sprint open. --metrics feeds dispatch sizing
#       (spawn Check 8, engineer lane guidance); --lessons feeds the
#       [DB-CONTEXT] brief block. Graceful when empty (emits nothing) so the
#       caller falls back to static defaults / omits the section.
#
#   report [--md|--json]
#       Render the materialized sprint-patterns view (the markdown registry's
#       SQLite-canonical replacement).

set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

usage() {
  cat <<'EOF'
shctx adapt <roll|priors|report> [args]   (v6.0.4 #94/#95)

  roll --sprint=<branch> [--grade=G --size=XS|S|M|L|XL --lanes=N --waves=N
                          --loc-add=N --loc-del=N --wall-min=R --api=N]
      Record one sprint_metrics row (idempotent) + harvest HIGH/CRITICAL
      audit_findings into mem_entries(kind='prior'). Run at CLOSE-FINALIZE.

  priors [--metrics|--lessons|--all] [--json|--md]
      --metrics  measured averages: avg_sprint_minutes, avg_api_per_sprint,
                 avg_lane_count (empty ⇒ caller uses static defaults).
      --lessons  recent kind='prior' lessons (cap 10) for brief injection.
      --all      both (default). --json for tooling, --md for briefs.

  report [--md|--json]
      Materialized sprint-patterns table + averages.

Doctrine: skills/shepherd/doctrines/adaptation-loop.md (SQLite-canonical),
          skills/shepherd/doctrines/self-improvement.md (harvest→inject).
EOF
}

sub="${1:-}"; shift || true
case "$sub" in ""|-h|--help) usage; exit 0 ;; esac

pid=$(shctx_project_id)
now=$(shctx_now)

# SQL literal helpers ---------------------------------------------------------
# _txt: quoted text literal, or NULL when empty (mirrors cmd_audit NULLIF intent).
_txt() {
  local v="${1:-}"
  [[ -z "$v" ]] && { printf 'NULL'; return; }
  printf "'%s'" "${v//\'/\'\'}"
}
# _num: numeric literal, or NULL when empty; abort on a malformed value.
_num() {
  local v="${1:-}" label="${2:-value}"
  [[ -z "$v" ]] && { printf 'NULL'; return; }
  [[ "$v" =~ ^[0-9]+(\.[0-9]+)?$ ]] || { echo "ERROR: --$label must be numeric (got '$v')" >&2; exit 1; }
  printf '%s' "$v"
}

# ---------------------------------------------------------------------------
# roll — write metrics row + harvest priors
# ---------------------------------------------------------------------------
_cmd_roll() {
  local sprint="" grade="" size="" lanes="" waves="" loca="" locd="" wall="" api=""
  for arg in "$@"; do
    case "$arg" in
      --sprint=*)   sprint="${arg#--sprint=}" ;;
      --grade=*)    grade="${arg#--grade=}" ;;
      --size=*)     size="${arg#--size=}" ;;
      --lanes=*)    lanes="${arg#--lanes=}" ;;
      --waves=*)    waves="${arg#--waves=}" ;;
      --loc-add=*)  loca="${arg#--loc-add=}" ;;
      --loc-del=*)  locd="${arg#--loc-del=}" ;;
      --wall-min=*) wall="${arg#--wall-min=}" ;;
      --api=*)      api="${arg#--api=}" ;;
      -h|--help)    usage; exit 0 ;;
      *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
    esac
  done
  [[ -n "$sprint" ]] || { echo "ERROR: adapt roll requires --sprint=<branch>" >&2; exit 1; }

  local sprint_esc="${sprint//\'/\'\'}"

  # Findings summary for this sprint (high/critical counts), stored as JSON.
  local hi cr findings
  hi=$(shctx_sql "SELECT count(*) FROM audit_findings WHERE project_id='$pid' AND sprint_branch='$sprint_esc' AND severity='high';")
  cr=$(shctx_sql "SELECT count(*) FROM audit_findings WHERE project_id='$pid' AND sprint_branch='$sprint_esc' AND severity='critical';")
  findings=$(jq -cn --argjson h "${hi:-0}" --argjson c "${cr:-0}" '{high:$h,critical:$c}')

  # 1) metrics row (idempotent on UNIQUE(project_id,sprint_branch))
  shctx_sql "INSERT OR REPLACE INTO sprint_metrics
               (project_id, sprint_branch, grade, sprint_size, lane_count, wave_count,
                loc_add, loc_del, wall_minutes, api_calls, findings_json, created_at)
             VALUES ('$pid', '$sprint_esc', $(_txt "$grade"), $(_txt "$size"),
                     $(_num "$lanes" lanes), $(_num "$waves" waves),
                     $(_num "$loca" loc-add), $(_num "$locd" loc-del),
                     $(_num "$wall" wall-min), $(_num "$api" api),
                     '${findings//\'/\'\'}', $now);"

  # 2) harvest HIGH/CRITICAL findings → mem_entries(kind='prior'), deduped by title
  local ids harvested=0 fid concern gist sev title title_esc dup body body_esc tags tags_esc mid
  ids=$(shctx_sql "SELECT id FROM audit_findings
                   WHERE project_id='$pid' AND sprint_branch='$sprint_esc'
                     AND severity IN ('high','critical') ORDER BY id;")
  for fid in $ids; do
    concern=$(shctx_sql "SELECT concern FROM audit_findings WHERE id=$fid;")
    sev=$(shctx_sql "SELECT severity FROM audit_findings WHERE id=$fid;")
    # collapse newlines so each prior stays one line (briefs + tab-free reads)
    gist=$(shctx_sql "SELECT replace(replace(substr(finding,1,240),char(10),' '),char(13),' ') FROM audit_findings WHERE id=$fid;")
    title="prior: ${concern}"
    title_esc="${title//\'/\'\'}"
    dup=$(shctx_sql "SELECT 1 FROM mem_entries WHERE project_id='$pid' AND kind='prior' AND title='$title_esc' LIMIT 1;")
    [[ -n "$dup" ]] && continue
    body="[$sev] sprint $sprint: ${gist}"
    body_esc="${body//\'/\'\'}"
    tags=$(jq -cn --arg c "$concern" '[$c]')
    tags_esc="${tags//\'/\'\'}"
    mid=$(shctx_uuid7)
    shctx_sql "INSERT INTO mem_entries (id,project_id,kind,title,body,tags,pinned,created_at,updated_at)
               VALUES ('$mid','$pid','prior','$title_esc','$body_esc','$tags_esc',0,$now,$now);"
    harvested=$((harvested+1))
  done

  echo "adapt roll: sprint_metrics row ($sprint) + $harvested prior(s) harvested"
}

# ---------------------------------------------------------------------------
# priors — read metrics averages + lesson priors
# ---------------------------------------------------------------------------
# Emit the metrics averages. No row / n=0 ⇒ emit nothing (graceful fallback).
_emit_metrics() {
  local fmt="$1" row n awm aac alc ald
  row=$(shctx_sql "SELECT n, COALESCE(avg_wall_minutes,0), COALESCE(avg_api_calls,0),
                          COALESCE(avg_lane_count,0), COALESCE(avg_loc_delta,0)
                   FROM v_sprint_metrics_avg WHERE project_id='$pid';")
  [[ -z "$row" ]] && return 0
  IFS='|' read -r n awm aac alc ald <<< "$row"
  [[ -z "$n" || "$n" == "0" ]] && return 0
  case "$fmt" in
    json) jq -cn --argjson n "$n" --argjson m "$awm" --argjson a "$aac" \
                 --argjson l "$alc" --argjson d "$ald" \
            '{n:$n,avg_sprint_minutes:$m,avg_api_per_sprint:$a,avg_lane_count:$l,avg_loc_delta:$d}' ;;
    md)  printf '### Dispatch priors — measured (%s prior sprint(s))\n' "$n"
         printf -- '- avg_sprint_minutes: %s\n- avg_api_per_sprint: %s\n- avg_lane_count: %s\n' "$awm" "$aac" "$alc" ;;
    *)   printf 'n=%s\navg_sprint_minutes=%s\navg_api_per_sprint=%s\navg_lane_count=%s\navg_loc_delta=%s\n' \
                "$n" "$awm" "$aac" "$alc" "$ald" ;;
  esac
}

# Emit recent lesson priors (cap 10). No priors ⇒ emit nothing (omit-if-empty).
_emit_lessons() {
  local fmt="$1" any
  any=$(shctx_sql "SELECT 1 FROM mem_entries WHERE project_id='$pid' AND kind='prior' LIMIT 1;")
  [[ -z "$any" ]] && return 0
  case "$fmt" in
    json) shctx_sql "SELECT json_group_array(json_object('id',id,'title',title,'body',body,'tags',json(tags)))
                     FROM (SELECT id,title,body,tags FROM mem_entries
                           WHERE project_id='$pid' AND kind='prior'
                           ORDER BY created_at DESC, id DESC LIMIT 10);" ;;
    md)  echo "### Priors / lessons carried forward"
         shctx_sql "SELECT '- **' || title || '** _(id: ' || id || ')_ — ' || body
                    FROM mem_entries WHERE project_id='$pid' AND kind='prior'
                    ORDER BY created_at DESC, id DESC LIMIT 10;" ;;
    *)   shctx_sql "SELECT '[' || id || '] ' || title || ' — ' || body
                    FROM mem_entries WHERE project_id='$pid' AND kind='prior'
                    ORDER BY created_at DESC, id DESC LIMIT 10;" ;;
  esac
}

_cmd_priors() {
  local content="all" fmt="text"
  for arg in "$@"; do
    case "$arg" in
      --metrics) content="metrics" ;;
      --lessons) content="lessons" ;;
      --all)     content="all" ;;
      --json)    fmt="json" ;;
      --md)      fmt="md" ;;
      -h|--help) usage; exit 0 ;;
      *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
    esac
  done

  case "$content" in
    metrics) _emit_metrics "$fmt" ;;
    lessons) _emit_lessons "$fmt" ;;
    all)
      if [[ "$fmt" == "json" ]]; then
        local m l
        m=$(_emit_metrics json); [[ -z "$m" ]] && m="null"
        l=$(_emit_lessons json); [[ -z "$l" ]] && l="[]"
        jq -cn --argjson m "$m" --argjson l "$l" '{metrics:$m,lessons:$l}'
      else
        _emit_metrics "$fmt"
        _emit_lessons "$fmt"
      fi ;;
  esac
}

# ---------------------------------------------------------------------------
# report — materialized sprint-patterns view
# ---------------------------------------------------------------------------
_cmd_report() {
  local fmt="md"
  for arg in "$@"; do
    case "$arg" in
      --md)   fmt="md" ;;
      --json) fmt="json" ;;
      -h|--help) usage; exit 0 ;;
      *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
    esac
  done

  if [[ "$fmt" == "json" ]]; then
    shctx_sql "SELECT json_group_array(json_object(
                 'sprint',sprint_branch,'grade',grade,'size',sprint_size,
                 'lanes',lane_count,'waves',wave_count,'loc_add',loc_add,
                 'loc_del',loc_del,'wall_minutes',wall_minutes,'api_calls',api_calls,
                 'findings',json(findings_json),'created_at',created_at))
               FROM (SELECT * FROM sprint_metrics WHERE project_id='$pid'
                     ORDER BY created_at DESC, id DESC LIMIT 20);"
    return 0
  fi

  local count
  count=$(shctx_sql "SELECT count(*) FROM sprint_metrics WHERE project_id='$pid';")
  if [[ "${count:-0}" == "0" ]]; then
    echo "_(no sprint metrics recorded yet — first adaptation cycle lands at this sprint's close)_"
    return 0
  fi

  echo "## Sprint patterns (SQLite-canonical — \`shctx adapt report\`)"
  echo
  echo "| sprint | grade | size | lanes | waves | wall_min | api | findings |"
  echo "|---|---|---|---|---|---|---|---|"
  shctx_sql "SELECT '| ' || sprint_branch
                  || ' | ' || COALESCE(grade,'·')
                  || ' | ' || COALESCE(sprint_size,'·')
                  || ' | ' || COALESCE(lane_count,'·')
                  || ' | ' || COALESCE(wave_count,'·')
                  || ' | ' || COALESCE(CAST(wall_minutes AS INTEGER),'·')
                  || ' | ' || COALESCE(api_calls,'·')
                  || ' | ' || COALESCE(findings_json,'·') || ' |'
             FROM sprint_metrics WHERE project_id='$pid'
             ORDER BY created_at DESC, id DESC LIMIT 20;"
  echo
  _emit_metrics md
}

case "$sub" in
  roll)   _cmd_roll   "$@" ;;
  priors) _cmd_priors "$@" ;;
  report) _cmd_report "$@" ;;
  *) echo "ERROR: unknown subcommand: adapt $sub" >&2; usage >&2; exit 1 ;;
esac
