#!/usr/bin/env bash
# shctx adapt <roll|priors|report|recommend> [args]   (v6.0.4 #94/#95; v6.0.8)
#
# The SQLite-canonical adaptation loop. Replaces the advisory markdown
# sprint-patterns.md registry (see skills/adaptation/SKILL.md).
#
#   roll --sprint=<branch> [--grade= --size= --lanes= --waves=
#                           --loc-add= --loc-del= --wall-min= --api=]
#       Write one sprint_metrics row at CLOSE-FINALIZE (idempotent on
#       UNIQUE(project,sprint_branch)) AND harvest this sprint's HIGH/CRITICAL
#       audit_findings into mem_entries(kind='prior') lessons (deduped by title).
#       v6.0.8: every recurrence touches the prior's updated_at (last-seen);
#       unpinned priors not re-seen within SHCTX_ADAPT_DECAY_SPRINTS sprint
#       closes (default 6) are pruned so the store self-cleans (bounded arc).
#
#   reflect --sprint=<branch> --note="<lesson>" [--pin]
#       Store a one-line close reflection (Reflexion pattern) as a kind='prior'
#       lesson tagged ["reflection"]. Latent note in, deterministic storage out.
#       Idempotent per sprint; surfaces in close report + next [DB-CONTEXT].
#
#   priors [--metrics|--lessons|--all] [--json|--md]
#       Read priors at sprint open. --metrics feeds dispatch sizing
#       (spawn Check 8, engineer lane guidance); --lessons feeds the
#       [DB-CONTEXT] brief block. Graceful when empty (emits nothing) so the
#       caller falls back to static defaults / omits the section.
#
#   report [--md|--json] [--trends]
#       Render the materialized sprint-patterns view (the markdown registry's
#       SQLite-canonical replacement). --trends mechanizes adaptation-loop.md
#       §VI: deterministic TREND ALERT (recurring concern / grade trending
#       down / cost rising) over the last 3 sprints; emits nothing when
#       history is insufficient (graceful).
#
#   recommend [--md|--json]
#       Turn measured averages + recurring priors into a concrete dispatch
#       RECOMMENDATION (suggested lane count, t-shirt band, watch-concerns).
#       Empty store ⇒ "no history yet, use defaults" (graceful).

set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

usage() {
  cat <<'EOF'
shctx adapt <roll|priors|report|recommend> [args]   (v6.0.4 #94/#95; v6.0.8)

  roll --sprint=<branch> [--grade=G --size=XS|S|M|L|XL --lanes=N --waves=N
                          --loc-add=N --loc-del=N --wall-min=R --api=N]
      Record one sprint_metrics row (idempotent) + harvest HIGH/CRITICAL
      audit_findings into mem_entries(kind='prior'). Run at CLOSE-FINALIZE.
      Touches recurring priors' last-seen + prunes stale unpinned priors
      (SHCTX_ADAPT_DECAY_SPRINTS, default 6; pinned priors are never pruned).
      Pass --wall-min (sprint elapsed minutes) + --api: they power the
      cost-rising trend (§VI(c)) and Check 8 sizing — both stay dormant on NULL.

  reflect --sprint=<branch> --note="<lesson>" [--pin]
      Store the conductor's one-line close reflection ("what I'd do differently
      next sprint") as a kind='prior' lesson tagged ["reflection"]. The note is
      latent synthesis; storage/dedup/decay are deterministic. Idempotent per
      sprint. Surfaces in the close report, the dash, session_open, and the next
      sprint's [DB-CONTEXT] brief. Run once per close, after roll.

  priors [--metrics|--lessons|--all] [--json|--md]
      --metrics  measured averages: avg_sprint_minutes, avg_api_per_sprint,
                 avg_lane_count (empty ⇒ caller uses static defaults).
      --lessons  recent kind='prior' lessons (cap 10) for brief injection.
      --all      both (default). --json for tooling, --md for briefs.

  report [--md|--json] [--trends] [--compile-telemetry]
      Materialized sprint-patterns table + averages. --trends emits a
      deterministic TREND ALERT over the last 3 sprints (recurring HIGH/
      CRITICAL concern, grade trending down, cost rising sharply); nothing
      when history is insufficient. Mechanizes adaptation-loop.md §VI.
      --compile-telemetry emits the "## Compile-down telemetry" close-
      report subsection (per-segment faithfulness, peak concurrency, seam
      outcomes, degradation events) from the compile_runs table (migration
      0014). Emits nothing gracefully when no runs recorded. Mirrors the
      "## Cache telemetry" precedent (migration 0006, v_cache_usage).

  recommend [--md|--json]
      Dispatch RECOMMENDATION from measured averages + recurring priors:
      suggested lane count, t-shirt size band, watch-concerns. Empty store
      ⇒ "no history yet, use defaults".

Doctrine: skills/adaptation/SKILL.md (SQLite-canonical),
          skills/adaptation/SKILL.md (harvest→inject).
EOF
}

sub="${1:-}"; shift || true
case "$sub" in ""|-h|--help) usage; exit 0 ;; esac

pid=$(shctx_project_id)
now=$(shctx_now)

# SQL literal helpers ---------------------------------------------------------
# esc: double every single quote so a value round-trips through SQL text-
# literal interpolation intact (SQL escaping, not shell escaping). The bash
# parameter-expansion form `${v//\'/\'\'}` does NOT do this on bash 3.2 — it
# leaves a literal backslash in the output and the original quote unescaped,
# so any free-text value (a note, a reason, a title) containing an apostrophe
# produces malformed SQL (#285). Mirrors the proven-correct idiom already in
# cmd_teammate.sh's esc() (sed "s/'/''/g"); duplicated here rather than
# sourced because it belongs in the shared _lib.sh, which is a sibling's
# scope this wave — see #285 follow-up to consolidate.
esc() { printf '%s' "$1" | sed "s/'/''/g"; }
# _txt: quoted text literal, or NULL when empty (mirrors cmd_audit NULLIF intent).
_txt() {
  local v="${1:-}"
  [[ -z "$v" ]] && { printf 'NULL'; return; }
  printf "'%s'" "$(esc "$v")"
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

  local sprint_esc; sprint_esc="$(esc "$sprint")"

  # Findings summary for this sprint (high/critical counts), stored as JSON.
  local hi cr findings findings_esc
  hi=$(shctx_sql "SELECT count(*) FROM audit_findings WHERE project_id='$pid' AND sprint_branch='$sprint_esc' AND severity='high';")
  cr=$(shctx_sql "SELECT count(*) FROM audit_findings WHERE project_id='$pid' AND sprint_branch='$sprint_esc' AND severity='critical';")
  findings=$(jq -cn --argjson h "${hi:-0}" --argjson c "${cr:-0}" '{high:$h,critical:$c}')
  findings_esc="$(esc "$findings")"

  # 1) metrics row (idempotent on UNIQUE(project_id,sprint_branch))
  shctx_sql "INSERT OR REPLACE INTO sprint_metrics
               (project_id, sprint_branch, grade, sprint_size, lane_count, wave_count,
                loc_add, loc_del, wall_minutes, api_calls, findings_json, created_at)
             VALUES ('$pid', '$sprint_esc', $(_txt "$grade"), $(_txt "$size"),
                     $(_num "$lanes" lanes), $(_num "$waves" waves),
                     $(_num "$loca" loc-add), $(_num "$locd" loc-del),
                     $(_num "$wall" wall-min), $(_num "$api" api),
                     '$findings_esc', $now);"

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
    title_esc="$(esc "$title")"
    dup=$(shctx_sql "SELECT 1 FROM mem_entries WHERE project_id='$pid' AND kind='prior' AND title='$title_esc' LIMIT 1;")
    # Recurrence: the concern already has a prior — refresh its last-seen
    # (updated_at) so decay never prunes a still-recurring lesson, then skip
    # the re-insert (dedup-by-title keeps the store bounded).
    if [[ -n "$dup" ]]; then
      shctx_sql "UPDATE mem_entries SET updated_at=$now
                 WHERE project_id='$pid' AND kind='prior' AND title='$title_esc';"
      continue
    fi
    body="[$sev] sprint $sprint: ${gist}"
    body_esc="$(esc "$body")"
    tags=$(jq -cn --arg c "$concern" '[$c]')
    tags_esc="$(esc "$tags")"
    mid=$(shctx_uuid7)
    shctx_sql "INSERT INTO mem_entries (id,project_id,kind,title,body,tags,pinned,created_at,updated_at)
               VALUES ('$mid','$pid','prior','$title_esc','$body_esc','$tags_esc',0,$now,$now);"
    harvested=$((harvested+1))
  done

  local pruned
  pruned=$(_decay_priors)

  echo "adapt roll: sprint_metrics row ($sprint) + $harvested prior(s) harvested + $pruned stale prior(s) pruned"
}

# Prune unpinned 'prior' rows whose last-seen (updated_at) has fallen outside
# the decay window, so the store stays bounded over long version arcs even as
# concerns rotate (skills/adaptation/SKILL.md "Bounded & graceful").
#
# Window = SHCTX_ADAPT_DECAY_SPRINTS sprint closes (default 6). The cutoff is
# gap-based on the close cadence, not wall-clock: a prior is stale once MORE
# than `window` recorded sprint closes carry a created_at strictly newer than
# the prior's updated_at — i.e. it went un-refreshed across `window` closes.
# This is collision-proof against same-second rolls (a prior refreshed THIS
# close has updated_at = now, so zero closes are newer ⇒ never pruned). Pinned
# priors are NEVER pruned. Graceful when <2 closes are recorded (no cadence to
# measure) — emits 0 and prunes nothing. Echoes the prune count.
_decay_priors() {
  local window="${SHCTX_ADAPT_DECAY_SPRINTS:-6}"
  [[ "$window" =~ ^[0-9]+$ ]] || window=6
  # Need ≥2 closes before a decay cadence is meaningful; otherwise no cutoff.
  local nsprints
  nsprints=$(shctx_sql "SELECT count(*) FROM sprint_metrics WHERE project_id='$pid';")
  [[ "${nsprints:-0}" -ge 2 ]] || { printf '0'; return 0; }
  # Count closes strictly newer than each prior's last-seen; prune when that
  # count exceeds the window. Single correlated DELETE keeps it atomic.
  local n
  n=$(shctx_sql "SELECT count(*) FROM mem_entries m
                 WHERE m.project_id='$pid' AND m.kind='prior' AND m.pinned=0
                   AND (SELECT count(*) FROM sprint_metrics s
                        WHERE s.project_id='$pid' AND s.created_at > m.updated_at) > $window;")
  shctx_sql "DELETE FROM mem_entries
             WHERE project_id='$pid' AND kind='prior' AND pinned=0
               AND (SELECT count(*) FROM sprint_metrics s
                    WHERE s.project_id='$pid' AND s.created_at > mem_entries.updated_at) > $window;"
  printf '%s' "${n:-0}"
}

# ---------------------------------------------------------------------------
# reflect — store the conductor's one-line close reflection (Reflexion pattern)
# ---------------------------------------------------------------------------
# The whole sprint is the trajectory; the NOTE is the conductor's latent
# synthesis ("what I'd do differently next sprint") over grade + metrics + top
# finding — judgment the model owns. Storage, dedup, and decay are deterministic
# here (the split this very loop teaches). Stored as mem_entries(kind='prior')
# tagged ["reflection"] so it rides the existing inject + surface paths:
# `adapt priors --lessons` injects it into the next [DB-CONTEXT] brief, the dash
# shows it as the latest lesson, and session_open surfaces it. Idempotent per
# sprint (title-keyed): re-running a close updates the reflection in place rather
# than duplicating. Decays like any unpinned prior unless --pin.
_cmd_reflect() {
  local sprint="" note="" pin=0
  for arg in "$@"; do
    case "$arg" in
      --sprint=*) sprint="${arg#--sprint=}" ;;
      --note=*)   note="${arg#--note=}" ;;
      --pin)      pin=1 ;;
      -h|--help)  usage; exit 0 ;;
      *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
    esac
  done
  [[ -n "$sprint" ]] || { echo "ERROR: adapt reflect requires --sprint=<branch>" >&2; exit 1; }
  [[ -n "$note" ]]   || { echo "ERROR: adapt reflect requires --note=<lesson>" >&2; exit 1; }

  local title="prior: reflection ($sprint)"
  local title_esc; title_esc="$(esc "$title")"
  local note1; note1=$(printf '%s' "$note" | tr '\n\r' '  ')
  local body="[reflection] sprint $sprint: $note1"
  local body_esc; body_esc="$(esc "$body")"
  local tags tags_esc; tags=$(jq -cn '["reflection"]'); tags_esc="$(esc "$tags")"

  local dup; dup=$(shctx_sql "SELECT id FROM mem_entries
                              WHERE project_id='$pid' AND kind='prior' AND title='$title_esc' LIMIT 1;")
  if [[ -n "$dup" ]]; then
    # Preserve an existing pin: the normal close re-runs reflect WITHOUT --pin, so
    # a plain `pinned=$pin` would silently unpin a previously pinned reflection
    # and make it decay-eligible. MAX keeps a pin sticky; unpin via `shctx mem unpin`.
    shctx_sql "UPDATE mem_entries SET body='$body_esc', pinned=MAX(pinned,$pin), updated_at=$now WHERE id='$dup';"
    echo "adapt reflect: updated reflection for $sprint"
  else
    local mid; mid=$(shctx_uuid7)
    shctx_sql "INSERT INTO mem_entries (id,project_id,kind,title,body,tags,pinned,created_at,updated_at)
               VALUES ('$mid','$pid','prior','$title_esc','$body_esc','$tags_esc',$pin,$now,$now);"
    echo "adapt reflect: stored reflection for $sprint (id $mid)"
  fi
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
  local fmt="md" trends=0 compile_tel=0
  for arg in "$@"; do
    case "$arg" in
      --md)                  fmt="md" ;;
      --json)                fmt="json" ;;
      --trends)              trends=1 ;;
      --compile-telemetry)   compile_tel=1 ;;
      -h|--help) usage; exit 0 ;;
      *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
    esac
  done

  (( trends ))      && { _emit_trends "$fmt"; return 0; }
  (( compile_tel )) && { _emit_compile_telemetry "$fmt"; return 0; }

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

# ---------------------------------------------------------------------------
# report --trends — deterministic TREND ALERT (mechanizes adaptation-loop.md §VI)
# ---------------------------------------------------------------------------
# Three signals computed over the last 3 recorded sprint closes:
#   (a) a HIGH/CRITICAL audit concern recurring across ALL of the last 3 sprints
#   (b) sprint grade trending strictly worse (best→worst, e.g. A→B→C)
#   (c) cost rising sharply: newest wall_minutes OR api_calls ≥ 1.5× the oldest
# Insufficient history (<3 closes) ⇒ emit nothing (graceful). All signals are
# pure SQL window functions over sprint_metrics — no heuristics, no clock.
_emit_trends() {
  local fmt="$1"
  # The last 3 closes, newest first. Need exactly 3 to assess a 3-point trend.
  local n3
  n3=$(shctx_sql "SELECT count(*) FROM (SELECT 1 FROM sprint_metrics
                  WHERE project_id='$pid' ORDER BY created_at DESC, id DESC LIMIT 3);")
  [[ "${n3:-0}" -ge 3 ]] || return 0

  # The 3 most-recent sprint branches (newest → oldest), as a CTE we can reuse.
  local last3="WITH last3 AS (
                 SELECT sprint_branch, grade, wall_minutes, api_calls, created_at, id,
                        ROW_NUMBER() OVER (ORDER BY created_at DESC, id DESC) AS rn
                 FROM sprint_metrics WHERE project_id='$pid'
                 ORDER BY created_at DESC, id DESC LIMIT 3)"

  # (a) concern present as HIGH/CRITICAL in every one of the last-3 sprints.
  local concern
  concern=$(shctx_sql "$last3
                       SELECT af.concern FROM audit_findings af
                       WHERE af.project_id='$pid' AND af.severity IN ('high','critical')
                         AND af.sprint_branch IN (SELECT sprint_branch FROM last3)
                       GROUP BY af.concern
                       HAVING COUNT(DISTINCT af.sprint_branch) = 3
                       ORDER BY af.concern LIMIT 1;")

  # (b) grade trending strictly worse from oldest→newest of the last 3. Map the
  # letter grade to a rank (A=0 … F=5); strictly increasing rank == worse.
  local grade_down
  grade_down=$(shctx_sql "$last3,
                  g AS (SELECT rn,
                          CASE substr(UPPER(grade),1,1)
                            WHEN 'A' THEN 0 WHEN 'B' THEN 1 WHEN 'C' THEN 2
                            WHEN 'D' THEN 3 WHEN 'E' THEN 4 WHEN 'F' THEN 5 END AS gr
                        FROM last3)
                  SELECT CASE WHEN
                    (SELECT gr FROM g WHERE rn=1) > (SELECT gr FROM g WHERE rn=2)
                    AND (SELECT gr FROM g WHERE rn=2) > (SELECT gr FROM g WHERE rn=3)
                    AND (SELECT count(*) FROM g WHERE gr IS NOT NULL) = 3
                  THEN 1 ELSE 0 END;")

  # (c) cost rising sharply: newest (rn=1) ≥ 1.5× oldest (rn=3) on wall or api.
  local cost_up
  cost_up=$(shctx_sql "$last3
                  SELECT CASE WHEN
                    ((SELECT wall_minutes FROM last3 WHERE rn=1) >=
                       1.5 * (SELECT wall_minutes FROM last3 WHERE rn=3)
                     AND (SELECT wall_minutes FROM last3 WHERE rn=3) > 0)
                    OR
                    ((SELECT api_calls FROM last3 WHERE rn=1) >=
                       1.5 * (SELECT api_calls FROM last3 WHERE rn=3)
                     AND (SELECT api_calls FROM last3 WHERE rn=3) > 0)
                  THEN 1 ELSE 0 END;")

  # Nothing fired ⇒ emit nothing (graceful — no noise on a healthy streak).
  [[ -z "$concern" && "${grade_down:-0}" != "1" && "${cost_up:-0}" != "1" ]] && return 0

  if [[ "$fmt" == "json" ]]; then
    jq -cn \
      --arg c "${concern:-}" \
      --argjson rc "$([[ -n "$concern" ]] && echo true || echo false)" \
      --argjson gd "$([[ "${grade_down:-0}" == "1" ]] && echo true || echo false)" \
      --argjson cu "$([[ "${cost_up:-0}" == "1" ]] && echo true || echo false)" \
      '{trend_alert:true, recurring_concern:$rc, concern:$c,
        grade_trending_down:$gd, cost_rising:$cu}'
    return 0
  fi

  echo "### TREND ALERT — last 3 sprints (\`shctx adapt report --trends\`)"
  echo
  [[ -n "$concern" ]] && \
    echo "- **Recurring concern:** \`$concern\` raised HIGH/CRITICAL in all of the last 3 sprints — give it a dedicated lane / acceptance criterion."
  [[ "${grade_down:-0}" == "1" ]] && \
    echo "- **Grade trending DOWN** across the last 3 sprints — scope may be outrunning capacity; size the next sprint smaller."
  [[ "${cost_up:-0}" == "1" ]] && \
    echo "- **Cost rising sharply** (newest ≥ 1.5× oldest wall/api over 3 sprints) — review lane fan-out and wave count."
  # Explicit success — never let the last optional `&&` line above set the
  # function's exit status (a fired alert must not exit non-zero under `set -e`).
  return 0
}

# ---------------------------------------------------------------------------
# _emit_compile_telemetry — "## Compile-down telemetry" close-report subsection
# (v6.0.9, #87; mirrors the "## Cache telemetry" precedent from migration 0006)
# ---------------------------------------------------------------------------
# Reads the compile_runs table (migration 0014) and emits a per-segment rollup
# for the close report: segment count/sizes, peak concurrency vs ceiling, §IV
# faithfulness pass/fail per dimension, seam-handoff outcomes, and degradation
# events with cause + recovery status.
#
# Graceful when no compile_runs rows exist (migration absent OR no compile-down
# runs recorded yet) — emits nothing, so callers omit the subsection cleanly.
# parse_error rows are excluded (honest measurements only, mirroring v_cache_usage
# from migration 0006).
#
# Called at CLOSE-FINALIZE as:
#   shctx adapt report --compile-telemetry [--md|--json]
_emit_compile_telemetry() {
  local fmt="$1"

  # Graceful: if compile_runs table doesn't exist yet (migration not applied),
  # emit nothing instead of crashing.
  local tbl_exists
  tbl_exists=$(shctx_sql "SELECT count(*) FROM sqlite_master
                           WHERE type='table' AND name='compile_runs';")
  [[ "${tbl_exists:-0}" == "1" ]] || return 0

  # Check for any data for this sprint.
  local sprint_branch sprint_esc
  sprint_branch=$(current_sprint)
  sprint_esc="$(esc "$sprint_branch")"

  local any
  any=$(shctx_sql "SELECT 1 FROM compile_runs
                   WHERE project_id='$pid' AND sprint='$sprint_esc'
                     AND parse_error IS NULL
                   LIMIT 1;")
  [[ -n "$any" ]] || return 0

  if [[ "$fmt" == "json" ]]; then
    shctx_sql "SELECT json_group_array(json_object(
                 'segment',               segment,
                 'runs',                  runs,
                 'node_count',            node_count,
                 'max_agents',            max_agents,
                 'avg_peak_concurrency',  ROUND(avg_peak_concurrency,1),
                 'concurrency_ceiling',   concurrency_ceiling,
                 'faithfulness_pass_rate',ROUND(faithfulness_pass_rate,2),
                 'soundness_failures',    soundness_failures,
                 'completeness_failures', completeness_failures,
                 'determinism_failures',  determinism_failures,
                 'seam_exports_present',  seam_exports_present,
                 'seam_exports_consumed', seam_exports_consumed,
                 'degradation_events',    degradation_events,
                 'recovered_events',      recovered_events,
                 'degradation_causes',    degradation_causes
               ))
               FROM v_compile_runs_sprint
               WHERE project_id='$pid' AND sprint='$sprint_esc'
               ORDER BY segment;"
    return 0
  fi

  # Markdown subsection (mirrors "## Cache telemetry" style from migration 0006).
  echo "## Compile-down telemetry (\`shctx adapt report --compile-telemetry\`)"
  echo
  echo "| segment | runs | nodes | agents | peak_conc/ceil | §IV ok | degrade | recovered | seam |"
  echo "|---|---|---|---|---|---|---|---|---|"
  shctx_sql "SELECT
               '| ' || segment
            || ' | ' || runs
            || ' | ' || COALESCE(node_count,'·')
            || ' | ' || COALESCE(max_agents,'·')
            || ' | ' || COALESCE(CAST(ROUND(avg_peak_concurrency) AS INTEGER),'·')
                      || '/' || concurrency_ceiling
            || ' | ' || CASE
                           WHEN faithfulness_pass_rate IS NULL THEN '·'
                           WHEN faithfulness_pass_rate = 1.0   THEN '✓'
                           ELSE 'FAIL(' ||
                             CASE WHEN soundness_failures    > 0 THEN 'S' ELSE '' END ||
                             CASE WHEN completeness_failures > 0 THEN 'C' ELSE '' END ||
                             CASE WHEN determinism_failures  > 0 THEN 'D' ELSE '' END ||
                           ')'
                         END
            || ' | ' || COALESCE(degradation_events,'0')
            || ' | ' || COALESCE(recovered_events,'·')
            || ' | ' || CASE
                           WHEN seam_exports_present IS NULL THEN '·'
                           WHEN seam_exports_consumed = seam_exports_present
                            AND seam_exports_present > 0 THEN 'ok'
                           ELSE COALESCE(CAST(seam_exports_consumed AS TEXT),'·')
                                || '/' || COALESCE(CAST(seam_exports_present AS TEXT),'·')
                         END
            || ' |'
             FROM v_compile_runs_sprint
             WHERE project_id='$pid' AND sprint='$sprint_esc'
             ORDER BY segment;"
  echo

  # Degradation detail block — only emitted when events were recorded.
  local deg_count
  deg_count=$(shctx_sql "SELECT COALESCE(SUM(degradation_events),0)
                          FROM v_compile_runs_sprint
                          WHERE project_id='$pid' AND sprint='$sprint_esc';")
  if [[ "${deg_count:-0}" -gt 0 ]]; then
    echo "**Degradation events** (direct-dispatch fallback activated):"
    shctx_sql "SELECT '- **' || segment || '**: '
                   || COALESCE(degradation_causes,'(cause unrecorded)')
                   || ' — ' || COALESCE(recovered_events,0)
                   || '/' || degradation_events || ' recovered'
               FROM v_compile_runs_sprint
               WHERE project_id='$pid' AND sprint='$sprint_esc'
                 AND degradation_events > 0
               ORDER BY segment;"
    echo
  fi
  # Explicit success — the trailing conditional above must not leave a non-zero
  # exit status under `set -e` (mirrors _emit_trends / _emit_recommend pattern).
  return 0
}

# ---------------------------------------------------------------------------
# recommend — concrete dispatch recommendation from measured averages + priors
# ---------------------------------------------------------------------------
# Turns sprint_metrics averages + recurring priors into a suggested lane count,
# a t-shirt size band, and watch-concerns. Empty store ⇒ "no history yet, use
# defaults" (graceful — caller omits the section, same contract as priors).
_emit_recommend() {
  local fmt="$1"
  local row n awm aac alc
  row=$(shctx_sql "SELECT n, COALESCE(avg_wall_minutes,0), COALESCE(avg_api_calls,0),
                          COALESCE(avg_lane_count,0)
                   FROM v_sprint_metrics_avg WHERE project_id='$pid';")
  if [[ -z "$row" ]]; then
    [[ "$fmt" == "json" ]] && jq -cn '{history:false,note:"no history yet, use defaults"}' \
      || echo "_(no history yet, use defaults)_"
    return 0
  fi
  IFS='|' read -r n awm aac alc <<< "$row"
  if [[ -z "$n" || "$n" == "0" ]]; then
    [[ "$fmt" == "json" ]] && jq -cn '{history:false,note:"no history yet, use defaults"}' \
      || echo "_(no history yet, use defaults)_"
    return 0
  fi

  # Suggested lanes: round the measured average to the nearest whole lane, floor 1.
  local lanes
  lanes=$(shctx_sql "SELECT MAX(1, CAST(ROUND($alc) AS INTEGER));")
  # T-shirt band from measured avg wall minutes (mirrors scope-scale defaults).
  local band
  band=$(shctx_sql "SELECT CASE
                      WHEN $awm < 30  THEN 'XS'
                      WHEN $awm < 60  THEN 'S'
                      WHEN $awm < 120 THEN 'M'
                      WHEN $awm < 240 THEN 'L'
                      ELSE 'XL' END;")
  # Watch-concerns: the recurring prior concerns (tags), most-recent first.
  local concerns
  concerns=$(shctx_sql "SELECT group_concat(c, ', ') FROM (
                          SELECT DISTINCT json_extract(tags,'\$[0]') AS c
                          FROM mem_entries
                          WHERE project_id='$pid' AND kind='prior'
                            AND json_extract(tags,'\$[0]') IS NOT NULL
                          ORDER BY updated_at DESC, id DESC LIMIT 5);")

  if [[ "$fmt" == "json" ]]; then
    jq -cn --argjson h true --argjson n "$n" \
       --argjson l "$lanes" --arg b "$band" --arg w "${concerns:-}" \
       '{history:$h, n:$n, suggested_lanes:$l, size_band:$b, watch_concerns:$w}'
    return 0
  fi

  printf '### Dispatch recommendation — measured (%s prior sprint(s))\n' "$n"
  printf -- '- suggested lanes: %s _(measured avg_lane_count %.1f)_\n' "$lanes" "$alc"
  printf -- '- t-shirt band: %s _(measured avg %s min/sprint)_\n' "$band" "$(printf '%.0f' "$awm")"
  [[ -n "$concerns" ]] && printf -- '- watch-concerns: %s\n' "$concerns"
  # Explicit success — a healthy recommendation with no watch-concerns must not
  # inherit the trailing `[[ ]] &&` non-zero status under `set -e`.
  return 0
}

_cmd_recommend() {
  local fmt="md"
  for arg in "$@"; do
    case "$arg" in
      --md)   fmt="md" ;;
      --json) fmt="json" ;;
      -h|--help) usage; exit 0 ;;
      *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
    esac
  done
  _emit_recommend "$fmt"
}

case "$sub" in
  roll)      _cmd_roll      "$@" ;;
  reflect)   _cmd_reflect   "$@" ;;
  priors)    _cmd_priors    "$@" ;;
  report)    _cmd_report    "$@" ;;
  recommend) _cmd_recommend "$@" ;;
  *) echo "ERROR: unknown subcommand: adapt $sub" >&2; usage >&2; exit 1 ;;
esac
