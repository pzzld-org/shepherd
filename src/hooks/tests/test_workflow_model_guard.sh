#!/usr/bin/env bash
# hooks/tests/test_workflow_model_guard.sh — tests for workflow_model_guard.sh (#178, tightened #255)
#
# Covers the PreToolUse(Workflow) dispatch-model-pin guard. #255 replaced the
# original `model: OR agentType:` check with a `model: AND agentType:` check
# (both required, independently) — the #255-specific regression coverage
# (agentType-alone no longer passing, off-flock values, unverifiable values,
# masking-after-value-reading, multi-code reporting) lives in the dedicated
# hooks/tests/test_workflow_off_flock.sh; this file keeps the #178 baseline
# shapes updated to the new law:
#   1.  bare `agent(prompt)` (no opts arg)             → DENY, both codes (no model AND no agentType)
#   2.  `agent(prompt, {model: "sonnet"})`  alone       → DENY DISPATCH-MISSING-SUBAGENT-TYPE (#255: single-key no longer enough)
#   3.  `agent(prompt, {agentType: "shepherd:coder"})`  → DENY DISPATCH-MODEL-UNPINNED (#255: single-key no longer enough)
#   3b. BOTH keys present, agentType in-flock            → PASS (the only shape that still passes)
#   4.  opts object present, neither key                → DENY, both codes
#   5.  prompt text merely MENTIONS "model:" in prose    → DENY (no false pass)
#   6.  a nested schema field named "model"              → DENY (no false pass; not top-level)
#   7.  opts is a non-literal variable                   → DENY ("cannot verify statically")
#   8.  multiple calls, only one non-compliant            → DENY names only the violator
#   9.  `subagent(` must not match (word-boundary check)  → PASS
#   10. `// shepherd:model-pin-override` marker present   → additionalContext, never deny
#   11. non-Workflow tool (Agent)                         → PASS (guard ignores it)
#   12. tool_input.scriptPath read from disk               → DENY (same as inline script)
#   13. tool_input.name only (no visible script)            → PASS (fail-open, logged)
#   14. [hooks].workflow_model_guard = warn                → additionalContext, never deny
#   15. [hooks].workflow_model_guard = off                 → PASS, no scan at all
#   16. no .claude/shepherd.toml                            → PASS (not a shepherd project)
#   17. template-literal prompt + multi-line opts object    → DENY/PASS correctly (multi-line scan)

set -uo pipefail
cd "$(dirname "$0")"
HOOKS_DIR="$(cd .. && pwd)/scripts"
SCRIPT="$HOOKS_DIR/workflow_model_guard.sh"

fails=0
total=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s — %s\n' "$1" "$2"; fails=$((fails+1)); }

is_deny()    { printf '%s' "$1" | grep -q '"permissionDecision"[[:space:]]*:[[:space:]]*"deny"'; }
is_context() { printf '%s' "$1" | grep -q '"additionalContext"'; }
has_code()   { printf '%s' "$1" | grep -q "WORKFLOW-MODEL-PIN-MISSING"; }

# Payload builder: JSON-encodes the script text via python3 (keeps escaping honest).
P() {  # P <script-text> [cwd]
  python3 -c '
import json, sys
script = sys.argv[1]
cwd = sys.argv[2] if len(sys.argv) > 2 else "/tmp"
print(json.dumps({"session_id": "s1", "tool_name": "Workflow", "cwd": cwd,
                   "tool_input": {"script": script}}))
' "$1" "${2:-/tmp}"
}

run_hook() {  # run_hook <payload>
  printf '%s' "$1" | bash "$SCRIPT" 2>/dev/null
  return 0
}

# ---------------------------------------------------------------------------
# 0. No .claude/shepherd.toml → PASS (not a shepherd project).
# ---------------------------------------------------------------------------
total=$((total+1))
tmp_bare=$(mktemp -d -t shep-wmg-bare.XXXXXX)
(
  cd "$tmp_bare"
  git init -q . && git config user.email t@t && git config user.name t
  git -c commit.gpgsign=false commit -q --allow-empty -m init
  out=$(run_hook "$(P 'const r = await agent("x")' "$tmp_bare")")
  if ! is_deny "$out"; then
    printf '  PASS  no-shepherd-toml: pass (not a shepherd project)\n'
  else
    printf '  FAIL  no-shepherd-toml: pass — got deny: %s\n' "${out:0:80}"
    exit 1
  fi
) || fails=$((fails+1))
rm -rf "$tmp_bare"

# ---------------------------------------------------------------------------
# Shared ephemeral shepherd-flagged repo.
# ---------------------------------------------------------------------------
tmp=$(mktemp -d -t shep-wmg-test.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q .
git config user.email t@t
git config user.name t
git -c commit.gpgsign=false commit -q --allow-empty -m init
mkdir -p .claude
touch .claude/shepherd.toml

echo "== workflow_model_guard.sh — bare / non-compliant calls DENY (block default) =="

total=$((total+1))
out=$(run_hook "$(P 'export const meta = {name:"x",description:"y"}
const r = await agent("do the thing")' "$tmp")")
if is_deny "$out" && has_code "$out" && printf '%s' "$out" | grep -q 'no opts argument'; then
  pass "1. bare agent(prompt): DENY + WORKFLOW-MODEL-PIN-MISSING"
else
  fail "1. bare agent(prompt): DENY" "out=${out:0:160}"
fi

total=$((total+1))
out=$(run_hook "$(P 'const r = await agent("do it", {schema: FOO, label: "x"})' "$tmp")")
if is_deny "$out" \
   && printf '%s' "$out" | grep -q 'DISPATCH-MODEL-UNPINNED' \
   && printf '%s' "$out" | grep -q 'DISPATCH-MISSING-SUBAGENT-TYPE'; then
  pass "4. opts present, missing both keys: DENY, both codes"
else
  fail "4. opts present, missing both keys: DENY, both codes" "out=${out:0:200}"
fi

echo "== workflow_model_guard.sh — #255: a single key is no longer enough =="

total=$((total+1))
out=$(run_hook "$(P 'const r = await agent("do the thing", {model: "sonnet"})' "$tmp")")
if is_deny "$out" \
   && printf '%s' "$out" | grep -q 'DISPATCH-MISSING-SUBAGENT-TYPE' \
   && ! printf '%s' "$out" | grep -q 'DISPATCH-MODEL-UNPINNED'; then
  pass "2. model: \"sonnet\" ALONE: DENY DISPATCH-MISSING-SUBAGENT-TYPE (#255: no longer enough)"
else
  fail "2. model: \"sonnet\" ALONE: DENY DISPATCH-MISSING-SUBAGENT-TYPE" "out=${out:0:200}"
fi

total=$((total+1))
out=$(run_hook "$(P 'const r = await agent("do the thing", {agentType: "shepherd:coder"})' "$tmp")")
if is_deny "$out" \
   && printf '%s' "$out" | grep -q 'DISPATCH-MODEL-UNPINNED' \
   && ! printf '%s' "$out" | grep -q 'DISPATCH-MISSING-SUBAGENT-TYPE'; then
  pass "3. agentType: \"shepherd:coder\" ALONE: DENY DISPATCH-MODEL-UNPINNED (#255 regression — the exact gap #178's OR-check let through)"
else
  fail "3. agentType: \"shepherd:coder\" ALONE: DENY DISPATCH-MODEL-UNPINNED" "out=${out:0:200}"
fi

echo "== workflow_model_guard.sh — BOTH keys present, agentType in-flock: PASS =="

total=$((total+1))
out=$(run_hook "$(P 'const r = await agent("do the thing", {agentType: "shepherd:coder", model: "sonnet"})' "$tmp")")
if ! is_deny "$out" && ! is_context "$out"; then
  pass "3b. agentType + model BOTH pinned: PASS (silent) — the only shape that still passes"
else
  fail "3b. agentType + model BOTH pinned: PASS (silent)" "unexpected output: ${out:0:200}"
fi

echo "== workflow_model_guard.sh — string-content-blind (no false positives) =="

total=$((total+1))
out=$(run_hook "$(P 'const r = await agent("please pick a pricing model: sonnet is cheaper", {schema: FOO})' "$tmp")")
if is_deny "$out"; then
  pass "5. \"model:\" mentioned in PROSE only: still DENY (no false pass from string content)"
else
  fail "5. \"model:\" mentioned in PROSE only: still DENY" "unexpectedly passed: ${out:0:160}"
fi

total=$((total+1))
out=$(run_hook "$(P 'const r = await agent("do it", {schema: {type:"object", properties:{model:{type:"string"}}}})' "$tmp")")
if is_deny "$out"; then
  pass "6. nested schema field named \"model\": still DENY (not top-level)"
else
  fail "6. nested schema field named \"model\": still DENY" "unexpectedly passed: ${out:0:160}"
fi

echo "== workflow_model_guard.sh — non-literal opts is unverifiable, not benefit-of-the-doubt =="

total=$((total+1))
out=$(run_hook "$(P 'const opts = {model: "sonnet"}
const r = await agent("do it", opts)' "$tmp")")
if is_deny "$out" && printf '%s' "$out" | grep -q 'cannot verify statically'; then
  pass "7. non-literal opts variable: DENY (unverifiable)"
else
  fail "7. non-literal opts variable: DENY (unverifiable)" "out=${out:0:160}"
fi

echo "== workflow_model_guard.sh — multi-call scripts flag only the violator =="

total=$((total+1))
out=$(run_hook "$(P 'const a = await agent("compliant", {model: "sonnet", agentType: "shepherd:coder"})
const b = await agent("also compliant", {agentType: "shepherd:auditor", model: "sonnet"})
const c = await agent("the culprit", {schema: X})' "$tmp")")
if is_deny "$out" \
   && printf '%s' "$out" | grep -q 'the culprit' \
   && ! printf '%s' "$out" | grep -q 'also compliant' \
   && ! printf '%s' "$out" | grep -q '"compliant"'; then
  pass "8. multi-call script: DENY names only the one violator"
else
  fail "8. multi-call script: DENY names only the one violator" "out=${out:0:200}"
fi

echo "== workflow_model_guard.sh — word-boundary: subagent( must not match agent( =="

total=$((total+1))
out=$(run_hook "$(P 'const x = subagent("not a real dispatch call")' "$tmp")")
if ! is_deny "$out"; then
  pass "9. subagent(...) not mistaken for agent(...): PASS"
else
  fail "9. subagent(...) not mistaken for agent(...): PASS" "out=${out:0:160}"
fi

echo "== workflow_model_guard.sh — operator override marker =="

total=$((total+1))
out=$(run_hook "$(P '// shepherd:model-pin-override — ack, verified manually
const r = await agent("do the thing")' "$tmp")")
if ! is_deny "$out" && is_context "$out" && printf '%s' "$out" | grep -q 'override marker present'; then
  pass "10. override marker: additionalContext, never a deny"
else
  fail "10. override marker: additionalContext, never a deny" "out=${out:0:200}"
fi

echo "== workflow_model_guard.sh — tool/source-shape fast-paths =="

total=$((total+1))
out=$(printf '{"session_id":"s1","tool_name":"Agent","tool_input":{"subagent_type":"shepherd:coder"}}' | bash "$SCRIPT" 2>/dev/null)
if ! is_deny "$out"; then
  pass "11. non-Workflow tool (Agent): PASS (guard ignores it)"
else
  fail "11. non-Workflow tool (Agent): PASS" "out=${out:0:160}"
fi

total=$((total+1))
mkdir -p "$tmp/.artifacts"
cat > "$tmp/.artifacts/wmg-test.workflow.js" <<'JS'
export const meta = {name:"x",description:"y"}
const r = await agent("do the thing")
JS
out=$(printf '{"session_id":"s1","tool_name":"Workflow","cwd":"%s","tool_input":{"scriptPath":".artifacts/wmg-test.workflow.js"}}' "$tmp" | bash "$SCRIPT" 2>/dev/null)
if is_deny "$out" && has_code "$out"; then
  pass "12. tool_input.scriptPath read from disk: DENY (same scan as inline script)"
else
  fail "12. tool_input.scriptPath read from disk: DENY" "out=${out:0:160}"
fi
rm -f "$tmp/.artifacts/wmg-test.workflow.js"

total=$((total+1))
out=$(printf '{"session_id":"s1","tool_name":"Workflow","cwd":"%s","tool_input":{"name":"a-saved-workflow"}}' "$tmp" | bash "$SCRIPT" 2>/dev/null)
if ! is_deny "$out"; then
  pass "13. tool_input.name only (no visible script): PASS (fail-open)"
else
  fail "13. tool_input.name only (no visible script): PASS (fail-open)" "out=${out:0:160}"
fi

echo "== workflow_model_guard.sh — [hooks].workflow_model_guard mode =="

total=$((total+1))
printf '[hooks]\nworkflow_model_guard = "warn"\n' > "$tmp/.claude/shepherd.toml"
out=$(run_hook "$(P 'const r = await agent("do it")' "$tmp")")
if ! is_deny "$out" && is_context "$out"; then
  pass "14. warn mode: additionalContext, never deny"
else
  fail "14. warn mode: additionalContext, never deny" "out=${out:0:160}"
fi

total=$((total+1))
printf '[hooks]\nworkflow_model_guard = "off"\n' > "$tmp/.claude/shepherd.toml"
out=$(run_hook "$(P 'const r = await agent("do it")' "$tmp")")
if ! is_deny "$out" && ! is_context "$out"; then
  pass "15. off mode: silent pass, no scan"
else
  fail "15. off mode: silent pass, no scan" "out=${out:0:160}"
fi
: > "$tmp/.claude/shepherd.toml"

echo "== workflow_model_guard.sh — multi-line template-literal prompt + opts =="

total=$((total+1))
out=$(run_hook "$(P 'const results = await pipeline(
  DIMENSIONS,
  d => agent(d.prompt, {
    label: `review:${d.key}`,
    phase: "Review",
    schema: FINDINGS_SCHEMA,
  }),
  review => parallel(review.findings.map(f => () =>
    agent(`Adversarially verify: ${f.title}`, {label: `verify:${f.file}`, phase: "Verify", model: "sonnet", agentType: "shepherd:auditor"})
  ))
)' "$tmp")")
if is_deny "$out" \
   && printf '%s' "$out" | grep -q 'DISPATCH-MODEL-UNPINNED' \
   && printf '%s' "$out" | grep -q 'DISPATCH-MISSING-SUBAGENT-TYPE' \
   && printf '%s' "$out" | grep -q 'review:' \
   && ! printf '%s' "$out" | grep -q 'verify:'; then
  pass "16. multi-line/template-literal calls: only the unpinned one flagged"
else
  fail "16. multi-line/template-literal calls: only the unpinned one flagged" "out=${out:0:250}"
fi

echo "—— $((total-fails))/$total passed ——"
exit "$fails"
