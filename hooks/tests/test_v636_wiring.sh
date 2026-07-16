#!/usr/bin/env bash
# hooks/tests/test_v636_wiring.sh — v6.3.6 doctrine-wiring regression guard
# (#207 lead-Workflow mandate, #206 seed-ready phantom-unread).
#
# Same shape as test_v630_wiring.sh: several v6.3.6 fixes are behavioral WIRING
# spread across a lint, a hook, and multiple doctrine/profile files rather than a
# single hook payload path. Each concern has THREE legs that must agree, or the
# "regression guard" is only half-true:
#   #207 — authoring-time lint (lint_agent_capabilities.sh) + runtime grading
#          (auditor.md §Dispatch-substrate) + documentation (invariant-matrix).
#   #206 — the guard SQL (coordinate_drive_guard.sh) + its regression cases.
# This file fails if any leg is dropped or a citation dangles. The mechanical
# behavior itself is pinned by test_lead_workflow_tool.sh and
# test_coordinate_drive_guard.sh; this asserts the prose/contract legs match.

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

echo "== #207 lead-Workflow mandated-tool guard (three agreeing legs) =="
# Leg 1 — authoring-time lint.
have hooks/tests/lint_agent_capabilities.sh 'LEAD_MANDATED_WORKFLOW'    "#207 lint has the lead mandated-Workflow presence block"
have hooks/tests/lint_agent_capabilities.sh 'grep -qx .Workflow.'       "#207 lint token-matches the exact Workflow grant"
have hooks/tests/test_lead_workflow_tool.sh 'SHEPHERD_LINT_AGENTS_DIR'  "#207 strip-and-reintroduce test exercises the lint override"
have hooks/tests/run.sh 'test_lead_workflow_tool.sh'                    "#207 regression test wired into the hook suite"
have 'agents/engineer.md' '^tools:.*\bWorkflow\b'                       "#207 engineer frontmatter grants Workflow"
have 'agents/conductor.md' '^tools:.*\bWorkflow\b'                      "#207 conductor frontmatter grants Workflow"
# Leg 2 — runtime wave-review grading agrees (auditor must not wave `absent` through).
have    agents/conductor.md 'is the guaranteed path'                    "#207 conductor §WORKFLOW SELF-CHECK reconciled (present is guaranteed)"
missing agents/auditor.md   'absent. is correct'                        "#207 auditor no longer grades absent as unconditionally correct"
have    agents/auditor.md   '#207'                                      "#207 auditor §Dispatch-substrate cites the regression"
# Leg 3 — documentation.
have skills/shepherd/references/invariant-matrix.md 'LEAD_MANDATED_WORKFLOW|test_lead_workflow_tool' "#207 invariant-matrix row documents the lint+test pair"

echo "== #206 seed-ready phantom-unread narrowing =="
have    hooks/scripts/coordinate_drive_guard.sh "kind <> 'seed-ready'"  "#206 guard excludes seed-ready mail from the lead-bound unread count"
have    hooks/scripts/coordinate_drive_guard.sh '#206'                  "#206 guard comment cites the concern"
have    hooks/tests/test_coordinate_drive_guard.sh 'seed-ready unread: no block' "#206 regression case: seed-ready never blocks"
have    hooks/tests/test_coordinate_drive_guard.sh 'genuine still BLOCKs'         "#206 regression case: genuine lead-bound unread still blocks"
have    hooks/tests/test_coordinate_drive_guard.sh "kind TEXT NOT NULL"           "#206 test schema mirrors production mailbox.kind"

if [[ "$fails" -eq 0 ]]; then echo "—— v6.3.6 wiring: OK ——"; else echo "—— v6.3.6 wiring: $fails FAIL ——"; fi
exit "$fails"
