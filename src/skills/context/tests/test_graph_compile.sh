#!/usr/bin/env bash
# test_graph_compile.sh — `shctx graph compile` (v6.0.1, GH #77).
#
# Verifies the compile-down path: segment detection (seams excluded), the §V
# φ-map emission (bounded fanout, read-only annotation, briefs map), and the
# §IV faithfulness diff (soundness / completeness / determinism), including a
# negative determinism case (hand-edit → diff fails).
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
export SHCTX_QUIET=1

# Minimal repo: extract takes --sprint, compile reads state.json — no commit
# needed (keeps the test independent of commit-signing in the runner).
cd "$SHCTX_TEST_TMP"
git init -q .
mkdir -p .shepherd .claude
# is_shepherd_project gate for workflow_model_guard.sh (the guard-clean check
# below is a no-op without it — #180 review finding #12).
touch .claude/shepherd.toml

cat > plan.md <<'EOF'
## Stage Graph

```yaml
- id: MESH
  type: MESH
  agents: [{role: engineer, count: 1}]
  out_edges: [{label: on-pass, target: PLAN-GATE}]
- id: PLAN-GATE
  type: PLAN-GATE
  in_predicates: [{predecessor: MESH, edge: on-pass}]
  out_edges: [{label: approved, target: WAVE-1-IMPL}]
- id: WAVE-1-IMPL
  type: WAVE-1-IMPL
  in_predicates: [{predecessor: PLAN-GATE, edge: approved}]
  parallel_with: [WORKER-IO]
  agents: [{role: coder, count: 3}]
  out_edges: [{label: on-pass, target: WAVE-1-AUDIT}]
- id: WORKER-IO
  type: WORKER-IO
  in_predicates: [{predecessor: PLAN-GATE, edge: approved}]
  parallel_with: [WAVE-1-IMPL]
  agents: [{role: worker, count: 1}]
  out_edges: [{label: on-pass, target: WAVE-1-AUDIT}]
- id: WAVE-1-AUDIT
  type: WAVE-1-AUDIT
  in_predicates: [{predecessor: WAVE-1-IMPL, edge: on-pass}]
  agents: [{role: auditor, count: 2, concerns: [code-quality, data-flow]}]
  out_edges: [{label: on-pass, target: WAVE-1-GATE}]
- id: WAVE-1-GATE
  type: WAVE-1-GATE
  in_predicates: [{predecessor: WAVE-1-AUDIT, edge: on-pass}]
  out_edges: [{label: on-pass, target: CLOSE-SWARM}]
- id: CLOSE-SWARM
  type: CLOSE-SWARM
  in_predicates: [{predecessor: WAVE-1-GATE, edge: on-pass}]
  agents: [{role: auditor, count: 3, concerns: [code-quality, data-flow, completeness]}]
  out_edges: [{label: on-no-finding, target: CLOSE-FINALIZE}]
- id: CLOSE-FINALIZE
  type: CLOSE-FINALIZE
  in_predicates: [{predecessor: CLOSE-SWARM, edge: on-no-finding}]
```
EOF

"$SHCTX" plan extract plan.md --sprint=v6.0.1-dev.0 >/dev/null

# --- segment detection: exactly two compilable segments; seams excluded -----
list=$("$SHCTX" graph compile --list)
assert_contains "list.close" "$list" "segment CLOSE-SWARM: CLOSE-SWARM"
assert_contains "list.wave"  "$list" "WAVE-1-IMPL, WORKER-IO"
if grep -qE "segment (PLAN-GATE|WAVE-1-GATE|CLOSE-FINALIZE|MESH):" <<<"$list"; then
  echo "FAIL: a seam node was emitted as a compilable segment" >&2; exit 1
fi

# --- default compile picks CLOSE-SWARM (doctrine §IX) + §IV diff is clean ----
out=$("$SHCTX" graph compile --verify)
assert_contains "default.segment"  "$out" "compiled segment 'CLOSE-SWARM'"
assert_contains "default.sound"    "$out" "✓ soundness"
assert_contains "default.complete" "$out" "✓ completeness"
assert_contains "default.determ"   "$out" "✓ determinism"
assert_contains "default.modelpin" "$out" "✓ model_pin"

script=".shepherd/graph/compiled/CLOSE-SWARM.workflow.js"
assert_file "$script"
body=$(cat "$script")
assert_eq       "close.auditor.count" "$(grep -c 'agentType: "shepherd:auditor"' "$script")" "3"
assert_contains "close.readonly"      "$body" "read-only: allowlist-enforced"
assert_contains "close.bounded"       "$body" "MAX_CONCURRENT = 16"
assert_contains "close.briefs"        "$body" 'briefs["CLOSE-SWARM:code-quality"]'

# --- #180 model-pin: real agent(prompt, opts) shape + explicit pins ----------
# The old broken shape passed the whole spawn object positionally as `prompt`
# and carried no model/agentType — inheriting the main-loop model. Assert the
# call shape is fixed and every spawn is pinned.
assert_contains "pin.callshape"  "$body" "() => agent(briefs["
if grep -qE '=>\s*agent\(\s*s\s*\)|agent\(s\)' "$script"; then
  echo "FAIL: legacy opts-less agent(s) call shape still emitted (#180)" >&2; exit 1
fi
assert_eq "pin.model.count"   "$(grep -c 'model: "sonnet"' "$script")" "3"   # 3 auditors, all sonnet
assert_eq "pin.agenttype.cnt" "$(grep -c 'agentType: "shepherd:auditor"' "$script")" "3"
# every spawn object carries BOTH agentType and model (no unpinned spawn)
nat=$(grep -c 'agentType: "shepherd:' "$script"); nmp=$(grep -c 'model: "' "$script")
if [[ "$nat" != "$nmp" ]]; then
  echo "FAIL: $nat agentType pins but $nmp model pins — an unpinned spawn (#180)" >&2; exit 1
fi
# "would it pass workflow_model_guard.sh?" — the guard never runs on this path
# (compiled scripts run via node, not the Workflow tool) but it is the right
# correctness bar (#180). Feed the compiled script as a Workflow payload.
guard="$SHCTX_SKILL_ROOT/../../hooks/scripts/workflow_model_guard.sh"
if [[ -f "$guard" ]]; then
  gpayload=$(python3 -c 'import json,sys;print(json.dumps({"session_id":"s","tool_name":"Workflow","tool_input":{"script":open(sys.argv[1]).read()}}))' "$script")
  gout=$(printf '%s' "$gpayload" | bash "$guard" 2>/dev/null || true)
  if printf '%s' "$gout" | grep -q '"permissionDecision"[[:space:]]*:[[:space:]]*"deny"'; then
    echo "FAIL: compiled script would be DENIED by workflow_model_guard.sh (unpinned) — #180" >&2
    printf '%s\n' "$gout" >&2; exit 1
  fi
fi
# Seam content must never leak into the EXECUTABLE body (engineer is root-tier;
# gates/finalize are conductor-inline). Doc comments may mention them; spawns
# and result-keys may not.
if grep -qE 'agentType: "shepherd:engineer"|results\["(CLOSE-FINALIZE|WAVE-1-GATE|MESH|PLAN-GATE)"\]' "$script"; then
  echo "FAIL: seam content leaked into compiled CLOSE-SWARM script body" >&2; exit 1
fi

# --- wave segment: 2 batches (coder×3 + worker || then auditor×2) ------------
wave=$("$SHCTX" graph compile --segment=WAVE-1-IMPL --verify)
assert_contains "wave.sound"    "$wave" "✓ soundness"
assert_contains "wave.complete" "$wave" "✓ completeness"
wscript=".shepherd/graph/compiled/WAVE-1-IMPL.workflow.js"
assert_file "$wscript"
wbody=$(cat "$wscript")
assert_eq "wave.coder"  "$(grep -c 'agentType: "shepherd:coder"'  "$wscript")" "3"
assert_eq "wave.worker" "$(grep -c 'agentType: "shepherd:worker"' "$wscript")" "1"
assert_eq "wave.audit"  "$(grep -c 'agentType: "shepherd:auditor"' "$wscript")" "2"
# two batches: IMPL/WORKER clique first, AUDIT second (sequential edge)
assert_eq "wave.batches" "$(grep -c 'await fanout(' "$wscript")" "2"

# --- negative §IV: hand-edit the script → determinism diff must FAIL ---------
printf '\n// tampered\n' >> "$script"
if "$SHCTX" graph compile --segment=CLOSE-SWARM --verify >/dev/null 2>&1; then
  echo "FAIL: faithfulness diff passed on a hand-edited (stale) script" >&2; exit 1
fi
# and it self-heals: the recompile rewrote the canonical script, so a re-verify passes
"$SHCTX" graph compile --segment=CLOSE-SWARM --verify >/dev/null \
  || { echo "FAIL: re-verify after recompile did not pass" >&2; exit 1; }

# --- Lane E parity (#78): cross-lane dependency coordinated by in-script -----
# --- await ordering, with NO pause/heartbeat machinery in the path. ---------
# (skills/harness/references/workflow-templates.md — the proven replacement Lane F depends on)
if grep -qiE "PAUSE|heartbeat|PAUSE-FOR-DEPENDENCY" "$wscript"; then
  echo "FAIL: pause/heartbeat machinery leaked into the compiled segment (#78)" >&2; exit 1
fi
# The WAVE-1-IMPL ‖ WORKER-IO -> WAVE-1-AUDIT dependency is realized purely by
# batch ordering: the coder/worker batch precedes the auditor batch.
coder_ln=$(grep -n 'shepherd:coder'   "$wscript" | head -1 | cut -d: -f1)
audit_ln=$(grep -n 'shepherd:auditor' "$wscript" | head -1 | cut -d: -f1)
if [[ -z "$coder_ln" || -z "$audit_ln" || "$coder_ln" -ge "$audit_ln" ]]; then
  echo "FAIL: cross-lane dependency not realized by in-script await ordering (#78)" >&2; exit 1
fi

echo "test_graph_compile: OK"
