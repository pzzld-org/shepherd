#!/usr/bin/env bash
# hooks/tests/test_v643_wiring.sh — v6.4.3 doctrine-wiring regression guard (#263).
#
# v6.4.3 re-cuts the fan-out vehicle axis. #220 recorded a REAL platform
# message — "Workflow is not available inside subagents" (CC 2.1.212) — and
# generalized it one word too far. It is TRUE for an Agent-tool SUBAGENT and
# FALSE for an Agent-Teams TEAMMATE. `@conductor` and `@engineer` under
# `/shepherd:spawn` are teammates, so the denial never applied to them.
#
# The discriminator is SUBSTRATE, never tier:
#   live Agent-Teams teammate  -> Workflow works; compile a Dynamic Workflow
#   Agent-tool subagent        -> Workflow genuinely denied; in-context
#                                 Agent() is correct AND the only option
#
# This file exists because the previous framing was pinned the same way, and
# that is what made #263 expensive. `test_v636_wiring.sh` (#207) and
# `test_v639_wiring.sh` (#220) string-pinned the old law across six agent and
# skill files, so the doctrine could not drift back — and equally could not
# move FORWARD when #233 shipped the grant and the operator measured the
# platform. Frontmatter said one thing, bodies said the opposite, tests
# defended the bodies, and a live sprint burned an hour on the contradiction.
# The superseded blocks in those two files are neutralized (they point here);
# this file is the single wiring pin for the vehicle law.
#
# Shape follows test_v639_wiring.sh: have/missing over the tracked tree.
#
# Exit 0 on pass; exit 1 with a per-leg diagnostic.

set -uo pipefail
cd "$(dirname "$0")"
REPO_ROOT="$(cd ../.. && pwd)"

fails=0
have() { # have <file> <regex> <label>
  if grep -qE "$2" "$REPO_ROOT/$1" 2>/dev/null; then
    printf '  PASS  %s\n' "$3"
  else
    printf '  FAIL  %s — /%s/ not found in %s\n' "$3" "$2" "$1"; fails=$((fails+1))
  fi
}
missing() { # missing <file> <regex> <label> — asserts the pattern is ABSENT
  if grep -qE "$2" "$REPO_ROOT/$1" 2>/dev/null; then
    printf '  FAIL  %s — /%s/ still present in %s\n' "$3" "$2" "$1"; fails=$((fails+1))
  else
    printf '  PASS  %s\n' "$3"
  fi
}

echo "== #263 the fan-out vehicle is SUBSTRATE-conditional, never tier-conditional =="
have agents/conductor.md \
  'SUBSTRATE-conditional, never tier-conditional' \
  "#263 conductor states the substrate axis"
have agents/engineer.md \
  'SUBSTRATE-conditional, never tier-conditional' \
  "#263 engineer states the substrate axis"
have skills/harness/SKILL.md \
  'SUBSTRATE-conditional, never tier-conditional' \
  "#263 harness SKILL owns the platform-level substrate rule"
have skills/shepherd/references/pipeline.md \
  'SUBSTRATE-CONDITIONAL, never DRIVER-CONDITIONAL' \
  "#263 pipeline §Lane law names the axis and what it replaced"
have skills/shepherd/references/wave-routine.md \
  'VEHICLE is SUBSTRATE-conditional' \
  "#263 wave-routine §Per-wave compile tracks the substrate"

# The over-correction is as wrong as the original error. Mandating a compiled
# Workflow regardless of substrate would break every genuine Agent-tool
# subagent, where the denial is real.
echo "== #263 BOTH substrate branches are stated, neither collapsed =="
have skills/shepherd/references/pipeline.md \
  'never unconditional' \
  "#263 pipeline rejects the unconditional over-correction too"
have agents/conductor.md \
  'Substrate-absent branch' \
  "#263 conductor states the subagent branch explicitly"
have skills/harness/SKILL.md \
  'a downgrade to apologize for' \
  "#263 harness SKILL refuses to frame the subagent branch as a downgrade"

# The platform message was never wrong -- only its scope was. Deleting it
# would lose a true fact; the correction is to re-scope it to subagents.
echo "== #263 retains the platform fact, re-scoped rather than deleted =="
have skills/shepherd/references/pipeline.md \
  'not available inside subagents' \
  "#263 pipeline keeps the CC 2.1.212 message as a fact about subagents"
have skills/harness/SKILL.md \
  'not available inside subagents' \
  "#263 harness SKILL keeps the platform message verbatim"

echo "== #263 the retired over-generalization is gone from every lead body =="
missing agents/conductor.md \
  'NEVER attempt a .Workflow. call' \
  "#263 conductor no longer forbids the Workflow call"
missing agents/conductor.md \
  "Compiling Dynamic Workflows is root's mode alone" \
  "#263 conductor no longer reserves Workflow to root"
missing agents/engineer.md \
  'you NEVER compile a Dynamic Workflow' \
  "#263 engineer no longer forbids compiling a Workflow"
missing skills/shepherd/references/wave-routine.md \
  'PERMANENT mode' \
  "#263 wave-routine no longer calls in-context dispatch permanent"
missing skills/shepherd/references/pipeline.md \
  'DRIVER-CONDITIONAL for the fan-out axis' \
  "#263 the fan-out axis is no longer driver-conditional"

echo "== #263 the probe confirms SUBSTRATE, and is required =="
have agents/conductor.md \
  'WORKFLOW-VEHICLE-PROBE' \
  "#263 conductor runs the vehicle probe"
have agents/engineer.md \
  'WORKFLOW-VEHICLE-PROBE' \
  "#263 engineer runs the vehicle probe"
have skills/harness/SKILL.md \
  'confirms SUBSTRATE, never a dormant grant' \
  "#263 harness SKILL frames the probe as a substrate check"

# Ask 2 of #263 was WITHDRAWN by the operator: the prohibition is correct
# guidance and keeps its original name. Only its stated REASON was wrong --
# the tool is not "discovery-invisible", it is not a ToolSearch target by
# construction. WORKFLOW-PROBE-WRONG-INDEX was our own first-pass invention
# and must exist nowhere in the tree.
echo "== #263 WORKFLOW-SELFCHECK-TOOLSEARCH survives; the reason is corrected =="
have agents/conductor.md \
  'WORKFLOW-SELFCHECK-TOOLSEARCH' \
  "#263 conductor retains the prohibition under its original name"
have skills/shepherd/references/escalation.md \
  'WORKFLOW-SELFCHECK-TOOLSEARCH' \
  "#263 the halt-code index keeps it as a LIVE entry"
have agents/conductor.md \
  'false negative by construction' \
  "#263 conductor states the CORRECTED reason (a null proves nothing)"
for f in agents/conductor.md agents/engineer.md agents/auditor.md \
         skills/harness/SKILL.md skills/harness/references/workflow-templates.md \
         skills/shepherd/SKILL.md skills/shepherd/references/escalation.md \
         skills/shepherd/references/pipeline.md \
         skills/shepherd/references/invariant-matrix.md \
         services/cli/shepherd_cli/templates/boot-prompt.md.j2 \
         hooks/scripts/dispatch_guard.sh; do
  missing "$f" 'WORKFLOW-PROBE-WRONG-INDEX' \
    "#263 no invented WORKFLOW-PROBE-WRONG-INDEX in ${f##*/}"
done

# #251 IS resolved by the #263 measurement: its "invisible to discovery" probe
# used ToolSearch against a native tool (a guaranteed null) AND ran inside a
# generic workflow-spawned subagent, the one construct where the denial is
# genuinely real. Both halves are invalid read onto a teammate. The first pass
# kept it framed as an open dispute, preserving a doubt already retired.
echo "== #263 resolves #251 rather than preserving it as an open dispute =="
missing skills/harness/SKILL.md \
  'NOT resolved by #263' \
  "#251 is no longer framed as an unresolved dispute"
missing agents/conductor.md \
  'do NOT assume either reading' \
  "#251 conductor no longer hedges denied-vs-invisible"
have skills/harness/SKILL.md \
  'discovery-vs-invocation ambiguity' \
  "#251 harness SKILL records the resolution explicitly"
# ScheduleWakeup is a DIFFERENT question, genuinely unmeasured in a teammate
# session, and stays honestly open -- decoupled from Workflow's status.
have agents/conductor.md \
  'ScheduleWakeup' \
  "#251 the separate ScheduleWakeup uncertainty survives the resolution"

echo "== #263 the probe directive reaches the rendered boot brief =="
have services/cli/shepherd_cli/templates/boot-prompt.md.j2 \
  'WORKFLOW-VEHICLE-PROBE' \
  "#263 boot prompt instructs the conductor to probe before its first fan-out"
have services/cli/shepherd_cli/templates/boot-prompt.md.j2 \
  'Agent-tool subagent' \
  "#263 boot prompt names the substrate-absent branch"
have commands/spawn.md \
  'WORKFLOW-VEHICLE-PROBE' \
  "#263 spawn.md describes the probe directive the template renders"

echo "== #263 the auditor grades the substrate, not the vehicle =="
have agents/auditor.md \
  'FANOUT-VEHICLE-DOWNGRADE' \
  "#263 auditor grades a live-substrate hand-roll as a finding"
missing agents/auditor.md \
  'workflow_tool: absent. \+ .fanout: in-context. is EXPECTED and CORRECT' \
  "#263 auditor no longer certifies the in-context vehicle unconditionally"

echo "== #263 the #255 pin law rides along unchanged =="
have agents/conductor.md \
  'agentType: "shepherd:<role>"' \
  "#255/#263 conductor pins agentType on every agent() call"
have agents/engineer.md \
  'flockAgent\(\)' \
  "#255/#263 engineer authors agent() through the guarded wrapper"
have skills/shepherd/references/wave-routine.md \
  'agentType: "shepherd:coder"' \
  "#255/#263 wave-routine's compile schematic shows both pins"

echo "== #263 the resource counterweight still binds =="
have agents/conductor.md \
  'Fan-out counterweight' \
  "#256/#263 conductor cites the counterweight it is bound by"
have skills/shepherd/references/pipeline.md \
  'Fan-out counterweight' \
  "#256/#263 pipeline cites it beside the new authorization"

echo "== #263 the invariant matrix agrees with the bodies =="
have skills/shepherd/references/invariant-matrix.md \
  'test_v643_wiring.sh' \
  "#263 invariant matrix points at this file as the pin"
missing skills/shepherd/references/invariant-matrix.md \
  'compiles to a Dynamic Workflow at ROOT ONLY' \
  "#263 invariant row 3 is no longer root-only"
have skills/shepherd/references/invariant-matrix.md \
  'substrate' \
  "#263 invariant matrix states the substrate axis"

if [[ "$fails" -gt 0 ]]; then
  printf 'test_v643_wiring: %d leg(s) FAILED — the #263 substrate axis has drifted\n' "$fails"
  exit 1
fi
printf 'test_v643_wiring: OK — #263 substrate axis wired across conductor/engineer/auditor/harness/pipeline/wave-routine/escalation/invariant-matrix/boot-prompt\n'
exit 0
