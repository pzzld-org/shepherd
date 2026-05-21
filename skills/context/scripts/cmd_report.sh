#!/usr/bin/env bash
# shctx report <kind> [filters]
# Materializes markdown views from canonical SQLite rows.
# Kinds: discovery, audit, escalation, close, teammates
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB="${SHCTX_DB:-$(git rev-parse --show-toplevel 2>/dev/null)/.artifacts/root.db}"
[[ -f "$DB" ]] || { echo "ERR: registry DB not found at $DB" >&2; exit 1; }

usage() { cat <<'U'
shctx report discovery --run=<id> [--sprint=<branch>]
shctx report audit --sprint=<branch> [--concern=<c>] [--severity=<s>]
shctx report escalation [--open-only]
shctx report close --sprint=<branch>
shctx report teammates [--team=<name>] [--stale-mins=<n>]
U
}

kind="${1:-}"; shift || true
case "$kind" in
  discovery)
    run=""; sprint=""
    while [[ $# -gt 0 ]]; do case "$1" in
      --run=*)    run="${1#*=}";;
      --sprint=*) sprint="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    [[ -n "$run" ]] || { usage; exit 2; }
    echo "# Discovery report — run \`$run\`"
    [[ -n "$sprint" ]] && echo "Sprint: \`$sprint\`"
    echo
    sqlite3 -separator $'\x1f' "$DB" "SELECT section, title, body, sources FROM discovery_findings WHERE discovery_run='$run'$([ -n "$sprint" ] && echo " AND sprint_branch='$sprint'") ORDER BY section, created_at;" \
      | while IFS=$'\x1f' read -r section title body sources; do
          echo "## ${section:-General} — $title"
          echo
          echo "$body"
          [[ -n "$sources" && "$sources" != "" ]] && echo -e "\n_sources_: \`$sources\`"
          echo
        done
    ;;
  audit)
    sprint=""; concern=""; sev=""
    while [[ $# -gt 0 ]]; do case "$1" in
      --sprint=*)   sprint="${1#*=}";;
      --concern=*)  concern="${1#*=}";;
      --severity=*) sev="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    [[ -n "$sprint" ]] || { usage; exit 2; }
    where="sprint_branch='$sprint'"
    [[ -n "$concern" ]] && where="$where AND concern='$concern'"
    [[ -n "$sev" ]]     && where="$where AND severity='$sev'"
    echo "# Audit report — sprint \`$sprint\`"
    echo
    sqlite3 -separator $'\x1f' "$DB" "SELECT concern, severity, hypothesis, falsification, confidence, finding, gh_issue FROM audit_findings WHERE $where ORDER BY CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 WHEN 'low' THEN 4 ELSE 5 END, created_at;" \
      | while IFS=$'\x1f' read -r concern severity hypothesis falsification confidence finding gh; do
          echo "### [$severity / $concern] $hypothesis"
          [[ -n "$gh" && "$gh" != "" ]] && echo "(filed as #$gh)"
          echo
          echo "**Finding:** $finding"
          [[ -n "$falsification" && "$falsification" != "" ]] && echo -e "\n**Falsification attempt:** $falsification"
          [[ -n "$confidence" && "$confidence" != "" ]] && echo -e "\n**Confidence:** $confidence"
          echo
        done
    ;;
  escalation)
    open=0
    while [[ $# -gt 0 ]]; do case "$1" in
      --open-only) open=1;;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    echo "# Escalations"
    echo
    if [[ "$open" == "1" ]]; then
      sqlite3 -separator $'\x1f' "$DB" "SELECT id, role, phase, question, raised_at FROM v_escalations_open;" \
        | while IFS=$'\x1f' read -r id role phase q raised; do
            echo "- **#$id [$role/${phase:-?}]** $q (raised: $raised)"
          done
    else
      sqlite3 -separator $'\x1f' "$DB" "SELECT id, role, question, raised_at, resolved_at FROM escalations ORDER BY raised_at DESC;" \
        | while IFS=$'\x1f' read -r id role q raised resolved; do
            status="OPEN"; [[ -n "$resolved" && "$resolved" != "" ]] && status="RESOLVED"
            echo "- **#$id [$role/$status]** $q"
          done
    fi
    ;;
  close)
    sprint=""
    while [[ $# -gt 0 ]]; do case "$1" in
      --sprint=*) sprint="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    [[ -n "$sprint" ]] || { usage; exit 2; }
    echo "# Close report — \`$sprint\`"
    echo
    echo "## Audit findings"
    "$HERE/cmd_report.sh" audit --sprint="$sprint"
    echo
    echo "## Open escalations"
    "$HERE/cmd_report.sh" escalation --open-only
    echo
    echo "## Teammate roster"
    "$HERE/cmd_report.sh" teammates
    ;;
  teammates)
    team=""; stale=5
    while [[ $# -gt 0 ]]; do case "$1" in
      --team=*)       team="${1#*=}";;
      --stale-mins=*) stale="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    echo "# Teammates"
    echo
    where="1=1"
    [[ -n "$team" ]] && where="team_name='$team'"
    sqlite3 -separator $'\x1f' "$DB" "SELECT teammate_name, agent_type, status, last_seen_at FROM teammates WHERE $where ORDER BY spawned_at DESC;" \
      | while IFS=$'\x1f' read -r name type status seen; do
          echo "- **$name** ($type) — status: $status — last seen: $seen"
        done
    ;;
  ""|help|--help|-h) usage;;
  *) echo "unknown kind: $kind" >&2; usage; exit 2;;
esac
