#!/usr/bin/env bash
# shepherd hook — PreToolUse(Agent|Task) role tagger (v5.1.2; role-signal fixed
# DF-77 FIX 1, #187/#215-adjacent field incident)
#
# Resolves the dispatched role from tool_input.subagent_type (PRIMARY signal
# — see DF-77 header note below) and writes a structured record at
# <ns>/dispatch/<sprint>/<tool_use_id>.json. Downstream PreToolUse hooks
# (bash_guard, lock_guard, coder_git_guard) read this record via
# `current_role()` (_lib.sh) to make role-conditional decisions.
#
# DF-77 (63/63 live dispatch records carried agent_role:"unknown" before this
# fix): the PRIOR implementation derived role by grepping tool_input.prompt
# for a `^# @<role>` header — but skills/shepherd/SKILL.md §Dispatch law
# mandates "put the brief in `prompt`, NEVER inline-embed the agent body," so
# that header lives in agents/<role>.md (loaded via subagent_type), never in
# the prompt this hook can see. tool_input.subagent_type is the one role
# signal the dispatch law GUARANTEES present: dispatch_guard.sh already
# denies a flock dispatch missing it (DISPATCH-MISSING-SUBAGENT-TYPE). The
# `# @<role>` prompt-header grep is kept as a SECONDARY fallback (covers a
# hand-rolled dispatch that bypassed subagent_type), tried only when the
# primary signal doesn't resolve.
#
# Input:  PreToolUse JSON { tool_name, tool_use_id, tool_input.{subagent_type,prompt}, ... }
# Output: silent exit 0 (never blocks; pure side-effect).
#
# Schema written:
#   {
#     "tool_use_id":            "<from hook input>",
#     "agent_role":             "engineer|critic|coder|auditor|worker|discovery|conductor|unknown",
#     "sprint":                 "<git branch at dispatch>",
#     "dispatched_at":          <unix-ts>,
#     "model":                  "<from tool_input.model>",
#     "sprint_branch_recorded": "<git rev-parse HEAD>",
#     "declared_tools":         [<tokens from agents/<role>.md 'tools:' frontmatter>],
#     "declared_source":        "agents/<role>.md#tools" | "role-unresolved",
#     "session_id":             "<from hook input, best-effort self-report lookup key>",
#     "observed_tools":         null,
#     "observed_at":            null,
#     "observed_source":        "self-report-pending"
#   }
#
# DF-17 (runtime capability guarantees are unverified): this hook fires
# PreToolUse, before the dispatched role's own session exists, so it can only
# ever record the DECLARED half of the contract (what agents/<role>.md's
# `tools:` frontmatter grants) — it has no introspection into what tools that
# session will actually see once it boots. `observed_tools`/`observed_at`/
# `observed_source` are written as an explicit PENDING placeholder, not
# omitted, so the schema is stable from the first write: the intended
# convention is that the dispatched role itself, from inside its own session,
# runs the tool-presence self-probe already mandated by
# `skills/harness/SKILL.md §Tool presence` (e.g. `WORKFLOW-VEHICLE-PROBE`) and
# then PATCHES this same record (matched by `session_id`, the most plausible
# durable key a running session could plausibly know about itself — matching
# on `tool_use_id` is not viable, since that identifier is never surfaced back
# into the dispatched session's own context) to fill in the observed side.
# No such self-report write exists yet anywhere in `agents/*.md` — wiring one
# is a future-wave follow-up (`agents/*.md` is outside this step's
# file_scope). `hooks/tests/lint_agent_capabilities.sh` is the reader half of
# this contract: it diffs `declared_tools` against any `observed_tools` a
# record actually carries and reports the delta as a finding.

set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
source "$HERE/_lib.sh"

# Echo the comma-separated, trimmed 'tools:' frontmatter tokens for an
# agents/<role>.md file (empty string if the file or the line is absent).
# The trailing '|| true' matters under this file's 'set -eu -o pipefail': an
# empty match (e.g. no 'tools:' line) makes grep exit 1, and pipefail would
# otherwise propagate that into the caller's assignment and abort the whole
# hook — this function must always return 0 to preserve "never blocks".
declared_tools_csv() {
  local f="$1"
  [[ -f "$f" ]] || return 0
  awk '/^tools:[[:space:]]/ {sub(/^tools:[[:space:]]*/, ""); print; exit}' "$f" \
    | tr ',' '\n' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' | grep -v '^$' | paste -sd, - 2>/dev/null || true
}

input=$(cat)
is_shepherd_project || exit 0

tool=$(json_field "$input" '.tool_name')
case "$tool" in Agent|Task) ;; *) exit 0 ;; esac

tool_use_id=$(json_field "$input" '.tool_use_id')
[[ -z "$tool_use_id" ]] && exit 0

subagent_type=$(json_field "$input" '.tool_input.subagent_type')
prompt=$(json_field "$input" '.tool_input.prompt')
model=$(json_field "$input" '.tool_input.model')
session=$(json_field "$input" '.session_id')

# PRIMARY signal (DF-77 FIX 1): tool_input.subagent_type. The dispatch law
# (skills/shepherd/SKILL.md §Dispatch law) makes "shepherd:<role>" mandatory
# on every flock/conductor dispatch, and dispatch_guard.sh already denies a
# dispatch missing it — so by the time this hook fires, a conforming
# dispatch's role is sitting right here, never buried in a prompt the same
# doctrine forbids the role header from ever appearing in.
role=""
case "$subagent_type" in
  shepherd:engineer|shepherd:critic|shepherd:coder|shepherd:auditor|shepherd:worker|shepherd:discovery|shepherd:conductor)
    role="${subagent_type#shepherd:}"
    ;;
esac

# SECONDARY signal (fallback only): a `# @<role>` header in the first 100
# lines of the prompt — covers a hand-rolled dispatch that skipped
# subagent_type (dispatch_guard.sh would deny it under the doctrine above,
# but this hook must still degrade gracefully for a dispatch it never saw
# gated, e.g. a pre-guard installation or a guard misconfiguration).
if [[ -z "$role" ]]; then
  role=$(printf '%s\n' "$prompt" | head -100 | grep -m1 -oE '^# @(engineer|critic|coder|auditor|worker|discovery)\b' | sed 's/^# @//' || true)
fi
role="${role:-unknown}"

sprint=$(current_sprint)
sprint_sha=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
ts=$(date +%s 2>/dev/null || echo 0)

# Declared half of the DF-17 capability record — see the file header for why
# 'observed_tools' below is always written as a pending placeholder, never
# derived here.
declared_csv=""
declared_source="role-unresolved"
role_file="$REPO_ROOT/agents/${role}.md"
if [[ "$role" != "unknown" && -f "$role_file" ]]; then
  declared_csv="$(declared_tools_csv "$role_file")"
  declared_source="agents/${role}.md#tools"
fi

ns=$(resolve_namespace)
dispatch_dir="$ns/dispatch/$sprint"
mkdir -p "$dispatch_dir" 2>/dev/null || exit 0
record_file="$dispatch_dir/${tool_use_id}.json"

if command -v jq &>/dev/null; then
  jq -n \
    --arg id "$tool_use_id" --arg role "$role" --arg sprint "$sprint" \
    --argjson ts "$ts" --arg model "$model" --arg sha "$sprint_sha" \
    --arg declared "$declared_csv" --arg dsrc "$declared_source" --arg sess "$session" \
    '{tool_use_id:$id, agent_role:$role, sprint:$sprint, dispatched_at:$ts,
      model:$model, sprint_branch_recorded:$sha,
      declared_tools: ($declared | split(",") | map(select(length>0))),
      declared_source: $dsrc, session_id: $sess,
      observed_tools: null, observed_at: null,
      observed_source: "self-report-pending"}' > "$record_file" 2>/dev/null || true
else
  python3 -c '
import json, sys
declared = [t for t in sys.argv[8].split(",") if t]
record = {
    "tool_use_id":            sys.argv[1],
    "agent_role":             sys.argv[2],
    "sprint":                 sys.argv[3],
    "dispatched_at":          int(sys.argv[4] or 0),
    "model":                  sys.argv[5],
    "sprint_branch_recorded": sys.argv[6],
    "declared_tools":         declared,
    "declared_source":        sys.argv[9],
    "session_id":             sys.argv[10],
    "observed_tools":         None,
    "observed_at":            None,
    "observed_source":        "self-report-pending",
}
with open(sys.argv[7], "w") as f:
    json.dump(record, f)
' "$tool_use_id" "$role" "$sprint" "$ts" "$model" "$sprint_sha" "$record_file" \
  "$declared_csv" "$declared_source" "$session" 2>/dev/null || true
fi

log_event "agent_invocation_tagger" "pass" "$tool" "$role" "$session" \
  "$(emit_json_obj agent_role "$role" sprint "$sprint" tool_use_id "$tool_use_id")"
exit 0
