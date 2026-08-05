#!/usr/bin/env bash
# hooks/tests/test_v630_wiring.sh — v6.3.0 doctrine-wiring regression guard
# (#181/#183/#184/#185/#186/#187).
#
# Several v6.3.0 fixes are behavioral WIRING across doctrine + profiles rather
# than a single hook payload path. This guard fails if any load-bearing leg is
# dropped or a citation dangles — the same shape as
# test_engineer_self_contained.sh (v6.2.5) and test_flock_output_review.sh
# (v6.2.4). Hook-behavioral legs have their own payload-driven tests
# (test_coder_git_guard.sh, test_teammate_idle.sh, test_graph_compile.sh);
# this file asserts the prose/contract legs agree with them.

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

echo "== #184 conductor boot lead-attested escape =="
have agents/conductor.md 'BOOT-FORMAT: lead-attested'          "#184 conductor §Boot verification documents the marker"
have agents/conductor.md 'checks 1 and 3 relax'                "#184 marker relaxes shape checks 1+3 to substance"
have agents/conductor.md 'check 2 \(.dispatcher: teammate-conductor.\) is NEVER relaxed' "#184 dispatcher check is never relaxed"
have commands/spawn.md    'BOOT-FORMAT: lead-attested'         "#184 spawn.md documents the marker for leads"
have skills/shepherd/references/escalation.md 'lead-attested' "#184 escalation.md TEAMMATE-BOOT-MALFORMED notes the escape"

echo "== #185 worker GH write capability + CLI fallback =="
# SUPERSEDED by v6.4.3 (#110 enforcement). This leg pinned the literal token
# `mcp__plugin_github_github__add_issue_comment` in worker.md's frontmatter.
# That token named ONE server's ONE naming scheme, which shepherd cannot
# guarantee exists — the same capability is `mcp__github__*` natively and
# `mcp__MCP_DOCKER__*` behind a Docker MCP gateway. All 129 provider tokens
# were dropped from agent frontmatter; the capability is now DISCOVERED via
# ToolSearch, and lint_agent_capabilities.sh fails on any re-added token.
# What #185 actually cared about — that the worker can write to GitHub and
# degrades to the sanctioned CLI when it cannot — is pinned by the two legs
# below, which were always the load-bearing half.
have agents/worker.md 'ToolSearch' "#185→#110 worker can DISCOVER the GH write capability at runtime"
have agents/worker.md 'SANCTIONED write fallback'                    "#185 worker.md sanctions CLI fallback when MCP unavailable"
have skills/shepherd/SKILL.md 'SANCTIONED write fallback'            "#185 SKILL.md §MCP-over-CLI sanctions CLI fallback"

echo "== #186 engineer SendMessage grant =="
have agents/engineer.md '^tools:.*\bSendMessage\b'                   "#186 engineer frontmatter grants SendMessage"

echo "== #187 coder no-git custody =="
have hooks/scripts/coder_git_guard.sh 'CODER-GIT-WRITE'              "#187 coder_git_guard.sh exists + emits CODER-GIT-WRITE"
have hooks/hooks.json 'coder_git_guard.sh'                           "#187 coder_git_guard.sh registered in hooks.json"
have agents/coder.md 'CODER-GIT-WRITE'                               "#187 coder.md registers CODER-GIT-WRITE halt"
have agents/coder.md 'NEVER run git at all'                          "#187 coder.md prohibits all git"
have agents/coder.md '### Step 5 — Hand off \(no git\)'             "#187 coder.md Step 5 is no-git hand-off"
missing agents/coder.md 'Stage only your files.*Commit with the'    "#187 coder.md old commit Step 5 removed"
have skills/shepherd/references/flock.md 'ZERO git'                  "#187 flock.md §@coder: coders run ZERO git"
have skills/shepherd/references/flock.md 'the CONDUCTOR commits coder output' "#187 flock.md: conductor commits coder output"
have agents/conductor.md 'Commit custody is yours, PASS-gated'       "#187 conductor.md §Lane walk: PASS-gated commit custody"
have skills/shepherd/references/escalation.md 'CODER-GIT-WRITE'      "#187 escalation.md registers CODER-GIT-WRITE"
have hooks/scripts/_lib.sh 'git rev-parse --git-common-dir'          "#187 current_role resolves the dispatch record from a linked worktree"
have hooks/scripts/coder_git_guard.sh 'ALWAYS runs'                  "#187 guard runs the raw write-scan backstop unconditionally (bash -c bypass)"
if [[ -x "$REPO_ROOT/hooks/scripts/coder_git_guard.sh" ]]; then
  printf '  PASS  %s\n' "#187 coder_git_guard.sh is executable"
else
  printf '  FAIL  %s — coder_git_guard.sh not executable\n' "#187 exec-bit"; fails=$((fails+1))
fi

echo "== #183 teammate registration + idle routing =="
have skills/context/scripts/cmd_teammate.sh 'conductor\|shepherd:conductor\|engineer\|shepherd:engineer' "#183 register gate allows conductor + engineer"
have skills/context/scripts/cmd_teammate.sh 'ON CONFLICT\(project_id, team_name, teammate_name\)'      "#183 register is an idempotent upsert"
have commands/spawn.md 'Register teammates \(mandatory\)'                                                "#183 spawn path registers teammates before liveness"
have commands/spawn.md 'shctx teammate register .* --type=engineer'                                      "#183 spawn registers the self-contained engineer teammate"
have hooks/scripts/teammate_idle.sh "'\.agent_id'"                                                       "#183 idle hook reads .agent_id identity fallback"
have hooks/scripts/teammate_idle.sh 'no live rows'                                                       "#183 idle hook suppresses flood when no spawn is live"

echo "== #181/#180 compile-down model pin =="
have skills/context/scripts/cmd_graph.sh '\(\) => agent\(briefs'                                         "#180 compiler emits () => agent(prompt, opts) — real signature, static pin"
have skills/context/scripts/cmd_graph.sh 'agentType: .* model:'                                          "#180 compiler injects agentType + model pin"
have skills/context/scripts/cmd_graph.sh '"model_pin"'                                                   "#180 --verify has the model_pin invariant"
have skills/context/scripts/cmd_graph.sh '_graph_role_model'                                             "#180 model resolved from [models] via cfg_section_get"
missing skills/context/scripts/cmd_graph.sh 'subagent_type: .shepherd:.\{s'                              "#180 legacy subagent_type emission removed"
have skills/harness/references/workflow-templates.md 'Pinned.* \(#180\)'                                 "#180 workflow-templates §Compile-down adds the Pinned invariant"
have docs/specs/v630-dispatch-pin-dsl-decision.md 'Decision: do NOT build the broad DSL now'             "#181 explore/decision doc records the DSL decision"
have hooks/scripts/bash_guard.sh 'subagent_type\|agentType'                                              "#180 bash_guard Check 0-bis matches the renamed agentType key"

if [[ "$fails" -eq 0 ]]; then echo "—— v6.3.0 wiring: OK ——"; else echo "—— v6.3.0 wiring: $fails FAIL ——"; fi
exit "$fails"
