#!/usr/bin/env bash
# hooks/tests/focus_rehydrate_test.sh — tests for focus_rehydrate.sh
#
# Covers the SessionStart/UserPromptSubmit rehydration hook (v6.0.9, Item A2):
#   1. No shepherd.toml → exit 0, no output.
#   2. Config [focus] rehydrate = off → exit 0, no output.
#   3. No pending flag for this session → exit 0, no output (silent pass).
#   4. Pending flag present + snapshot → emits additionalContext with digest.
#   5. Digest contains: sprint, active_node, ready_nodes, obligations.
#   6. Flag is drained after first fire (second call is silent).
#   7. Pending flag present but no snapshot file → drains flag, silent pass.

set -eu -o pipefail
cd "$(dirname "$0")"
HOOKS_DIR="$(cd .. && pwd)/scripts"
SCRIPT="$HOOKS_DIR/focus_rehydrate.sh"

fails=0
total=0
pass()  { printf '  PASS  %s\n' "$1"; }
fail()  { printf '  FAIL  %s — %s\n' "$1" "$2"; fails=$((fails+1)); }
skip()  { printf '  SKIP  %s — %s\n' "$1" "$2"; }

run_hook() {
  local payload="$1"
  printf '%s' "$payload" | bash "$SCRIPT" 2>/dev/null
  return 0
}

is_context() { printf '%s' "$1" | grep -q '"additionalContext"'; }

# ---------------------------------------------------------------------------
# 1. No shepherd.toml → exit 0, no output.
# ---------------------------------------------------------------------------
total=$((total+1))
tmp_bare=$(mktemp -d -t shep-frh-bare.XXXXXX)
(
  cd "$tmp_bare"
  git init -q . && git config user.email t@t && git config user.name t
  git -c commit.gpgsign=false commit -q --allow-empty -m init
  rc=0
  out=$(printf '{"session_id":"s1","hook_event_name":"SessionStart","source":"compact"}' | bash "$SCRIPT" 2>/dev/null) || rc=$?
  if [[ "${rc:-0}" -eq 0 ]] && ! printf '%s' "$out" | grep -q '"additionalContext"'; then
    printf '  PASS  no-shepherd-toml: exit 0, no context\n'
  else
    printf '  FAIL  no-shepherd-toml: exit 0, no context — rc=%d out=%s\n' "${rc:-0}" "$out"
    exit 1
  fi
) || fails=$((fails+1))
rm -rf "$tmp_bare"

# ---------------------------------------------------------------------------
# Shared ephemeral shepherd-flagged repo for remaining tests.
# ---------------------------------------------------------------------------
tmp=$(mktemp -d -t shep-frh-test.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q .
git config user.email t@t
git config user.name t
git -c commit.gpgsign=false commit -q --allow-empty -m init
git checkout -q -b v0.9.0-dev.0 2>/dev/null || true
mkdir -p .claude .artifacts/cache/snapshots .artifacts/tmp
touch .claude/shepherd.toml

SESSION="sess-rhy-01"
SESSION_SAFE="${SESSION//[^A-Za-z0-9_.-]/_}"
FLAG_FILE=".artifacts/tmp/rehydrate-pending.${SESSION_SAFE}"
SNAP_FILE=".artifacts/cache/snapshots/precompact-${SESSION_SAFE}-$(date +%s).json"

PAYLOAD_SS="{\"session_id\":\"${SESSION}\",\"hook_event_name\":\"SessionStart\",\"source\":\"compact\"}"
PAYLOAD_UPS="{\"session_id\":\"${SESSION}\",\"hook_event_name\":\"UserPromptSubmit\",\"prompt\":\"continue\"}"

# Write a realistic snapshot file.
write_snapshot() {
  cat > "$SNAP_FILE" <<'JSON'
{
  "session_id": "sess-rhy-01",
  "trigger": "auto",
  "sprint": "v0.9.0-dev.0",
  "captured_at": "2026-06-09T12:00:00Z",
  "cursor": {
    "ready_nodes": ["node-B", "node-C"],
    "in_flight_nodes": ["node-A"]
  },
  "trace_tail": "{\"ts\":1,\"event\":\"wave-start\"}",
  "lock": "{\"session_id\":\"sess-rhy-01\",\"sprint\":\"v0.9.0-dev.0\"}",
  "focus": {
    "sprint": "v0.9.0-dev.0",
    "objective": "Implement v6.0.9 focus loop and compaction resilience",
    "active_node": "WAVE-1",
    "ready_set": "node-B,node-C",
    "obligations": "{\"open_lanes\":[\"lane-2\"],\"undrained_mail\":1}",
    "invariants": "{\"rules\":[\"no teammate git integration\"]}",
    "updated_at": 1234567890
  }
}
JSON
}

# ---------------------------------------------------------------------------
# 2. Config [focus] rehydrate = off → no output.
# ---------------------------------------------------------------------------
total=$((total+1))
printf '[focus]\nrehydrate = "off"\n' > .claude/shepherd.toml
touch "$FLAG_FILE"
write_snapshot
out=$(run_hook "$PAYLOAD_SS")
rm -f "$FLAG_FILE" 2>/dev/null || true
if ! is_context "$out"; then
  pass "config-off: no additionalContext emitted"
else
  fail "config-off: no additionalContext emitted" "out=${out:0:80}"
fi
printf '' > .claude/shepherd.toml

# ---------------------------------------------------------------------------
# 3. No pending flag → silent pass, no context.
# ---------------------------------------------------------------------------
total=$((total+1))
rm -f "$FLAG_FILE" 2>/dev/null || true
write_snapshot
out=$(run_hook "$PAYLOAD_SS")
if ! is_context "$out"; then
  pass "no-flag: silent pass, no additionalContext"
else
  fail "no-flag: silent pass, no additionalContext" "out=${out:0:80}"
fi

# ---------------------------------------------------------------------------
# 4. Pending flag present + snapshot → emits additionalContext.
# ---------------------------------------------------------------------------
total=$((total+1))
touch "$FLAG_FILE"
write_snapshot
out=$(run_hook "$PAYLOAD_SS")
if is_context "$out"; then
  pass "flag+snapshot: additionalContext emitted"
else
  fail "flag+snapshot: additionalContext emitted" "out=${out:0:200}"
fi

# ---------------------------------------------------------------------------
# 5. Digest contains sprint, active_node, ready_nodes.
# ---------------------------------------------------------------------------
total=$((total+1))
# Re-set flag (drained by test 4).
touch "$FLAG_FILE"
write_snapshot
out=$(run_hook "$PAYLOAD_SS")
CONTEXT_VAL=""
if command -v jq &>/dev/null; then
  CONTEXT_VAL="$(printf '%s' "$out" | jq -r '.additionalContext // ""' 2>/dev/null || true)"
else
  # Crude extraction without jq.
  CONTEXT_VAL="$(printf '%s' "$out" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("additionalContext",""))' 2>/dev/null || true)"
fi
if printf '%s' "$CONTEXT_VAL" | grep -q 'v0.9.0-dev.0' \
   && printf '%s' "$CONTEXT_VAL" | grep -q 'WAVE-1' \
   && printf '%s' "$CONTEXT_VAL" | grep -q 'node-B'; then
  pass "digest-fields: sprint, active_node, ready_nodes present in digest"
else
  fail "digest-fields: sprint, active_node, ready_nodes present" "context=${CONTEXT_VAL:0:200}"
fi

# ---------------------------------------------------------------------------
# 6. Flag is drained after first fire (second call is silent).
# ---------------------------------------------------------------------------
total=$((total+1))
touch "$FLAG_FILE"
write_snapshot
run_hook "$PAYLOAD_SS" > /dev/null  # first fire → drains flag
out2=$(run_hook "$PAYLOAD_SS")      # second fire → flag gone → no context
if ! is_context "$out2"; then
  pass "drain-once: second call is silent (flag drained)"
else
  fail "drain-once: second call is silent" "out2=${out2:0:80}"
fi

# ---------------------------------------------------------------------------
# 7. Pending flag present but no snapshot file → drains flag, silent pass.
# ---------------------------------------------------------------------------
total=$((total+1))
touch "$FLAG_FILE"
rm -f "$SNAP_FILE" 2>/dev/null || true
rm -f .artifacts/cache/snapshots/precompact-"${SESSION_SAFE}"-*.json 2>/dev/null || true
out=$(run_hook "$PAYLOAD_UPS")
FLAG_AFTER=0; [[ -f "$FLAG_FILE" ]] && FLAG_AFTER=1
if ! is_context "$out" && [[ "$FLAG_AFTER" -eq 0 ]]; then
  pass "flag-no-snapshot: drains flag silently, no context"
else
  fail "flag-no-snapshot: drains flag silently, no context" "out=${out:0:80} flag_after=$FLAG_AFTER"
fi

# ---------------------------------------------------------------------------
# 8. (v6.4.1) A snapshot carrying a `run` field surfaces the run-scoped graph
#    home in the digest; a run-less (pre-v6.4.1) snapshot stays run-silent —
#    the compat shim never invents a run line.
# ---------------------------------------------------------------------------
total=$((total+1))
touch "$FLAG_FILE"
write_snapshot
# Inject the run field the v6.4.1 precompact_snapshot.sh records.
if command -v jq &>/dev/null; then
  jq '. + {run: "v090-dev0"}' "$SNAP_FILE" > "$SNAP_FILE.tmp" && mv "$SNAP_FILE.tmp" "$SNAP_FILE"
else
  python3 - "$SNAP_FILE" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p)); d["run"] = "v090-dev0"
json.dump(d, open(p, "w"))
PY
fi
out=$(run_hook "$PAYLOAD_SS")
if printf '%s' "$out" | grep -q 'runs/v090-dev0/graph/'; then
  pass "run-field: digest surfaces runs/{run}/graph/ as the state home"
else
  fail "run-field: digest surfaces run-scoped graph home" "out=${out:0:250}"
fi

total=$((total+1))
touch "$FLAG_FILE"
write_snapshot   # plain snapshot, NO run field
out=$(run_hook "$PAYLOAD_SS")
if is_context "$out" && ! printf '%s' "$out" | grep -q 'Run: '; then
  pass "no-run-field: legacy snapshot digest carries no Run line (compat)"
else
  fail "no-run-field: legacy snapshot run-silent" "out=${out:0:250}"
fi

# ---------------------------------------------------------------------------
# (v6.4.4) A stale snapshot in a leftover memory/snapshots/ must NEVER shadow a
# fresh one in cache/snapshots/. The pre-v6.4.4 reader picked the first
# directory that existed, so a leftover memory/ pinned rehydration to
# pre-upgrade state permanently.
# ---------------------------------------------------------------------------
total=$((total+1))
mkdir -p .artifacts/memory/snapshots
STALE=".artifacts/memory/snapshots/precompact-${SESSION_SAFE}-1000000000.json"
FRESH=".artifacts/cache/snapshots/precompact-${SESSION_SAFE}-2000000000.json"
rm -f .artifacts/cache/snapshots/precompact-*.json 2>/dev/null || true
SNAP_FILE="$STALE"; write_snapshot
sed -i.bak 's/"v0\.9\.0-dev\.0"/"v0.1.0-STALE"/' "$STALE" && rm -f "$STALE.bak"
SNAP_FILE="$FRESH"; write_snapshot
touch "$FLAG_FILE"
out=$(run_hook "$PAYLOAD_SS")
if printf '%s' "$out" | grep -q 'v0.9.0-dev.0' && ! printf '%s' "$out" | grep -q 'STALE'; then
  pass "no-stale-shadow: fresh cache/ snapshot wins over a leftover memory/ one"
else
  fail "no-stale-shadow: fresh cache/ snapshot wins" "out=${out:0:250}"
fi
rm -rf .artifacts/memory 2>/dev/null || true

echo "—— $((total-fails))/$total passed ——"
exit "$fails"
