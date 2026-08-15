#!/usr/bin/env bash
# shepherd hook — PostToolUse(Agent|Task): capture optional cross-lane insights.
#
# This is telemetry, never enforcement. Source-tree adapters use jq as their
# only JSON runtime; when jq is absent the hook emits a diagnostic and skips.

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=_lib.sh
source "$HERE/_lib.sh"

input="$(cat)"
is_shepherd_project || exit 0
shepherd_skip_without_jq "agent_insight_capture" || exit 0

tool="$(json_field "$input" '.tool_name')"
case "$tool" in Agent|Task) ;; *) exit 0 ;; esac

response="$(json_response "$input")"
printf '%s' "$response" | grep -qE '^[[:space:]]*##[[:space:]]+INSIGHTS\b' || exit 0

repo_root="$(primary_worktree_root 2>/dev/null || pwd)"
run_dir="$(primary_active_run_dir 2>/dev/null || true)"
if [[ -z "$run_dir" ]]; then
  printf '[shepherd] agent_insight_capture skipped: no executing run is available for evidence.\n' >&2
  exit 0
fi
run_id="$(basename "$run_dir")"
insights_dir="$run_dir/events/insights"
mkdir -p "$insights_dir" 2>/dev/null || exit 0

# Emit one ASCII-record-separator-delimited record per valid insight. The
# Markdown shape is deliberately small and normalized before jq owns all JSON
# encoding, so no response text is ever interpolated into a JSON literal.
parse_insights() {
  printf '%s\n' "$response" | awk '
    function trim(value) {
      sub(/^[ \t]+/, "", value)
      sub(/[ \t]+$/, "", value)
      return value
    }
    function clear_fields() {
      kind = ""; subject = ""; observation = ""; rationale = ""; current = ""
    }
    function flush() {
      normalized = tolower(trim(kind))
      if (normalized == "relocation" || normalized == "extension" ||
          normalized == "duplication" || normalized == "consolidation" ||
          normalized == "gap" || normalized == "nit") {
        printf "%s\034%s\034%s\034%s\n", normalized, trim(subject), trim(observation), trim(rationale)
      }
      clear_fields()
    }
    BEGIN { in_block = 0; clear_fields() }
    /^[ \t]*##[ \t]+INSIGHTS([ \t]|$)/ {
      if (in_block) flush()
      in_block = 1
      next
    }
    in_block && /^[ \t]*##[ \t]+/ {
      flush()
      exit
    }
    !in_block { next }
    /^[ \t]*-[ \t]+kind[ \t]*:/ {
      flush()
      line = $0
      sub(/^[ \t]*-[ \t]+kind[ \t]*:[ \t]*/, "", line)
      kind = trim(line)
      current = "kind"
      next
    }
    /^[ \t]{0,4}(kind|subject|observation|rationale)[ \t]*:/ {
      line = $0
      sub(/^[ \t]*/, "", line)
      split(line, pair, ":")
      key = pair[1]
      sub(/^[^:]*:[ \t]*/, "", line)
      value = trim(line)
      if (key == "kind") kind = value
      else if (key == "subject") subject = value
      else if (key == "observation") observation = value
      else if (key == "rationale") rationale = value
      current = key
      next
    }
    current != "" && (/^[ \t][ \t][ \t][ \t]/ || /^\t/) {
      line = trim($0)
      if (line == "") next
      if (current == "kind") kind = trim(kind " " line)
      else if (current == "subject") subject = trim(subject " " line)
      else if (current == "observation") observation = trim(observation " " line)
      else if (current == "rationale") rationale = trim(rationale " " line)
    }
    END { if (in_block) flush() }
  '
}

count=0
while IFS=$'\034' read -r kind subject observation rationale; do
  [[ -n "$kind" ]] || continue
  captured_at="$(date -u +%s 2>/dev/null || echo 0)"
  stamp="$(date -u +%Y%m%dT%H%M%S 2>/dev/null || echo unknown)"
  suffix="$(od -An -tx1 -N4 /dev/urandom 2>/dev/null | tr -d ' \n' || echo rnd)"
  insight_id="$stamp-$suffix"
  record_file="$insights_dir/$insight_id.json"
  jq -n \
    --arg id "$insight_id" \
    --arg run "$run_id" \
    --arg kind "$kind" \
    --arg subject "$subject" \
    --arg observation "$observation" \
    --arg rationale "$rationale" \
    --argjson captured_at "$captured_at" \
    '{id:$id, schema_version:1, run:$run, captured_at:$captured_at,
      kind:$kind, subject:$subject, observation:$observation, rationale:$rationale,
      actioned:false, actioned_in:null}' > "$record_file" 2>/dev/null || continue
  count=$((count + 1))
done < <(parse_insights)

[[ "$count" -gt 0 ]] || exit 0

msg="[shepherd] captured $count cross-lane INSIGHT(s)."$'\n'
msg+="  Run:         $run_id"$'\n'
msg+="  Stored at:   ${insights_dir#${repo_root}/}/"$'\n'
msg+="  Inspect with: shepherd insights --help"

emit_json_obj additionalContext "$msg"
