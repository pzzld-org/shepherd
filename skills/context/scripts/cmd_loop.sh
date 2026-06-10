#!/usr/bin/env bash
# shctx loop <init|status|record|close|list|focus> [args]   (v6.0.9 #134 / Item A0)
#
# SQLite-backed Loop-Until-Done state. Backs `/shepherd:loop` (v6.0.7+) and the
# Focus Loop runtime (v6.0.9). Loop state is canonical (survives compaction) so
# the focus loop never loses its place across context resets.
#
# See: .artifacts/docs/specs/2026-06-09-v609-focus-loop-and-compaction-resilience.spec.md §4.2
#
#   init --task=<text> --max=<N> [--kind=focus|convergence|watch|generic]
#        [--agent=worker|discovery|orchestrator] [--until=<field>] [--interval=<dur>]
#       Register a new loop. Emits the loop-id (e.g. loop-20260609-001).
#
#   status --id=<loop-id>
#       Show one loop + its iteration history. --json | --md output supported.
#
#   record --id=<loop-id> --iteration=<N> --new_findings=<true|false|0|1>
#          [--summary=<text>]
#       Append one iteration result row. Idempotent on (loop_id, iteration).
#
#   close --id=<loop-id> --status=<converged|cap-reached|aborted>
#       Finalize the loop, writing its terminal status.
#
#   list [--active|--all] [--json|--md]
#       List loops for this project (default: active only).
#
#   focus <upsert|show> --sprint=<branch> [--objective=<text>]
#         [--active-node=<id>] [--ready-set=<csv>]
#         [--obligations=<json>] [--invariants=<json>]
#       Read or write the focus record for a sprint (thin wrapper on the
#       `focus` table added by migration 0013).

set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

usage() {
  cat <<'EOF'
shctx loop <init|status|record|close|list|focus> [args]   (v6.0.9)

  init --task=<text> --max=<N>
       [--kind=focus|convergence|watch|generic]
       [--agent=worker|discovery|orchestrator]
       [--until=<field>]  [--interval=<duration>]
      Register a new loop. Prints the loop-id on stdout.

  status --id=<loop-id> [--json|--md]
      Show loop header + iteration history.

  record --id=<loop-id> --iteration=<N> --new_findings=<true|false|0|1>
         [--summary=<text>]
      Append one iteration record (idempotent).

  close --id=<loop-id> --status=<converged|cap-reached|aborted>
      Finalize a loop.

  list [--active|--all] [--json|--md]
      List loops for this project (default: active).

  focus <upsert|show> --sprint=<branch>
        [--objective=<text>] [--active-node=<id>] [--ready-set=<csv>]
        [--obligations=<json>] [--invariants=<json>]
        [--json|--md]
      Upsert or show the focus record for a sprint.

Doctrine: skills/shepherd/doctrines/workflow-patterns.md §Pattern 6
EOF
}

sub="${1:-}"; shift || true
case "$sub" in ""|-h|--help) usage; exit 0 ;; esac

pid=$(shctx_project_id)
now=$(shctx_now)

# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------
_txt() {
  local v="${1:-}"
  [[ -z "$v" ]] && { printf 'NULL'; return; }
  printf "'%s'" "${v//\'/\'\'}"
}
_num() {
  local v="${1:-}" label="${2:-value}"
  [[ -z "$v" ]] && { printf 'NULL'; return; }
  [[ "$v" =~ ^[0-9]+$ ]] || { echo "ERROR: --$label must be a positive integer (got '$v')" >&2; exit 1; }
  printf '%s' "$v"
}
# Normalise true/false/1/0 → 0|1 for new_findings column.
_bool() {
  local v="${1:-}"
  case "$v" in
    true|1)  printf '1' ;;
    false|0) printf '0' ;;
    *) echo "ERROR: --new_findings must be true|false|1|0 (got '$v')" >&2; exit 1 ;;
  esac
}

# ---------------------------------------------------------------------------
# init — register a new loop, emit the loop-id
# ---------------------------------------------------------------------------
_cmd_init() {
  local task="" max="" kind="generic" agent="" until_field="new_findings" interval=""
  for arg in "$@"; do
    case "$arg" in
      --task=*)      task="${arg#--task=}" ;;
      --max=*)       max="${arg#--max=}" ;;
      --kind=*)      kind="${arg#--kind=}" ;;
      --agent=*)     agent="${arg#--agent=}" ;;
      --until=*)     until_field="${arg#--until=}" ;;
      --interval=*)  interval="${arg#--interval=}" ;;
      -h|--help)     usage; exit 0 ;;
      *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
    esac
  done

  [[ -n "$max" ]] || { echo "ERROR: loop init requires --max=<N>" >&2; exit 1; }
  [[ "$max" =~ ^[0-9]+$ && "$max" -gt 0 ]] \
    || { echo "ERROR: --max must be a positive integer (got '$max')" >&2; exit 1; }

  # Validate kind if supplied.
  case "$kind" in
    focus|convergence|watch|generic) ;;
    *) echo "ERROR: --kind must be focus|convergence|watch|generic (got '$kind')" >&2; exit 1 ;;
  esac

  # Generate a day-scoped sequence id: loop-YYYYMMDD-NNN
  local today seq loop_id
  today=$(date +%Y%m%d)
  seq=$(shctx_sql "SELECT COALESCE(MAX(CAST(substr(id,16) AS INTEGER)),0) + 1
                   FROM loops
                   WHERE project_id='${pid//\'/\'\'}' AND id LIKE 'loop-${today}-%';")
  loop_id=$(printf 'loop-%s-%03d' "$today" "${seq:-1}")

  shctx_sql "INSERT INTO loops
               (id, project_id, kind, task, agent, max_iterations, until_field,
                interval, status, created_at)
             VALUES (
               '$loop_id',
               '${pid//\'/\'\'}',
               $(_txt "$kind"),
               $(_txt "$task"),
               $(_txt "$agent"),
               $(_num "$max" max),
               '${until_field//\'/\'\'}',
               $(_txt "$interval"),
               'active',
               $now
             );"

  printf '%s\n' "$loop_id"
}

# ---------------------------------------------------------------------------
# status — show one loop + iteration history
# ---------------------------------------------------------------------------
_cmd_status() {
  local loop_id="" fmt="text"
  for arg in "$@"; do
    case "$arg" in
      --id=*)    loop_id="${arg#--id=}" ;;
      --json)    fmt="json" ;;
      --md)      fmt="md" ;;
      -h|--help) usage; exit 0 ;;
      *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
    esac
  done
  [[ -n "$loop_id" ]] || { echo "ERROR: loop status requires --id=<loop-id>" >&2; exit 1; }

  local lid_esc="${loop_id//\'/\'\'}"
  local row
  row=$(shctx_sql "SELECT id,kind,task,agent,max_iterations,until_field,interval,status,created_at
                   FROM loops WHERE id='$lid_esc' AND project_id='${pid//\'/\'\'}';")
  [[ -n "$row" ]] || { echo "ERROR: loop not found: $loop_id" >&2; exit 1; }

  if [[ "$fmt" == "json" ]]; then
    shctx_sql "SELECT json_object(
                 'id',l.id,'kind',l.kind,'task',l.task,'agent',l.agent,
                 'max_iterations',l.max_iterations,'until_field',l.until_field,
                 'interval',l.interval,'status',l.status,'created_at',l.created_at,
                 'iterations', (
                   SELECT json_group_array(json_object(
                     'iteration',li.iteration,'new_findings',li.new_findings,
                     'summary',li.summary,'recorded_at',li.recorded_at))
                   FROM loop_iterations li WHERE li.loop_id = l.id
                   ORDER BY li.iteration))
               FROM loops l
               WHERE l.id='$lid_esc' AND l.project_id='${pid//\'/\'\'}'; "
    return 0
  fi

  IFS='|' read -r lid lkind ltask lagent lmax luntil linterval lstatus lcreated <<< "$row"

  if [[ "$fmt" == "md" ]]; then
    printf '## Loop: %s\n' "$lid"
    printf -- '- kind: %s\n- task: %s\n- agent: %s\n- max: %s\n- until: %s\n- interval: %s\n- status: **%s**\n- created_at: %s\n' \
      "${lkind:-·}" "${ltask:-·}" "${lagent:-·}" "$lmax" "$luntil" "${linterval:-none}" "$lstatus" "$lcreated"
    echo
    echo "### Iterations"
    local rows
    rows=$(shctx_sql "SELECT iteration, new_findings, COALESCE(summary,''), recorded_at
                      FROM loop_iterations WHERE loop_id='$lid_esc' ORDER BY iteration;")
    [[ -z "$rows" ]] && echo "_(none yet)_" && return 0
    echo "| # | new_findings | summary | recorded_at |"
    echo "|---|---|---|---|"
    while IFS='|' read -r iter nf summ rec; do
      local nf_label; nf_label=$([ "${nf:-}" = "1" ] && echo "true" || echo "false")
      printf '| %s | %s | %s | %s |\n' "$iter" "$nf_label" "${summ:-·}" "$rec"
    done <<< "$rows"
    return 0
  fi

  # text
  printf 'id=%s kind=%s status=%s max=%s until=%s\n' \
    "$lid" "${lkind:-generic}" "$lstatus" "$lmax" "$luntil"
  printf 'task=%s agent=%s interval=%s created_at=%s\n' \
    "${ltask:-·}" "${lagent:-·}" "${linterval:-none}" "$lcreated"
  local rows
  rows=$(shctx_sql "SELECT iteration, new_findings, COALESCE(summary,''), recorded_at
                    FROM loop_iterations WHERE loop_id='$lid_esc' ORDER BY iteration;")
  if [[ -n "$rows" ]]; then
    echo "iterations:"
    while IFS='|' read -r iter nf summ rec; do
      local nf_label; nf_label=$([ "${nf:-}" = "1" ] && echo "true" || echo "false")
      printf '  [%s] new_findings=%s recorded_at=%s summary=%s\n' "$iter" "$nf_label" "$rec" "${summ:-none}"
    done <<< "$rows"
  else
    echo "iterations: (none yet)"
  fi
}

# ---------------------------------------------------------------------------
# record — append one iteration result (idempotent on loop_id + iteration)
# ---------------------------------------------------------------------------
_cmd_record() {
  local loop_id="" iteration="" new_findings="" summary=""
  for arg in "$@"; do
    case "$arg" in
      --id=*)           loop_id="${arg#--id=}" ;;
      --iteration=*)    iteration="${arg#--iteration=}" ;;
      --new_findings=*) new_findings="${arg#--new_findings=}" ;;
      --summary=*)      summary="${arg#--summary=}" ;;
      -h|--help)        usage; exit 0 ;;
      *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
    esac
  done

  [[ -n "$loop_id" ]]    || { echo "ERROR: loop record requires --id=<loop-id>" >&2; exit 1; }
  [[ -n "$iteration" ]]  || { echo "ERROR: loop record requires --iteration=<N>" >&2; exit 1; }
  [[ -n "$new_findings" ]] || { echo "ERROR: loop record requires --new_findings=<true|false|0|1>" >&2; exit 1; }

  local lid_esc="${loop_id//\'/\'\'}"
  local exists
  exists=$(shctx_sql "SELECT 1 FROM loops WHERE id='$lid_esc' AND project_id='${pid//\'/\'\'}' LIMIT 1;")
  [[ -n "$exists" ]] || { echo "ERROR: loop not found: $loop_id" >&2; exit 1; }

  local nf; nf=$(_bool "$new_findings")
  local iter_n; iter_n=$(_num "$iteration" iteration)

  shctx_sql "INSERT OR REPLACE INTO loop_iterations
               (loop_id, iteration, new_findings, summary, recorded_at)
             VALUES ('$lid_esc', $iter_n, $nf, $(_txt "$summary"), $now);"

  printf 'loop record: %s iteration %s new_findings=%s\n' \
    "$loop_id" "$iteration" "$new_findings"
}

# ---------------------------------------------------------------------------
# close — finalize a loop with terminal status
# ---------------------------------------------------------------------------
_cmd_close() {
  local loop_id="" status=""
  for arg in "$@"; do
    case "$arg" in
      --id=*)     loop_id="${arg#--id=}" ;;
      --status=*) status="${arg#--status=}" ;;
      -h|--help)  usage; exit 0 ;;
      *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
    esac
  done

  [[ -n "$loop_id" ]] || { echo "ERROR: loop close requires --id=<loop-id>" >&2; exit 1; }
  [[ -n "$status" ]]  || { echo "ERROR: loop close requires --status=<converged|cap-reached|aborted>" >&2; exit 1; }
  case "$status" in
    converged|cap-reached|aborted) ;;
    *) echo "ERROR: --status must be converged|cap-reached|aborted (got '$status')" >&2; exit 1 ;;
  esac

  local lid_esc="${loop_id//\'/\'\'}"
  local exists
  exists=$(shctx_sql "SELECT 1 FROM loops WHERE id='$lid_esc' AND project_id='${pid//\'/\'\'}' LIMIT 1;")
  [[ -n "$exists" ]] || { echo "ERROR: loop not found: $loop_id" >&2; exit 1; }

  shctx_sql "UPDATE loops SET status='${status//\'/\'\'}' WHERE id='$lid_esc';"

  # Summary line mirrors the close report's loop summary block.
  local iters
  iters=$(shctx_sql "SELECT COUNT(*) FROM loop_iterations WHERE loop_id='$lid_esc';")
  printf 'loop close: %s status=%s iterations=%s\n' "$loop_id" "$status" "${iters:-0}"
}

# ---------------------------------------------------------------------------
# list — list loops for this project
# ---------------------------------------------------------------------------
_cmd_list() {
  local filter="active" fmt="text"
  for arg in "$@"; do
    case "$arg" in
      --active)  filter="active" ;;
      --all)     filter="all" ;;
      --json)    fmt="json" ;;
      --md)      fmt="md" ;;
      -h|--help) usage; exit 0 ;;
      *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
    esac
  done

  local where="project_id='${pid//\'/\'\'}'"
  [[ "$filter" == "active" ]] && where="$where AND status='active'"

  if [[ "$fmt" == "json" ]]; then
    shctx_sql "SELECT json_group_array(json_object(
                 'id',id,'kind',kind,'task',task,'agent',agent,
                 'max_iterations',max_iterations,'status',status,'created_at',created_at))
               FROM (SELECT * FROM loops WHERE $where ORDER BY created_at DESC, id DESC LIMIT 50);"
    return 0
  fi

  local count
  count=$(shctx_sql "SELECT COUNT(*) FROM loops WHERE $where;")
  if [[ "${count:-0}" == "0" ]]; then
    echo "_(no loops found)_"
    return 0
  fi

  if [[ "$fmt" == "md" ]]; then
    echo "## Loops (${filter})"
    echo
    echo "| id | kind | status | task | agent | max | created_at |"
    echo "|---|---|---|---|---|---|---|"
    shctx_sql "SELECT '| ' || id
                    || ' | ' || COALESCE(kind,'·')
                    || ' | ' || status
                    || ' | ' || COALESCE(substr(task,1,40),'·')
                    || ' | ' || COALESCE(agent,'·')
                    || ' | ' || max_iterations
                    || ' | ' || created_at || ' |'
               FROM loops WHERE $where
               ORDER BY created_at DESC, id DESC LIMIT 50;"
    return 0
  fi

  # text
  shctx_sql "SELECT id || '  ' || status || '  kind=' || COALESCE(kind,'generic')
                  || '  max=' || max_iterations
                  || '  agent=' || COALESCE(agent,'·')
                  || '  task=' || COALESCE(substr(task,1,50),'·')
             FROM loops WHERE $where
             ORDER BY created_at DESC, id DESC LIMIT 50;"
}

# ---------------------------------------------------------------------------
# focus — read / upsert the focus record (thin wrapper on the `focus` table)
# ---------------------------------------------------------------------------
_cmd_focus() {
  local focussub="${1:-show}"; shift || true
  local sprint="" objective="" active_node="" ready_set="" obligations="" invariants="" fmt="text"
  for arg in "$@"; do
    case "$arg" in
      --sprint=*)      sprint="${arg#--sprint=}" ;;
      --objective=*)   objective="${arg#--objective=}" ;;
      --active-node=*) active_node="${arg#--active-node=}" ;;
      --ready-set=*)   ready_set="${arg#--ready-set=}" ;;
      --obligations=*) obligations="${arg#--obligations=}" ;;
      --invariants=*)  invariants="${arg#--invariants=}" ;;
      --json)          fmt="json" ;;
      --md)            fmt="md" ;;
      -h|--help)       usage; exit 0 ;;
      *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
    esac
  done

  case "$focussub" in
    upsert)
      [[ -n "$sprint" ]] || { echo "ERROR: focus upsert requires --sprint=<branch>" >&2; exit 1; }

      # Validate JSON columns if provided.
      if [[ -n "$obligations" ]]; then
        echo "$obligations" | jq -e . >/dev/null 2>&1 \
          || { echo "ERROR: --obligations is not valid JSON" >&2; exit 1; }
      fi
      if [[ -n "$invariants" ]]; then
        echo "$invariants" | jq -e . >/dev/null 2>&1 \
          || { echo "ERROR: --invariants is not valid JSON" >&2; exit 1; }
      fi

      local sp_esc="${sprint//\'/\'\'}"
      local exists
      exists=$(shctx_sql "SELECT 1 FROM focus WHERE sprint='$sp_esc' LIMIT 1;")
      if [[ -n "$exists" ]]; then
        # Patch only supplied columns, keep the rest.
        [[ -n "$objective" ]]   && shctx_sql "UPDATE focus SET objective=$(_txt "$objective") WHERE sprint='$sp_esc';"
        [[ -n "$active_node" ]] && shctx_sql "UPDATE focus SET active_node=$(_txt "$active_node") WHERE sprint='$sp_esc';"
        [[ -n "$ready_set" ]]   && shctx_sql "UPDATE focus SET ready_set=$(_txt "$ready_set") WHERE sprint='$sp_esc';"
        [[ -n "$obligations" ]] && shctx_sql "UPDATE focus SET obligations=$(_txt "$obligations") WHERE sprint='$sp_esc';"
        [[ -n "$invariants" ]]  && shctx_sql "UPDATE focus SET invariants=$(_txt "$invariants") WHERE sprint='$sp_esc';"
        shctx_sql "UPDATE focus SET updated_at=$now WHERE sprint='$sp_esc';"
        echo "focus upsert: refreshed $sprint"
      else
        shctx_sql "INSERT INTO focus (sprint,objective,active_node,ready_set,obligations,invariants,updated_at)
                   VALUES ('$sp_esc',$(_txt "$objective"),$(_txt "$active_node"),
                           $(_txt "$ready_set"),$(_txt "$obligations"),
                           $(_txt "$invariants"),$now);"
        echo "focus upsert: created $sprint"
      fi
      ;;

    show)
      local target="$sprint"
      if [[ -z "$target" ]]; then
        target=$(current_sprint)
      fi
      local t_esc="${target//\'/\'\'}"
      local row
      row=$(shctx_sql "SELECT sprint,objective,active_node,ready_set,obligations,invariants,updated_at
                       FROM focus WHERE sprint='$t_esc';")
      if [[ -z "$row" ]]; then
        echo "_(no focus record for sprint: ${target})_"
        return 0
      fi
      if [[ "$fmt" == "json" ]]; then
        shctx_sql "SELECT json_object('sprint',sprint,'objective',objective,
                     'active_node',active_node,'ready_set',ready_set,
                     'obligations',json(obligations),'invariants',json(invariants),
                     'updated_at',updated_at)
                   FROM focus WHERE sprint='$t_esc';"
        return 0
      fi
      IFS='|' read -r fsprint fobj fnode fready foblig finvar fupdated <<< "$row"
      if [[ "$fmt" == "md" ]]; then
        printf '## Focus record — %s\n' "$fsprint"
        printf -- '- **objective:** %s\n' "${fobj:-·}"
        printf -- '- **active_node:** %s\n' "${fnode:-·}"
        printf -- '- **ready_set:** %s\n' "${fready:-·}"
        printf -- '- **obligations:** %s\n' "${foblig:-·}"
        printf -- '- **invariants:** %s\n' "${finvar:-·}"
        printf -- '- **updated_at:** %s\n' "$fupdated"
      else
        printf 'sprint=%s active_node=%s ready_set=%s updated_at=%s\n' \
          "$fsprint" "${fnode:-·}" "${fready:-·}" "$fupdated"
        printf 'objective=%s\n' "${fobj:-·}"
        printf 'obligations=%s\n' "${foblig:-·}"
        printf 'invariants=%s\n' "${finvar:-·}"
      fi
      ;;

    *) echo "ERROR: unknown focus subcommand: $focussub (use upsert|show)" >&2; exit 1 ;;
  esac
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
case "$sub" in
  init)   _cmd_init   "$@" ;;
  status) _cmd_status "$@" ;;
  record) _cmd_record "$@" ;;
  close)  _cmd_close  "$@" ;;
  list)   _cmd_list   "$@" ;;
  focus)  _cmd_focus  "$@" ;;
  *) echo "ERROR: unknown subcommand: loop $sub" >&2; usage >&2; exit 1 ;;
esac
