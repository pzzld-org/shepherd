#!/usr/bin/env bash
# Regression: compaction snapshots belong to the active run. Recreating
# namespace cache/tmp/snapshot roots or an orphaned rehydration marker is a bug.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PRECOMPACT="$ROOT/hooks/scripts/precompact_snapshot.sh"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/shepherd-compaction-run.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT

cd "$tmp"
git init -q
git config user.email test@example.invalid
git config user.name test
git -c commit.gpgsign=false commit -q --allow-empty -m init
git checkout -q -b v6.4.5-dev.0
run=".shepherd/runs/v645"
mkdir -p "$run/graph"
touch .shepherd/shepherd.toml
printf '%s\n' '{"run":"v645","status":"executing"}' > "$run/run.json"
printf '%s\n' '{"ready":["node-ready"],"in_flight":["node-flight"]}' > "$run/graph/state.json"

session="compact-s1"
payload="{\"session_id\":\"$session\",\"trigger\":\"manual\",\"hook_event_name\":\"PreCompact\"}"
printf '%s' "$payload" | bash "$PRECOMPACT" >/dev/null

fails=0
fail() {
  printf 'FAIL: %s\n' "$1" >&2
  fails=$((fails + 1))
}

snapshot=""
for candidate in "$run"/snapshots/precompact-$session-*.json; do
  [[ -f "$candidate" ]] && snapshot="$candidate"
done
[[ -n "$snapshot" ]] || fail "snapshot was not written under the active run"
[[ ! -e "$run/fixtures/rehydrate-pending.$session" ]] \
  || fail "orphaned rehydration marker was written"

jq -e '.run == "v645" and .cursor.ready_nodes == ["node-ready"] and .cursor.in_flight_nodes == ["node-flight"]' "$snapshot" >/dev/null 2>&1 \
  || fail "snapshot did not preserve active-run cursor evidence"

for retired_root in cache logs memory snapshots tmp; do
  [[ ! -e ".shepherd/$retired_root" ]] || fail "retired top-level root recreated: $retired_root"
done

[[ "$fails" -eq 0 ]] || exit 1
printf 'test_compaction_run_scope: PASS\n'
