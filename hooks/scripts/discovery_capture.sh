#!/usr/bin/env bash
# shepherd hook — PostToolUse(Agent|Task) DISCOVERY REPORT capture (v5.1.2)
#
# Mirror of agent_insight_capture.sh for `## DISCOVERY REPORT` returns from
# @discovery agents. Indexes structured records to
# <active-run>/events/discoveries/<id>.json so evidence has one run owner
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
shepherd_skip_without_jq "discovery_capture" || exit 0

tool=$(json_field "$input" '.tool_name')
case "$tool" in Agent|Task) ;; *) exit 0 ;; esac

response=$(json_response "$input")

# Fast-path: no DISCOVERY REPORT marker → exit
printf '%s' "$response" | grep -qE '^[[:space:]]*##[[:space:]]+DISCOVERY REPORT\b' || exit 0

run_dir="$(primary_active_run_dir 2>/dev/null || true)"
if [[ -z "$run_dir" ]]; then
  printf '[shepherd] discovery_capture skipped: no executing run is available for evidence.\n' >&2
  exit 0
fi
run_id="$(basename "$run_dir")"
disc_dir="$run_dir/events/discoveries"
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

captured_at="$(date -u +%s 2>/dev/null || echo 0)"
jq -n \
  --arg id "$disc_id" \
  --arg run "$run_id" \
  --arg question "$question" \
  --arg sources_count "$sources_count" \
  --arg tool_calls "$tool_calls" \
  --arg time_used "$time_used" \
  --arg report_path "$report_path" \
  --arg confidence "$confidence" \
  --arg status "$status" \
  --arg anomalies "$anomalies" \
  --arg reporter "$reporter" \
  --argjson captured_at "$captured_at" \
  '{id:$id, schema_version:1, run:$run, captured_at:$captured_at,
    question:$question, sources_count:$sources_count, tool_calls:$tool_calls,
    time_used:$time_used, report_path:$report_path, confidence:$confidence,
    status:$status, anomalies:$anomalies, reporter:$reporter,
    consumed:false, consumed_by:null}' > "$record_file" 2>/dev/null || exit 0

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
msg+="  Run:           $run_id"$'\n'
msg+="  Inspect with:   shepherd discovery --run=$run_id"

log_event "discovery_capture" "warn" "$tool" "discovery" "$session" \
  "$(emit_json_obj discovery_id "$disc_id" run "$run_id" confidence "$confidence")"
emit_json_obj additionalContext "$msg"
exit 0
