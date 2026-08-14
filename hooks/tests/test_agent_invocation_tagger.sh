#!/usr/bin/env bash
# hooks/tests/test_agent_invocation_tagger.sh — tests for
# agent_invocation_tagger.sh (NEW, DF-77 FIX 1).
#
# DF-77: 63/63 live dispatch records carried agent_role:"unknown" because the
# tagger's ONLY role signal was a `^# @<role>` grep over tool_input.prompt —
# but skills/shepherd/SKILL.md §Dispatch law mandates "put the brief in
# `prompt`, NEVER inline-embed the agent body," so that header can never
# legally be there. FIX 1 makes tool_input.subagent_type (the field the
# dispatch law GUARANTEES present — dispatch_guard.sh already denies a
# dispatch missing it) the PRIMARY signal, keeping the prompt-header grep as
# a secondary fallback only.
#
# This file asserts:
#   1. a REALISTIC, dispatch-law-COMPLIANT payload (subagent_type set, prompt
#      carries NO `# @<role>` header) produces a record with the RIGHT
#      agent_role — the exact shape that was broken 63/63 times before FIX 1.
#   2. every closed-flock role resolves via subagent_type (not just coder).
#   3. NEGATIVE CONTROL: a payload with NO subagent_type and no `# @<role>`
#      header does NOT silently produce a plausible-looking role — it must
#      resolve to "unknown", never guessed.
#   4. NEGATIVE CONTROL: an off-flock subagent_type (not one of the six flock
#      roles, nor shepherd:conductor) is rejected by the validation, not
#      passed through verbatim — falls through to "unknown" (no prompt header
#      either).
#   5. the secondary fallback still resolves a hand-rolled dispatch (no
#      subagent_type, but a `# @<role>` prompt header) — kept for exactly
#      that degrade path, tried only when the primary signal is absent.
#   6. Task (not just Agent) is tagged.
#   7. a non-Agent/Task tool never gets tagged.
#   8. no shepherd.toml → no record, no crash (never-blocks contract).

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$(cd "$HERE/../scripts" && pwd)/agent_invocation_tagger.sh"

fails=0; total=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s — %s\n' "$1" "$2"; fails=$((fails+1)); }

if ! command -v python3 >/dev/null 2>&1; then
  printf '  SKIP  all cases — python3 required to build payloads and inspect JSON records\n'
  exit 0
fi

# Ephemeral shepherd-flagged repo (the hook gates on .claude/shepherd.toml).
tmp=$(mktemp -d -t shep-tagger-test.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp" || exit 1
git init -q . && git config user.email t@t && git config user.name t
git -c commit.gpgsign=false commit -q --allow-empty -m init
mkdir -p .claude && touch .claude/shepherd.toml
sprint=$(git rev-parse --abbrev-ref HEAD)

# <tool_name> <tool_use_id> <subagent_type|""> <prompt>
AGENT_PAYLOAD() {
  python3 -c '
import json, sys
tool, tid, sat, prompt = sys.argv[1:5]
ti = {"model": "claude-sonnet-5", "prompt": prompt}
if sat:
    ti["subagent_type"] = sat
print(json.dumps({"session_id": "s", "tool_name": tool, "tool_use_id": tid, "tool_input": ti}))
' "$1" "$2" "$3" "$4"
}

run_tagger() { # <payload>
  printf '%s' "$1" | bash "$SCRIPT" >/dev/null 2>&1 || true
}

record_role() { # <tool_use_id>
  local f=".shepherd/dispatch/$sprint/$1.json"
  [[ -f "$f" ]] || { printf '__NO_RECORD__'; return; }
  python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('agent_role','__MISSING_FIELD__'))" "$f" 2>/dev/null || printf '__PARSE_ERROR__'
}

record_declared_source() { # <tool_use_id>
  local f=".shepherd/dispatch/$sprint/$1.json"
  [[ -f "$f" ]] || { printf '__NO_RECORD__'; return; }
  python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('declared_source','__MISSING_FIELD__'))" "$f" 2>/dev/null || printf '__PARSE_ERROR__'
}

check_role() { # <label> <tool_use_id> <expected_role>
  total=$((total+1))
  local got; got=$(record_role "$2")
  if [[ "$got" == "$3" ]]; then pass "$1"; else fail "$1" "expected agent_role=$3, got $got"; fi
}

# --- case 1: dispatch-law-compliant payload — the exact shape that was
# broken 63/63 times (subagent_type set, prompt carries NO # @<role> header,
# matching the real dispatch-law-mandated brief-only prompt) ---------------
run_tagger "$(AGENT_PAYLOAD Agent tida-coder shepherd:coder 'implement the thing. no role header here, per dispatch law.')"
check_role "dispatch-law-compliant coder payload -> agent_role=coder (FIX 1, the 63/63 bug)" tida-coder coder

# --- case 2: every closed-flock role resolves via subagent_type -----------
run_tagger "$(AGENT_PAYLOAD Agent tida-engineer  shepherd:engineer  'plan the sprint')"
check_role "subagent_type=shepherd:engineer -> agent_role=engineer" tida-engineer engineer
run_tagger "$(AGENT_PAYLOAD Agent tida-critic    shepherd:critic    'gate the plan')"
check_role "subagent_type=shepherd:critic -> agent_role=critic"     tida-critic critic
run_tagger "$(AGENT_PAYLOAD Agent tida-auditor   shepherd:auditor   'grade the diff')"
check_role "subagent_type=shepherd:auditor -> agent_role=auditor"   tida-auditor auditor
run_tagger "$(AGENT_PAYLOAD Agent tida-worker    shepherd:worker    'run the batch')"
check_role "subagent_type=shepherd:worker -> agent_role=worker"     tida-worker worker
run_tagger "$(AGENT_PAYLOAD Agent tida-discovery shepherd:discovery 'investigate')"
check_role "subagent_type=shepherd:discovery -> agent_role=discovery" tida-discovery discovery
run_tagger "$(AGENT_PAYLOAD Agent tida-conductor shepherd:conductor 'run the lane')"
check_role "subagent_type=shepherd:conductor -> agent_role=conductor" tida-conductor conductor

# --- case 3: NEGATIVE CONTROL — no subagent_type, no prompt header --------
# Must NOT silently produce a plausible-looking role.
run_tagger "$(AGENT_PAYLOAD Agent tida-nosignal '' 'just a plain prompt with no header and no subagent_type')"
check_role "NO subagent_type, no header -> unknown (not silently guessed)" tida-nosignal unknown
total=$((total+1))
got_src=$(record_declared_source tida-nosignal)
if [[ "$got_src" == "role-unresolved" ]]; then
  pass "unresolved role -> declared_source=role-unresolved (schema honesty)"
else
  fail "unresolved role -> declared_source=role-unresolved (schema honesty)" "got $got_src"
fi

# --- case 4: NEGATIVE CONTROL — off-flock subagent_type -------------------
# Not one of the six flock roles nor shepherd:conductor; must not pass through
# verbatim (e.g. as agent_role="bogus" or "general-purpose").
run_tagger "$(AGENT_PAYLOAD Agent tida-offflock shepherd:bogus-role 'no header either')"
check_role "off-flock subagent_type -> unknown (validated, not passed through)" tida-offflock unknown
run_tagger "$(AGENT_PAYLOAD Agent tida-builtin general-purpose 'built-in agent type, no header')"
check_role "built-in subagent_type (general-purpose) -> unknown" tida-builtin unknown

# --- case 5: secondary fallback — hand-rolled dispatch, no subagent_type,
# but a legacy `# @<role>` prompt header -----------------------------------
run_tagger "$(AGENT_PAYLOAD Agent tida-fallback '' '# @coder
rest of a hand-rolled prompt that inlines the header')"
check_role "no subagent_type + '# @coder' header -> coder (secondary fallback)" tida-fallback coder

# --- case 6: Task tool also tagged -----------------------------------------
run_tagger "$(AGENT_PAYLOAD Task tida-task shepherd:coder 'dispatched via Task, not Agent')"
check_role "Task(subagent_type=shepherd:coder) -> agent_role=coder" tida-task coder

# --- case 7: non-Agent/Task tool never tagged ------------------------------
total=$((total+1))
run_tagger "$(python3 -c 'import json; print(json.dumps({"session_id":"s","tool_name":"Bash","tool_use_id":"tida-bash","tool_input":{"command":"ls"}}))')"
if [[ -f ".shepherd/dispatch/$sprint/tida-bash.json" ]]; then
  fail "Bash tool call never gets a dispatch record" "record was written"
else
  pass "Bash tool call never gets a dispatch record"
fi

# --- case 8: no shepherd.toml -> no record, no crash -----------------------
total=$((total+1))
bare=$(mktemp -d -t shep-tagger-bare.XXXXXX)
(
  cd "$bare"; git init -q .; git config user.email t@t; git config user.name t
  git -c commit.gpgsign=false commit -q --allow-empty -m init
  printf '%s' "$(python3 -c 'import json; print(json.dumps({"session_id":"s","tool_name":"Agent","tool_use_id":"tida-bare","tool_input":{"subagent_type":"shepherd:coder","prompt":"x"}}))')" \
    | bash "$SCRIPT" >/dev/null 2>&1
  rc=$?
  if [[ $rc -ne 0 ]]; then
    printf '  FAIL  no-shepherd-toml: never blocks — exit %d\n' "$rc"; exit 1
  fi
  if [[ -d ".shepherd" ]]; then
    printf '  FAIL  no-shepherd-toml: no record written — .shepherd/ exists\n'; exit 1
  fi
  printf '  PASS  no-shepherd-toml: never blocks, no record\n'
) || fails=$((fails+1))
rm -rf "$bare"

echo "—— $((total-fails))/$total passed ——"
exit "$fails"
