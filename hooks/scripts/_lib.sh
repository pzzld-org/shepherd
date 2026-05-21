#!/usr/bin/env bash
# shepherd hooks — shared library
#
# Sourced by every hook script. Exports:
#
#   is_shepherd_project              — returns 0 if .claude/shepherd.toml exists
#   resolve_namespace                — echoes .shepherd (default) or .artifacts (legacy)
#   emit_context "<msg>"             — emit {"additionalContext":"<msg>"} and exit 0
#   emit_deny "<msg>"                — emit {"permissionDecision":"deny","message":"<msg>"} and exit 0
#   log_event hook decision tool role session fields_json
#                                    — append one JSONL entry to <ns>/logs/hooks/YYYY-MM-DD.jsonl
#   current_role tool_use_id         — echo agent role from <ns>/dispatch/<sprint>/<id>.json, or "unknown"
#   json_field input "<field>"       — extract scalar from JSON stdin; jq-then-python fallback
#
# All emit_* functions log_event before emitting JSON. Log failures are silent.
#
# This library does NOT set `set -euo pipefail` — sourcing scripts decide.

# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------

is_shepherd_project() {
  [[ -f ".claude/shepherd.toml" ]]
}

# Echoes .shepherd OR .artifacts (whichever exists), defaulting to .shepherd
resolve_namespace() {
  local repo_root
  repo_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
  for cand in "$repo_root/.shepherd" "$repo_root/.artifacts"; do
    if [[ -d "$cand" ]]; then
      printf '%s' "$cand"
      return 0
    fi
  done
  printf '%s' "$repo_root/.shepherd"
}

# ---------------------------------------------------------------------------
# JSON extraction (jq preferred, python3 fallback)
# ---------------------------------------------------------------------------

# Usage: json_field "$input_json" '.tool_input.command'
# Echoes the field value (empty string if absent).
json_field() {
  local input="$1" path="$2"
  if command -v jq &>/dev/null; then
    printf '%s' "$input" | jq -r "$path // empty" 2>/dev/null
  else
    # Convert jq path like '.foo.bar' into a python dict.get chain.
    python3 -c '
import json, sys
data = json.load(sys.stdin)
path = sys.argv[1].lstrip(".").split(".")
for p in path:
    if isinstance(data, dict):
        data = data.get(p, "")
    else:
        data = ""
        break
print(data if isinstance(data, str) else (json.dumps(data) if data else ""))
' "$path" <<<"$input" 2>/dev/null
  fi
}

# Extract the tool_response (which varies — string, dict.content, dict.text, or list).
# Usage: json_response "$input_json"
json_response() {
  local input="$1"
  if command -v jq &>/dev/null; then
    printf '%s' "$input" | jq -r '
      (.tool_response.content // .tool_response.text // .tool_response // empty)
      | if type == "array" then map(.text // .) | join("\n") else . end' 2>/dev/null
  else
    python3 -c '
import json, sys
d = json.load(sys.stdin)
r = d.get("tool_response", "")
if isinstance(r, dict):
    r = r.get("content") or r.get("text") or ""
if isinstance(r, list):
    r = "\n".join(x.get("text", "") if isinstance(x, dict) else str(x) for x in r)
print(r)
' 2>/dev/null <<<"$input"
  fi
}

# ---------------------------------------------------------------------------
# JSON emission
# ---------------------------------------------------------------------------

# Usage: emit_json_obj key1 val1 key2 val2 ...
# Echoes a single-line JSON object. Used by emit_context / emit_deny.
emit_json_obj() {
  if command -v jq &>/dev/null; then
    local args=() i=0
    while [[ $# -gt 0 ]]; do
      args+=(--arg "k$i" "$1")
      args+=(--arg "v$i" "$2")
      i=$((i+1))
      shift 2
    done
    local jq_filter=""
    for ((j=0; j<i; j++)); do
      [[ -n "$jq_filter" ]] && jq_filter+=" + "
      jq_filter+="{ (\$k$j): \$v$j }"
    done
    jq -nc "${args[@]}" "$jq_filter"
  else
    python3 -c '
import json, sys
args = sys.argv[1:]
obj = {args[i]: args[i+1] for i in range(0, len(args), 2)}
print(json.dumps(obj))
' "$@"
  fi
}

# Returns 0 if `.claude/shepherd.toml` contains `quiet_warnings = true` under
# `[hooks]`. Used by emit_context to suppress informational additionalContext
# emissions for operators who find them noisy in the UI (issue #19, v5.1.8+).
# Default: false (preserve v5.1.7 and prior behavior — warnings visible).
# Cheap grep — no TOML parser needed; the key is unique enough.
quiet_warnings() {
  [[ -f .claude/shepherd.toml ]] || return 1
  grep -qE '^[[:space:]]*quiet_warnings[[:space:]]*=[[:space:]]*true' .claude/shepherd.toml 2>/dev/null
}

# Emit an additionalContext warning and exit 0.
# Usage: emit_context "<msg>" [hook_name] [tool] [role] [session_id]
# The optional fields are for log_event; if omitted, log_event is skipped.
# When [hooks].quiet_warnings = true in shepherd.toml, the additionalContext
# JSON is suppressed (log_event still fires); operators can grep
# `<namespace>/logs/hooks/YYYY-MM-DD.jsonl` to recover the warning text.
emit_context() {
  local msg="$1" hook="${2:-}" tool="${3:-}" role="${4:-unknown}" session="${5:-}"
  [[ -n "$hook" ]] && log_event "$hook" "warn" "$tool" "$role" "$session" "$(emit_json_obj reason "$msg")"
  if quiet_warnings; then
    exit 0
  fi
  emit_json_obj additionalContext "$msg"
  exit 0
}

# Emit a permissionDecision:deny and exit 0.
# Usage: emit_deny "<msg>" [hook_name] [tool] [role] [session_id]
emit_deny() {
  local msg="$1" hook="${2:-}" tool="${3:-}" role="${4:-unknown}" session="${5:-}"
  [[ -n "$hook" ]] && log_event "$hook" "deny" "$tool" "$role" "$session" "$(emit_json_obj reason "$msg")"
  emit_json_obj permissionDecision "deny" message "$msg"
  exit 0
}

# Emit nothing, just exit 0 with optional log.
# Usage: pass_silent [hook_name] [tool] [role] [session_id] [fields_json]
pass_silent() {
  local hook="${1:-}" tool="${2:-}" role="${3:-unknown}" session="${4:-}" fields="${5:-{\}}"
  [[ -n "$hook" ]] && log_event "$hook" "pass" "$tool" "$role" "$session" "$fields"
  exit 0
}

# ---------------------------------------------------------------------------
# Event log
# ---------------------------------------------------------------------------

# Append one JSONL entry to <ns>/logs/hooks/YYYY-MM-DD.jsonl.
# Errors are silent; log failures must not break hooks.
log_event() {
  local hook="$1" decision="$2" tool="$3" role="$4" session="$5" fields_json="${6:-{\}}"
  local ns log_dir log_file ts
  ns=$(resolve_namespace) 2>/dev/null || return 0
  log_dir="$ns/logs/hooks"
  mkdir -p "$log_dir" 2>/dev/null || return 0
  log_file="$log_dir/$(date -u +%Y-%m-%d).jsonl"
  ts=$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ 2>/dev/null) || ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)

  if command -v jq &>/dev/null; then
    jq -cn \
      --arg ts "$ts" --arg hook "$hook" --arg decision "$decision" \
      --arg tool "$tool" --arg role "$role" --arg session "$session" \
      --argjson fields "${fields_json:-{}}" \
      '{ts:$ts, hook:$hook, decision:$decision, tool:$tool, role:$role, session_id:$session, fields:$fields}' \
      >> "$log_file" 2>/dev/null || true
  else
    python3 -c '
import json, sys
print(json.dumps({
    "ts":         sys.argv[1],
    "hook":       sys.argv[2],
    "decision":   sys.argv[3],
    "tool":       sys.argv[4],
    "role":       sys.argv[5],
    "session_id": sys.argv[6],
    "fields":     json.loads(sys.argv[7] or "{}"),
}))
' "$ts" "$hook" "$decision" "$tool" "$role" "$session" "${fields_json:-{}}" \
      >> "$log_file" 2>/dev/null || true
  fi
  return 0
}

# ---------------------------------------------------------------------------
# Role resolution (from agent_invocation_tagger writes)
# ---------------------------------------------------------------------------

# Given a tool_use_id, echo the agent role written by agent_invocation_tagger.sh.
# Returns "unknown" if no dispatch record exists. Conductor invocations (no
# Agent dispatch in progress) will always return "conductor" because no
# matching record will be found AND the caller passes through to conductor.
#
# Usage: role=$(current_role "$tool_use_id" "$sprint")
current_role() {
  local tool_use_id="${1:-}" sprint="${2:-unknown}"
  [[ -z "$tool_use_id" ]] && { printf 'conductor'; return 0; }

  local ns dispatch_file
  ns=$(resolve_namespace)
  dispatch_file="$ns/dispatch/$sprint/${tool_use_id}.json"

  if [[ -f "$dispatch_file" ]] && command -v jq &>/dev/null; then
    jq -r '.agent_role // "unknown"' "$dispatch_file" 2>/dev/null || printf 'unknown'
  elif [[ -f "$dispatch_file" ]]; then
    python3 -c "import json; print(json.load(open('$dispatch_file')).get('agent_role','unknown'))" 2>/dev/null || printf 'unknown'
  else
    printf 'conductor'
  fi
}

# Echo the current sprint branch name (or "unknown").
current_sprint() {
  git rev-parse --abbrev-ref HEAD 2>/dev/null || printf 'unknown'
}

# Echo the path the conductor's HEAD claims (sprint root).
sprint_root() {
  git rev-parse --git-common-dir 2>/dev/null | sed 's|/\.git$||; s|/.git$||' || pwd
}

# Returns 0 if pwd is inside a sub-worktree (not the primary).
in_subworktree() {
  local git_dir git_common
  git_dir=$(git rev-parse --git-dir 2>/dev/null) || return 1
  git_common=$(git rev-parse --git-common-dir 2>/dev/null) || return 1
  [[ -n "$git_dir" && "$git_dir" != "$git_common" ]]
}
