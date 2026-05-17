#!/usr/bin/env bash
# shepherd hook — PostToolUse(Agent|Task) DISCOVERY REPORT capture (v5.1.2)
#
# Mirror of agent_insight_capture.sh for `## DISCOVERY REPORT` returns from
# @discovery agents. Indexes structured records to
# <ns>/discoveries/<sprint>/<id>.json so the engineer + conductor can query
# without re-parsing report text.
#
# Input:  PostToolUse JSON { tool_name, tool_response, ... }
# Output: {"additionalContext":"..."} when a discovery is captured;
#         silent exit 0 otherwise.

set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

input=$(cat)
is_shepherd_project || exit 0

tool=$(json_field "$input" '.tool_name')
case "$tool" in Agent|Task) ;; *) exit 0 ;; esac

response=$(json_response "$input")

# Fast-path: no DISCOVERY REPORT marker → exit
printf '%s' "$response" | grep -qE '^[[:space:]]*##[[:space:]]+DISCOVERY REPORT\b' || exit 0

ns=$(resolve_namespace)
sprint=$(current_sprint)
disc_dir="$ns/discoveries/$sprint"
mkdir -p "$disc_dir" 2>/dev/null || exit 0

# Extract structured fields. The DISCOVERY REPORT shape is in agents/discovery.md §"Workflow Step 4".
_extract() {
  printf '%s' "$response" \
    | grep -m1 -E "^[[:space:]]*([-*][[:space:]]+)?${1}[[:space:]]*:" \
    | sed -E "s/^[[:space:]]*([-*][[:space:]]+)?${1}[[:space:]]*:[[:space:]]*//; s/[[:space:]]*$//"
}

question=$(_extract "Question" || true)
sources_count=$(_extract "Sources consulted" || true)
tool_calls=$(_extract "Tool calls used" || true)
time_used=$(_extract "Time used" || true)
report_path=$(_extract "Report path" || true)
confidence=$(_extract "Confidence" || true)
status=$(_extract "Status" || true)
anomalies=$(_extract "Anomalies" || true)
reporter=$(_extract "Reporter" || true)

ts=$(date -u +%Y%m%dT%H%M%S 2>/dev/null || echo unknown)
rand=$(od -An -tx1 -N4 /dev/urandom 2>/dev/null | tr -d ' \n' || echo rnd)
disc_id="${ts}-${rand}"
record_file="$disc_dir/${disc_id}.json"

python3 - "$record_file" "$disc_id" "$sprint" "$question" "$sources_count" \
  "$tool_calls" "$time_used" "$report_path" "$confidence" "$status" \
  "$anomalies" "$reporter" <<'PY' 2>/dev/null || true
import json, sys, time
(out, did, sprint, question, sources, tool_calls, time_used, report_path,
 confidence, status, anomalies, reporter) = sys.argv[1:]
record = {
    "id":             did,
    "schema_version": 1,
    "sprint":         sprint,
    "captured_at":    int(time.time()),
    "question":       question,
    "sources_count":  sources,
    "tool_calls":     tool_calls,
    "time_used":      time_used,
    "report_path":    report_path,
    "confidence":     confidence,
    "status":         status,
    "anomalies":      anomalies,
    "reporter":       reporter,
    "consumed":       False,
    "consumed_by":    None,
}
with open(out, "w") as f:
    json.dump(record, f, indent=2)
PY

session=$(json_field "$input" '.session_id')
repo_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
rel_record="${record_file#$repo_root/}"
rel_report="${report_path#$repo_root/}"

msg="[shepherd] DISCOVERY REPORT captured (v5.1.2)."$'\n'
msg+="  Discovery id:  $disc_id"$'\n'
msg+="  Question:      ${question:-unknown}"$'\n'
msg+="  Confidence:    ${confidence:-unknown}"$'\n'
msg+="  Report:        ${rel_report:-${report_path:-unknown}}"$'\n'
msg+="  Indexed at:    $rel_record"$'\n'
msg+="  Browse with:   shctx discovery list --sprint=$sprint"

log_event "discovery_capture" "warn" "$tool" "discovery" "$session" \
  "$(emit_json_obj discovery_id "$disc_id" sprint "$sprint" confidence "$confidence")"
emit_json_obj additionalContext "$msg"
exit 0
