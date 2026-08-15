#!/usr/bin/env bash
# Shared telemetry helpers may write only under an executing run.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LIB="$ROOT/hooks/scripts/_lib.sh"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/shepherd-run-scoped-state.XXXXXX")"
trap 'find "$tmp" -depth -delete' EXIT

cd "$tmp"
git init -q
mkdir -p .shepherd/runs/v645
touch .shepherd/shepherd.toml
printf '%s\n' '{"run":"v645","status":"executing"}' > .shepherd/runs/v645/run.json

(
  source "$LIB"
  log_event "run-state-test" "pass" "Bash" "shepherd" "s1" '{}'
) >/dev/null

fails=0
fail() {
  printf 'FAIL: %s\n' "$1" >&2
  fails=$((fails + 1))
}

[[ -f ".shepherd/runs/v645/events/hooks-$(date -u +%Y-%m-%d).jsonl" ]] \
  || fail "event log was not written under active run"

for retired_root in cache logs memory snapshots tmp insights discoveries; do
  [[ ! -e ".shepherd/$retired_root" ]] || fail "retired top-level root recreated: $retired_root"
done

for retired_helper in shepherd_mcp_available safe_dispatch_id session_tier_marker; do
  ! rg -q "^${retired_helper}\\(\\)" "$LIB" || fail "retired policy helper remains in shared telemetry library: ${retired_helper}"
done

[[ "$fails" -eq 0 ]] || exit 1
printf 'test_run_scoped_hook_state: PASS\n'
