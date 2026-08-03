#!/usr/bin/env bash
# shepherd hook — PostToolUse(Bash): cwd drift detection (v5.1.2) + the #59
# gates-ran ledger (v6.5.0).
#
# Fires after every Bash tool call. Detects if the conductor's cwd has drifted
# into a sub-worktree — the most common silent fault (conductor-cwd.md §IV) —
# and records configured-gate invocations to the per-session ledger.
#
# Does NOT block (PostToolUse cannot deny). Injects an additionalContext
# warning so the conductor notices the drift before the next operation.

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

input=$(cat)
is_shepherd_project || exit 0

session=$(json_field "$input" '.session_id')
tool_use_id=$(json_field "$input" '.tool_use_id')
sprint=$(current_sprint)
role=$(current_role "$tool_use_id" "$sprint")

# --- #59: gates-ran ledger ---------------------------------------------------
# Deterministic record that a configured gate actually RAN this session. When
# the Bash command CONTAINS one of the configured gate command strings —
# [gates].check, [gates].lint, or any [gates.extra] entry — append one JSONL
# row {ts, gate, command} to <ns>/tmp/gates-ran-<session>.jsonl. Readers:
# `shepherd doctor` (gates section) and close_finalize_check.sh (warns when a
# [gates.extra] entry never ran before finalize). The invocation is recorded
# regardless of the command's exit status — the ledger answers "did it run
# this session", not "did it pass" (pass/fail is the gate's own exit code at
# the wave gate). Substring match, so wrappers (`bash <path> …`, `… && echo`)
# still register. Best-effort at every step.
cmd=$(json_field "$input" '.tool_input.command')
if [[ -n "$cmd" && -n "$session" ]]; then
  gate_hits=""
  g_check="$(cfg_section_get gates check 2>/dev/null || true)"
  g_lint="$(cfg_section_get gates lint 2>/dev/null || true)"
  [[ -n "$g_check" && "$cmd" == *"$g_check"* ]] && gate_hits="check"$'\n'
  [[ -n "$g_lint" && "$cmd" == *"$g_lint"* ]] && gate_hits+="lint"$'\n'
  while IFS= read -r gate_key; do
    [[ -n "$gate_key" ]] || continue
    gate_val="$(cfg_section_get gates.extra "$gate_key" 2>/dev/null || true)"
    [[ -n "$gate_val" && "$cmd" == *"$gate_val"* ]] && gate_hits+="extra:$gate_key"$'\n'
  done < <(cfg_section_keys gates.extra 2>/dev/null || true)
  if [[ -n "$gate_hits" ]]; then
    gates_ns="$(resolve_namespace 2>/dev/null || echo .shepherd)"
    mkdir -p "$gates_ns/tmp" 2>/dev/null || true
    gates_ledger="$gates_ns/tmp/gates-ran-${session//[^A-Za-z0-9_.-]/_}.jsonl"
    gates_ts="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo '')"
    while IFS= read -r gate_hit; do
      [[ -n "$gate_hit" ]] || continue
      emit_json_obj ts "$gates_ts" gate "$gate_hit" command "${cmd:0:200}" \
        >> "$gates_ledger" 2>/dev/null || true
    done <<< "$gate_hits"
  fi
fi

if in_subworktree; then
  sr=$(sprint_root)
  cwd=$(pwd)
  msg="[shepherd] CWD DRIFT DETECTED — conductor is now inside a sub-worktree."$'\n'
  msg+="  cwd:        $cwd"$'\n'
  msg+="  sprint root: $sr"$'\n'
  msg+="Recovery: cd $sr"$'\n'
  msg+="Then verify: git rev-parse --abbrev-ref HEAD (should be sprint branch)"$'\n'
  msg+="See skills/shepherd/references/flock.md §Mandatory verification"
  emit_context "$msg" "bash_post" "Bash" "$role" "$session"
fi

pass_silent "bash_post" "Bash" "$role" "$session"
