#!/usr/bin/env bash
# shctx close-lane <lane-id> --sprint=<sprint-branch> [--issues=#a,#b,...] [--status=clean|partial|failed]
#
# v5.0.3 — record a lane closure and auto-resolve carry-forward ledger entries.
# Field origin: shepherd v5.0.1 conductor feedback §2.7. Mid-sprint the
# conductor invokes this after each WAVE-GATE per lane; the auditor reads
# `lane_closures` at close-time to verify carry-forward refresh discipline.
#
# Behaviors:
#   1. Inserts a row in lane_closures (idempotent — UNIQUE on
#      (project_id, sprint_branch, lane_id) with UPDATE on conflict).
#   2. For each --issues=#N item, runs `gh issue view <N> --json state` and:
#        a. If state=closed: marks resolved in the closure row's resolved_issues,
#           emits a markdown patch the conductor can apply to the carry-forward
#           ledger ("- [#N] ✅ Resolved (lane <lane-id>)").
#        b. If state=open: leaves it in the carry-forward as Pending; warns.
#   3. Logs an event to logs_events (level=audit) with the closure summary.
#
# The conductor still applies the carry-forward markdown patch — this command
# emits it; the conductor commits it. Symmetric with how dedup-check works:
# the registry produces the verdict, the conductor enforces it.

set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

lane_id=""
sprint_branch=""
issues_csv=""
status="clean"
acceptance_log=""

usage() {
  cat <<'EOF'
shctx close-lane <lane-id> --sprint=<branch> [--issues=#a,#b] [--status=clean|partial|failed] [--acceptance=<path>]

Record a mid-sprint lane closure. Auto-resolves carry-forward ledger items
whose underlying GH issues have transitioned to closed.

  <lane-id>           short identifier (e.g. "lane-3", "wave-2-lane-b")
  --sprint=<branch>   sprint branch this lane closed under
  --issues=#a,#b      GH issue numbers the lane was supposed to resolve
  --status=...        clean (gates green) | partial (gates green w/ scope cuts) | failed
  --acceptance=<path> optional path to the lane's [ACCEPTANCE] markdown to record

Output: markdown patch for the carry-forward ledger (apply manually or via diff).
EOF
}

while (( $# > 0 )); do
  case "$1" in
    -h|--help)        usage; exit 0 ;;
    --sprint=*)       sprint_branch="${1#*=}" ;;
    --issues=*)       issues_csv="${1#*=}" ;;
    --status=*)       status="${1#*=}" ;;
    --acceptance=*)   acceptance_log=$(cat "${1#*=}" 2>/dev/null || true) ;;
    --*)              echo "ERROR: unknown flag: $1" >&2; usage >&2; exit 1 ;;
    *)                if [[ -z "$lane_id" ]]; then lane_id="$1"; else echo "ERROR: extra arg: $1" >&2; exit 1; fi ;;
  esac
  shift
done

[[ -n "$lane_id" ]] || { echo "ERROR: lane-id required" >&2; usage >&2; exit 1; }
[[ -n "$sprint_branch" ]] || { echo "ERROR: --sprint= required" >&2; usage >&2; exit 1; }
case "$status" in clean|partial|failed) ;; *) echo "ERROR: --status must be clean|partial|failed" >&2; exit 1 ;; esac

# Verify migration 0003 applied.
if ! shctx_sql "SELECT 1 FROM sqlite_master WHERE type='table' AND name='lane_closures';" | grep -q 1; then
  echo "ERROR: lane_closures table missing. Run \`shctx migrate\` to apply 0003_canonical_types_filter.sql." >&2
  exit 2
fi

project_id=$(shctx_project_id)
now=$(shctx_now)
uid=$(shctx_uuid7)

# Resolve issues — query gh CLI (if available) and bucket into closed/open.
resolved=()
still_open=()
if [[ -n "$issues_csv" ]] && command -v gh >/dev/null 2>&1; then
  IFS=',' read -ra issues_arr <<< "$issues_csv"
  for raw in "${issues_arr[@]}"; do
    n="${raw#\#}"; n="${n// /}"
    [[ -n "$n" ]] || continue
    state=$(shctx_gh_retry issue view "$n" --json state -q .state 2>/dev/null || echo "?")
    case "$state" in
      CLOSED|closed) resolved+=("$n") ;;
      OPEN|open)     still_open+=("$n") ;;
      *)             still_open+=("$n") ;;  # unknown ⇒ treat as still open
    esac
  done
elif [[ -n "$issues_csv" ]]; then
  echo "shctx close-lane: gh CLI not found; skipping issue-state probe (treating all listed as still-open)" >&2
  IFS=',' read -ra issues_arr <<< "$issues_csv"
  for raw in "${issues_arr[@]}"; do
    n="${raw#\#}"; n="${n// /}"
    [[ -n "$n" ]] && still_open+=("$n")
  done
fi

# Build resolved JSON array.
if (( ${#resolved[@]} == 0 )); then
  resolved_json='[]'
else
  resolved_json=$(printf '%s\n' "${resolved[@]}" | jq -R . | jq -sc .)
fi

acc_esc=$(esc "$acceptance_log")
sprint_esc=$(esc "$sprint_branch")
lane_esc=$(esc "$lane_id")
# $resolved_json is built from --issues= CLI-supplied issue numbers (via
# `jq -R`, which JSON-escapes but does not SQL-escape) — esc() it too before
# it lands in the VALUES literal below.
resolved_json_esc=$(esc "$resolved_json")

shctx_sql "INSERT INTO lane_closures
  (id, project_id, sprint_branch, lane_id, closed_at, resolved_issues, acceptance_log, status, notes)
  VALUES ('$uid','$(esc "$project_id")','$sprint_esc','$lane_esc',$now,'$resolved_json_esc',
          ${acc_esc:+'$acc_esc'}${acc_esc:-NULL},'$status',NULL)
  ON CONFLICT(project_id, sprint_branch, lane_id) DO UPDATE SET
    closed_at=excluded.closed_at,
    resolved_issues=excluded.resolved_issues,
    acceptance_log=excluded.acceptance_log,
    status=excluded.status;"

# Audit-log the closure.
payload=$(jq -nc \
  --arg lane "$lane_id" \
  --arg sprint "$sprint_branch" \
  --arg status "$status" \
  --argjson resolved "$resolved_json" \
  '{lane:$lane, sprint:$sprint, status:$status, resolved:$resolved}')
payload_esc=$(esc "$payload")
shctx_sql "INSERT INTO logs_events (project_id, ts, level, source, event, payload, sprint_branch)
           VALUES ('$(esc "$project_id")', $now, 'audit', 'close-lane', 'lane-closed', '$payload_esc', '$sprint_esc');"

# Emit the carry-forward markdown patch.
echo "# carry-forward patch — lane \`$lane_id\` (sprint \`$sprint_branch\`)"
echo
echo "_Generated $(date -u +%Y-%m-%dT%H:%M:%SZ) by shctx close-lane._"
echo
if (( ${#resolved[@]} > 0 )); then
  echo "## Resolved (move from Pending → Resolved)"
  for n in "${resolved[@]}"; do
    echo "- [#$n] ✅ Resolved by lane \`$lane_id\` (status: $status)"
  done
  echo
fi
if (( ${#still_open[@]} > 0 )); then
  echo "## Still open (keep in Pending)"
  for n in "${still_open[@]}"; do
    echo "- [#$n] ⏳ Lane \`$lane_id\` closed but issue still open — verify manually"
  done
fi
if (( ${#resolved[@]} == 0 && ${#still_open[@]} == 0 )); then
  echo "_No issues recorded for this lane closure._"
fi

echo
echo "shctx close-lane: recorded $lane_id under $sprint_branch (resolved=${#resolved[@]}, still-open=${#still_open[@]}, status=$status)" >&2
