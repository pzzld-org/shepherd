#!/usr/bin/env bash
# shepherd hook — user-prompt context priming (v5.1.8)
#
# Fires at UserPromptSubmit (Claude Code v2.1+). Detects /shepherd:*
# invocations and auto-injects DB-cached state ([DB-CONTEXT]-style status
# block) into Claude's context, so the conductor sees the registry's view
# of the sprint immediately on the same turn as the slash-command.
#
# UserPromptSubmit payload (per https://code.claude.com/docs/en/hooks):
#   { "session_id", "transcript_path", "cwd", "permission_mode",
#     "hook_event_name", "prompt" }
#
# Output:
#   - Plain pass-through when the prompt is not /shepherd:*
#   - {"additionalContext":"..."} when shepherd.toml missing or
#     when a registry status snapshot can be injected
#   - Never blocks (no "decision": "block") — informational only.

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$HERE/..}"
source "$HERE/_lib.sh"

input=$(cat 2>/dev/null || true)

prompt=$(json_field "$input" '.prompt')
session=$(json_field "$input" '.session_id')

# Bail early if no prompt or no /shepherd: prefix (case-insensitive).
[[ -z "$prompt" ]] && pass_silent "user_prompt_submit" "UserPrompt" "user" "$session"

trimmed="${prompt#"${prompt%%[![:space:]]*}"}"   # ltrim
lower=$(printf '%s' "$trimmed" | tr '[:upper:]' '[:lower:]')

if [[ ! "$lower" =~ ^/shepherd: ]]; then
  pass_silent "user_prompt_submit" "UserPrompt" "user" "$session"
fi

# Extract subcommand: text between `:` and the first whitespace.
subcmd=$(printf '%s' "$lower" | sed -E 's|^/shepherd:([a-z_-]+).*$|\1|')
[[ -z "$subcmd" || "$subcmd" == "$lower" ]] && subcmd="unknown"

# Missing shepherd.toml — warn but don't block. Most /shepherd:* commands
# require it; /shepherd:ctx init is the legitimate exception, so we surface
# a hint rather than a hard error.
if ! is_shepherd_project; then
  msg="[shepherd] /shepherd:${subcmd} invoked but .claude/shepherd.toml not found —"$'\n'
  msg+="most shepherd commands require it. Copy examples/minimal/shepherd.toml to"$'\n'
  msg+=".claude/shepherd.toml and adjust before running /shepherd:start or /shepherd:spawn."
  emit_context "$msg" "user_prompt_submit" "UserPrompt" "user" "$session"
fi

# Resolve namespace and DB path.
ns=$(resolve_namespace)
db="$ns/root.db"

# Only inject for /shepherd:start and /shepherd:spawn. /shepherd:ctx is
# self-querying (operator about to inspect the registry manually).
# /shepherd:plant predates DB state. /shepherd:cleanup runs before state.
case "$subcmd" in
  start|spawn)
    if [[ -f "$db" ]]; then
      # Fire shctx status; cap output at 2KB. shctx status currently emits
      # plain text — adequate for additionalContext consumption.
      status_out=$(bash "${PLUGIN_ROOT}/skills/context/scripts/shctx" status 2>/dev/null || true)
      if [[ -n "$status_out" ]]; then
        # Tail to 2KB if longer to keep within UserPromptSubmit's 30s budget.
        byte_count=$(printf '%s' "$status_out" | wc -c | tr -d ' ')
        if [[ "${byte_count:-0}" -gt 2048 ]]; then
          status_out=$(printf '%s' "$status_out" | tail -c 2048)
          status_out="[truncated to last 2KB]"$'\n'"$status_out"
        fi
        msg="[shepherd] /shepherd:${subcmd} primer — DB-cached registry state:"$'\n'
        msg+='```'$'\n'
        msg+="$status_out"$'\n'
        msg+='```'$'\n'
        msg+="Use this as a starting point; refresh with 'shctx refresh' if stale."
        emit_context "$msg" "user_prompt_submit" "UserPrompt" "user" "$session"
      fi
    fi
    ;;
  ctx|cleanup|plant|*)
    : # no injection — these commands either query the DB themselves or run pre-state
    ;;
esac

pass_silent "user_prompt_submit" "UserPrompt" "user" "$session" \
  "$(emit_json_obj subcommand "$subcmd")"
