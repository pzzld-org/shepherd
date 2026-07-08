#!/usr/bin/env bash
# shepherd hook — Bash pre-use guard (v5.1.2)
#
# Fires at PreToolUse(Bash). Five checks (first-match-wins):
#
# 1. git commit BLOCK            — HEAD on agent/lane branch (conductor-cwd.md §Ban 2)
# 2. auditor cwd BLOCK           — auditor invoking gate while HEAD ≠ sprint branch (auditor-readonly.md WORKTREE-DRIFT)
# 3. discovery state-mod BLOCK   — @discovery invoking mutation Bash (discovery-readonly.md)
# 4. cargo parallel WARN         — backgrounded cargo (cargo-sequential-gates.md, v5.0.9)
# 5. cd-into-worktree WARN       — drifts cwd (conductor-cwd.md §Ban 1, v5.0.9)
#
# Input  (stdin): PreToolUse JSON { tool_name, tool_input.command, tool_use_id, ... }
# Output (stdout):
#   {"permissionDecision":"deny","message":"..."}    — Checks 1, 2, 3
#   {"additionalContext":"..."}                       — Checks 4, 5
#   exit 0 silently if no check fires.

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

input=$(cat)
is_shepherd_project || exit 0

cmd=$(json_field "$input" '.tool_input.command')
bg=$(json_field "$input" '.tool_input.run_in_background')
tool_use_id=$(json_field "$input" '.tool_use_id')
session=$(json_field "$input" '.session_id')
sprint=$(current_sprint)
role=$(current_role "$tool_use_id" "$sprint")

[[ -z "$cmd" ]] && pass_silent "bash_guard" "Bash" "$role" "$session"

# ---------------------------------------------------------------------------
# Check 0-bis — Dynamic Workflow used to instantiate teammate-conductors (BLOCK)
# #89 inversion 1 / primitive-axis-binding.md §III.1: a compiled workflow
# orchestrates SUBAGENTS (the execution axis). Spawning a lane (teammate-
# conductor) is the Agent Teams axis — never a workflow. A *.workflow.js whose
# script carries teammate-spawn markers is the inversion — refuse to run it.
# ---------------------------------------------------------------------------
if printf '%s' "$cmd" | grep -qE '[A-Za-z0-9._/-]+\.workflow\.js'; then
  while IFS= read -r wf; do
    [[ -f "$wf" ]] || continue
    if grep -qE "team_name[[:space:]]*:|(subagent_type|agentType)[\"'[:space:]]*:[\"'[:space:]]*shepherd:conductor|/shepherd:spawn" "$wf" 2>/dev/null; then
      msg="[shepherd] PRIMITIVE-INVERSION — workflow-spawns-teammates — BLOCKED."$'\n'
      msg+="  Workflow: $wf"$'\n'
      msg+="A Dynamic Workflow orchestrates SUBAGENTS (the execution axis). Spawning a"$'\n'
      msg+="lane (teammate-conductor) is the Agent Teams axis — Agent({team_name:...,"$'\n'
      msg+="subagent_type: \"shepherd:conductor\"}) — NEVER a workflow. This is the v6.0.1"$'\n'
      msg+="field regression (#89 inversion 1). Spawn lanes via Agent Teams; let each"$'\n'
      msg+="teammate compile its OWN gate-free step fan-out. See skills/shepherd/references/pipeline.md §Lane law.1."
      emit_deny "$msg" "bash_guard" "Bash" "$role" "$session"
    fi
  done < <(printf '%s' "$cmd" | grep -oE '[A-Za-z0-9._/-]+\.workflow\.js')
fi

# ---------------------------------------------------------------------------
# Check 1 — git commit on agent/lane branch (BLOCK)
# ---------------------------------------------------------------------------
if printf '%s' "$cmd" | grep -q 'git commit'; then
  branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
  if [[ "$branch" =~ ^(agent-|lane-) ]]; then
    msg="[shepherd] git commit BLOCKED — HEAD is on agent lane '${branch}'."$'\n'
    msg+="The conductor must only commit to the sprint branch, never an agent-* or lane-* branch."$'\n'
    msg+="Recover: git checkout <sprint_branch>  (see skills/shepherd/references/flock.md §Ban 2)"
    emit_deny "$msg" "bash_guard" "Bash" "$role" "$session"
  fi
fi

# ---------------------------------------------------------------------------
# Check 2 — auditor invoking gate command from wrong cwd (BLOCK)
# ---------------------------------------------------------------------------
# An auditor must run gates AT SPRINT ROOT. If the auditor is invoking
# cargo / pnpm / pytest / etc. from a sub-worktree, FALSE-CRITICAL findings
# result (v5.0.3 field origin — auditor-readonly.md §Where auditors RUN).
if [[ "$role" == "auditor" ]]; then
  # Detect known gate-invocation tools. Cheap regex; extend per project.
  if printf '%s' "$cmd" | grep -qE '(^|[[:space:];|&])(cargo|pnpm|npm|pytest|ruff|mypy|tsc|eslint|prettier|go test|go build|make)[[:space:]]'; then
    if in_subworktree; then
      sprint_path=$(sprint_root)
      msg="[shepherd] WORKTREE-DRIFT BLOCKED — @auditor invoking gate from sub-worktree."$'\n'
      msg+="  Cwd:         $(pwd)"$'\n'
      msg+="  Sprint root: $sprint_path"$'\n'
      msg+="  Command:     ${cmd:0:120}"$'\n'
      msg+="Auditors MUST run gates at the sprint root, not from a coder's worktree —"$'\n'
      msg+="otherwise uncommitted worktree state produces FALSE-CRITICAL findings."$'\n'
      msg+="See skills/shepherd/references/flock.md §@auditor."
      emit_deny "$msg" "bash_guard" "Bash" "$role" "$session"
    fi
  fi
fi

# ---------------------------------------------------------------------------
# Check 3 — @discovery invoking state-modifying Bash (BLOCK)
# ---------------------------------------------------------------------------
# Per skills/shepherd/references/flock.md §@discovery, @discovery is read-only. The agent
# system prompt enumerates forbidden patterns; this hook is the second line
# of defense.
if [[ "$role" == "discovery" ]]; then
  # Patterns that mutate state. Each pattern is scoped to avoid false
  # positives on read-only invocations of the same command name.
  mutate_pattern='(^|[[:space:];|&])(rm[[:space:]]+-[rRf]|mv[[:space:]]|cp[[:space:]].*[^[:space:]]+/[^[:space:]]+[[:space:]]|tee[[:space:]]|git[[:space:]]+(commit|push|merge|rebase|reset|checkout|switch|tag)[[:space:]]?|gh[[:space:]]+(issue|pr|release)[[:space:]]+(create|close|edit|merge|reopen|delete)|npm[[:space:]]+(install|run|publish)|pnpm[[:space:]]+(install|publish)|pip[[:space:]]+install|cargo[[:space:]]+(build|run|install|publish|clean|fix|fmt|clippy)|make([[:space:]]|$)|docker[[:space:]]+(run|build|push|exec)|kubectl[[:space:]]+(apply|delete|edit)|terraform[[:space:]]+(apply|destroy))'
  # Also block any redirect into a file: ` > path ` or ` >> path ` (but not 2>/dev/null etc.)
  redirect_pattern='([^&|0-9]>[[:space:]]*[a-zA-Z._/]|>>[[:space:]]*[a-zA-Z._/])'

  if printf '%s' "$cmd" | grep -qE "$mutate_pattern" \
     || printf '%s' "$cmd" | grep -qE "$redirect_pattern"; then
    msg="[shepherd] DISCOVERY-MUTATE BLOCKED — @discovery is read-only."$'\n'
    msg+="  Command:  ${cmd:0:160}"$'\n'
    msg+="Discovery agents NEVER mutate state. If you need to write a report,"$'\n'
    msg+="the brief's [OUTPUT-PATH] is your ONLY write target — use the Write tool"$'\n'
    msg+="(restricted by lock_guard), not shell redirection."$'\n'
    msg+="See skills/shepherd/references/flock.md §@discovery."
    emit_deny "$msg" "bash_guard" "Bash" "$role" "$session"
  fi
fi

# ---------------------------------------------------------------------------
# Check 3-bis — cargo GATE command backgrounded via run_in_background (BLOCK, #91)
# cargo-sequential-gates.md: wave gates run as ONE &&-chained FOREGROUND call.
# run_in_background:true on a gate command yields concurrent cargo holding the
# target/ lock — the dev.4 field violation. Forbidden for gate commands.
# ---------------------------------------------------------------------------
if [[ "$bg" == "true" ]] && printf '%s' "$cmd" | grep -qE '(^|[[:space:];|&])cargo[[:space:]]+(check|clippy|test|build|fmt|nextest)'; then
  msg="[shepherd] CARGO-GATE-BACKGROUNDED — BLOCKED (#91)."$'\n'
  msg+="  run_in_background:true on a cargo gate command."$'\n'
  msg+="Cargo gates MUST run as a SINGLE &&-chained FOREGROUND Bash call — never"$'\n'
  msg+="run_in_background, never two gate commands in separate tool calls. Concurrent"$'\n'
  msg+="cargo deadlocks on the target/ lock and silently violates sequential gating."$'\n'
  msg+="Use: cargo fmt --all && cargo check ... && cargo clippy ... && cargo test ..."$'\n'
  msg+="See skills/shepherd/references/pipeline.md §Gates (Execution pattern)."
  emit_deny "$msg" "bash_guard" "Bash" "$role" "$session"
fi

# ---------------------------------------------------------------------------
# Check 4 — parallel cargo invocations (WARN)
# ---------------------------------------------------------------------------
clean=$(printf '%s' "$cmd" | sed -e 's/&&/__AND__/g' -e 's/||/__OR__/g')
bg_cargo_count=$(printf '%s' "$clean" | grep -oE 'cargo[[:space:]]+[a-z_-]+[^|;]*&([[:space:]]|$)' | wc -l | tr -d ' ' || true)
if [[ "${bg_cargo_count:-0}" -gt 0 ]]; then
  warn="[shepherd] cargo parallel WARN — ${bg_cargo_count}+ backgrounded cargo invocation(s) detected."$'\n'
  warn+="Cargo holds an exclusive lock on target/; parallel cargo processes deadlock."$'\n'
  warn+="Use sequential: cargo check && cargo clippy (not '&' backgrounding)."$'\n'
  warn+="See skills/shepherd/references/pipeline.md §Gates"
  emit_context "$warn" "bash_guard" "Bash" "$role" "$session"
fi

# ---------------------------------------------------------------------------
# Check 5 — `cd` into a worktree path (WARN — Ban 1, conductor-cwd.md)
# ---------------------------------------------------------------------------
if printf '%s' "$cmd" | grep -qE 'cd\s+.*\.claude/worktrees|pushd\s+.*\.claude/worktrees'; then
  warn="[shepherd] cd into worktree WARN — 'cd' into a .claude/worktrees/ path drifts conductor cwd."$'\n'
  warn+="Use 'git -C <path>' for inspection; absolute paths for Read/Write."$'\n'
  warn+="See skills/shepherd/references/flock.md §Ban 1"
  emit_context "$warn" "bash_guard" "Bash" "$role" "$session"
fi

pass_silent "bash_guard" "Bash" "$role" "$session"
