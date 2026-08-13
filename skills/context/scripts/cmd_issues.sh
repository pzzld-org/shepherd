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
# Exit codes: 0=ok, 1=no DB / stale, 2=usage error,
#             3=malformed [ledger] config array (see _cfg_ledger_array_raw)

set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

# Requires bash 4+ for associative arrays. macOS ships bash 3.2 by default.
if (( BASH_VERSINFO[0] < 4 )); then
  echo "ERROR: shctx issues requires bash 4+ (have ${BASH_VERSION:-unknown})." >&2
  echo "  On macOS: brew install bash, then re-run via the brewed bash." >&2
  exit 1
fi

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
  labeled-non-issue     labels contain wontfix/tracking-future/design-question/rfc
                        (override the list via [ledger].non_issue_labels — single-
                        line or multi-line TOML array, both forms supported)
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

# Fallback bucket-labeled-non-issue set, applied only when [ledger].
# non_issue_labels is unset. Matches docs/configuration.md §[ledger]
# `non_issue_labels`'s documented default value VERBATIM
# (["wontfix","tracking-future","design-question","rfc"]) — these two lists
# must be kept in sync by hand; a drift here silently changes classify's
# default bucketing with no doc to catch it (the earlier code default —
# deferred/wontfix/won't fix/invalid/duplicate/question — disagreed with the
# doc it claimed to implement). Newline-delimited (not space-delimited) so a
# future multi-word label survives the same `while IFS= read -r` split used
# for a config-supplied list in _classify_row() below.
_DEFAULT_NON_ISSUE_LABELS=$'wontfix\ntracking-future\ndesign-question\nrfc'

# Read a TOML array value for [section].key from the shepherd config
# precedence chain (shctx_config_files — the same local/harness/project/user
# order cfg_section_get resolves, sourced via _lib.sh), collecting every line
# from the "key = [" line through the line holding the matching "]". Exists
# because cfg_section_get is line-based (`awk` matches only `^key[ \t]*=` on
# a SINGLE line): given the idiomatic multi-line array form
#   non_issue_labels = [
#     "wontfix",
#     ...
#   ]
# cfg_section_get returns just "[" (the rest of the array is on later lines
# it never reads), which _non_issue_labels_from_toml() below would then
# silently treat as an unset/empty override and fall back to the built-in
# default with no warning — the exact "documented override no-ops silently"
# failure class this reader exists to close. Single-line arrays
# (`key = ["a","b"]`) still parse identically to before.
# Echoes the raw bracketed text (including the outer `[`/`]`) on stdout, or
# "" if the key is absent from every config file (the normal, expected
# "not overridden" case — the caller falls back to the default for this).
# Returns 3, after printing a diagnostic to stderr, if a "key = [" line is
# found but no closing "]" is ever reached before EOF (malformed/
# unterminated TOML) or any other read failure occurs — never silently
# treated as "unset". Callers MUST check the exit status: do not swallow it
# by putting this inside `... || true` the way cfg_section_get callers do.
_cfg_ledger_array_raw() {
  local section="$1" key="$2" f v rc
  while IFS= read -r f; do
    [[ -f "$f" ]] || continue
    if v="$(awk -v sect="$section" -v k="$key" '
      /^[ \t]*\[/ {
        h=$0; sub(/^[ \t]*\[/,"",h); sub(/\].*$/,"",h); gsub(/[ \t]/,"",h)
        cur=h; in_val=0; next
      }
      cur==sect && !in_val && $0 ~ ("^[ \t]*" k "[ \t]*=") {
        line=$0; sub(/^[^=]*=[ \t]*/,"",line); sub(/[ \t]+#.*$/,"",line)
        val=line; in_val=1
        if (val ~ /\]/) { print val; found=1; in_val=0; exit }
        next
      }
      in_val {
        ln=$0; sub(/[ \t]+#.*$/,"",ln)
        val = val "\n" ln
        if (ln ~ /\]/) { print val; found=1; in_val=0; exit }
        next
      }
      END { if (!found && in_val) exit 3 }
    ' "$f")"; then
      rc=0
    else
      rc=$?
    fi
    if [[ $rc -ne 0 ]]; then
      if [[ $rc -eq 3 ]]; then
        echo "ERROR: shctx issues: [$section].$key in $f opens a TOML array" \
             "(\"$key = [\") but never closes it (\"]\") before end of file" \
             "— malformed config. Refusing to silently fall back to the" \
             "default $key list; fix the array in $f." >&2
      else
        echo "ERROR: shctx issues: failed to read [$section].$key from $f" \
             "(awk exit $rc)." >&2
      fi
      return "$rc"
    fi
    [[ -n "$v" ]] && { printf '%s' "$v"; return 0; }
  done < <(shctx_config_files)
  printf '%s' ""
  return 0
}

_non_issue_labels_from_toml() {
  # Read [ledger].non_issue_labels from shepherd config so the documented
  # override (docs/configuration.md §[ledger]) actually takes effect —
  # finding NON-ISSUE-LABELS-CONFIG-MISMATCH — for both single-line and
  # multi-line TOML array forms. Uses _cfg_ledger_array_raw() above rather
  # than cfg_section_get directly, because cfg_section_get truncates a
  # multi-line array (see that function's header comment for the failure
  # mode). Echoes a newline-separated label list, or "" when the key is
  # unset so the caller falls back to $_DEFAULT_NON_ISSUE_LABELS. Propagates
  # (does not swallow) a non-zero exit from _cfg_ledger_array_raw — a
  # malformed override must fail the whole `classify` invocation, never
  # silently degrade to the default.
  local raw rc
  if raw="$(_cfg_ledger_array_raw ledger non_issue_labels)"; then
    rc=0
  else
    rc=$?
  fi
  [[ $rc -ne 0 ]] && return "$rc"
  [[ -z "$raw" ]] && return 0
  # Strip the TOML array's [ ] brackets, split on commas, trim surrounding
  # whitespace/quotes per element. `sed`'s `^`/`$` anchor per line (not per
  # stream), so this also correctly unwraps a multi-line raw value: the lone
  # "[" and "]" lines strip to empty, and each element line's own leading/
  # trailing quote+whitespace is trimmed same as the single-line case.
  # Newline- (not space-) joined so a future multi-word label survives the
  # split intact.
  printf '%s' "$raw" | sed -e 's/^\[//' -e 's/\]$//' | tr ',' '\n' \
    | sed -E 's/^[[:space:]]*"?//; s/"?[[:space:]]*$//'
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
  # Args: number title state labels milestone updated_at current_milestone
  #       drift_threshold_epoch non_issue_labels_cfg
  local number="$1" title="$2" state="$3" labels="$4" milestone="${5:-}" \
        updated_at="$6" current_milestone="$7" drift_thresh="$8" non_issue_cfg="${9:-}"

  # labeled-non-issue (checked first — explicit dismissal labels win). Honors
  # the [ledger].non_issue_labels override (non_issue_cfg, resolved once by
  # the caller via _non_issue_labels_from_toml — reading per-row would be
  # wasteful); falls back to the hardcoded default when the key is unset.
  local -a non_issue_labels=()
  local _nil_line _nil_src="${non_issue_cfg:-$_DEFAULT_NON_ISSUE_LABELS}"
  while IFS= read -r _nil_line; do
    [[ -n "$_nil_line" ]] && non_issue_labels+=("$_nil_line")
  done <<< "$_nil_src"
  if _has_label "$labels" "${non_issue_labels[@]}"; then
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

  # Resolve the [ledger].non_issue_labels override ONCE (not per-row inside
  # the classify loop below) — see _non_issue_labels_from_toml(). A malformed
  # override (e.g. an unterminated multi-line array) must abort here rather
  # than silently classifying against the default list.
  local non_issue_labels_cfg rc
  if non_issue_labels_cfg="$(_non_issue_labels_from_toml)"; then
    rc=0
  else
    rc=$?
  fi
  [[ $rc -ne 0 ]] && exit "$rc"

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

  # Classify each row.
  # Bucket storage is bash-3.2-safe (macOS ships bash 3.2 — `declare -A` is a
  # fatal "invalid option" there, which would break `shctx issues` outright).
  # Each bucket maps to two plain vars: _bk_<key> (newline-joined rows) and
  # _bc_<key> (count). `printf -v` assigns by computed name WITHOUT eval, so a
  # title with shell metacharacters can never break or inject.
  _bk_key()   { printf '%s' "$1" | tr '-' '_'; }
  _bk_get()   { local v="_bk_$(_bk_key "$1")"; printf '%s' "${!v:-}"; }
  _bk_count() { local v="_bc_$(_bk_key "$1")"; printf '%s' "${!v:-0}"; }
  _bk_append() {
    local kv="_bk_$(_bk_key "$1")" cv="_bc_$(_bk_key "$1")"
    printf -v "$kv" '%s%s' "${!kv:-}" "$2"
    printf -v "$cv" '%d' "$(( ${!cv:-0} + 1 ))"
  }

  # JSON output accumulator
  local json_rows='[]'

  while IFS='|' read -r number title state labels milestone updated_at; do
    [[ -z "$number" ]] && continue
    local bucket
    bucket=$(_classify_row "$number" "$title" "$state" "$labels" "$milestone" \
              "$updated_at" "$current_milestone" "$drift_thresh" "$non_issue_labels_cfg")

    _bk_append "$bucket" "${number}|${title}|${labels}|${milestone}"$'\n'

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
    local rows_str count
    rows_str="$(_bk_get "$name")"; count="$(_bk_count "$name")"
    [[ -z "$rows_str" ]] && return
    if [[ "$fmt" == "md" ]]; then
      echo ""
      echo "### ${heading} (${count})"
      echo ""
      while IFS='|' read -r num ttl lbl ms; do
        [[ -z "$num" ]] && continue
        local ms_str=""; [[ -n "$ms" ]] && ms_str=" · milestone: $ms"
        local lbl_str; lbl_str=$(printf '%s' "$lbl" | tr -d '[]"' | tr ',' ' ')
        printf '- #%-5s  %s%s\n' "$num" "$ttl" "$ms_str"
        [[ -n "$lbl_str" ]] && printf '         labels: %s\n' "$lbl_str"
      done <<< "$rows_str"
    else
      printf '\n%-26s (%d)\n' "$heading" "${count}"
      printf '%-7s  %-55s  %s\n' "Issue" "Title" "Labels"
      printf '%-7s  %-55s  %s\n' "-------" "-------------------------------------------------------" "------"
      while IFS='|' read -r num ttl lbl _ms; do
        [[ -z "$num" ]] && continue
        local lbl_str; lbl_str=$(printf '%s' "$lbl" | tr -d '[]"' | tr ',' ' ' | xargs)
        printf '#%-6s  %-55s  %s\n' "$num" "${ttl:0:55}" "${lbl_str:0:40}"
      done <<< "$rows_str"
    fi
  }

  if [[ "$fmt" == "md" ]]; then
    echo "## Issue triage — ${sprint} (milestone: ${current_milestone})"
    echo ""
    echo "| Bucket | Count |"
    echo "|---|---|"
    for bkt in blocking-this-sprint labeled-non-issue tracking-future drift-risk unclassified; do
      echo "| ${bkt} | $(_bk_count "$bkt") |"
    done
  else
    printf 'Issue triage — sprint: %s  current_milestone: %s\n' "$sprint" "$current_milestone"
    printf 'drift_days=%d  db=%s\n' "$drift_days" "$db"
    printf '\n%-26s  %5s\n' "Bucket" "Count"
    printf '%-26s  %5s\n' "--------------------------" "-----"
    for bkt in blocking-this-sprint labeled-non-issue tracking-future drift-risk unclassified; do
      printf '%-26s  %5d\n' "$bkt" "$(_bk_count "$bkt")"
    done
  fi

  print_bucket "blocking-this-sprint" "Blocking this sprint"
  print_bucket "drift-risk"           "Drift risk (high-severity, no sprint milestone)"
  print_bucket "unclassified"         "Unclassified (review manually)"
  print_bucket "tracking-future"      "Tracking / future work"
  print_bucket "labeled-non-issue"    "Labeled non-issue (wontfix / tracking-future / etc.)"

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
    sqlite3 -bail -cmd ".mode json" "$db" \
      "SELECT number, title, state, COALESCE(milestone,'') AS milestone, labels, url
       FROM index_issues WHERE $where ORDER BY updated_at DESC LIMIT $limit;" 2>/dev/null \
      || echo "[]"
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
