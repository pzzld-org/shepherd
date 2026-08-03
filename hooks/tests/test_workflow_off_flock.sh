#!/usr/bin/env bash
# hooks/tests/test_workflow_off_flock.sh — #255 enforcement-half regression suite.
#
# workflow_model_guard.sh (#178) originally accepted `model: OR agentType:` —
# satisfying EITHER passed. #255's field incident is exactly the gap that
# left open: a script whose agent() calls carried `agentType:
# "shepherd:<role>"` alone scanned clean while every fanned-out agent still
# inherited the main-loop model (opus, xhigh) instead of the mandated
# sonnet. This file is the dedicated regression suite for the fix — BOTH
# `model:` and `agentType:` are now required, independently, and
# `agentType`'s VALUE is checked against the `shepherd:` flock prefix when
# it is statically verifiable. hooks/tests/test_workflow_model_guard.sh
# keeps the #178 baseline shapes (masking, word-boundary, overrides, config
# modes, scriptPath/name source handling); this file covers only what #255
# changed:
#   1. agentType + model BOTH present, agentType in-flock        → PASS (clean)
#   2. agentType present, model MISSING                          → DISPATCH-MODEL-UNPINNED
#   3. agentType MISSING, model present                          → DISPATCH-MISSING-SUBAGENT-TYPE
#   4. agentType: "shepherd:coder" ALONE (no model)               → DISPATCH-MODEL-UNPINNED
#      — the exact #255 regression: the old OR-check let this pass clean.
#   5. agentType: "general-purpose" + model present               → WORKFLOW-OFF-FLOCK
#   6. agentType: <computed/variable> + model present             → flagged unverifiable,
#      NEVER a false WORKFLOW-OFF-FLOCK (cannot guess a value we can't read)
#   7. prompt TEMPLATE LITERAL containing the literal text
#      `agentType: "general-purpose"` as prose, real opts clean   → PASS (masking still
#      holds after value-reading was added for the flock-prefix check)
#   8. `agentType` nested inside `opts.schema` (not top-level)     → still counts as
#      MISSING at the top level (DISPATCH-MISSING-SUBAGENT-TYPE, not a false pass)
#   9. `// shepherd:model-pin-override` still suppresses the deny  → additionalContext
#  10. a single call missing model AND with an off-flock agentType → BOTH codes reported

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
has()        { printf '%s' "$1" | grep -q -- "$2"; }

# Deterministic extraction of the guard's own "codes seen: X, Y." summary
# from its deny/context message — NOT a substring grep against the whole
# message, because the message's static help text legitimately mentions
# WORKFLOW-OFF-FLOCK and WORKFLOW-AGENTTYPE-UNVERIFIABLE by name in every
# deny (explaining what they mean), which would make a blanket `has "$out"
# 'WORKFLOW-OFF-FLOCK'` pass even when that code never fired. This is the
# same parse workflow_model_guard.sh itself uses to build the summary, run
# in reverse, so the test verifies the guard's REPORTED codes, not prose
# that happens to share a substring.
codes_seen() {  # codes_seen <hook-json-output>
  printf '%s' "$1" | python3 -c '
import json, re, sys
try:
    data = json.load(sys.stdin)
except Exception:
    print("")
    raise SystemExit(0)
msg = data.get("message") or data.get("additionalContext") or ""
m = re.search(r"codes seen: ([^.\n]*)", msg)
print(m.group(1) if m else "")
' 2>/dev/null
}

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

tmp=$(mktemp -d -t shep-wof-test.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q .
git config user.email t@t
git config user.name t
git -c commit.gpgsign=false commit -q --allow-empty -m init
mkdir -p .claude
touch .claude/shepherd.toml

echo "== workflow_off_flock — clean shape =="

total=$((total+1))
out=$(run_hook "$(P 'const r = await agent("do it", {agentType: "shepherd:coder", model: "sonnet"})' "$tmp")")
if ! is_deny "$out" && ! is_context "$out"; then
  pass "1. agentType: shepherd:coder + model: sonnet: PASS (silent)"
else
  fail "1. agentType: shepherd:coder + model: sonnet: PASS (silent)" "unexpected output: ${out:0:200}"
fi

echo "== workflow_off_flock — either law missing, independently =="

total=$((total+1))
out=$(run_hook "$(P 'const r = await agent("do it", {model: "sonnet"})' "$tmp")")
if is_deny "$out" && [[ "$(codes_seen "$out")" == "DISPATCH-MISSING-SUBAGENT-TYPE" ]]; then
  pass "2. agentType MISSING (model present): DENY DISPATCH-MISSING-SUBAGENT-TYPE only"
else
  fail "2. agentType MISSING (model present): DENY DISPATCH-MISSING-SUBAGENT-TYPE only" "codes=$(codes_seen "$out") out=${out:0:200}"
fi

total=$((total+1))
out=$(run_hook "$(P 'const r = await agent("do it", {agentType: "shepherd:coder"})' "$tmp")")
if is_deny "$out" && [[ "$(codes_seen "$out")" == "DISPATCH-MODEL-UNPINNED" ]]; then
  pass "3. model MISSING (agentType present): DENY DISPATCH-MODEL-UNPINNED only"
else
  fail "3. model MISSING (agentType present): DENY DISPATCH-MODEL-UNPINNED only" "codes=$(codes_seen "$out") out=${out:0:200}"
fi

echo "== workflow_off_flock — #255 NAMED REGRESSION: agentType alone is no longer enough =="
echo "   (this is the exact shape the old model:-OR-agentType: check let through clean)"

total=$((total+1))
out=$(run_hook "$(P 'const r = await agent("run the deep audit", {agentType: "shepherd:auditor"})' "$tmp")")
if is_deny "$out" && [[ "$(codes_seen "$out")" == "DISPATCH-MODEL-UNPINNED" ]]; then
  pass "4. #255 REGRESSION: agentType: \"shepherd:auditor\" ALONE → DENY DISPATCH-MODEL-UNPINNED"
else
  fail "4. #255 REGRESSION: agentType: \"shepherd:auditor\" ALONE → DENY DISPATCH-MODEL-UNPINNED" "codes=$(codes_seen "$out") out=${out:0:200}"
fi

echo "== workflow_off_flock — agentType VALUE checked against the shepherd: flock prefix =="

total=$((total+1))
out=$(run_hook "$(P 'const r = await agent("do it", {agentType: "general-purpose", model: "sonnet"})' "$tmp")")
if is_deny "$out" && [[ "$(codes_seen "$out")" == "WORKFLOW-OFF-FLOCK" ]]; then
  pass "5. agentType: \"general-purpose\" (model pinned): DENY WORKFLOW-OFF-FLOCK"
else
  fail "5. agentType: \"general-purpose\" (model pinned): DENY WORKFLOW-OFF-FLOCK" "codes=$(codes_seen "$out") out=${out:0:200}"
fi

total=$((total+1))
out=$(run_hook "$(P 'const role = pickRole()
const r = await agent("do it", {agentType: role, model: "sonnet"})' "$tmp")")
if is_deny "$out" && [[ "$(codes_seen "$out")" == "WORKFLOW-AGENTTYPE-UNVERIFIABLE" ]]; then
  pass "6. agentType: <computed/variable> (model pinned): flagged unverifiable, NEVER a false WORKFLOW-OFF-FLOCK"
else
  fail "6. agentType: <computed/variable> (model pinned): flagged unverifiable, NEVER a false WORKFLOW-OFF-FLOCK" "codes=$(codes_seen "$out") out=${out:0:200}"
fi

echo "== workflow_off_flock — masking still holds after value-reading (#255) =="

total=$((total+1))
out=$(run_hook "$(P 'const r = await agent(`Please avoid agentType: "general-purpose" style dispatch in your writeup`, {agentType: "shepherd:coder", model: "sonnet"})' "$tmp")")
if ! is_deny "$out" && ! is_context "$out"; then
  pass "7. \`agentType: \"general-purpose\"\` text inside a TEMPLATE-LITERAL PROMPT (real opts clean): PASS — proves masking still holds"
else
  fail "7. template-literal prompt decoy text: PASS (masking must still hold)" "unexpectedly denied/warned: ${out:0:200}"
fi

echo "== workflow_off_flock — nested agentType does not count as top-level =="

total=$((total+1))
out=$(run_hook "$(P 'const r = await agent("do it", {schema: {type: "object", properties: {agentType: {const: "general-purpose"}}}, model: "sonnet"})' "$tmp")")
if is_deny "$out" && has "$out" 'DISPATCH-MISSING-SUBAGENT-TYPE'; then
  pass "8. agentType nested inside opts.schema: still counts as MISSING at top level"
else
  fail "8. agentType nested inside opts.schema: still counts as MISSING at top level" "out=${out:0:200}"
fi

echo "== workflow_off_flock — operator override still suppresses the deny =="

total=$((total+1))
out=$(run_hook "$(P '// shepherd:model-pin-override — ack, verified manually
const r = await agent("run the deep audit", {agentType: "shepherd:auditor"})' "$tmp")")
if ! is_deny "$out" && is_context "$out" && has "$out" 'override marker present'; then
  pass "9. override marker: additionalContext, never a deny (even for the #255 shape)"
else
  fail "9. override marker: additionalContext, never a deny" "out=${out:0:200}"
fi

echo "== workflow_off_flock — a single call can trip multiple codes, all reported =="

total=$((total+1))
out=$(run_hook "$(P 'const r = await agent("do it", {agentType: "general-purpose"})' "$tmp")")
codes="$(codes_seen "$out")"
if is_deny "$out" && [[ "$codes" == *"DISPATCH-MODEL-UNPINNED"* ]] && [[ "$codes" == *"WORKFLOW-OFF-FLOCK"* ]]; then
  pass "10. one call, two laws broken: BOTH DISPATCH-MODEL-UNPINNED and WORKFLOW-OFF-FLOCK reported"
else
  fail "10. one call, two laws broken: BOTH DISPATCH-MODEL-UNPINNED and WORKFLOW-OFF-FLOCK reported" "codes=$codes out=${out:0:200}"
fi

echo "—— $((total-fails))/$total passed ——"
exit "$fails"
