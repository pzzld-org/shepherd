#!/usr/bin/env bash
# shepherd hook — SubagentStop: per-dispatch cache-telemetry capture (v5.1.3)
#
# Captures prompt-caching health for every subagent that completes. The hook
# parses the subagent's transcript JSONL — emitted by Claude Code at
# `agent_transcript_path` in the SubagentStop payload — and aggregates the
# four cache-related Anthropic-API usage fields:
#
#     input_tokens
#     output_tokens
#     cache_read_input_tokens
#     cache_creation_input_tokens
#     cache_creation.ephemeral_5m_input_tokens
#     cache_creation.ephemeral_1h_input_tokens
#
# One JSONL line is appended to `<ns>/logs/events-YYYY-MM-DD.jsonl`. The line
# follows the doctrines/cache-telemetry.md contract (see also
# doctrines/hook-event-log.md for the broader event-log convention).
#
# Discipline:
#   • Never block.    The hook exits 0 unconditionally; parse failures emit
#                     a `parse_error` event rather than going silent.
#   • Never lie.      Missing fields surface as `null`, not zero — zero means
#                     "the assistant turn measured zero tokens", which is a
#                     meaningful signal (cache hit on a very small prefix).
#   • Counts only.    No prompt content is captured; the event log carries
#                     token counts and identifiers.
#
# Input  (stdin): SubagentStop JSON
#   {
#     "session_id": "...",
#     "transcript_path": "...",          (parent session)
#     "cwd": "...",
#     "hook_event_name": "SubagentStop",
#     "stop_hook_active": ...,
#     "agent_id": "agt-...",
#     "agent_type": "Explore | <subagent-type>",
#     "agent_transcript_path": "...jsonl",
#     "last_assistant_message": "..."
#   }
#
# Output (stdout): silent exit 0 (the hook's signal is on disk, not in chat).

set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=_lib.sh
source "$HERE/_lib.sh"

input=$(cat)
is_shepherd_project || exit 0

# The lane runs only on SubagentStop. If something else routes here, no-op.
hook_event=$(json_field "$input" '.hook_event_name')
case "$hook_event" in
  SubagentStop) ;;
  *) exit 0 ;;
esac

session_id=$(json_field "$input" '.session_id')
agent_id=$(json_field "$input" '.agent_id')
agent_type=$(json_field "$input" '.agent_type')
transcript_path=$(json_field "$input" '.agent_transcript_path')

# Expand a leading ~ in the transcript path (Claude Code emits paths like
# "~/.claude/projects/...").
case "$transcript_path" in
  "~/"*) transcript_path="${HOME}/${transcript_path#\~/}" ;;
esac

# Resolve the role written by agent_invocation_tagger.sh. The tagger keys on
# `tool_use_id`, which SubagentStop does NOT carry — but `agent_id` is the
# durable identifier. Falling back to agent_type if no per-id mapping is
# available is honest: it captures whatever signal IS present.
sprint=$(current_sprint)
role="${agent_type:-unknown}"

# Map agent_type to the canonical flock role when possible. Claude Code's
# built-in agent_type is the subagent's `name` field (e.g., "engineer",
# "coder", etc., for shepherd dispatches; "Explore" for the built-in).
case "$role" in
  engineer|critic|coder|auditor|worker|discovery) ;;
  *) role="${role:-unknown}" ;;
esac

ns=$(resolve_namespace)
logs_dir="$ns/logs"
mkdir -p "$logs_dir" 2>/dev/null || true
day=$(date -u +%Y-%m-%d 2>/dev/null || echo "unknown")
events_file="$logs_dir/events-${day}.jsonl"
# Millisecond timestamp. macOS `date` lacks %N; fall back through gdate, then
# python3, then second-precision (still valid ISO-8601).
ts=$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ 2>/dev/null) || ts=""
case "$ts" in
  *NZ|"")
    if command -v gdate >/dev/null 2>&1; then
      ts=$(gdate -u +%Y-%m-%dT%H:%M:%S.%3NZ 2>/dev/null) || ts=""
    fi
    ;;
esac
case "$ts" in
  *NZ|"")
    ts=$(python3 -c "import datetime as d; n=d.datetime.now(d.timezone.utc); print(n.strftime('%Y-%m-%dT%H:%M:%S.')+str(n.microsecond//1000).zfill(3)+'Z')" 2>/dev/null) || ts=""
    ;;
esac
[[ -z "$ts" ]] && ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# ---------------------------------------------------------------------------
# Parse the subagent transcript. Python carries the JSONL aggregation because
# jq's loop semantics over a streaming file are awkward and the math is
# trivial in Python.
# ---------------------------------------------------------------------------
emit_event() {
  # emit_event "<json line>"
  local line="$1"
  printf '%s\n' "$line" >> "$events_file" 2>/dev/null || true
}

build_parse_error_event() {
  local reason="$1"
  python3 - "$ts" "$session_id" "$role" "$agent_id" "$sprint" "$reason" <<'PY' 2>/dev/null
import json, sys
ts, session_id, role, agent_id, sprint, reason = sys.argv[1:]
print(json.dumps({
    "ts":                          ts,
    "event_type":                  "cache_usage",
    "session_id":                  session_id or None,
    "role":                        role or "unknown",
    "agent_id":                    agent_id or None,
    "sprint":                      sprint or None,
    "turns":                       None,
    "input_tokens":                None,
    "output_tokens":               None,
    "cache_read_input_tokens":     None,
    "cache_creation_input_tokens": None,
    "ephemeral_5m_input_tokens":   None,
    "ephemeral_1h_input_tokens":   None,
    "hit_rate":                    None,
    "parse_error":                 reason,
}))
PY
}

# Early-out: no transcript path → emit a parse_error event so the absence is
# visible to the auditor, then exit 0.
if [[ -z "$transcript_path" ]]; then
  ev=$(build_parse_error_event "missing agent_transcript_path in SubagentStop payload")
  [[ -n "$ev" ]] && emit_event "$ev"
  log_event "subagent_telemetry" "warn" "SubagentStop" "$role" "$session_id" \
    "$(emit_json_obj agent_id "$agent_id" reason "missing_transcript_path")"
  exit 0
fi

if [[ ! -r "$transcript_path" ]]; then
  ev=$(build_parse_error_event "agent_transcript_path not readable: $transcript_path")
  [[ -n "$ev" ]] && emit_event "$ev"
  log_event "subagent_telemetry" "warn" "SubagentStop" "$role" "$session_id" \
    "$(emit_json_obj agent_id "$agent_id" reason "transcript_unreadable")"
  exit 0
fi

# Aggregate usage. The transcript shape is the Anthropic SDK message-stream
# JSONL: one record per line, with assistant turns carrying `message.usage`.
event_json=$(python3 - "$ts" "$session_id" "$role" "$agent_id" "$sprint" "$transcript_path" <<'PY' 2>/dev/null || true
import json, sys

ts, session_id, role, agent_id, sprint, path = sys.argv[1:]

def nz(v):
    """Treat None / missing as 0 for SUMs; preserve None for downstream nulls."""
    return v if isinstance(v, (int, float)) else 0

totals = {
    "input_tokens":                0,
    "output_tokens":                0,
    "cache_read_input_tokens":      0,
    "cache_creation_input_tokens":  0,
    "ephemeral_5m_input_tokens":    0,
    "ephemeral_1h_input_tokens":    0,
}
turns = 0
saw_any_usage = False
parse_error = None

try:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            msg = rec.get("message") if isinstance(rec, dict) else None
            if not isinstance(msg, dict):
                continue
            if msg.get("role") != "assistant":
                continue
            usage = msg.get("usage")
            if not isinstance(usage, dict):
                continue
            saw_any_usage = True
            turns += 1
            totals["input_tokens"]                += nz(usage.get("input_tokens"))
            totals["output_tokens"]                += nz(usage.get("output_tokens"))
            totals["cache_read_input_tokens"]      += nz(usage.get("cache_read_input_tokens"))
            totals["cache_creation_input_tokens"]  += nz(usage.get("cache_creation_input_tokens"))
            cc = usage.get("cache_creation")
            if isinstance(cc, dict):
                totals["ephemeral_5m_input_tokens"]   += nz(cc.get("ephemeral_5m_input_tokens"))
                totals["ephemeral_1h_input_tokens"]   += nz(cc.get("ephemeral_1h_input_tokens"))
except Exception as e:
    parse_error = "transcript_read_failed: {}".format(type(e).__name__)

if parse_error is None and not saw_any_usage:
    parse_error = "no_assistant_usage_records_in_transcript"

# Hit-rate. Defined as cache_read / (cache_read + cache_creation + fresh input).
# Total billable input across the dispatch:
#   cache_read + cache_creation + raw input_tokens
# If the denominator is zero, the rate is undefined (null), not zero.
denom = (totals["cache_read_input_tokens"]
         + totals["cache_creation_input_tokens"]
         + totals["input_tokens"])
if denom > 0:
    hit_rate = round(totals["cache_read_input_tokens"] / denom, 4)
else:
    hit_rate = None

# When parse_error fires, surface counts as null rather than zero so the
# auditor's hit-rate aggregation isn't poisoned by phantom rows.
def maybe(v):
    return None if parse_error else v

event = {
    "ts":                          ts,
    "event_type":                  "cache_usage",
    "session_id":                  session_id or None,
    "role":                        role or "unknown",
    "agent_id":                    agent_id or None,
    "sprint":                      sprint or None,
    "turns":                       maybe(turns) if turns else (None if parse_error else 0),
    "input_tokens":                maybe(totals["input_tokens"]),
    "output_tokens":               maybe(totals["output_tokens"]),
    "cache_read_input_tokens":     maybe(totals["cache_read_input_tokens"]),
    "cache_creation_input_tokens": maybe(totals["cache_creation_input_tokens"]),
    "ephemeral_5m_input_tokens":   maybe(totals["ephemeral_5m_input_tokens"]),
    "ephemeral_1h_input_tokens":   maybe(totals["ephemeral_1h_input_tokens"]),
    "hit_rate":                    None if parse_error else hit_rate,
    "parse_error":                 parse_error,
}
print(json.dumps(event))
PY
)

if [[ -z "$event_json" ]]; then
  # Python pipeline itself failed (truly unexpected — emit parse_error rather
  # than going silent, so the gap is visible to the auditor).
  event_json=$(build_parse_error_event "python_aggregation_failed")
fi

emit_event "$event_json"

# Mirror to the structured hook-event-log so `shctx doctor` sees the fire.
log_event "subagent_telemetry" "pass" "SubagentStop" "$role" "$session_id" \
  "$(emit_json_obj agent_id "$agent_id" sprint "$sprint" events_file "$events_file")"

# v5.1.7: emit teammate heartbeat if running inside a teammate session.
if [[ -n "${CLAUDE_TEAMMATE_NAME:-}" ]]; then
  ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
  if [[ -n "$ROOT" && -f "$ROOT/.artifacts/root.db" ]]; then
    bash "$ROOT/skills/context/scripts/cmd_teammate.sh" \
      heartbeat "$CLAUDE_TEAMMATE_NAME" \
      --tool="${CLAUDE_TOOL_NAME:-unknown}" 2>/dev/null || true
  fi
fi

exit 0
