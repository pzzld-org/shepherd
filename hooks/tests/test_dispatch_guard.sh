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

P() {  # P <tool_input_json> [cwd]
  # cwd is OPTIONAL (2nd arg) -- every existing single-arg call site is
  # byte-for-byte unchanged. Needed so Check 7/Check 8 fixtures can set a
  # `.worktrees` cwd inline, the same teammate-detection signal
  # CHECK6_PAYLOAD below already builds by hand (#93 cwd-based tier
  # detection) -- this just makes that signal available via the shared
  # payload-builder instead of a one-off raw-JSON literal per fixture.
  if [[ -n "${2:-}" ]]; then
    printf '{"session_id":"s1","cwd":"%s","tool_name":"Agent","tool_input":%s}' "$2" "$1"
  else
    printf '{"session_id":"s1","tool_name":"Agent","tool_input":%s}' "$1"
  fi
}

echo "== dispatch_guard.sh — well-formed dispatches PASS =="
expect_pass "step: shepherd:coder (no team_name)"        dispatch_guard.sh "$(P '{"subagent_type":"shepherd:coder"}')"
expect_pass "step: shepherd:auditor (no team_name)"      dispatch_guard.sh "$(P '{"subagent_type":"shepherd:auditor","prompt":"[CONCERN] code-quality"}')"
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
  dispatch_guard.sh "$(P '{"subagent_type":"shepherd:auditor","prompt":"[INVOCATION-CONTEXT].dispatcher: engineer-self-contained\n[CONCERN] intro-audit"}')" CLAUDE_TEAMMATE_NAME=lane-a
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

echo "== dispatch_guard.sh — Check 7 AUDIT-CONCERN-UNDECLARED (agents/auditor.md:92) =="
# Combined DENY assertion: exit-behavior (is_deny) AND the specific halt-code text in
# the denial message. A check that only confirms "some rule denied it" passes even when
# the WRONG rule fired -- the exact DF-41 shape this lane exists to prevent. Composes the
# file's own is_deny + has (already defined above for the Check 6 CONTENT assertions) --
# no new JSON-parsing or payload-building primitive.
expect_block_code() {  # name script payload code [env...]
  local name="$1" script="$2" payload="$3" code="$4"; shift 4
  local out; out=$(run_guard "$script" "$payload" "$@")
  if is_deny "$out" && has "$out" "$code"; then
    printf '  PASS  BLOCK  %s\n' "$name"
  else
    printf '  FAIL  BLOCK  %s (expected deny+%s, got: %s)\n' "$name" "$code" "${out:0:160}"
    fails=$((fails+1))
  fi
}

echo "== dispatch_guard.sh — Check 0 malformed payload fails CLOSED, not open (GH #284) =="
# GH #284: json_field (_lib.sh) is DELIBERATELY fail-open on malformed JSON --
# empty string for every field, the correct contract for a sourcing hook
# under `set -e` -- but this file's OWN top-of-script tool_name gate then
# read that empty string as "not Agent/Task" and exited 0 SILENTLY, taking
# every downstream check (1-8) down with it at once. Feed deliberately
# broken JSON and assert this now DENIES loud and attributable -- the
# `scripts/check-workspace.sh --self-test` discipline the issue names
# ("every rule must be able to fail" -- prove the checker actually detects
# a bad fixture), explicitly NOT a grep-for-prose assertion (the DF-19
# pattern this exists to kill). Asserting the script merely exits 0 proves
# nothing here (the pre-fix script ALSO exited 0 on every case below); the
# DENY reaching stdout in the shape Claude's hook contract expects, with
# the specific halt code, is the only thing that proves the fix.
expect_block_code "Check 0: truncated JSON (unterminated object) denies, not silently passes" \
  dispatch_guard.sh '{"session_id":"s1","tool_name":"Agent","tool_input":{"subagent_type":' \
  DISPATCH-GUARD-MALFORMED-PAYLOAD

# The exact regression shape from the issue: a malformed payload that WOULD
# have carried a Check-1-triggering subagent_type ("general-purpose") had it
# parsed cleanly -- must still deny on the malformed-payload code, not
# silently pass just because the corrupted tail makes tool_name unreadable.
expect_block_code "Check 0: malformed payload that would-be Check-1-triggering still denies" \
  dispatch_guard.sh '{"session_id":"s1","tool_name":"Agent","tool_input":{"subagent_type":"general-purpose"' \
  DISPATCH-GUARD-MALFORMED-PAYLOAD

# Not-quite-JSON garbage (never was JSON) -- same fail-closed contract.
expect_block_code "Check 0: non-JSON garbage payload denies" \
  dispatch_guard.sh 'not json at all {{{' \
  DISPATCH-GUARD-MALFORMED-PAYLOAD

# Positive control: a well-formed dispatch is unaffected by the new gate.
expect_pass "Check 0: well-formed dispatch is unaffected (positive control)" dispatch_guard.sh \
  "$(P '{"subagent_type":"shepherd:coder"}')"

expect_block_code "Check 7: zero [CONCERN] declarations" dispatch_guard.sh \
  "$(P '{"subagent_type":"shepherd:auditor","prompt":"Please review the lane for issues."}')" \
  AUDIT-CONCERN-UNDECLARED

expect_block_code "Check 7: prose mention of concern (no bracket tag) still zero-declared" dispatch_guard.sh \
  "$(P '{"subagent_type":"shepherd:auditor","prompt":"There is a concern about naming in this module -- please look."}')" \
  AUDIT-CONCERN-UNDECLARED

TWO_CONCERN_PAYLOAD=$(P '{"subagent_type":"shepherd:auditor","prompt":"[CONCERN] code-quality\n[CONCERN] data-flow\nReview both."}')
expect_block_code "Check 7: two [CONCERN] declarations (must split into separate dispatches)" \
  dispatch_guard.sh "$TWO_CONCERN_PAYLOAD" AUDIT-CONCERN-UNDECLARED
TWO_CONCERN_OUT=$(run_guard dispatch_guard.sh "$TWO_CONCERN_PAYLOAD")
if has "$TWO_CONCERN_OUT" "Split into"; then
  printf '  PASS  CONTENT Check 7 two-concern denial tells the dispatcher to split into N dispatches\n'
else
  printf '  FAIL  CONTENT Check 7 two-concern denial missing split-into-N-dispatches guidance: %s\n' "${TWO_CONCERN_OUT:0:160}"
  fails=$((fails+1))
fi

expect_pass "Check 7: exactly one [CONCERN] declaration passes (positive control)" dispatch_guard.sh \
  "$(P '{"subagent_type":"shepherd:auditor","prompt":"[CONCERN] code-quality\nReview naming and dead code."}')"

expect_pass "Check 7/8: legal shepherd:coder step dispatch is untouched (positive control)" dispatch_guard.sh \
  "$(P '{"subagent_type":"shepherd:coder"}')"

# CRITICAL topology gap (guard-fail-closed audit finding): every fixture above
# exercises Check 7 at the ROOT topology (no cwd, teammate_mode=0). Check 6
# (PRIMITIVE-INVERSION, #263 default-ON) sits BEFORE Check 7 in this file's
# pre-existing ordering and unconditionally `emit_context`s-and-exits (see
# hooks/scripts/_lib.sh emit_context) whenever teammate_mode==1 AND
# subagent_type is shepherd:coder/shepherd:auditor -- so a dispatch from a
# TEAMMATE-CONDUCTOR'S OWN worktree (the real DF-43/DF-46 topology) never
# reached Check 7 at all, and this suite's 54/54 GREEN never noticed. Same
# bundled-multi-topic, zero-[CONCERN] violation shape as the fixtures above,
# just with a `.worktrees` cwd set via P()'s new optional 2nd arg instead of
# no cwd -- so it actually exercises the teammate topology Check 7 exists to
# gate DF-44 for.
WT_CONCERN_PAYLOAD=$(P '{"subagent_type":"shepherd:auditor","prompt":"Review the auth module for security issues and also check the database migration for correctness and please look at the frontend routing too."}' "$tmp/.worktrees/lane-check7-cwd")
expect_block_code "Check 7 (teammate .worktrees cwd, #93 topology): bundled multi-topic prompt, zero [CONCERN]" \
  dispatch_guard.sh "$WT_CONCERN_PAYLOAD" AUDIT-CONCERN-UNDECLARED

echo "== dispatch_guard.sh — Check 8 DISPATCH-OWNERSHIP-RECORD (non-denying observer) =="
# DISPATCHER-PATCH (received mid-dispatch from shepherd-conductor-v645-l6-guards, applied
# here -- see the CODER REPORT for full text): the original WAVE-GATE-USURPED deny-check
# finding was RETRACTED (root misattributed a routed-in completion dispatched by a
# different conductor as its own). Check 8 is now DISPATCH-OWNERSHIP-RECORD -- a
# non-denying observer that appends an ownership row (dispatcher session, subagent_type,
# model, lane if resolvable, concern slug if Check 7 found one, timestamp) to the registry
# on every shepherd:* dispatch, and NEVER denies -- including on an unwritable registry,
# where it emit_context-warns and still passes (an ABSENT-but-creatable namespace is
# NOT a failure -- it self-heals via mkdir -p, silently, same as every other hook).
# This section replaces the original
# root-dispatch-into-live-lane deny fixture and the teammate-session-unaffected fixture
# (neither applies to a check with no deny path).
#
# The patch did not pin the exact persistence mechanism/schema, so `ownership_evidence`
# below searches BOTH plausible reuse-consistent sinks: the existing
# hooks/scripts/_lib.sh log_event() JSONL log (<ns>/logs/hooks/*.jsonl -- the established
# "append a record" idiom every OTHER check in this file already relies on via
# emit_context/emit_deny/pass_silent) and any sqlite *.db under the namespace. See the
# CODER REPORT for the explicit finding recommending the conductor pin one.
ownership_evidence() {  # session_marker
  {
    [[ -d ".shepherd/logs" ]] && grep -r -- "$1" ".shepherd/logs" 2>/dev/null
    if command -v sqlite3 >/dev/null 2>&1; then
      local db
      for db in .shepherd/*.db; do
        [[ -f "$db" ]] || continue
        sqlite3 "$db" .dump 2>/dev/null | grep -- "$1"
      done
    fi
  } 2>/dev/null || true
}

# Self-heal A: registry namespace ABSENT entirely is NOT a failure -- the guard's own
# `mkdir -p "$(dirname "$do_db")"` (matching every other hook's resolve_namespace +
# mkdir -p convention, e.g. log_event()) creates it on first write. This must stay a
# CLEAN SILENT PASS (no context, no deny) AND actually leave a real row behind --
# verified live: a first-ever-dispatch repo with no .shepherd/ at all correctly ends up
# with .shepherd/shepherd.db + a dispatch_ownership row, no additionalContext emitted.
rm -rf .shepherd
ABSENT_PAYLOAD=$(P '{"subagent_type":"shepherd:auditor","prompt":"[CONCERN] code-quality\nAudit the lane."}')
expect_silent "Check 8: absent registry namespace self-heals silently (no warning needed)" dispatch_guard.sh "$ABSENT_PAYLOAD"
ABSENT_EVIDENCE=$(ownership_evidence "shepherd:auditor")
if [[ -f ".shepherd/shepherd.db" ]] && printf '%s' "$ABSENT_EVIDENCE" | grep -q "code-quality"; then
  printf '  PASS  RECORD Check 8: self-heal actually created the namespace and wrote the row\n'
else
  printf '  FAIL  RECORD Check 8: self-heal did not leave a real row behind: db_exists=%s evidence=%s\n' \
    "$([[ -f .shepherd/shepherd.db ]] && echo yes || echo no)" "${ABSENT_EVIDENCE:0:160}"
  fails=$((fails+1))
fi
rm -rf .shepherd

# Fail-visible: registry namespace PRESENT but UNWRITABLE -- warn + PASS, never deny.
# `chmod 500` only simulates "unwritable" for a NON-root process -- the root unix user
# bypasses filesystem permission bits entirely, so under root this fixture would silently
# stop exercising the fail-visible path at all (.shepherd stays writable despite chmod,
# no warning fires, and the assertion below would "pass" for the wrong reason: never
# having tested anything). Detect root explicitly and SKIP visibly rather than let that
# happen quietly -- a checker that cannot fail in some environment is not known to check
# anything there, same discipline as the invert-to-red sweep, just environment-scoped
# instead of mutation-scoped.
if [[ "$(id -u 2>/dev/null || echo 0)" -eq 0 ]]; then
  printf '  SKIP  Check 8: unwritable-registry fixture skipped -- running as uid 0 (root)\n'
  printf '        bypasses chmod permission bits; a chmod-based unwritable-registry\n'
  printf '        simulation cannot hold as root, so this assertion cannot exercise the\n'
  printf '        fail-visible path here and is skipped rather than passing vacuously.\n'
else
  mkdir -p .shepherd
  chmod 500 .shepherd
  UNWRITABLE_PAYLOAD=$(P '{"subagent_type":"shepherd:auditor","prompt":"[CONCERN] code-quality\nAudit the lane."}')
  expect_context "Check 8: unwritable registry -> additionalContext (fail-visible)" dispatch_guard.sh "$UNWRITABLE_PAYLOAD"
  UNWRITABLE_OUT=$(run_guard dispatch_guard.sh "$UNWRITABLE_PAYLOAD")
  chmod 700 .shepherd
  rm -rf .shepherd
  if ! is_deny "$UNWRITABLE_OUT"; then
    printf '  PASS  NODENY Check 8: unwritable registry never denies (fail-visible, not fail-closed)\n'
  else
    printf '  FAIL  NODENY Check 8: unwritable registry incorrectly denied: %s\n' "${UNWRITABLE_OUT:0:160}"
    fails=$((fails+1))
  fi
fi

# Well-formed dispatch WITH a resolvable .worktrees/<lane> path -- must PASS (never deny)
# and leave an inspectable ownership row whose fields actually match this dispatch
# (dispatcher session / subagent_type / model / lane), not just "some row exists".
OWN_LANE_PAYLOAD='{"session_id":"s-own1","tool_name":"Agent","tool_input":{"subagent_type":"shepherd:auditor","model":"sonnet","prompt":"[CONCERN] code-quality\nAudit .worktrees/lane-owner for wave-review."}}'
expect_pass "Check 8: well-formed dispatch with resolvable lane never denies" dispatch_guard.sh "$OWN_LANE_PAYLOAD"
OWN1_EVIDENCE=$(ownership_evidence "s-own1")
if printf '%s' "$OWN1_EVIDENCE" | grep -q "shepherd:auditor" \
   && printf '%s' "$OWN1_EVIDENCE" | grep -q "sonnet" \
   && printf '%s' "$OWN1_EVIDENCE" | grep -q "lane-owner"; then
  printf '  PASS  RECORD Check 8: ownership row records dispatcher/subagent_type/model/lane\n'
else
  printf '  FAIL  RECORD Check 8: ownership row missing expected fields (dispatcher/subagent_type/model/lane): %s\n' "${OWN1_EVIDENCE:0:200}"
  fails=$((fails+1))
fi

# Well-formed dispatch with NO .worktrees/<lane> path in the prompt -- the row's lane
# field must be null/absent, never guessed or defaulted to something.
OWN_NOLANE_PAYLOAD='{"session_id":"s-own2","tool_name":"Agent","tool_input":{"subagent_type":"shepherd:coder","model":"opus","prompt":"Implement the fix for issue 42."}}'
expect_pass "Check 8: well-formed dispatch with no lane path never denies" dispatch_guard.sh "$OWN_NOLANE_PAYLOAD"
OWN2_EVIDENCE=$(ownership_evidence "s-own2")
if printf '%s' "$OWN2_EVIDENCE" | grep -q "shepherd:coder" \
   && printf '%s' "$OWN2_EVIDENCE" | grep -q "opus" \
   && ! printf '%s' "$OWN2_EVIDENCE" | grep -q '\.worktrees/'; then
  printf '  PASS  RECORD Check 8: ownership row records subagent_type/model, lane not fabricated\n'
else
  printf '  FAIL  RECORD Check 8: ownership row wrong shape (expected no fabricated lane): %s\n' "${OWN2_EVIDENCE:0:200}"
  fails=$((fails+1))
fi
rm -rf .shepherd

# CRITICAL topology gap (guard-fail-closed audit finding, same root cause as
# the new Check 7 fixture above): OWN_LANE_PAYLOAD/OWN_NOLANE_PAYLOAD above
# both run at the ROOT topology (no cwd set) -- Check 6's teammate_mode gate
# never fires there, so those two never actually exercised the topology
# where the ordering bug hides the observer entirely. This is the SAME
# well-formed, single-[CONCERN] "record-a-row" case as OWN_LANE_PAYLOAD,
# just with an actual `.worktrees` cwd set via P()'s cwd arg (not merely
# mentioned in the prompt text) -- teammate_mode=1, so pre-fix this dispatch
# never reaches Check 8 at all and no row gets written despite being a
# textbook-legal dispatch that must never denied AND must be recorded.
WT_OWN_PAYLOAD=$(P '{"subagent_type":"shepherd:auditor","model":"sonnet","prompt":"[CONCERN] code-quality\nAudit the lane for wave-review."}' "$tmp/.worktrees/lane-check8-cwd")
expect_pass "Check 8 (teammate .worktrees cwd, #93 topology): well-formed dispatch never denies" dispatch_guard.sh "$WT_OWN_PAYLOAD"
WT_OWN_EVIDENCE=$(ownership_evidence "lane-check8-cwd")
if printf '%s' "$WT_OWN_EVIDENCE" | grep -q "shepherd:auditor" \
   && printf '%s' "$WT_OWN_EVIDENCE" | grep -q "sonnet" \
   && printf '%s' "$WT_OWN_EVIDENCE" | grep -q "code-quality"; then
  printf '  PASS  RECORD Check 8 (teammate .worktrees cwd): ownership row recorded subagent_type/model/lane/concern\n'
else
  printf '  FAIL  RECORD Check 8 (teammate .worktrees cwd): no matching row (subagent_type/model/lane/concern): %s\n' "${WT_OWN_EVIDENCE:0:200}"
  fails=$((fails+1))
fi
rm -rf .shepherd

# REDO (guard-fail-closed audit, Finding 1, HIGH): sql_lit()'s original
# `${v//\'/\'\'}` bash-expansion escaping inserted a spurious backslash
# instead of doubling the quote, so sqlite3 rejected the INSERT and the
# ownership row for ANY apostrophe-bearing field was silently dropped --
# Check 8 never denies, so nothing on stdout signalled the loss. Asserting
# only "did not deny" (expect_pass alone) is exactly the blind spot that let
# the defect through the first time: it passes whether or not the write
# succeeded. This fixture instead queries the registry DB directly and
# asserts the exact apostrophe-bearing value round-tripped, plus that the
# adjacent adversarial DROP-TABLE-shaped `session_id` neither executed nor
# corrupted the table (it must land as an inert, quoted string value, same
# as any other field -- sql_lit() has no injection-prevention job beyond
# correct literal quoting, but a broken escaper masking its own SQL syntax
# errors would hide that too).
rm -rf .shepherd
APOS_SESSION="s-apos-o'brien"
APOS_MODEL="claude-o'brien-sonnet"
APOS_PAYLOAD=$(printf '{"session_id":"%s","tool_name":"Agent","tool_input":{"subagent_type":"shepherd:coder","model":"%s","prompt":"Implement the fix."}}' \
  "$APOS_SESSION" "$APOS_MODEL")
expect_pass "Check 8: apostrophe in session_id + model never denies" dispatch_guard.sh "$APOS_PAYLOAD"
APOS_ROW=$(sqlite3 -separator '|' .shepherd/shepherd.db \
  "SELECT session_id, model FROM dispatch_ownership WHERE subagent_type='shepherd:coder';" 2>/dev/null || true)
if [[ "$APOS_ROW" == "${APOS_SESSION}|${APOS_MODEL}" ]]; then
  printf '  PASS  RECORD Check 8: apostrophe-bearing session_id/model round-tripped exactly through sql_lit()\n'
else
  printf '  FAIL  RECORD Check 8: apostrophe-bearing row did not round-trip (want %s|%s, got: %s)\n' \
    "$APOS_SESSION" "$APOS_MODEL" "${APOS_ROW:-<no row>}"
  fails=$((fails+1))
fi
rm -rf .shepherd

# Adversarial DROP-TABLE-shaped value: must land as an inert quoted string
# (table survives, row count is exactly 1), never execute as SQL.
DROP_SESSION="s-drop'; DROP TABLE dispatch_ownership; --"
DROP_PAYLOAD=$(printf '{"session_id":"%s","tool_name":"Agent","tool_input":{"subagent_type":"shepherd:coder","model":"sonnet","prompt":"Implement the fix."}}' "$DROP_SESSION")
expect_pass "Check 8: DROP-TABLE-shaped session_id never denies" dispatch_guard.sh "$DROP_PAYLOAD"
DROP_ROW=$(sqlite3 .shepherd/shepherd.db "SELECT session_id FROM dispatch_ownership WHERE subagent_type='shepherd:coder';" 2>/dev/null || true)
DROP_ROWCOUNT=$(sqlite3 .shepherd/shepherd.db "SELECT COUNT(*) FROM dispatch_ownership;" 2>/dev/null || echo 0)
if [[ "$DROP_ROW" == "$DROP_SESSION" && "$DROP_ROWCOUNT" == "1" ]]; then
  printf '  PASS  RECORD Check 8: DROP-TABLE-shaped session_id stored inert, table intact, exactly 1 row\n'
else
  printf '  FAIL  RECORD Check 8: DROP-TABLE-shaped session_id mishandled (want %s / count 1, got: %s / count %s)\n' \
    "$DROP_SESSION" "${DROP_ROW:-<no row>}" "$DROP_ROWCOUNT"
  fails=$((fails+1))
fi
rm -rf .shepherd

if [[ "$fails" -gt 0 ]]; then
  printf 'test_dispatch_guard: %d expectation(s) failed\n' "$fails"; exit 1
fi
printf 'test_dispatch_guard: OK — #89 inversions + dispatch-class #66 violations mechanically blocked; clean dispatches pass\n'
exit 0
