#!/usr/bin/env bash
# hooks/tests/test_dispatch_guard.sh — Gate 1 evidence (v6.0.2, Wave 1).
#
# Reproduces the two #89 primitive↔axis inversions and the dispatch-class #66
# violations, and proves each is now mechanically BLOCKED by the pre-dispatch
# guards (dispatch_guard.sh + bash_guard.sh). Also proves that well-formed
# dispatches PASS (no false positives).
#
# A "block" = the guard emits {"permissionDecision":"deny",...} on stdout
# (the guard itself exits 0; the deny lives in the JSON). A "pass" = no deny.
#
# Exit 0 if every expectation holds; exit 1 with a per-case diagnostic.

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS="$(cd "$HERE/../scripts" && pwd)"

fails=0
note() { printf '  %s\n' "$*"; }

# Run a guard with a payload (+ optional env) and capture stdout.
# Usage: out=$(run_guard <script> <payload> [ENVVAR=val ...])
run_guard() {
  local script="$1" payload="$2"; shift 2
  printf '%s' "$payload" | env "$@" bash "$SCRIPTS/$script" 2>/dev/null || true
}

is_deny() { printf '%s' "$1" | grep -q '"permissionDecision"[[:space:]]*:[[:space:]]*"deny"'; }

expect_block() {  # name script payload [env...]
  local name="$1" script="$2" payload="$3"; shift 3
  local out; out=$(run_guard "$script" "$payload" "$@")
  if is_deny "$out"; then printf '  PASS  BLOCK  %s\n' "$name"
  else printf '  FAIL  BLOCK  %s (expected deny, got: %s)\n' "$name" "${out:0:80}"; fails=$((fails+1)); fi
}

expect_pass() {  # name script payload [env...]
  local name="$1" script="$2" payload="$3"; shift 3
  local out; out=$(run_guard "$script" "$payload" "$@")
  if is_deny "$out"; then printf '  FAIL  PASS   %s (unexpected deny: %s)\n' "$name" "${out:0:80}"; fails=$((fails+1))
  else printf '  PASS  PASS   %s\n' "$name"; fi
}

# Ephemeral shepherd-flagged repo (the guards gate on .claude/shepherd.toml).
tmp=$(mktemp -d -t shep-dispatch-test.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q . && git config user.email t@t && git config user.name t
git -c commit.gpgsign=false commit -q --allow-empty -m init
mkdir -p .claude && touch .claude/shepherd.toml

P() { printf '{"session_id":"s1","tool_name":"Agent","tool_input":%s}' "$1"; }

echo "== dispatch_guard.sh — well-formed dispatches PASS =="
expect_pass "step: shepherd:coder (no team_name)"        dispatch_guard.sh "$(P '{"subagent_type":"shepherd:coder"}')"
expect_pass "step: shepherd:auditor (no team_name)"      dispatch_guard.sh "$(P '{"subagent_type":"shepherd:auditor"}')"
expect_pass "lane: conductor + team_name (Agent Teams)"  dispatch_guard.sh "$(P '{"subagent_type":"shepherd:conductor","team_name":"shepherd-lane-x"}')"
expect_pass "lane: cased Conductor + team_name (MEDIUM-1 regr)" dispatch_guard.sh "$(P '{"subagent_type":"Shepherd:Conductor","team_name":"t"}')"
expect_pass "root dispatches engineer (not teammate)"    dispatch_guard.sh "$(P '{"subagent_type":"shepherd:engineer"}')"
expect_pass "non-shepherd specialist (not adjudicated)"  dispatch_guard.sh "$(P '{"subagent_type":"code-review:code-review"}')"

echo "== dispatch_guard.sh — #66 / #89 dispatch violations BLOCKED =="
# #66.1 — coders dispatched as teammates instead of conductors
expect_block "#66.1 coder-as-teammate (team_name+coder)"  dispatch_guard.sh "$(P '{"subagent_type":"shepherd:coder","team_name":"t"}')"
# #89/§IV-bis.1 — missing / default subagent_type
expect_block "missing subagent_type (unset)"              dispatch_guard.sh "$(P '{"description":"x"}')"
expect_block "general-purpose subagent_type"              dispatch_guard.sh "$(P '{"subagent_type":"general-purpose"}')"
expect_block "Explore subagent_type"                      dispatch_guard.sh "$(P '{"subagent_type":"Explore"}')"
# §IV-bis.3 — off-flock shepherd impersonation
expect_block "off-flock shepherd:architect"              dispatch_guard.sh "$(P '{"subagent_type":"shepherd:architect"}')"
# §IV-bis.2 — any flock role carrying team_name is a step-as-lane mismatch
expect_block "auditor-as-teammate (team_name+auditor)"   dispatch_guard.sh "$(P '{"subagent_type":"shepherd:auditor","team_name":"t"}')"
# §IV-bis.4 — teammate nesting (teammate session constructs team_name)
expect_block "teammate nesting (conductor+team_name)"    dispatch_guard.sh "$(P '{"subagent_type":"shepherd:conductor","team_name":"t"}')" CLAUDE_TEAMMATE_NAME=lane-a
# §IV-bis.5 — teammate dispatches engineer/critic (root-tier-exclusive)
expect_block "teammate dispatches engineer"              dispatch_guard.sh "$(P '{"subagent_type":"shepherd:engineer"}')" CLAUDE_TEAMMATE_NAME=lane-a
expect_block "teammate dispatches critic"                dispatch_guard.sh "$(P '{"subagent_type":"shepherd:critic"}')" CLAUDE_TEAMMATE_NAME=lane-a
# #93 — env-independent teammate detection via the hook-input `.worktrees/` cwd
# (the platform exposes NO teammate identity env var; cwd is the reliable signal).
expect_block "teammate-by-cwd (.worktrees) dispatches engineer" \
  dispatch_guard.sh '{"session_id":"s1","cwd":"/repo/.worktrees/v6-lane-a","tool_name":"Agent","tool_input":{"subagent_type":"shepherd:engineer"}}'
# No false positive: a normal (non-worktree) cwd is NOT a teammate — root may dispatch engineer.
expect_pass  "root-by-cwd (normal) dispatches engineer" \
  dispatch_guard.sh '{"session_id":"s1","cwd":"/repo","tool_name":"Agent","tool_input":{"subagent_type":"shepherd:engineer"}}'

echo "== dispatch_guard.sh — v6.2.6 engineer self-contained topology (#172) =="
# 4b — a self-contained engineer dispatched as a SUBAGENT is the wrong topology
# (must be a named teammate-spawn). The mode marker in the brief is the signal.
expect_block "self-contained engineer as subagent (ENGINEER-TOPOLOGY-MISMATCH)" \
  dispatch_guard.sh "$(P '{"subagent_type":"shepherd:engineer","prompt":"[INVOCATION-CONTEXT].mode: self-contained\ndispatcher: root-shepherd"}')"
# Classic engineer dispatch (no mode marker) is unaffected — still a valid subagent.
expect_pass  "classic engineer subagent (no mode marker) still passes" \
  dispatch_guard.sh "$(P '{"subagent_type":"shepherd:engineer","prompt":"[INVOCATION-CONTEXT].mode: classic"}')"
# 4 — a teammate dispatching @engineer is ALWAYS refused (no nested/phantom engineer),
# even carrying the self-contained marker.
expect_block "teammate dispatches @engineer (nested, marked)" \
  dispatch_guard.sh "$(P '{"subagent_type":"shepherd:engineer","prompt":"[INVOCATION-CONTEXT].mode: self-contained"}')" CLAUDE_TEAMMATE_NAME=lane-a
# 4' — the self-contained ENGINEER teammate MAY dispatch @critic on its own plan
# (brief tagged dispatcher: engineer-self-contained) — its adversarial self-gate.
expect_pass  "engineer teammate dispatches marked @critic (self-gate)" \
  dispatch_guard.sh "$(P '{"subagent_type":"shepherd:critic","prompt":"[INVOCATION-CONTEXT].dispatcher: engineer-self-contained"}')" CLAUDE_TEAMMATE_NAME=lane-a
# 4' — but a conductor lane (no marker) still cannot re-gate a fixed plan.
expect_block "conductor lane dispatches @critic (no marker, re-gate)" \
  dispatch_guard.sh "$(P '{"subagent_type":"shepherd:critic","prompt":"gate this plan"}')" CLAUDE_TEAMMATE_NAME=lane-a
# The engineer teammate MAY also run its intro-audit wave (@auditor is not tier-blocked).
expect_pass  "engineer teammate dispatches @auditor (intro wave)" \
  dispatch_guard.sh "$(P '{"subagent_type":"shepherd:auditor","prompt":"[INVOCATION-CONTEXT].dispatcher: engineer-self-contained"}')" CLAUDE_TEAMMATE_NAME=lane-a
# 4c — a marked engineer sub-flock dispatch may target ONLY {discovery,auditor,critic};
# a marked dispatch to a WRITE role is refused (no code is touched in this phase).
expect_block "engineer marked dispatch to @coder (ENGINEER-SUBFLOCK-VIOLATION)" \
  dispatch_guard.sh "$(P '{"subagent_type":"shepherd:coder","prompt":"[INVOCATION-CONTEXT].dispatcher: engineer-self-contained"}')" CLAUDE_TEAMMATE_NAME=lane-a
expect_block "engineer marked dispatch to @worker (ENGINEER-SUBFLOCK-VIOLATION)" \
  dispatch_guard.sh "$(P '{"subagent_type":"shepherd:worker","prompt":"[INVOCATION-CONTEXT].dispatcher: engineer-self-contained"}')" CLAUDE_TEAMMATE_NAME=lane-a
expect_pass  "engineer marked dispatch to @discovery (sub-flock ok)" \
  dispatch_guard.sh "$(P '{"subagent_type":"shepherd:discovery","prompt":"[INVOCATION-CONTEXT].dispatcher: engineer-self-contained"}')" CLAUDE_TEAMMATE_NAME=lane-a

echo "== dispatch_guard.sh — v6.2.6 marker robustness (false-positive / block-form) =="
# False positive fixed: a CLASSIC brief that merely mentions the phrase in prose is NOT blocked.
expect_pass  "classic brief mentioning 'mode: self-contained' in prose (no false block)" \
  dispatch_guard.sh "$(P '{"subagent_type":"shepherd:engineer","prompt":"[INVOCATION-CONTEXT].mode: classic\nNote: do NOT run in mode: self-contained here."}')"
# Block form of the marker (indented under an [INVOCATION-CONTEXT] header) still fires 4b.
expect_block "block-form mode marker (indented) still ENGINEER-TOPOLOGY-MISMATCH" \
  dispatch_guard.sh "$(P '{"subagent_type":"shepherd:engineer","prompt":"[INVOCATION-CONTEXT]\n  dispatcher: root-shepherd\n  mode: self-contained\n"}')"

echo "== bash_guard.sh — #89 inversion 1 (workflow spawns teammates) BLOCKED =="
mkdir -p .shepherd/graph/compiled
# A faithful compiled workflow: only subagent spawns → PASS.
cat > .shepherd/graph/compiled/clean.workflow.js <<'JS'
const w1 = await Promise.all(steps.map(s => agent({ subagent_type: "shepherd:coder", brief: s.brief })));
JS
# MEDIUM-2 regression: a faithful workflow that merely MENTIONS team_name in prose
# (no `team_name:` property) must NOT be falsely blocked.
cat > .shepherd/graph/compiled/mentions.workflow.js <<'JS'
// Faithful: subagents only. This script never performs a team_name spawn.
const w1 = await Promise.all(steps.map(s => agent({ subagent_type: "shepherd:coder", brief: s.brief })));
JS
# The inversion: a workflow that instantiates teammate-conductors → BLOCK.
cat > .shepherd/graph/compiled/inverted.workflow.js <<'JS'
const lanes = await Promise.all(plan.lanes.map(l =>
  agent({ team_name: "shepherd-" + l.id, subagent_type: "shepherd:conductor", brief: l.brief })));
JS
B() { printf '{"session_id":"s1","tool_name":"Bash","tool_input":{"command":"%s"%s}}' "$1" "${2:-}"; }
expect_pass  "faithful workflow (subagents only)"        bash_guard.sh "$(B 'node .shepherd/graph/compiled/clean.workflow.js')"
expect_pass  "workflow mentioning team_name in comment (MEDIUM-2 regr)" bash_guard.sh "$(B 'node .shepherd/graph/compiled/mentions.workflow.js')"
expect_block "inverted workflow (spawns teammates)"      bash_guard.sh "$(B 'node .shepherd/graph/compiled/inverted.workflow.js')"

echo "== bash_guard.sh — #91 cargo gate sequential-execution BLOCKED =="
expect_pass  "cargo gate foreground &&-chain"            bash_guard.sh "$(B 'cargo fmt --all && cargo check && cargo clippy')"
expect_block "cargo gate run_in_background:true (#91)"   bash_guard.sh "$(B 'cargo test --workspace --features full' ',"run_in_background":true')"

echo "== dispatch_guard.sh — Check 6 hand-rolled fan-out reminder (#263 default-ON) =="
# #263 flips Check 6 from opt-in (default off, avoided per-step noise) to
# default ON (the behavior it flags — a teammate hand-rolling an in-context
# fan-out instead of compiling a Dynamic Workflow — is now a real doctrine
# finding, not noise). The config knob survives so an operator can still
# silence it. This is an emit_context (additionalContext) reminder, never a
# deny — a per-call hook cannot see the whole batch, so it must never block.
is_context() { printf '%s' "$1" | grep -q '"additionalContext"'; }
has()        { printf '%s' "$1" | grep -q -- "$2"; }

expect_context() {  # name script payload [env...]
  local name="$1" script="$2" payload="$3"; shift 3
  local out; out=$(run_guard "$script" "$payload" "$@")
  if is_context "$out"; then printf '  PASS  CONTEXT %s\n' "$name"
  else printf '  FAIL  CONTEXT %s (expected additionalContext, got: %s)\n' "$name" "${out:0:80}"; fails=$((fails+1)); fi
}
expect_silent() {  # name script payload [env...]
  local name="$1" script="$2" payload="$3"; shift 3
  local out; out=$(run_guard "$script" "$payload" "$@")
  if [[ -z "$out" ]]; then printf '  PASS  SILENT  %s\n' "$name"
  else printf '  FAIL  SILENT  %s (expected empty output, got: %s)\n' "$name" "${out:0:80}"; fails=$((fails+1)); fi
}

CHECK6_PAYLOAD=$(printf '{"session_id":"s1","cwd":"%s/.worktrees/lane-a","tool_name":"Agent","tool_input":{"subagent_type":"shepherd:coder","prompt":"do work"}}' "$tmp")

# No [hooks] config at all → the reminder now fires BY DEFAULT (#263).
: > .claude/shepherd.toml
expect_context "no config: reminder fires by default (#263)" dispatch_guard.sh "$CHECK6_PAYLOAD"
FANOUT_DEFAULT_OUT=$(run_guard dispatch_guard.sh "$CHECK6_PAYLOAD")
if has "$FANOUT_DEFAULT_OUT" '#263' && has "$FANOUT_DEFAULT_OUT" 'FANOUT-VEHICLE-DOWNGRADE' \
   && has "$FANOUT_DEFAULT_OUT" 'WORKFLOW-VEHICLE-PROBE'; then
  printf '  PASS  CONTENT default reminder names the probe/downgrade contract (#263)\n'
else
  printf '  FAIL  CONTENT default reminder missing probe/downgrade contract: %s\n' "${FANOUT_DEFAULT_OUT:0:200}"
  fails=$((fails+1))
fi
if has "$FANOUT_DEFAULT_OUT" 'dispatch-cascade'; then
  printf '  FAIL  CONTENT default reminder still cites the retired dispatch-cascade.md doc path\n'
  fails=$((fails+1))
else
  printf '  PASS  CONTENT default reminder no longer cites the retired dispatch-cascade.md doc path\n'
fi
if has "$FANOUT_DEFAULT_OUT" 'pipeline.md §Lane law' && has "$FANOUT_DEFAULT_OUT" 'SKILL.md §Dispatch law'; then
  printf '  PASS  CONTENT default reminder cites the live doctrine surfaces\n'
else
  printf '  FAIL  CONTENT default reminder does not cite the live doctrine surfaces: %s\n' "${FANOUT_DEFAULT_OUT:0:200}"
  fails=$((fails+1))
fi

# Operator can still silence it explicitly (the config knob survives #263).
printf '[hooks]\nflag_handrolled_fanout = false\n' > .claude/shepherd.toml
expect_silent "flag_handrolled_fanout = false: operator silences the reminder" dispatch_guard.sh "$CHECK6_PAYLOAD"

# Explicit true still fires (back-compat with the pre-#263 opt-in spelling).
printf '[hooks]\nflag_handrolled_fanout = true\n' > .claude/shepherd.toml
expect_context "flag_handrolled_fanout = true: reminder still fires" dispatch_guard.sh "$CHECK6_PAYLOAD"

# Root (non-teammate) dispatching the same role is NEVER Check 6's concern,
# regardless of the default flip.
: > .claude/shepherd.toml
expect_silent "root (non-teammate) coder dispatch: Check 6 never fires" dispatch_guard.sh "$(P '{"subagent_type":"shepherd:coder"}')"

# Restore the shared empty config for anything appended after this block.
: > .claude/shepherd.toml

if [[ "$fails" -gt 0 ]]; then
  printf 'test_dispatch_guard: %d expectation(s) failed\n' "$fails"; exit 1
fi
printf 'test_dispatch_guard: OK — #89 inversions + dispatch-class #66 violations mechanically blocked; clean dispatches pass\n'
exit 0
