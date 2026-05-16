#!/usr/bin/env bash
# shctx discovery — discovery report registry (v5.1.1)
#
# The discovery_capture.sh hook writes per-discovery records to
# <ns>/discoveries/<sprint>/<id>.json. This CLI reads + searches them so
# the conductor can find existing answers before dispatching a new
# discovery (cross-sprint reuse — doctrines/discovery-readonly.md).
#
# Subcommands:
#   list [--sprint=<branch>] [--json|--md]   List discoveries (default: current sprint)
#   show <id> [--md|--json|--report]         Show structured record OR open the report
#   search --question="<paraphrase>" [...]   Find discoveries whose question matches
#   clear --sprint=<branch>                  Purge sprint discoveries (operator confirmed)
#   help

set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

sub="${1:-help}"
shift || true

usage() {
  cat <<'EOF'
shctx discovery — discovery report registry

USAGE
  shctx discovery list [--sprint=<branch>] [--json|--md]
  shctx discovery show <id> [--md|--json|--report]
  shctx discovery search --question="<paraphrase>" [--sprint=<branch>] [--max-age-sprints=<N>]
  shctx discovery clear --sprint=<branch> [--force]

EXAMPLES
  shctx discovery list                              # current sprint, markdown
  shctx discovery show 20260515T141023-a3f9         # structured record
  shctx discovery search --question="canonical types freshness"
  shctx discovery clear --sprint=v5.1.2-dev.0 --force
EOF
}

ns=$(resolve_namespace)
current_sprint_name=$(current_sprint)

discovery_dir_for() {
  echo "$ns/discoveries/$1"
}

cmd_list() {
  local sprint="$current_sprint_name" fmt="md"
  for arg in "$@"; do
    case "$arg" in
      --sprint=*) sprint="${arg#--sprint=}" ;;
      --json)     fmt="json" ;;
      --md)       fmt="md" ;;
    esac
  done

  local dir
  dir=$(discovery_dir_for "$sprint")
  if [[ ! -d "$dir" ]]; then
    echo "[shctx discovery] no discoveries for sprint '$sprint' (dir: $dir)"
    exit 0
  fi

  local files
  files=$(find "$dir" -maxdepth 1 -name "*.json" -type f 2>/dev/null | sort)
  if [[ -z "$files" ]]; then
    echo "[shctx discovery] no discoveries for sprint '$sprint'"
    exit 0
  fi

  if [[ "$fmt" == "json" ]]; then
    echo "["
    local first=1
    while IFS= read -r f; do
      [[ $first -eq 0 ]] && echo ","
      first=0
      cat "$f"
    done <<<"$files"
    echo ""
    echo "]"
  else
    echo "| id | question | confidence | sources | reporter |"
    echo "|---|---|---|---|---|"
    while IFS= read -r f; do
      if command -v jq &>/dev/null; then
        jq -r '"| \(.id) | \(.question[:60]) | \(.confidence) | \(.sources_count) | \(.reporter) |"' "$f"
      else
        python3 -c "
import json
d = json.load(open('$f'))
print('| {} | {} | {} | {} | {} |'.format(
  d.get('id',''), (d.get('question','') or '')[:60],
  d.get('confidence',''), d.get('sources_count',''), d.get('reporter','')))
"
      fi
    done <<<"$files"
  fi
}

cmd_show() {
  local id="" fmt="json"
  for arg in "$@"; do
    case "$arg" in
      --md)     fmt="md" ;;
      --json)   fmt="json" ;;
      --report) fmt="report" ;;
      *)        [[ -z "$id" ]] && id="$arg" ;;
    esac
  done
  [[ -z "$id" ]] && { echo "ERROR: shctx discovery show <id>" >&2; exit 1; }

  # Search across all sprints for the id
  local found
  found=$(find "$ns/discoveries" -maxdepth 2 -name "${id}.json" -type f 2>/dev/null | head -1)
  if [[ -z "$found" ]]; then
    echo "[shctx discovery] id not found: $id" >&2
    exit 1
  fi

  case "$fmt" in
    json) cat "$found" ;;
    md)
      if command -v jq &>/dev/null; then
        jq -r '"# Discovery \(.id)\n\n- Sprint:       \(.sprint)\n- Question:     \(.question)\n- Confidence:   \(.confidence)\n- Sources:      \(.sources_count)\n- Tool calls:   \(.tool_calls)\n- Time used:    \(.time_used)\n- Report:       \(.report_path)\n- Status:       \(.status)\n- Reporter:     \(.reporter)\n- Consumed:     \(.consumed)\n"' "$found"
      else
        cat "$found"
      fi
      ;;
    report)
      local report_path
      if command -v jq &>/dev/null; then
        report_path=$(jq -r '.report_path // empty' "$found")
      else
        report_path=$(python3 -c "import json; print(json.load(open('$found')).get('report_path',''))")
      fi
      if [[ -f "$report_path" ]]; then
        cat "$report_path"
      else
        echo "[shctx discovery] report file not found: $report_path" >&2
        exit 1
      fi
      ;;
  esac
}

cmd_search() {
  local question="" sprint="" max_age=2
  for arg in "$@"; do
    case "$arg" in
      --question=*)         question="${arg#--question=}" ;;
      --sprint=*)           sprint="${arg#--sprint=}" ;;
      --max-age-sprints=*)  max_age="${arg#--max-age-sprints=}" ;;
    esac
  done
  [[ -z "$question" ]] && { echo "ERROR: shctx discovery search --question=\"<text>\"" >&2; exit 1; }

  # Naive substring match across all .json files. For richer matching, use
  # shctx search (FTS5) once we add discoveries to the FTS index — v5.2.0 work.
  local matches=()
  while IFS= read -r f; do
    local q
    if command -v jq &>/dev/null; then
      q=$(jq -r '.question // empty' "$f" 2>/dev/null)
    else
      q=$(python3 -c "import json; print(json.load(open('$f')).get('question',''))" 2>/dev/null)
    fi
    # Case-insensitive substring match
    if [[ "$(echo "$q" | tr '[:upper:]' '[:lower:]')" == *"$(echo "$question" | tr '[:upper:]' '[:lower:]')"* ]]; then
      matches+=("$f")
    fi
  done < <(find "$ns/discoveries" -maxdepth 2 -name "*.json" -type f 2>/dev/null)

  if [[ ${#matches[@]} -eq 0 ]]; then
    echo "[shctx discovery] no matches for: $question"
    exit 0
  fi

  echo "| id | sprint | question | confidence | report |"
  echo "|---|---|---|---|---|"
  for f in "${matches[@]}"; do
    if command -v jq &>/dev/null; then
      jq -r '"| \(.id) | \(.sprint) | \(.question[:60]) | \(.confidence) | \(.report_path) |"' "$f"
    else
      python3 -c "
import json
d = json.load(open('$f'))
print('| {} | {} | {} | {} | {} |'.format(
  d.get('id',''), d.get('sprint',''), (d.get('question','') or '')[:60],
  d.get('confidence',''), d.get('report_path','')))
"
    fi
  done
}

cmd_clear() {
  local sprint="" force=0
  for arg in "$@"; do
    case "$arg" in
      --sprint=*) sprint="${arg#--sprint=}" ;;
      --force)    force=1 ;;
    esac
  done
  [[ -z "$sprint" ]] && { echo "ERROR: shctx discovery clear --sprint=<branch>" >&2; exit 1; }
  local dir
  dir=$(discovery_dir_for "$sprint")
  if [[ ! -d "$dir" ]]; then
    echo "[shctx discovery] no records to clear for sprint '$sprint'"
    exit 0
  fi
  local count
  count=$(find "$dir" -name "*.json" -type f 2>/dev/null | wc -l | tr -d ' ')
  if [[ $force -eq 0 ]]; then
    echo "[shctx discovery] would clear $count records in $dir; pass --force to execute"
    exit 0
  fi
  rm -f "$dir"/*.json
  echo "[shctx discovery] cleared $count records for sprint '$sprint'"
}

case "$sub" in
  help|-h|--help) usage ;;
  list)           cmd_list "$@" ;;
  show)           cmd_show "$@" ;;
  search)         cmd_search "$@" ;;
  clear)          cmd_clear "$@" ;;
  *) echo "ERROR: unknown shctx discovery subcommand: $sub" >&2; usage >&2; exit 1 ;;
esac
