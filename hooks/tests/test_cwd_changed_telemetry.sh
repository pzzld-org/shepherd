#!/usr/bin/env bash
# CwdChanged remains informational telemetry, never a policy verdict.

set -eu -o pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$ROOT/hooks/scripts/cwd_changed.sh"
fails=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s — %s\n' "$1" "$2"; fails=$((fails + 1)); }

if ! command -v jq >/dev/null 2>&1; then
  printf 'SKIP: jq is required by the registered telemetry adapter\n'
  exit 0
fi

tmp="$(mktemp -d -t shep-cwd-telemetry.XXXXXX)"
trap 'find "$tmp" -depth -delete' EXIT
cd "$tmp"
git init -q .
git config user.email t@t
git config user.name t
git -c commit.gpgsign=false commit -q --allow-empty -m init
mkdir -p .shepherd/runs/v100-dev0
touch .shepherd/shepherd.toml
printf '%s\n' '{"status":"executing"}' > .shepherd/runs/v100-dev0/run.json

payload="$(jq -nc '{hook_event_name:"CwdChanged",session_id:"s1",cwd:"/tmp/example"}')"
out="$(printf '%s' "$payload" | bash "$HOOK" 2>/dev/null || true)"
events=".shepherd/runs/v100-dev0/events/hooks-$(date -u +%Y-%m-%d).jsonl"

if [[ -z "$out" ]] || jq -e '.additionalContext? | type == "string"' <<<"$out" >/dev/null 2>&1; then
  pass "CwdChanged emits no policy verdict"
else
  fail "CwdChanged emits no policy verdict" "out=$out"
fi

if [[ -f "$events" ]] && jq -e 'select(.hook == "cwd_changed" and .decision == "pass")' "$events" >/dev/null; then
  pass "CwdChanged records run-scoped telemetry"
else
  fail "CwdChanged records run-scoped telemetry" "events=$(cat "$events" 2>/dev/null || echo MISSING)"
fi

echo "—— $((2 - fails))/2 passed ——"
exit "$fails"
