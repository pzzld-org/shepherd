#!/usr/bin/env bash
# hooks/tests/precompact_snapshot_test.sh — tests for precompact_snapshot.sh
#
# Covers the PreCompact snapshot hook (v6.0.9, Item A2):
#   1. No shepherd.toml → exit 0, no output (not a shepherd project).
#   2. Config [compaction] precompact_snapshot = off → no snapshot, no flag.
#   3. Default (on) → snapshot JSON written to snapshots/, pending flag set.
#   4. Snapshot JSON contains expected fields (session, trigger, cursor, focus).
#   5. Retention trim: write 7 snapshots with retention=5; only 5 remain.
#   6. Missing state.json / trace.jsonl → fail-open, snapshot still written.
#   7. Script always exits 0 (never blocks compaction).

set -eu -o pipefail
cd "$(dirname "$0")"
HOOKS_DIR="$(cd .. && pwd)/scripts"
SCRIPT="$HOOKS_DIR/precompact_snapshot.sh"

fails=0
total=0
pass()  { printf '  PASS  %s\n' "$1"; }
fail()  { printf '  FAIL  %s — %s\n' "$1" "${2:-}"; fails=$((fails+1)); }
skip()  { printf '  SKIP  %s — %s\n' "$1" "$2"; }

# Safe file count: avoid pipefail interaction with `ls | wc -l`.
count_files() {
  local pat="$1" n=0 f
  for f in $pat; do [[ -f "$f" ]] && n=$((n+1)); done
  printf '%d' "$n"
}

run_hook() {
  printf '%s' "$1" | bash "$SCRIPT" 2>/dev/null
  return 0
}

# ---------------------------------------------------------------------------
# 1. No shepherd.toml → exit 0, no output (not a shepherd project).
# ---------------------------------------------------------------------------
total=$((total+1))
tmp_bare=$(mktemp -d -t shep-pcs-bare.XXXXXX)
(
  cd "$tmp_bare"
  git init -q . && git config user.email t@t && git config user.name t
  git -c commit.gpgsign=false commit -q --allow-empty -m init
  # No .claude/shepherd.toml
  rc=0
  out=$(printf '' | bash "$SCRIPT" 2>/dev/null) || rc=$?
  if [[ "${rc:-0}" -eq 0 ]] && [[ -z "$out" ]]; then
    printf '  PASS  no-shepherd-toml: exit 0, no output\n'
  else
    printf '  FAIL  no-shepherd-toml — rc=%d out=%s\n' "${rc:-0}" "$out"
    exit 1
  fi
) || fails=$((fails+1))
rm -rf "$tmp_bare"

# ---------------------------------------------------------------------------
# Shared ephemeral shepherd-flagged repo for remaining tests.
# ---------------------------------------------------------------------------
tmp=$(mktemp -d -t shep-pcs-test.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q .
git config user.email t@t
git config user.name t
git -c commit.gpgsign=false commit -q --allow-empty -m init
git checkout -q -b v0.9.0-dev.0 2>/dev/null || true
mkdir -p .claude .artifacts/graph .artifacts/memory/snapshots .artifacts/tmp
touch .claude/shepherd.toml   # default config

# Minimal state.json with ready and in_flight arrays.
cat > .artifacts/graph/state.json <<'JSON'
{"ready":["node-B","node-C"],"in_flight":["node-A"]}
JSON
# Minimal trace.jsonl.
printf '{"ts":1,"event":"wave-start","node":"node-A"}\n' >> .artifacts/graph/trace.jsonl
printf '{"ts":2,"event":"dispatch","node":"node-A","role":"coder"}\n' >> .artifacts/graph/trace.jsonl

PAYLOAD_BASE='{"session_id":"sess-test-01","trigger":"manual","cwd":"/repo","hook_event_name":"PreCompact"}'

# ---------------------------------------------------------------------------
# 2. Config off → exit 0, no snapshot written, no pending flag.
# ---------------------------------------------------------------------------
total=$((total+1))
printf '[compaction]\nprecompact_snapshot = "off"\n' > .claude/shepherd.toml
BEFORE=$(count_files '.artifacts/memory/snapshots/precompact-*.json')
run_hook "$PAYLOAD_BASE"
AFTER=$(count_files '.artifacts/memory/snapshots/precompact-*.json')
FLAG_EXISTS=0; [[ -f ".artifacts/tmp/rehydrate-pending.sess-test-01" ]] && FLAG_EXISTS=1
if [[ "$AFTER" -eq "$BEFORE" ]] && [[ "$FLAG_EXISTS" -eq 0 ]]; then
  pass "config-off: no snapshot written, no flag"
else
  fail "config-off: no snapshot written, no flag" "before=$BEFORE after=$AFTER flag=$FLAG_EXISTS"
fi
printf '' > .claude/shepherd.toml   # reset to default

# ---------------------------------------------------------------------------
# 3. Default (on) → snapshot JSON written, pending flag set.
# ---------------------------------------------------------------------------
total=$((total+1))
run_hook "$PAYLOAD_BASE"
# Collect matching snapshots safely (avoid pipefail globbing).
SNAPS=()
for f in .artifacts/memory/snapshots/precompact-sess-test-01-*.json; do [[ -f "$f" ]] && SNAPS+=("$f"); done
FLAG_PATH=".artifacts/tmp/rehydrate-pending.sess-test-01"
if [[ "${#SNAPS[@]}" -ge 1 ]] && [[ -f "$FLAG_PATH" ]]; then
  pass "default-on: snapshot written and pending flag set"
else
  fail "default-on: snapshot written and pending flag set" \
    "snap_count=${#SNAPS[@]} flag_exists=$([[ -f $FLAG_PATH ]] && echo 1 || echo 0)"
fi

# ---------------------------------------------------------------------------
# 4. Snapshot JSON contains expected fields.
# ---------------------------------------------------------------------------
total=$((total+1))
SNAP_FILE="${SNAPS[0]:-}"
if [[ -z "$SNAP_FILE" ]] || ! command -v jq &>/dev/null; then
  skip "snapshot-fields" "no snapshot file or jq missing"
else
  SESSION_OK="$(jq -r '.session_id // ""' "$SNAP_FILE" 2>/dev/null || true)"
  TRIGGER_OK="$(jq -r '.trigger // ""' "$SNAP_FILE" 2>/dev/null || true)"
  READY_OK="$(jq -r '.cursor.ready_nodes | length' "$SNAP_FILE" 2>/dev/null || echo 0)"
  INFLIGHT_OK="$(jq -r '.cursor.in_flight_nodes | length' "$SNAP_FILE" 2>/dev/null || echo 0)"
  FILE_SZ="$(wc -c < "$SNAP_FILE" | tr -d '[:space:]')"
  if [[ "$SESSION_OK" == "sess-test-01" ]] \
     && [[ "$TRIGGER_OK" == "manual" ]] \
     && [[ "${READY_OK:-0}" -ge 1 ]] \
     && [[ "${INFLIGHT_OK:-0}" -ge 1 ]] \
     && [[ "${FILE_SZ:-0}" -gt 10 ]]; then
    pass "snapshot-fields: session, trigger, cursor.ready_nodes, cursor.in_flight_nodes present"
  else
    fail "snapshot-fields" \
      "session=$SESSION_OK trigger=$TRIGGER_OK ready=$READY_OK inflight=$INFLIGHT_OK size=$FILE_SZ"
  fi
fi

# ---------------------------------------------------------------------------
# 5. Retention trim: write 7 snapshots with retention=5, only ≤5 remain.
# ---------------------------------------------------------------------------
total=$((total+1))
printf '[compaction]\nsnapshot_retention = 5\n' > .claude/shepherd.toml
# Remove prior snapshots to get a clean slate for the count.
rm -f .artifacts/memory/snapshots/precompact-*.json 2>/dev/null || true
# Write 7 snapshots with different session IDs (each has a distinct safe name).
for i in 1 2 3 4 5 6 7; do
  # Use `date +%s%N` or a counter to guarantee distinct epoch digits.
  # Since epoch seconds may repeat within a loop, append $i to session id so
  # filenames are unique even if date +%s repeats.
  RET_PAYLOAD="{\"session_id\":\"sess-ret-${i}\",\"trigger\":\"auto\"}"
  run_hook "$RET_PAYLOAD"
done
FINAL=$(count_files '.artifacts/memory/snapshots/precompact-*.json')
if [[ "$FINAL" -le 5 ]]; then
  pass "retention-trim: ${FINAL} snapshot(s) remain (≤ 5)"
else
  fail "retention-trim: ${FINAL} snapshot(s) remain (> 5)"
fi
printf '' > .claude/shepherd.toml

# ---------------------------------------------------------------------------
# 6. Missing state.json / trace.jsonl → fail-open, snapshot still written.
# ---------------------------------------------------------------------------
# Clean up all snapshots from prior tests so the retention trimmer cannot
# remove the newly-written snapshot during this test.
rm -f .artifacts/memory/snapshots/precompact-*.json 2>/dev/null || true
total=$((total+1))
mv .artifacts/graph/state.json .artifacts/graph/state.json.bak 2>/dev/null || true
mv .artifacts/graph/trace.jsonl .artifacts/graph/trace.jsonl.bak 2>/dev/null || true
SESS6="sess-missing-files"
SESS6_SAFE="${SESS6//[^A-Za-z0-9_.-]/_}"
run_hook "{\"session_id\":\"${SESS6}\",\"trigger\":\"auto\"}"
SNAP6=()
for f in ".artifacts/memory/snapshots/precompact-${SESS6_SAFE}-"*.json; do [[ -f "$f" ]] && SNAP6+=("$f"); done
mv .artifacts/graph/state.json.bak .artifacts/graph/state.json 2>/dev/null || true
mv .artifacts/graph/trace.jsonl.bak .artifacts/graph/trace.jsonl 2>/dev/null || true
if [[ "${#SNAP6[@]}" -ge 1 ]]; then
  pass "missing-graph-files: fail-open, snapshot still written"
else
  fail "missing-graph-files: fail-open, snapshot still written" "snap_count=${#SNAP6[@]}"
fi

# ---------------------------------------------------------------------------
# 7. Script always exits 0 (never blocks compaction).
# ---------------------------------------------------------------------------
total=$((total+1))
rc=0
printf '{}' | bash "$SCRIPT" 2>/dev/null || rc=$?
if [[ "${rc:-0}" -eq 0 ]]; then
  pass "exit-0-always: empty payload exits 0 (compaction never blocked)"
else
  fail "exit-0-always: empty payload exits 0" "rc=$rc"
fi

# ---------------------------------------------------------------------------
# 8. (v6.4.1) Active run → the snapshot reads the RUN-SCOPED graph
#    (runs/{run}/graph/state.json) and records the run id; the legacy
#    $NS/graph twin (different node ids) is NOT the source.
# ---------------------------------------------------------------------------
total=$((total+1))
if ! command -v jq &>/dev/null; then
  skip "run-scoped-graph" "jq missing"
else
  rm -f .artifacts/memory/snapshots/precompact-*.json 2>/dev/null || true
  mkdir -p .artifacts/runs/v090-dev0/graph
  printf '{"schema_version":1,"run":"v090-dev0","status": "executing"}\n' > .artifacts/runs/v090-dev0/run.json
  printf '{"ready":["run-node-R"],"in_flight":["run-node-F"]}\n' > .artifacts/runs/v090-dev0/graph/state.json
  run_hook '{"session_id":"sess-run-01","trigger":"auto"}'
  SNAP_RUN=""
  for f in .artifacts/memory/snapshots/precompact-sess-run-01-*.json; do [[ -f "$f" ]] && SNAP_RUN="$f"; done
  RUN_VAL="$(jq -r '.run // ""' "$SNAP_RUN" 2>/dev/null || true)"
  READY_VAL="$(jq -r '.cursor.ready_nodes | join(",")' "$SNAP_RUN" 2>/dev/null || true)"
  if [[ "$RUN_VAL" == "v090-dev0" && "$READY_VAL" == "run-node-R" ]]; then
    pass "run-scoped-graph: active run's graph read + run id recorded"
  else
    fail "run-scoped-graph" "run=$RUN_VAL ready=$READY_VAL snap=$SNAP_RUN"
  fi
fi

# ---------------------------------------------------------------------------
# 9. (v6.4.1) Active run WITHOUT its own graph/ files → per-file fallback to
#    the legacy $NS/graph (compat shim: mid-migration projects keep working).
# ---------------------------------------------------------------------------
total=$((total+1))
if ! command -v jq &>/dev/null; then
  skip "run-graph-fallback" "jq missing"
else
  rm -f .artifacts/runs/v090-dev0/graph/state.json 2>/dev/null || true
  run_hook '{"session_id":"sess-run-02","trigger":"auto"}'
  SNAP_FB=""
  for f in .artifacts/memory/snapshots/precompact-sess-run-02-*.json; do [[ -f "$f" ]] && SNAP_FB="$f"; done
  RUN_FB="$(jq -r '.run // ""' "$SNAP_FB" 2>/dev/null || true)"
  READY_FB="$(jq -r '.cursor.ready_nodes | join(",")' "$SNAP_FB" 2>/dev/null || true)"
  if [[ "$RUN_FB" == "v090-dev0" && "$READY_FB" == "node-B,node-C" ]]; then
    pass "run-graph-fallback: missing run graph falls back to \$NS/graph"
  else
    fail "run-graph-fallback" "run=$RUN_FB ready=$READY_FB snap=$SNAP_FB"
  fi
fi

# ---------------------------------------------------------------------------
# 10. (v6.4.1) No EXECUTING run (status closed) → legacy behavior: run field
#     empty, legacy graph read.
# ---------------------------------------------------------------------------
total=$((total+1))
if ! command -v jq &>/dev/null; then
  skip "no-active-run" "jq missing"
else
  printf '{"schema_version":1,"run":"v090-dev0","status": "closed"}\n' > .artifacts/runs/v090-dev0/run.json
  run_hook '{"session_id":"sess-run-03","trigger":"auto"}'
  SNAP_NA=""
  for f in .artifacts/memory/snapshots/precompact-sess-run-03-*.json; do [[ -f "$f" ]] && SNAP_NA="$f"; done
  RUN_NA="$(jq -r '.run // "MISSING"' "$SNAP_NA" 2>/dev/null || true)"
  if [[ "$RUN_NA" == "" ]]; then
    pass "no-active-run: closed run ignored, run field empty (legacy path)"
  else
    fail "no-active-run" "run='$RUN_NA' snap=$SNAP_NA"
  fi
fi

echo "—— $((total-fails))/$total passed ——"
exit "$fails"
