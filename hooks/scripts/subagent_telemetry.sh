#!/usr/bin/env bash
# shepherd hook — SubagentStop: cache-usage telemetry.
#
# This source-tree hook is observational. jq is its one parser dependency; if
# unavailable it emits a diagnostic and deliberately records no synthetic row.

set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=_lib.sh
source "$HERE/_lib.sh"

input="$(cat)"
is_shepherd_project || exit 0
shepherd_skip_without_jq "subagent_telemetry" || exit 0

hook_event="$(json_field "$input" '.hook_event_name')"
[[ "$hook_event" == "SubagentStop" ]] || exit 0

session_id="$(json_field "$input" '.session_id')"
agent_id="$(json_field "$input" '.agent_id')"
agent_type="$(json_field "$input" '.agent_type')"
transcript_path="$(json_field "$input" '.agent_transcript_path')"
case "$transcript_path" in "~/"*) transcript_path="$HOME/${transcript_path#\~/}" ;; esac

role="${agent_type:-unknown}"
case "$role" in engineer|critic|coder|auditor|worker|discovery) ;; *) role="${role:-unknown}" ;; esac

# Telemetry belongs to its exact executing run. There is no cross-run
# fallback: without one, skipping with a diagnostic is more honest than
# creating a retired logs root or assigning the event by branch guesswork.
run_dir="$(primary_active_run_dir 2>/dev/null || true)"
if [[ -z "$run_dir" ]]; then
  printf '[shepherd] subagent_telemetry skipped: no executing run is available for the event.\n' >&2
  exit 0
fi
run_id="$(basename "$run_dir")"
events_dir="$run_dir/events"
if ! mkdir -p "$events_dir" 2>/dev/null; then
  printf '[shepherd] subagent_telemetry skipped: cannot create active-run events directory.\n' >&2
  exit 0
fi
day="$(date -u +%Y-%m-%d 2>/dev/null || echo unknown)"
events_file="$events_dir/events-$day.jsonl"
ts="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo unknown)"

emit_event() {
  printf '%s\n' "$1" >> "$events_file" 2>/dev/null || true
}

parse_error_event() {
  local reason="$1"
  jq -cn \
    --arg ts "$ts" \
    --arg session_id "$session_id" \
    --arg role "$role" \
    --arg agent_id "$agent_id" \
    --arg run "$run_id" \
    --arg reason "$reason" \
    '{
      ts:$ts, event_type:"cache_usage",
      session_id:(if $session_id == "" then null else $session_id end),
      role:(if $role == "" then "unknown" else $role end),
      agent_id:(if $agent_id == "" then null else $agent_id end),
      run:$run,
      turns:null, input_tokens:null, output_tokens:null,
      cache_read_input_tokens:null, cache_creation_input_tokens:null,
      ephemeral_5m_input_tokens:null, ephemeral_1h_input_tokens:null,
      hit_rate:null, parse_error:$reason
    }'
}

if [[ -z "$transcript_path" ]]; then
  emit_event "$(parse_error_event "missing agent_transcript_path in SubagentStop payload")"
  log_event "subagent_telemetry" "warn" "SubagentStop" "$role" "$session_id" \
    "$(emit_json_obj agent_id "$agent_id" reason "missing_transcript_path")"
  exit 0
fi

if [[ ! -r "$transcript_path" ]]; then
  emit_event "$(parse_error_event "agent_transcript_path not readable: $transcript_path")"
  log_event "subagent_telemetry" "warn" "SubagentStop" "$role" "$session_id" \
    "$(emit_json_obj agent_id "$agent_id" reason "transcript_unreadable")"
  exit 0
fi

# Parse JSONL as raw lines. fromjson? intentionally drops malformed transcript
# lines, matching the former parser's best-effort semantics without adding a
# second language runtime.
event_json="$(
  jq -Rn \
    --arg ts "$ts" \
    --arg session_id "$session_id" \
    --arg role "$role" \
    --arg agent_id "$agent_id" \
    --arg run "$run_id" '
      def number_or_zero:
        if type == "number" then . else 0 end;
      def sum_field($name):
        (map(.[$name] | number_or_zero) | add) // 0;
      def sum_cache_field($name):
        (map(
          if (.cache_creation | type) == "object"
          then (.cache_creation[$name] | number_or_zero)
          else 0
          end
        ) | add) // 0;
      [
        inputs
        | fromjson?
        | .message?
        | select(
            type == "object"
            and .role == "assistant"
            and (.usage | type) == "object"
          )
        | .usage
      ] as $usage
      | ($usage | length) as $turns
      | (if $turns == 0 then "no_assistant_usage_records_in_transcript" else null end) as $parse_error
      | ($usage | sum_field("input_tokens")) as $input_tokens
      | ($usage | sum_field("output_tokens")) as $output_tokens
      | ($usage | sum_field("cache_read_input_tokens")) as $cache_read
      | ($usage | sum_field("cache_creation_input_tokens")) as $cache_creation
      | ($usage | sum_cache_field("ephemeral_5m_input_tokens")) as $ephemeral_5m
      | ($usage | sum_cache_field("ephemeral_1h_input_tokens")) as $ephemeral_1h
      | ($cache_read + $cache_creation + $input_tokens) as $denominator
      | (if $denominator > 0
         then ((($cache_read / $denominator) * 10000 | round) / 10000)
         else null
         end) as $hit_rate
      | {
          ts:$ts, event_type:"cache_usage",
          session_id:(if $session_id == "" then null else $session_id end),
          role:(if $role == "" then "unknown" else $role end),
          agent_id:(if $agent_id == "" then null else $agent_id end),
          run:$run,
          turns:(if $parse_error == null then $turns else null end),
          input_tokens:(if $parse_error == null then $input_tokens else null end),
          output_tokens:(if $parse_error == null then $output_tokens else null end),
          cache_read_input_tokens:(if $parse_error == null then $cache_read else null end),
          cache_creation_input_tokens:(if $parse_error == null then $cache_creation else null end),
          ephemeral_5m_input_tokens:(if $parse_error == null then $ephemeral_5m else null end),
          ephemeral_1h_input_tokens:(if $parse_error == null then $ephemeral_1h else null end),
          hit_rate:(if $parse_error == null then $hit_rate else null end),
          parse_error:$parse_error
        }
    ' < "$transcript_path" 2>/dev/null || true
)"

[[ -n "$event_json" ]] || event_json="$(parse_error_event "transcript_aggregation_failed")"
emit_event "$event_json"
log_event "subagent_telemetry" "pass" "SubagentStop" "$role" "$session_id" \
  "$(emit_json_obj agent_id "$agent_id" run "$run_id" events_file "$events_file")"
exit 0
