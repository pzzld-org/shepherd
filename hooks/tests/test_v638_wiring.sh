#!/usr/bin/env bash
# hooks/tests/test_v638_wiring.sh — v6.3.8 doctrine-wiring regression guard.
#
# The v6.3.8 "dev.5 evidence cluster" (#213 journal wave-return, #214 disk guard,
# #215 coder governance, #216 LOC counter, #217 /shepherd:start wave routine) plus
# the two #207-class tool-wiring gaps the build wave surfaced (root missing
# Workflow, critic missing Bash) are behavioral WIRING spread across new scripts,
# a canonical reference, a command, six agent/doctrine files, and the lint. Each
# concern's legs must AGREE or the guarantee is only half-true. This file fails if
# any leg is dropped or a citation dangles. The script BEHAVIOR itself is pinned by
# test_loc_count.sh / test_journal_status.sh / test_df_guard.sh; this asserts the
# prose/contract legs match the mechanism.

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
exists() { # exists <file> <label>
  if [[ -f "$REPO_ROOT/$1" ]]; then printf '  PASS  %s\n' "$2"
  else printf '  FAIL  %s — %s missing\n' "$2" "$1"; fails=$((fails+1)); fi
}

echo "== #217 wave routine (single canonical definition) + /shepherd:start =="
exists skills/shepherd/references/wave-routine.md            "wave-routine.md canonical reference exists"
have skills/shepherd/references/wave-routine.md '## Per-wave compile'      "wave-routine defines §Per-wave compile"
have skills/shepherd/references/wave-routine.md '## Root gate'             "wave-routine defines the serial §Root gate"
have skills/shepherd/references/wave-routine.md '## Abbreviated conductor' "wave-routine defines the abbreviated conductor driver"
have skills/shepherd/references/wave-routine.md '## Fallback semantics'    "wave-routine defines the agent-teams fallback"
have skills/shepherd/references/wave-routine.md 'journal-status.sh'        "wave-routine root gate cites journal-status (#213)"
have skills/shepherd/references/wave-routine.md 'loc-count.py'             "wave-routine cites loc-count (#216)"
have skills/shepherd/references/wave-routine.md 'df-guard.sh'             "wave-routine hard-rule preamble cites df-guard (#214)"
exists commands/start.md                                    "/shepherd:start command resurrected"
have commands/start.md '^allowed-tools:.*\bWorkflow\b'      "start.md grants Workflow (the whole command drives workflows; #207 class)"
have commands/start.md 'wave-routine\.md'                   "start.md references the canonical wave routine, not a re-definition"
have agents/shepherd.md 'Root-drives-workflows mode'        "shepherd.md wires the root direct-drive / fallback mode"
have agents/shepherd.md 'wave-routine\.md'                  "shepherd.md references the wave routine"
have agents/conductor.md 'lane walk IS the wave routine'    "conductor §Lane walk is the abbreviated wave routine"
have agents/conductor.md 'wave-routine\.md'                 "conductor.md references the wave routine"
have commands/spawn.md 'wave-routine\.md'                   "spawn.md: conductors run the abbreviated wave routine"

echo "== #216 deterministic LOC counter =="
exists scripts/loc-count.py                                 "loc-count.py exists"
have skills/shepherd/references/pipeline.md 'Deterministic LOC \(#216\)' "pipeline §Gates documents the deterministic LOC assert"
have skills/shepherd/references/pipeline.md 'loc-count\.py'  "pipeline cites loc-count.py"
have hooks/tests/run.sh 'test_loc_count\.sh'                "loc-count test wired into the hook suite"

echo "== #213 journal.jsonl wave-return signal =="
exists scripts/journal-status.sh                            "journal-status.sh exists"
have skills/shepherd/references/pipeline.md 'Wave-return signal \(#213\)' "pipeline documents the journal wave-return signal"
have skills/shepherd/references/pipeline.md 'journal-status\.sh'          "pipeline cites journal-status.sh"
have agents/shepherd.md 'journal\.jsonl. path in the plan frontmatter|runId. \+ absolute .journal\.jsonl. path in the plan frontmatter' "shepherd records runId+journal path in plan frontmatter (survives /compact)"
have hooks/tests/run.sh 'test_journal_status\.sh'          "journal-status test wired into the hook suite"

echo "== #214 disk-pressure guard =="
exists scripts/df-guard.sh                                  "df-guard.sh exists"
have skills/shepherd/references/pipeline.md 'Disk discipline \(#214\)'    "pipeline §Gates documents disk discipline"
have skills/shepherd/references/pipeline.md 'df-guard\.sh --min=12'       "pipeline cites the df-guard precheck"
have agents/coder.md 'df-guard\.sh'                         "coder.md carries the df-guard precheck expectation"
have agents/auditor.md 'Disk discipline \(#214\)'           "auditor.md wires shared CARGO_TARGET_DIR + delete-on-PASS"
have agents/auditor.md 'df-guard\.sh --min=12'              "auditor.md runs df-guard before cargo"
have hooks/tests/run.sh 'test_df_guard\.sh'                "df-guard test wired into the hook suite"

echo "== #215 coder governance + the ONE-LOC rule =="
have agents/coder.md 'ONE-LOC rule'                         "coder.md states the ONE-LOC rule verbatim"
have agents/coder.md 'LOC-BUDGET-GOVERNANCE'               "coder.md has the governance-escalation halt code"
have agents/coder.md 'Dropping a mandated deliverable is NEVER a valid LOC remedy' "coder.md forbids dropping a deliverable to fit budget"

echo "== #207-class tool-wiring gaps (surfaced by the build wave's audit) =="
have agents/shepherd.md '^tools:.*\bWorkflow\b'             "shepherd frontmatter grants Workflow (root can drive workflows)"
have agents/critic.md '^tools:.*\bBash\b'                   "critic frontmatter grants Bash (its Step 0.5 shctx runs)"
have hooks/tests/lint_agent_capabilities.sh 'LEAD_MANDATED_WORKFLOW="engineer conductor shepherd"' "lint pins root's Workflow grant"
have hooks/tests/lint_agent_capabilities.sh 'read-only-role Bash PRESENCE' "lint pins read-only shctx-runners grant Bash"
have hooks/tests/test_exec_bits.sh "scripts/\*\.sh"        "exec-bits guard covers the new scripts/ tools"

echo "== root-drives-workflows doctrine reconciliation (verify-wave findings) =="
have skills/shepherd/SKILL.md 'root-drives-workflows mode'  "SKILL.md Dispatch law carves out the root-@coder fallback"
have agents/shepherd.md 'or by root itself in'             "shepherd prohibition #2 carves out root-driven @coder"
have agents/shepherd.md 'BODY runs as root-driven Dynamic-Workflow waves' "shepherd prohibition #12 carves out the direct-drive BODY"
have agents/shepherd.md 'per-wave SOURCE commit in root-drives-workflows'  "shepherd side-effect boundary permits the wave source commit"
have hooks/scripts/bash_guard.sh 'CRITIC-MUTATE'           "bash_guard Check 3 blocks @critic shell mutation (critic gained Bash)"
have hooks/tests/run.sh 'test_readonly_bash_guard\.sh'     "read-only reviewer mutate-guard test wired into the suite"

echo "== deterministic-tooling behavior pinned by dedicated tests =="
have hooks/tests/run.sh 'test_v638_wiring\.sh'             "this wiring test is itself wired into the suite"
have skills/shepherd/references/invariant-matrix.md 'wave-routine|/shepherd:start|#217' "invariant-matrix records the v6.3.8 wave routine"

if [[ "$fails" -eq 0 ]]; then echo "—— v6.3.8 wiring: OK ——"; else echo "—— v6.3.8 wiring: $fails FAIL ——"; fi
exit "$fails"
