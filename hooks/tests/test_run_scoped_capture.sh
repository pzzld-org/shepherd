#!/usr/bin/env bash
# Registered Agent/Task telemetry must write evidence only inside the active run.

set -eu -o pipefail
cd "$(dirname "$0")"
HOOKS_DIR="$(cd .. && pwd)/scripts"

fails=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s — %s\n' "$1" "$2"; fails=$((fails + 1)); }

if ! command -v jq >/dev/null 2>&1; then
  printf '  SKIP  jq is unavailable; registered telemetry declares it as required\n'
  exit 0
fi

tmp="$(mktemp -d -t shep-run-capture.XXXXXX)"
trap 'find "$tmp" -depth -delete' EXIT
cd "$tmp"
git init -q .
git config user.email t@t
git config user.name t
git -c commit.gpgsign=false commit -q --allow-empty -m init
mkdir -p .shepherd/runs/v100-dev0
touch .shepherd/shepherd.toml
printf '%s\n' '{"status":"executing"}' > .shepherd/runs/v100-dev0/run.json

insight='## INSIGHTS
- kind: gap
  subject: active run
  observation: evidence must have one owner
  rationale: canonical layout'
insight_payload="$(jq -nc --arg response "$insight" '{tool_name:"Agent",session_id:"s1",tool_response:$response}')"
printf '%s' "$insight_payload" | bash "$HOOKS_DIR/agent_insight_capture.sh" >/dev/null 2>&1 || true

insight_file="$(find .shepherd/runs/v100-dev0/events/insights -type f -name '*.json' -print -quit 2>/dev/null || true)"
if [[ -n "$insight_file" ]] && jq -e '.run == "v100-dev0" and .kind == "gap"' "$insight_file" >/dev/null; then
  pass "insight capture writes active-run evidence"
else
  fail "insight capture writes active-run evidence" "file=${insight_file:-MISSING}"
fi

discovery='## DISCOVERY REPORT
Question: Where belongs evidence?
Sources consulted: 1
Tool calls used: 1
Time used: 1m
Report path: .shepherd/runs/v100-dev0/reports/discovery.md
Confidence: high
Status: complete
Anomalies: none
Reporter: discovery'
discovery_payload="$(jq -nc --arg response "$discovery" '{tool_name:"Task",session_id:"s2",tool_response:$response}')"
printf '%s' "$discovery_payload" | bash "$HOOKS_DIR/discovery_capture.sh" >/dev/null 2>&1 || true

discovery_file="$(find .shepherd/runs/v100-dev0/events/discoveries -type f -name '*.json' -print -quit 2>/dev/null || true)"
if [[ -n "$discovery_file" ]] && jq -e '.run == "v100-dev0" and .question == "Where belongs evidence?"' "$discovery_file" >/dev/null; then
  pass "discovery capture writes active-run evidence"
else
  fail "discovery capture writes active-run evidence" "file=${discovery_file:-MISSING}"
fi

if [[ ! -e .shepherd/insights && ! -e .shepherd/discoveries && ! -e .shepherd/cache && ! -e .shepherd/logs && ! -e .shepherd/memory && ! -e .shepherd/snapshots && ! -e .shepherd/tmp ]]; then
  pass "capture creates no retired top-level root"
else
  fail "capture creates no retired top-level root" "found=$(find .shepherd -maxdepth 1 -mindepth 1 -type d -print | tr '\n' ' ')"
fi

echo "—— $((3 - fails))/3 passed ——"
exit "$fails"
