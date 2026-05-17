#!/usr/bin/env bash
# shepherd hook — PostToolUse(Agent|Task): capture PAUSE-FOR-DEPENDENCY reports (v5.1.2)
#
# Mechanizes pause detection from doctrines/pause-for-dependency.md §III–IV.
# v5.1.2 extends this hook to ALSO write an auto-drafted dispatch brief stub
# alongside the JSON record — so the conductor reads a ready-to-fire brief
# instead of composing it from scratch.
#
# Input  (stdin): PostToolUse JSON { tool_name, tool_input, tool_response, ... }
# Output (stdout):
#   {"additionalContext":"..."}  surfaces pause-alert + brief-stub path
#   exit 0 silently               no pause detected.
#
# Writes:
#   <ns>/pauses/<id>.json        — structured pause record (canonical)
#   <ns>/pauses/<id>.brief.md    — auto-drafted dispatch brief stub for the satellite

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

input=$(cat)
is_shepherd_project || exit 0

tool=$(json_field "$input" '.tool_name')
case "$tool" in Agent|Task) ;; *) exit 0 ;; esac

response=$(json_response "$input")
# Fast path
printf '%s' "$response" | grep -qE 'Halt code:\s*PAUSE-FOR-DEPENDENCY' || exit 0

# ---------------------------------------------------------------------------
# Locate namespace and mint a sortable id
# ---------------------------------------------------------------------------
ns=$(resolve_namespace)
pauses_dir="$ns/pauses"
mkdir -p "$pauses_dir"

ts=$(date +%Y%m%dT%H%M%S 2>/dev/null || echo "unknown")
rand=$(od -An -tx1 -N4 /dev/urandom 2>/dev/null | tr -d ' \n' || echo "rnd")
pause_id="${ts}-${rand}"
pause_file="$pauses_dir/${pause_id}.json"
brief_file="$pauses_dir/${pause_id}.brief.md"

# ---------------------------------------------------------------------------
# Field extraction — tolerant to indentation/whitespace
# ---------------------------------------------------------------------------
_extract() {
  printf '%s' "$response" \
    | grep -m1 -E "^[[:space:]]*([-*][[:space:]]+)?${1}[[:space:]]*:" \
    | sed -E "s/^[[:space:]]*([-*][[:space:]]+)?${1}[[:space:]]*:[[:space:]]*//; s/[[:space:]]*$//"
}

lane=$(_extract "Lane" || true)
role=$(_extract "Role" || true)
reason=$(_extract "Reason" || true)
target_path=$(_extract "target_path" || true)
file_scope=$(_extract "file_scope_proposed" || true)
work=$(_extract "work" || true)
size=$(_extract "estimated_size" || true)
new_symbol=$(_extract "new_symbol_or_path" || true)
[[ -z "$new_symbol" ]] && new_symbol=$(_extract "new_symbol" || true)
satellite_role=$(_extract "satellite_role" || true)
[[ -z "$satellite_role" ]] && satellite_role="coder"
acceptance=$(_extract "acceptance" || true)
branch=$(_extract "branch" || true)
wip_sha=$(_extract "wip_sha" || true)
resume_cond=$(_extract "Resume condition" || true)
agent_id=$(_extract "Reporter" || true)
[[ -z "$agent_id" ]] && agent_id=$(_extract "Agent ID" || true)

# ---------------------------------------------------------------------------
# Write structured pause record (JSON)
# ---------------------------------------------------------------------------
python3 - "$pause_file" \
  "$pause_id" "$agent_id" "$role" "$lane" "$reason" \
  "$target_path" "$file_scope" "$work" "$size" "$new_symbol" \
  "$satellite_role" "$acceptance" "$branch" "$wip_sha" "$resume_cond" <<'PY'
import json, sys, time
(out_path, pause_id, agent_id, role, lane, reason,
 target_path, file_scope, work, size, new_symbol,
 satellite_role, acceptance, branch, wip_sha, resume_cond) = sys.argv[1:]
record = {
    "id": pause_id,
    "schema_version": 2,
    "status": "active",
    "paused_at": int(time.time()),
    "resolved_at": None,
    "satellite_sha": None,
    "agent_id":   agent_id,
    "agent_role": role,
    "lane":       lane,
    "reason":     reason,
    "satellite_request": {
        "target_path":         target_path,
        "file_scope_proposed": file_scope,
        "work":                work,
        "estimated_size":      size,
        "new_symbol_or_path":  new_symbol,
        "satellite_role":      satellite_role,
        "acceptance":          acceptance,
    },
    "lane_state": {"branch": branch, "wip_sha": wip_sha},
    "resume_condition": resume_cond,
    "brief_stub_path":  out_path.replace(".json", ".brief.md"),
}
with open(out_path, "w") as f:
    json.dump(record, f, indent=2)
PY

# ---------------------------------------------------------------------------
# Auto-draft satellite dispatch brief stub (v5.1.2)
# Shape varies by satellite_role. The brief is a near-complete dispatch
# stub the conductor reviews + adjusts + fires with minimal additional work.
# ---------------------------------------------------------------------------
sprint=$(current_sprint)
sprint_root_path=$(sprint_root)

case "$satellite_role" in
  discovery)
    cat > "$brief_file" <<EOF
# Satellite dispatch brief stub — @discovery
# Auto-drafted by agent_pause_detector.sh (v5.1.2)
# Source pause: ${pause_id}
# Paused agent: ${agent_id:-unknown} (${role:-unknown}) on lane: ${lane:-unknown}

[ROLE]            @discovery — read-only orientation

[QUESTION]
${work:-<refine: one-sentence question to answer>}

[SOURCES]
- ${target_path:-<refine: files/dirs to consult>}
- $(echo "$file_scope" | sed 's/^/- /')

[OUTPUT-PATH]    ${sprint_root_path}/.shepherd/reports/$(date -u +%Y-%m-%d)-discovery-${pause_id}.md

[BUDGET]
- Time: 10 min
- Max tool calls: 25

[FORMAT]
Markdown report. Required sections: ## Sources, ## Findings, ## Open questions, ## Confidence.

[NON-GOALS]
- Do NOT propose code changes; surface facts.
- Do NOT dispatch other agents.
- Do NOT Write outside [OUTPUT-PATH].
- Do NOT run state-modifying Bash.
EOF
    ;;

  worker)
    cat > "$brief_file" <<EOF
# Satellite dispatch brief stub — @worker
# Auto-drafted by agent_pause_detector.sh (v5.1.2)
# Source pause: ${pause_id}
# Paused agent: ${agent_id:-unknown} (${role:-unknown}) on lane: ${lane:-unknown}

You are @worker. Bounded task; report a summary; do not stream updates.

[ROLE]            @worker — bounded task

[DELIVERABLE]
${work:-<refine: one-sentence deliverable>}

[SOURCES]
- ${target_path:-<refine: source paths/queries>}

[BUDGET]
- Time: 10 min
- Max tool calls: 25

[FORMAT]
${acceptance:-<refine: deliverable format — markdown report, table, etc.>}

[OUT-OF-SCOPE]
- Do NOT modify source code outside the deliverable.
- Do NOT dispatch other agents.
- Do NOT exceed the budget.
EOF
    ;;

  auditor)
    cat > "$brief_file" <<EOF
# Satellite dispatch brief stub — @auditor
# Auto-drafted by agent_pause_detector.sh (v5.1.2)
# Source pause: ${pause_id}
# Paused agent: ${agent_id:-unknown} (${role:-unknown}) on lane: ${lane:-unknown}

[ROLE]            @auditor

[CONCERN]         <refine: code-quality | data-flow | dependency-topology | datastore-state | completeness>
[MODE]            close

[SCOPE]
${file_scope:-${target_path:-<refine: file scope to audit>}}

[OUTPUT-PATH]    ${sprint_root_path}/.shepherd/reports/$(date -u +%Y-%m-%d)-audit-satellite-${pause_id}.md
[SPRINT-ROOT]    ${sprint_root_path}
[SPRINT-BRANCH]  ${sprint}

[ACCEPTANCE]
${acceptance:-<refine: runnable verification per finding>}

[INSTRUCTIONS]
- Load superpowers:systematic-debugging on entry.
- Per-finding contract: Hypothesis + Falsification + Confidence (v5.1.1).
- LOW-confidence items → ## Open questions, not findings.
EOF
    ;;

  coder|*)
    # Default to coder brief stub (most common satellite request)
    cat > "$brief_file" <<EOF
# Satellite dispatch brief stub — @coder
# Auto-drafted by agent_pause_detector.sh (v5.1.2)
# Source pause: ${pause_id}
# Paused agent: ${agent_id:-unknown} (${role:-unknown}) on lane: ${lane:-unknown}

Repo: ${sprint_root_path}, branch \`${sprint}\`. Satellite task.
Commit template: fix(${sprint}/satellite-${pause_id}): ${work:-<refine subject>}
DO NOT run gates / build / test — main chat validates.
No new build-manifest dependencies without conductor approval.

**Mission:** ${work:-<refine: one-sentence goal>}

**Satellite-of:** ${lane:-unknown lane} (paused agent ${agent_id:-unknown})

[WORKTREE]
- Path:   <CONDUCTOR: cut new worktree before dispatch (shctx worktree create-batch)>
- Branch: <CONDUCTOR: agent-satellite-${pause_id}>
- Commit template: fix(${sprint}/satellite-${pause_id}): ${work:-<subject>}

[BASE-COMMIT-EXPECTED]
- ${sprint} HEAD: <CONDUCTOR: run git rev-parse HEAD before dispatch>

[SIBLING-LANES]
- ${lane:-unknown} (paused) — awaiting this satellite to land before resume

[SKILLS]
- code-style
- <CONDUCTOR: add language skill per [FILE-SCOPE] extension>

[CONTEXT-INVENTORY]
- ${new_symbol:-<refine: existing symbols to reference>} at ${target_path:-<path>}

[DO-NOT-DUPLICATE]
- rg -n "${new_symbol:-<symbol-pattern>}" → expected 0 hits (introducing new)

[USER-STYLE]
- code-style

[FILE-SCOPE]
MAY MODIFY:
${file_scope:-- <refine: files the satellite may modify>}

MUST NOT TOUCH:
- All paths owned by lane ${lane:-?} (the paused lane awaits this commit before resuming)

[NON-GOALS]
- Do NOT touch any other lanes' files
- Do NOT exceed XS or S scope (per pause-for-dependency.md cap)

[ACCEPTANCE]
${acceptance:-- <refine: runnable grep proving symbol now exists>}
EOF
    ;;
esac

# ---------------------------------------------------------------------------
# Surface the alert (structured pointer + brief stub path)
# ---------------------------------------------------------------------------
session=$(json_field "$input" '.session_id')
rel_pause="${pause_file#$sprint_root_path/}"
rel_brief="${brief_file#$sprint_root_path/}"

msg="[shepherd] PAUSE-FOR-DEPENDENCY captured (v5.1.2 — brief stub auto-drafted)."$'\n'
msg+="  Pause id:        $pause_id"$'\n'
msg+="  Paused agent:    ${agent_id:-unknown}"$'\n'
msg+="  Paused role:     ${role:-unknown}"$'\n'
msg+="  Lane:            ${lane:-unknown}"$'\n'
msg+="  Satellite role:  ${satellite_role} (size: ${size:-?})"$'\n'
msg+="  Structured:      $rel_pause"$'\n'
msg+="  Brief stub:      $rel_brief"$'\n'
msg+=""$'\n'
msg+="Next steps:"$'\n'
msg+="  1. Read the brief stub and refine the <CONDUCTOR: ...> placeholders"$'\n'
msg+="  2. (If satellite is @coder) cut a worktree first via shctx worktree create-batch"$'\n'
msg+="  3. Dispatch @${satellite_role} with the refined brief"$'\n'
msg+="  4. shctx pauses resolve $pause_id --satellite-sha=<sha>"$'\n'
msg+="  5. SendMessage to ${agent_id:-the paused agent} with the resume signal"$'\n'
msg+=""$'\n'
msg+="See doctrines/pause-for-dependency.md §III–IV"

log_event "agent_pause_detector" "warn" "$tool" "$role" "$session" \
  "$(emit_json_obj pause_id "$pause_id" satellite_role "$satellite_role" lane "$lane")"
emit_json_obj additionalContext "$msg"
exit 0
