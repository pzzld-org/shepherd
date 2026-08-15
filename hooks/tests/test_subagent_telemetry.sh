#!/usr/bin/env bash
# Run-scoped regression for SubagentStop cache telemetry.

set -eu -o pipefail
cd "$(dirname "$0")"
HOOKS_DIR="$(cd .. && pwd)/scripts"
SCRIPT="$HOOKS_DIR/subagent_telemetry.sh"

fails=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s — %s\n' "$1" "$2"; fails=$((fails + 1)); }

if ! command -v jq >/dev/null 2>&1; then
  printf '  SKIP  jq is unavailable; source telemetry declares it as required\n'
  exit 0
fi

tmp="$(mktemp -d -t shep-subagent-telemetry.XXXXXX)"
trap 'find "$tmp" -depth -delete' EXIT
cd "$tmp"
git init -q .
git config user.email t@t
git config user.name t
git -c commit.gpgsign=false commit -q --allow-empty -m init
mkdir -p .shepherd/runs/v100-dev0
touch .shepherd/shepherd.toml
printf '%s\n' '{"status":"executing"}' > .shepherd/runs/v100-dev0/run.json
printf '%s\n' '{"message":{"role":"assistant","usage":{"input_tokens":10,"output_tokens":4,"cache_read_input_tokens":8,"cache_creation_input_tokens":2}}}' > transcript.jsonl

payload="$(jq -nc --arg transcript "$tmp/transcript.jsonl" '{hook_event_name:"SubagentStop",session_id:"s1",agent_id:"a1",agent_type:"worker",agent_transcript_path:$transcript}')"
printf '%s' "$payload" | bash "$SCRIPT" >/dev/null 2>&1 || true
events_file=".shepherd/runs/v100-dev0/events/events-$(date -u +%Y-%m-%d).jsonl"

if [[ -f "$events_file" ]] \
   && jq -e 'select(.event_type == "cache_usage" and .run == "v100-dev0" and .input_tokens == 10 and .cache_read_input_tokens == 8)' "$events_file" >/dev/null; then
  pass "cache telemetry lands in active-run events with an exact run id"
else
  fail "cache telemetry lands in active-run events" "event=$(cat "$events_file" 2>/dev/null || echo MISSING)"
fi

if [[ ! -e .shepherd/logs && ! -e .shepherd/tmp && ! -e .shepherd/cache && ! -e .shepherd/memory && ! -e .shepherd/snapshots ]]; then
  pass "telemetry creates no retired top-level root"
else
  fail "telemetry creates no retired top-level root" "found=$(find .shepherd -maxdepth 1 -mindepth 1 -type d -print | tr '\n' ' ')"
fi

before="$(wc -l < "$events_file" 2>/dev/null || echo 0)"
printf '%s\n' '{"status":"completed"}' > .shepherd/runs/v100-dev0/run.json
printf '%s' "$payload" | bash "$SCRIPT" >/dev/null 2>&1 || true
after="$(wc -l < "$events_file" 2>/dev/null || echo 0)"
if [[ "$before" == "$after" ]]; then
  pass "no executing run: telemetry skips rather than inventing a sink"
else
  fail "no executing run: telemetry skips" "before=$before after=$after"
fi

echo "—— $((3 - fails))/3 passed ——"
exit "$fails"
