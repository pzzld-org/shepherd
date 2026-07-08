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

echo "== #185 worker GH MCP write + CLI fallback =="
have agents/worker.md 'mcp__plugin_github_github__add_issue_comment' "#185 worker grants add_issue_comment"
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
if [[ -x "$REPO_ROOT/hooks/scripts/coder_git_guard.sh" ]]; then
  printf '  PASS  %s\n' "#187 coder_git_guard.sh is executable"
else
  printf '  FAIL  %s — coder_git_guard.sh not executable\n' "#187 exec-bit"; fails=$((fails+1))
fi

if [[ "$fails" -eq 0 ]]; then echo "—— v6.3.0 wiring: OK ——"; else echo "—— v6.3.0 wiring: $fails FAIL ——"; fi
exit "$fails"
