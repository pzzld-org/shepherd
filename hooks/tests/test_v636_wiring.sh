#!/usr/bin/env bash
# hooks/tests/test_v636_wiring.sh — v6.3.6 doctrine-wiring regression guard
# (#207 lead-Workflow mandate, #206 mailbox retirement — completed v6.3.7).
#
# Same shape as test_v630_wiring.sh: several v6.3.6 fixes are behavioral WIRING
# spread across a lint, a hook, and multiple doctrine/profile files rather than a
# single hook payload path. Each concern has THREE legs that must agree, or the
# "regression guard" is only half-true:
#   #207 — authoring-time lint (lint_agent_capabilities.sh) + runtime grading
#          (auditor.md §Dispatch-substrate) + documentation (invariant-matrix).
#   #206 — mailbox removed (migration 0020 + guard + dispatcher) → dedicated
#          shctx signal channel; the v6.3.6 seed-ready workaround is retired.
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

echo "== #206 mailbox retired → dedicated shctx signal channel (v6.3.7 completion) =="
# The v6.3.6 seed-ready narrowing was a partial workaround over the generic
# mailbox. v6.3.7 removes the mailbox entirely (migration 0020) and replaces the
# ONE legitimate cross-session use with a dedicated `signal` channel. Every leg
# must agree the generic channel is GONE, not merely filtered.
missing hooks/scripts/coordinate_drive_guard.sh 'FROM mailbox'          "#206 guard no longer queries any mailbox table"
missing hooks/scripts/coordinate_drive_guard.sh "kind <> 'seed-ready'"  "#206 guard's seed-ready workaround retired with the table"
have    hooks/scripts/coordinate_drive_guard.sh '#206'                  "#206 guard comment cites the concern"
missing skills/context/scripts/shctx '\|mailbox\|'                      "#206 shctx dispatcher drops the mailbox subcommand"
have    skills/context/scripts/shctx '\|signal\|'                       "#206 shctx dispatcher routes the dedicated signal subcommand"
have    skills/context/scripts/cmd_signal.sh 'CROSS-SESSION'            "#206 dedicated cross-session signal command exists"
have    skills/context/schema/migrations/0020_drop_mailbox.sql 'DROP TABLE IF EXISTS mailbox'               "#206 migration 0020 drops the mailbox table"
have    skills/context/schema/migrations/0020_drop_mailbox.sql 'CREATE TABLE IF NOT EXISTS session_signals' "#206 migration 0020 creates the dedicated session_signals table"
have    skills/shepherd/references/spawn-flags.md 'shctx signal'        "#206 --staged doctrine uses the dedicated signal channel"
have    hooks/tests/test_coordinate_drive_guard.sh 'no mail channel'    "#206 guard test proves idle-only triggering (no mail dependency)"

if [[ "$fails" -eq 0 ]]; then echo "—— v6.3.6 wiring: OK ——"; else echo "—— v6.3.6 wiring: $fails FAIL ——"; fi
exit "$fails"
