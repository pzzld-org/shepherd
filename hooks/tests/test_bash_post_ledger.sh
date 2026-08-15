#!/usr/bin/env bash
# PostToolUse(Bash) telemetry records configured gate invocations in one run.

set -eu -o pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$ROOT/hooks/scripts/bash_post.sh"
fails=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s — %s\n' "$1" "$2"; fails=$((fails + 1)); }

if ! command -v jq >/dev/null 2>&1; then
  printf 'SKIP: jq is required by the registered telemetry adapter\n'
  exit 0
fi

tmp="$(mktemp -d -t shep-bash-post.XXXXXX)"
trap 'find "$tmp" -depth -delete' EXIT
cd "$tmp"
git init -q .
git config user.email t@t
git config user.name t
git -c commit.gpgsign=false commit -q --allow-empty -m init
mkdir -p .shepherd/runs/v100-dev0
cat > .shepherd/shepherd.toml <<'TOML'
[gates]
check = "cargo test -p shepherd-core"
TOML
printf '%s\n' '{"status":"executing"}' > .shepherd/runs/v100-dev0/run.json

payload="$(jq -nc '{session_id:"s1",tool_name:"Bash",tool_input:{command:"cargo test -p shepherd-core && echo done"}}')"
printf '%s' "$payload" | bash "$HOOK" >/dev/null 2>&1 || true
ledger=".shepherd/runs/v100-dev0/events/gates-ran-s1.jsonl"
if [[ -f "$ledger" ]] && jq -e 'select(.gate == "check" and (.command | contains("cargo test -p shepherd-core")))' "$ledger" >/dev/null; then
  pass "configured gate is recorded under active-run events"
else
  fail "configured gate is recorded under active-run events" "ledger=$(cat "$ledger" 2>/dev/null || echo MISSING)"
fi

if [[ ! -e .shepherd/cache && ! -e .shepherd/logs && ! -e .shepherd/memory && ! -e .shepherd/snapshots && ! -e .shepherd/tmp ]]; then
  pass "ledger creates no retired top-level root"
else
  fail "ledger creates no retired top-level root" "found=$(find .shepherd -maxdepth 1 -mindepth 1 -type d -print | tr '\n' ' ')"
fi

echo "—— $((2 - fails))/2 passed ——"
exit "$fails"
