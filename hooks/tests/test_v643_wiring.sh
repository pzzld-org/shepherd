#!/usr/bin/env bash
# hooks/tests/test_v643_wiring.sh — v6.4.3 doctrine-wiring regression guard (#263).
#
# v6.4.3 inverts the fan-out vehicle: every tier holding the `Workflow` grant
# — root, a teammate-@conductor, a self-contained @engineer — compiles its OWN
# Dynamic Workflow, and in-context Agent() fan-out becomes a probed, recorded
# DOWNGRADE rather than the first-class teammate mode.
#
# This file exists because the previous inversion was pinned the same way and
# that is exactly what made #263 expensive. `test_v636_wiring.sh` (#207) and
# `test_v639_wiring.sh` (#220) string-pinned the old law across six agent and
# skill files, so the doctrine could not drift back — and equally could not
# move FORWARD when the operator's design changed and #233 shipped the grant.
# The frontmatter said one thing, the bodies said the opposite, the tests
# defended the bodies, and a live sprint burned an hour on the contradiction.
# The superseded blocks in those two files are neutralized (they point here);
# this file is now the single wiring pin for the vehicle law.
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

echo "== #263 the fan-out vehicle is a Dynamic Workflow at every grant-holding tier =="
have agents/conductor.md \
  'Fan-out vehicle: the Dynamic Workflow' \
  "#263 conductor carries the vehicle law"
have agents/engineer.md \
  'Fan-out vehicle: the Dynamic Workflow' \
  "#263 engineer carries the vehicle law"
have skills/harness/SKILL.md \
  'Fan-out vehicle: the Dynamic Workflow' \
  "#263 harness SKILL owns the platform-level vehicle fact"
have skills/shepherd/references/wave-routine.md \
  'EVERY driver compiles ONE Dynamic Workflow script per wave' \
  "#263 wave-routine §Per-wave compile is driver-agnostic"

echo "== #263 the retired instruction is gone from every lead body =="
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
  "#263 pipeline §Lane law fan-out axis is no longer driver-conditional"

echo "== #263 the probe is a REQUIREMENT, not a prohibition =="
have agents/conductor.md \
  'WORKFLOW-VEHICLE-PROBE' \
  "#263 conductor runs the vehicle probe"
have agents/engineer.md \
  'WORKFLOW-VEHICLE-PROBE' \
  "#263 engineer runs the vehicle probe"
have skills/harness/SKILL.md \
  'WORKFLOW-VEHICLE-PROBE' \
  "#263 harness SKILL defines the probe as the oracle"
missing agents/conductor.md \
  'NEVER .ToolSearch. for .Workflow. \(.WORKFLOW-SELFCHECK-TOOLSEARCH' \
  "#263 the bare WORKFLOW-SELFCHECK-TOOLSEARCH prohibition is retired"
have agents/conductor.md \
  'WORKFLOW-PROBE-WRONG-INDEX' \
  "#263 conductor names the wrong-index code, not a probe ban"

# ToolSearch remains the WRONG index for a native primitive — that platform
# fact is UNCHANGED by #263 and must not be lost in the inversion. What
# changed is only which thing is forbidden: the wrong probe, not probing.
echo "== #263 ToolSearch is still never the oracle for a native primitive =="
have skills/harness/SKILL.md \
  'Never .ToolSearch. for the answer' \
  "#263 harness SKILL keeps the ToolSearch-is-the-wrong-index fact"
have agents/conductor.md \
  'the visible tool list is the only valid oracle' \
  "#263 conductor names the visible tool list as the oracle"

# The rendered boot prompt is where a spawned conductor actually READS its
# contract — doctrine that never reaches the brief is doctrine the teammate
# never sees. commands/spawn.md promises this line renders from the stable
# block; this leg is what makes that promise checkable.
echo "== #263 the probe directive reaches the rendered boot brief =="
have services/cli/shepherd_cli/templates/boot-prompt.md.j2 \
  'WORKFLOW-VEHICLE-PROBE' \
  "#263 boot prompt instructs the conductor to probe before its first fan-out"
have services/cli/shepherd_cli/templates/boot-prompt.md.j2 \
  'fanout_downgrade_reason' \
  "#263 boot prompt names the downgrade record"
have commands/spawn.md \
  'WORKFLOW-VEHICLE-PROBE' \
  "#263 spawn.md describes the probe directive the template renders"

echo "== #263 a downgrade is legitimate only when RECORDED =="
have agents/conductor.md \
  'fanout_downgrade_reason' \
  "#263 conductor WAVE-COMPLETE carries the downgrade reason"
have agents/conductor.md \
  'workflow_tool: "present"' \
  "#263 conductor WAVE-COMPLETE expects workflow_tool present"
have agents/conductor.md \
  'fanout: "workflow"' \
  "#263 conductor WAVE-COMPLETE expects a compiled workflow"
have agents/auditor.md \
  'FANOUT-VEHICLE-DOWNGRADE' \
  "#263 auditor grades a silent downgrade as a finding"
missing agents/auditor.md \
  'workflow_tool: absent. \+ .fanout: in-context. is EXPECTED and CORRECT' \
  "#263 auditor no longer certifies the in-context vehicle as correct"

echo "== #263 the #255 pin law widens with the vehicle rather than relaxing =="
have agents/conductor.md \
  'agentType: "shepherd:<role>"' \
  "#255/#263 conductor pins agentType on every agent() call"
have agents/engineer.md \
  'flockAgent\(\)' \
  "#255/#263 engineer authors agent() through the guarded wrapper"
have skills/shepherd/references/wave-routine.md \
  'agentType: "shepherd:coder"' \
  "#255/#263 wave-routine's compile schematic shows both pins"

echo "== #263 the resource counterweight still binds at the new tiers =="
have agents/conductor.md \
  'Fan-out counterweight' \
  "#256/#263 conductor cites the counterweight it is now bound by"
have skills/shepherd/references/pipeline.md \
  'Fan-out counterweight' \
  "#256/#263 pipeline cites the counterweight beside the new authorization"

echo "== #263 the invariant matrix agrees with the bodies =="
have skills/shepherd/references/invariant-matrix.md \
  'test_v643_wiring.sh' \
  "#263 invariant matrix points at this file as the pin"
missing skills/shepherd/references/invariant-matrix.md \
  'compiles to a Dynamic Workflow at ROOT ONLY' \
  "#263 invariant row 3 is no longer root-only"

# #251 is deliberately NOT resolved by #263 — the probe is agnostic to which
# failure mode is real. A body that re-asserts either reading as settled fact
# would reintroduce exactly the confident-but-unverified claim #263 removed.
echo "== #263 does not silently resolve the open #251 measurement dispute =="
have agents/conductor.md \
  '#251' \
  "#251 conductor still records the open question"
have skills/harness/SKILL.md \
  'NOT resolved by #263' \
  "#251 harness SKILL keeps the dispute open rather than papering over it"

if [[ "$fails" -gt 0 ]]; then
  printf 'test_v643_wiring: %d leg(s) FAILED — the #263 vehicle inversion has drifted\n' "$fails"
  exit 1
fi
printf 'test_v643_wiring: OK — #263 vehicle law wired across conductor/engineer/auditor/harness/pipeline/wave-routine/invariant-matrix\n'
exit 0
