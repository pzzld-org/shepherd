#!/usr/bin/env bash
# shctx issues <classify|list> [args]
#
#   classify [--sprint=<branch>] [--json|--md] [--unclassified-only]
#       Rule-based bucket classification against the index_issues cache.
#       Buckets: blocking-this-sprint | labeled-non-issue | tracking-future |
#                drift-risk | unclassified
#       Skips LLM inference — deterministic from labels + milestone metadata.
#
#   list [--state=open|closed|all] [--limit=N] [--json|--md]
#       Plain issue listing from cache, no classification.
#
# Exit codes: 0=ok, 1=no DB / stale, 2=usage error

set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

sub="${1:-}"; shift || true

usage() {
  cat <<'EOF'
shctx issues <classify|list> [args]

  classify [--sprint=BRANCH] [--md] [--json] [--unclassified-only]
           [--drift-days=N]
      Bucket open issues using deterministic label/milestone rules.
      --sprint     sprint branch to resolve current milestone (reads shepherd.toml)
      --drift-days days since last update to qualify as drift-risk (default: 30)
      --unclassified-only  print only the unclassified bucket (for LLM review)

  list [--state=open|closed|all] [--limit=N] [--md] [--json]
      List issues from cache.

Buckets (classify):
  blocking-this-sprint  milestone == sprint OR labels contain blocking/critical
  labeled-non-issue     labels contain deferred/wontfix/invalid/duplicate/question
  tracking-future       labels contain tracking/epic/enhancement, no sprint milestone
  drift-risk            labels contain critical/high/bug + no sprint milestone +
                        updated within --drift-days days
  unclassified          everything else — review with LLM judgment
EOF
}

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
_sprint_from_toml() {
  # Extract current sprint branch from shepherd.toml [branching].sprint_branch_pattern
  # This is a best-effort parse; full TOML parse is not available here.
  local root; root="$(shctx_repo_root)"
  local toml="$root/.claude/shepherd.toml"
  [[ -f "$toml" ]] || { echo ""; return; }
  # Try to find sprint_branch_pattern and sprint_number values
  local pattern; pattern=$(grep -E '^\s*sprint_branch_pattern\s*=' "$toml" \
    | head -1 | sed 's/.*=\s*"\(.*\)".*/\1/' || true)
  echo "${pattern:-}"
}

_current_milestone_from_branch() {
  # Derive expected milestone from sprint branch name.
  # Convention: v{X}.{Y}.{Z}-dev.{N} → milestone "v{X}.{Y}.{Z}" or the full branch name.
  local branch="$1"
  # Strip -dev.N suffix to get the patch version as candidate milestone
  echo "$branch" | sed 's/-dev\.[0-9]*$//'
}

_has_label() {
  # Returns 0 (true) if the JSON label array contains any of the given labels (case-insensitive)
  # Usage: _has_label "$labels_json" "blocking" "critical"
  local labels="$1"; shift
  local lc_labels; lc_labels=$(printf '%s' "$labels" | tr '[:upper:]' '[:lower:]')
  for lbl in "$@"; do
    if printf '%s' "$lc_labels" | grep -qF "\"$lbl\""; then
      return 0
    fi
  done
  return 1
}

_classify_row() {
  # Classify a single issue row into a bucket.
  # Args: number title state labels milestone updated_at current_milestone drift_threshold_epoch
  local number="$1" title="$2" state="$3" labels="$4" milestone="${5:-}" \
        updated_at="$6" current_milestone="$7" drift_thresh="$8"

  # labeled-non-issue (checked first — explicit dismissal labels win)
  if _has_label "$labels" "deferred" "wontfix" "invalid" "duplicate" "question" "won't fix" "wontfix"; then
    echo "labeled-non-issue"
    return
  fi

  # blocking-this-sprint: milestone matches OR explicit blocking label
  if [[ -n "$milestone" && "$milestone" == "$current_milestone" ]]; then
    echo "blocking-this-sprint"
    return
  fi
  if _has_label "$labels" "blocking" "blocker" "critical" "must-fix" "p0"; then
    echo "blocking-this-sprint"
    return
  fi

  # tracking-future: tracking/epic/enhancement labels, no current-sprint milestone
  if _has_label "$labels" "tracking" "epic" "enhancement" "feature" "roadmap"; then
    echo "tracking-future"
    return
  fi

  # drift-risk: high-severity label + no sprint milestone + recently active
  if _has_label "$labels" "critical" "high" "bug" "regression" "security"; then
    if [[ -z "$milestone" || "$milestone" != "$current_milestone" ]]; then
      if [[ "$updated_at" -ge "$drift_thresh" ]]; then
        echo "drift-risk"
        return
      fi
    fi
  fi

  echo "unclassified"
}

# ---------------------------------------------------------------------------
# classify subcommand
# ---------------------------------------------------------------------------
cmd_classify() {
  local sprint="" fmt="text" unclassified_only=0 drift_days=30

  for arg in "$@"; do
    case "$arg" in
      --sprint=*)           sprint="${arg#--sprint=}" ;;
      --drift-days=*)       drift_days="${arg#--drift-days=}" ;;
      --md)                 fmt="md" ;;
      --json)               fmt="json" ;;
      --unclassified-only)  unclassified_only=1 ;;
      -h|--help)            usage; exit 0 ;;
      *) echo "ERROR: unknown arg: $arg" >&2; exit 2 ;;
    esac
  done

  command -v sqlite3 >/dev/null || { echo "ERROR: sqlite3 required" >&2; exit 1; }
  local db; db="$(shctx_db_path)"
  [[ -f "$db" ]] || { echo "ERROR: no root.db — run 'shctx init && shctx refresh'" >&2; exit 1; }

  # Resolve current milestone
  [[ -z "$sprint" ]] && sprint=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
  local current_milestone; current_milestone=$(_current_milestone_from_branch "$sprint")

  # Drift threshold: epoch N days ago
  local now; now=$(shctx_now)
  local drift_thresh=$(( now - drift_days * 86400 ))

  local project_id; project_id=$(shctx_project_id)

  # Fetch open issues from cache
  local rows
  rows=$(shctx_sql "SELECT number, title, state, labels, COALESCE(milestone,''), updated_at
    FROM index_issues
    WHERE project_id='$project_id' AND state='open'
    ORDER BY updated_at DESC;" 2>/dev/null || true)

  if [[ -z "$rows" ]]; then
    echo "No open issues in cache. Run 'shctx refresh --scope=github' to populate." >&2
    exit 0
  fi

  # Classify each row
  declare -A buckets
  buckets[blocking-this-sprint]=""
  buckets[labeled-non-issue]=""
  buckets[tracking-future]=""
  buckets[drift-risk]=""
  buckets[unclassified]=""

  declare -A bucket_counts
  bucket_counts[blocking-this-sprint]=0
  bucket_counts[labeled-non-issue]=0
  bucket_counts[tracking-future]=0
  bucket_counts[drift-risk]=0
  bucket_counts[unclassified]=0

  # JSON output accumulator
  local json_rows='[]'

  while IFS='|' read -r number title state labels milestone updated_at; do
    [[ -z "$number" ]] && continue
    local bucket
    bucket=$(_classify_row "$number" "$title" "$state" "$labels" "$milestone" \
              "$updated_at" "$current_milestone" "$drift_thresh")

    buckets[$bucket]+="${number}|${title}|${labels}|${milestone}"$'\n'
    bucket_counts[$bucket]=$(( bucket_counts[$bucket] + 1 ))

    if [[ "$fmt" == "json" ]]; then
      local entry
      entry=$(printf '{"number":%d,"title":%s,"bucket":"%s","labels":%s,"milestone":%s}' \
        "$number" \
        "$(printf '%s' "$title" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))' 2>/dev/null || echo "\"$title\"")" \
        "$bucket" \
        "$labels" \
        "$([ -n "$milestone" ] && echo "\"$milestone\"" || echo 'null')")
      json_rows=$(printf '%s' "$json_rows" | python3 -c \
        "import json,sys; arr=json.load(sys.stdin); arr.append(json.loads(sys.argv[1])); print(json.dumps(arr))" \
        "$entry" 2>/dev/null || echo "$json_rows")
    fi
  done <<< "$rows"

  # --- Output ---
  if [[ "$fmt" == "json" ]]; then
    printf '%s\n' "$json_rows"
    return
  fi

  local print_bucket
  print_bucket() {
    local name="$1" heading="$2"
    [[ "$unclassified_only" -eq 1 && "$name" != "unclassified" ]] && return
    [[ -z "${buckets[$name]}" ]] && return
    if [[ "$fmt" == "md" ]]; then
      echo ""
      echo "### ${heading} (${bucket_counts[$name]})"
      echo ""
      while IFS='|' read -r num ttl lbl ms; do
        [[ -z "$num" ]] && continue
        local ms_str=""; [[ -n "$ms" ]] && ms_str=" · milestone: $ms"
        local lbl_str; lbl_str=$(printf '%s' "$lbl" | tr -d '[]"' | tr ',' ' ')
        printf '- #%-5s  %s%s\n' "$num" "$ttl" "$ms_str"
        [[ -n "$lbl_str" ]] && printf '         labels: %s\n' "$lbl_str"
      done <<< "${buckets[$name]}"
    else
      printf '\n%-26s (%d)\n' "$heading" "${bucket_counts[$name]}"
      printf '%-7s  %-55s  %s\n' "Issue" "Title" "Labels"
      printf '%-7s  %-55s  %s\n' "-------" "-------------------------------------------------------" "------"
      while IFS='|' read -r num ttl lbl _ms; do
        [[ -z "$num" ]] && continue
        local lbl_str; lbl_str=$(printf '%s' "$lbl" | tr -d '[]"' | tr ',' ' ' | xargs)
        printf '#%-6s  %-55s  %s\n' "$num" "${ttl:0:55}" "${lbl_str:0:40}"
      done <<< "${buckets[$name]}"
    fi
  }

  if [[ "$fmt" == "md" ]]; then
    echo "## Issue triage — ${sprint} (milestone: ${current_milestone})"
    echo ""
    echo "| Bucket | Count |"
    echo "|---|---|"
    for bkt in blocking-this-sprint labeled-non-issue tracking-future drift-risk unclassified; do
      echo "| ${bkt} | ${bucket_counts[$bkt]} |"
    done
  else
    printf 'Issue triage — sprint: %s  current_milestone: %s\n' "$sprint" "$current_milestone"
    printf 'drift_days=%d  db=%s\n' "$drift_days" "$db"
    printf '\n%-26s  %5s\n' "Bucket" "Count"
    printf '%-26s  %5s\n' "--------------------------" "-----"
    for bkt in blocking-this-sprint labeled-non-issue tracking-future drift-risk unclassified; do
      printf '%-26s  %5d\n' "$bkt" "${bucket_counts[$bkt]}"
    done
  fi

  print_bucket "blocking-this-sprint" "Blocking this sprint"
  print_bucket "drift-risk"           "Drift risk (high-severity, no sprint milestone)"
  print_bucket "unclassified"         "Unclassified (review manually)"
  print_bucket "tracking-future"      "Tracking / future work"
  print_bucket "labeled-non-issue"    "Labeled non-issue (deferred / wontfix / etc.)"

  if [[ "$unclassified_only" -eq 0 ]]; then
    echo ""
    echo "Tip: use --unclassified-only to show only the bucket requiring LLM review."
  fi
}

# ---------------------------------------------------------------------------
# list subcommand
# ---------------------------------------------------------------------------
cmd_list() {
  local state="open" limit=100 fmt="text"

  for arg in "$@"; do
    case "$arg" in
      --state=*) state="${arg#--state=}" ;;
      --limit=*) limit="${arg#--limit=}" ;;
      --md)      fmt="md" ;;
      --json)    fmt="json" ;;
      -h|--help) usage; exit 0 ;;
      *) echo "ERROR: unknown arg: $arg" >&2; exit 2 ;;
    esac
  done

  command -v sqlite3 >/dev/null || { echo "ERROR: sqlite3 required" >&2; exit 1; }
  local db; db="$(shctx_db_path)"
  [[ -f "$db" ]] || { echo "ERROR: no root.db" >&2; exit 1; }

  local project_id; project_id=$(shctx_project_id)
  local where="project_id='$project_id'"
  [[ "$state" != "all" ]] && where+=" AND state='$state'"

  local rows
  rows=$(shctx_sql "SELECT number, title, state, COALESCE(milestone,'—'), labels, url
    FROM index_issues WHERE $where ORDER BY updated_at DESC LIMIT $limit;")

  if [[ "$fmt" == "json" ]]; then
    shctx_sql ".mode json
SELECT number, title, state, COALESCE(milestone,'') AS milestone, labels, url
FROM index_issues WHERE $where ORDER BY updated_at DESC LIMIT $limit;"
    return
  fi

  if [[ "$fmt" == "md" ]]; then
    echo "| # | Title | State | Milestone | Labels |"
    echo "|---|---|---|---|---|"
    while IFS='|' read -r num ttl st ms lbl url; do
      [[ -z "$num" ]] && continue
      local lbl_str; lbl_str=$(printf '%s' "$lbl" | tr -d '[]"' | tr ',' ', ' | xargs)
      printf '| [#%s](%s) | %s | %s | %s | %s |\n' "$num" "$url" "$ttl" "$st" "$ms" "$lbl_str"
    done <<< "$rows"
  else
    printf '#%-6s  %-50s  %-8s  %-15s\n' "Issue" "Title" "State" "Milestone"
    printf '%-7s  %-50s  %-8s  %-15s\n'  "-------" "--------------------------------------------------" "--------" "---------------"
    while IFS='|' read -r num ttl st ms lbl _url; do
      [[ -z "$num" ]] && continue
      printf '#%-6s  %-50s  %-8s  %-15s\n' "$num" "${ttl:0:50}" "$st" "${ms:0:15}"
    done <<< "$rows"
  fi
}

# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------
case "$sub" in
  classify) cmd_classify "$@" ;;
  list)     cmd_list "$@" ;;
  ""|-h|--help) usage; exit 0 ;;
  *) echo "ERROR: unknown subcommand: $sub" >&2; usage >&2; exit 2 ;;
esac
