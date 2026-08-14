#!/usr/bin/env bash
# shctx handoff — standard sprint-handoff template + per-sprint document.
#
# Subcommands:
#   create [--branch=<name>] [--out=<path>]
#     Render references/handoff-template.md into
#     ${shctx_artifacts_root}/docs/handoffs/<YYYY-MM-DD>-<branch>-close-handoff.md.
#     Auto-populated sections come from git + the registry; operator-curated
#     sections carry [FILL IN] markers.
#
#   list
#     ls of the handoffs directory, sorted by mtime desc.
#
#   show [<branch|date>]
#     cat the most recent matching handoff (no arg = most recent overall).

set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

usage() {
  cat <<'EOF'
shctx handoff <create|list|show> [args]

  create [--branch=<name>] [--out=<path>]
      Emit a filled-in handoff template at
      ${shctx_artifacts_root}/docs/handoffs/<YYYY-MM-DD>-<branch>-close-handoff.md.

  list
      List existing handoffs (newest first).

  show [<branch|date>]
      Print the most recent handoff matching the substring (no arg = newest).
EOF
}

handoff_root() {
  echo "$(shctx_artifacts_root)/docs/handoffs"
}

# Count rows from a sqlite query, returning 0 on any failure (DB missing, table absent).
count_or_zero() {
  local query="$1"
  shctx_sql "$query" 2>/dev/null || echo 0
}

# Run a registry query script and emit its row count (header line excluded).
query_count() {
  local name="$1"
  bash "$HERE/cmd_query.sh" "$name" --json 2>/dev/null | jq 'length' 2>/dev/null || echo 0
}

cmd_create() {
  local branch="" out=""
  for a in "$@"; do
    case "$a" in
      --branch=*) branch="${a#--branch=}" ;;
      --out=*)    out="${a#--out=}" ;;
      -h|--help)  usage; exit 0 ;;
      *) echo "ERROR: unknown flag: $a" >&2; exit 1 ;;
    esac
  done

  [[ -n "$branch" ]] || branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
  local date; date=$(date +%Y-%m-%d)
  local session_id; session_id=$(shctx_uuid7)

  local hroot; hroot=$(handoff_root)
  mkdir -p "$hroot"
  [[ -n "$out" ]] || out="$hroot/${date}-${branch}-close-handoff.md"

  local tmpl="$(shctx_skill_root)/references/handoff-template.md"
  [[ -f "$tmpl" ]] || { echo "ERROR: template missing: $tmpl" >&2; exit 1; }

  # Auto-populated sections.
  local commits
  if git rev-parse --verify --quiet "$branch" >/dev/null 2>&1; then
    commits=$(git log --oneline -n 10 "$branch" 2>/dev/null || echo "(no commits)")
  else
    commits=$(git log --oneline -n 10 2>/dev/null || echo "(no commits)")
  fi
  [[ -n "$commits" ]] || commits="(no commits)"

  local project_id
  project_id=$(shctx_project_id 2>/dev/null || echo "")
  local artifacts_count=0 mem_count=0 lock_count=0 open_issues=0 drift_risk=0
  if [[ -n "$project_id" ]]; then
    local pid_esc; pid_esc="$(esc "$project_id")"
    artifacts_count=$(count_or_zero "SELECT COUNT(*) FROM artifacts WHERE project_id='$pid_esc';")
    mem_count=$(count_or_zero       "SELECT COUNT(*) FROM mem_entries WHERE project_id='$pid_esc';")
    lock_count=$(count_or_zero      "SELECT COUNT(*) FROM locks_history WHERE project_id='$pid_esc';")
    open_issues=$(query_count open-issues)
    drift_risk=$(query_count drift-risk)
  fi

  # Render via awk (portable substitution; handles multi-line COMMITS via single-pass token replace).
  # We use a Python-free pipeline: write each placeholder one at a time with sed.
  local content; content=$(cat "$tmpl")

  # Use awk for the multi-line COMMITS replacement, sed for the simple scalars.
  local rendered_path="$out"
  # Pass commits via a temp file to handle newlines safely.
  local tmpcommits; tmpcommits=$(mktemp)
  printf '%s\n' "$commits" > "$tmpcommits"

  awk -v branch="$branch" \
      -v date="$date" \
      -v session="$session_id" \
      -v north_star="[FILL IN]" \
      -v carry="[FILL IN]" \
      -v next_focus="[FILL IN]" \
      -v files="[FILL IN]" \
      -v artifacts_count="$artifacts_count" \
      -v mem_count="$mem_count" \
      -v lock_count="$lock_count" \
      -v open_issues="$open_issues" \
      -v drift_risk="$drift_risk" \
      -v commits_file="$tmpcommits" '
    BEGIN {
      while ((getline line < commits_file) > 0) {
        commits = (commits == "" ? line : commits ORS line)
      }
      close(commits_file)
    }
    {
      gsub(/\{\{BRANCH\}\}/,             branch)
      gsub(/\{\{DATE\}\}/,               date)
      gsub(/\{\{SESSION\}\}/,            session)
      gsub(/\{\{NORTH_STAR\}\}/,         north_star)
      gsub(/\{\{CARRY_FORWARDS\}\}/,     carry)
      gsub(/\{\{NEXT_FOCUS\}\}/,         next_focus)
      gsub(/\{\{FILES_OF_INTEREST\}\}/,  files)
      gsub(/\{\{ARTIFACTS_COUNT\}\}/,    artifacts_count)
      gsub(/\{\{MEM_COUNT\}\}/,          mem_count)
      gsub(/\{\{LOCK_COUNT\}\}/,         lock_count)
      gsub(/\{\{OPEN_ISSUES_COUNT\}\}/,  open_issues)
      gsub(/\{\{DRIFT_RISK_COUNT\}\}/,   drift_risk)
      if (index($0, "{{COMMITS}}") > 0) {
        sub(/\{\{COMMITS\}\}/, commits)
      }
      print
    }
  ' "$tmpl" > "$rendered_path"

  rm -f "$tmpcommits"
  echo "$rendered_path"
}

cmd_list() {
  local hroot; hroot=$(handoff_root)
  if [[ ! -d "$hroot" ]]; then
    echo "(no handoffs at $hroot)"
    return 0
  fi
  # macOS-portable: ls -t lists by mtime desc. shopt -s nullglob keeps glob safe when empty.
  shopt -s nullglob
  local files=("$hroot"/*.md)
  if (( ${#files[@]} == 0 )); then
    echo "(no handoffs at $hroot)"
    return 0
  fi
  ls -1t "$hroot"/*.md 2>/dev/null | while IFS= read -r f; do
    echo "$(basename "$f")"
  done
}

cmd_show() {
  local pat="${1:-}"
  local hroot; hroot=$(handoff_root)
  [[ -d "$hroot" ]] || { echo "(no handoffs at $hroot)"; return 0; }
  shopt -s nullglob
  local files=("$hroot"/*.md)
  (( ${#files[@]} > 0 )) || { echo "(no handoffs at $hroot)"; return 0; }
  local match=""
  if [[ -z "$pat" ]]; then
    match=$(ls -1t "$hroot"/*.md 2>/dev/null | head -1 || true)
  else
    # Disable pipefail for the grep step: a no-match should not abort.
    set +o pipefail
    match=$(ls -1t "$hroot"/*.md 2>/dev/null | grep -F "$pat" | head -1 || true)
    set -o pipefail
  fi
  if [[ -z "$match" ]]; then
    echo "(no handoff matching '$pat')"
    return 1
  fi
  cat "$match"
}

sub="${1:-}"; shift || true
case "$sub" in
  create) cmd_create "$@" ;;
  list)   cmd_list "$@" ;;
  show)   cmd_show "$@" ;;
  -h|--help|help|"") usage ;;
  *) echo "ERROR: unknown handoff sub: $sub" >&2; usage >&2; exit 1 ;;
esac
