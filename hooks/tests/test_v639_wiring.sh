#!/usr/bin/env bash
# hooks/tests/test_v639_wiring.sh — v6.3.9 doctrine-wiring regression guard.
#
# The v6.3.9 patch closes six token-costing bugs the dev.6 shepherd session
# filed (#220-#225). Several are behavioral WIRING spread across scripts, agent
# profiles, migrations, and doctrine — the mechanical behavior is pinned by the
# per-issue tests (test_worktree_root_resolution, test_graph_next,
# test_coordinate_drive_guard, test_teammate_git_guard, test_lead_workflow_tool);
# this file asserts the cross-file contract legs agree, so no leg drifts back.
#
# Same shape as test_v638_wiring.sh (have/missing over the tracked tree).

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

echo "== #220 Workflow denied in subagents → in-context Agent() is first-class =="
have skills/harness/SKILL.md          'not available inside subagents'   "#220 harness SKILL owns the Workflow platform fact"
have skills/harness/SKILL.md          'presence controls the OFFER'      "#220 harness SKILL: grant is offer, not runtime permission"
have skills/shepherd/references/wave-routine.md 'PERMANENT mode'         "#220 wave-routine: conductor in-context is permanent, not a fallback"
have skills/shepherd/references/pipeline.md     'DRIVER-CONDITIONAL'     "#220 pipeline lane law is driver-conditional"
have agents/conductor.md              'DISPATCH MODE'                    "#220 conductor §DISPATCH MODE supersedes the Workflow self-check"
have agents/engineer.md               'denied to you'                    "#220 engineer fans out in-context (Workflow denied)"

echo "== #221 shctx registry resolves to the shared main worktree =="
have skills/context/scripts/_lib.sh       'git rev-parse --git-common-dir' "#221 shctx_repo_root resolves via git-common-dir"
have skills/context/scripts/_lib.sh       'shctx_in_subworktree'           "#221 linked-worktree detector present"
have skills/context/scripts/cmd_doctor.sh 'stray worktree DB'             "#221 doctor warns on a stray per-worktree DB"
have skills/context/tests/test_worktree_root_resolution.sh 'lane-root-resolves-to-main' "#221 regression test asserts lane→main resolution"

echo "== #222 conductor commits AND pushes its own lane branch =="
have    hooks/scripts/teammate_git_guard.sh 'merge\|rebase\|cherry-pick' "#222 guard blocks merge/rebase/cherry-pick (integration)"
missing hooks/scripts/teammate_git_guard.sh 'merge\|rebase\|push'        "#222 guard no longer blocks push (lane-branch publish is allowed)"
have    commands/spawn.md                   'lane-branch git push are YOURS' "#222 spawn boot-brief allows lane-branch push"
have    agents/conductor.md                 'git_custody'                "#222 WAVE-COMPLETE carries a git_custody attestation"
have    skills/shepherd/references/escalation.md 'git_custody.committed' "#222 WAVE-COMPLETE-UNVERIFIED cross-checks the attestation"

echo "== #223 coordinate-drive guard fires only for the recorded lead =="
have skills/context/schema/migrations/0021_spawn_lead.sql 'CREATE TABLE IF NOT EXISTS spawn_leads' "#223 migration 0021 creates spawn_leads"
have skills/context/scripts/cmd_teammate.sh      'register-lead'         "#223 teammate register-lead subcommand exists"
have hooks/scripts/coordinate_drive_guard.sh     'spawn_leads'           "#223 guard lead-only gate reads spawn_leads"
# v6.5.0 #232 superseded the #223 conservative OTHER_LEAD bystander predicate:
# the guard now requires POSITIVE lead identity (MY_LEAD > 0) and exits for any
# unresolvable identity — pin the new shape and the marker fail-close.
have hooks/scripts/coordinate_drive_guard.sh     'MY_LEAD" -gt 0'        "#232 guard requires positive recorded-lead identity"
have hooks/scripts/coordinate_drive_guard.sh     'session_tier_marker'   "#232/#228 guard fail-closes on the session-tier teammate marker"
have commands/spawn.md                           'register-lead'         "#223 spawn boot wires register-lead at spawn"

echo "== #224 misrouted sub-dispatch completions are polled + relayed =="
have agents/conductor.md 'Defensive poll'  "#224 conductor defensive-polls a misrouted sub-dispatch notification"
have agents/shepherd.md  'RELAY'           "#224 root relays leaked sub-flock completions to the owning conductor"
have agents/worker.md    '^- Lane:'        "#224 WORKER REPORT carries Lane for the relay match key"

echo "== #225 graph next normalizes/guards agents entries =="
have skills/context/scripts/cmd_plan.sh  'malformed agents entry' "#225 plan extract/validate reject malformed agents"
have skills/context/scripts/cmd_graph.sh 'isinstance\(a, dict\)'  "#225 graph readers guard non-dict agents entries"
have skills/context/tests/test_graph_next.sh '@engineer'          "#225 regression test exercises the bare-string agents shorthand"

if [[ "$fails" -eq 0 ]]; then echo "—— v6.3.9 wiring: OK ——"; else echo "—— v6.3.9 wiring: $fails FAIL ——"; fi
exit "$fails"
