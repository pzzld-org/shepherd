#!/usr/bin/env bash
# shepherd hook — Bash pre-use guard (conductor-cwd + cargo doctrines)
#
# Fires at PreToolUse(Bash). Three checks (first-match-wins):
#
# 1. git commit BLOCK — HEAD on agent/lane branch (conductor-cwd.md §Ban 2)
# 2. cargo parallel WARN — backgrounded cargo (cargo-sequential-gates.md, v5.0.9)
# 3. cd-into-worktree WARN — drifts cwd (conductor-cwd.md §Ban 1, v5.0.9)
#
# Input  (stdin): PreToolUse JSON { tool_name, tool_input.command, ... }
# Output (stdout):
#   {"permissionDecision":"deny", "message":"..."}    — Check 1 only
#   {"additionalContext":"..."}                         — Checks 2 / 3
#   exit 0 silently if no check fires.

set -euo pipefail

input=$(cat)

# Skip if not a shepherd project
[[ -f ".claude/shepherd.toml" ]] || exit 0

# Extract the Bash command
if command -v jq &>/dev/null; then
  cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null || true)
else
  cmd=$(printf '%s' "$input" | python3 -c \
    "import json,sys; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('command',''))" \
    2>/dev/null || true)
fi

[[ -z "$cmd" ]] && exit 0

# ---------------------------------------------------------------------------
# Check 1 — git commit on agent/lane branch (BLOCK)
# ---------------------------------------------------------------------------
if printf '%s' "$cmd" | grep -q 'git commit'; then
  branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
  if [[ "$branch" =~ ^(agent-|lane-) ]]; then
    msg="[shepherd] git commit BLOCKED — HEAD is on agent lane '${branch}'."$'\n'
    msg+="The conductor must only commit to the sprint branch, never an agent-* or lane-* branch."$'\n'
    msg+="Recover: git checkout <sprint_branch>  (see doctrines/conductor-cwd.md §Ban 2)"
    if command -v jq &>/dev/null; then
      jq -n --arg m "$msg" '{"permissionDecision": "deny", "message": $m}'
    else
      python3 -c "import json,sys; print(json.dumps({'permissionDecision':'deny','message':sys.argv[1]}))" "$msg"
    fi
    exit 0
  fi
fi

# ---------------------------------------------------------------------------
# Check 2 — parallel cargo invocations (WARN, do not block)
# Detect: `cargo ... &` backgrounding (excluding `&&` which is sequential).
# ---------------------------------------------------------------------------
# Mask `&&` and `||` so they don't masquerade as backgrounding `&`.
clean=$(printf '%s' "$cmd" | sed -e 's/&&/__AND__/g' -e 's/||/__OR__/g')
# A backgrounded cargo is `cargo <subcmd> ...` followed by a `&` that is
# either end-of-string or followed by whitespace/newline (i.e., not `&&`).
bg_cargo_count=$(printf '%s' "$clean" | grep -oE 'cargo[[:space:]]+[a-z_-]+[^|;]*&([[:space:]]|$)' | wc -l | tr -d ' ' || true)
if [[ "${bg_cargo_count:-0}" -gt 0 ]]; then
  warn="[shepherd] cargo parallel WARN — ${bg_cargo_count}+ backgrounded cargo invocation(s) detected."$'\n'
  warn+="Cargo holds an exclusive lock on target/; parallel cargo processes deadlock."$'\n'
  warn+="Use sequential: cargo check && cargo clippy (not '&' backgrounding)."$'\n'
  warn+="See doctrines/cargo-sequential-gates.md"
  if command -v jq &>/dev/null; then
    jq -n --arg ctx "$warn" '{"additionalContext": $ctx}'
  else
    python3 -c "import json,sys; print(json.dumps({'additionalContext': sys.argv[1]}))" "$warn"
  fi
  exit 0
fi

# ---------------------------------------------------------------------------
# Check 3 — `cd` into a worktree path (WARN — Ban 1, conductor-cwd.md)
# ---------------------------------------------------------------------------
if printf '%s' "$cmd" | grep -qE 'cd\s+.*\.claude/worktrees|pushd\s+.*\.claude/worktrees'; then
  warn="[shepherd] cd into worktree WARN — 'cd' into a .claude/worktrees/ path drifts conductor cwd."$'\n'
  warn+="Use 'git -C <path>' for inspection; absolute paths for Read/Write."$'\n'
  warn+="See doctrines/conductor-cwd.md §Ban 1"
  if command -v jq &>/dev/null; then
    jq -n --arg ctx "$warn" '{"additionalContext": $ctx}'
  else
    python3 -c "import json,sys; print(json.dumps({'additionalContext': sys.argv[1]}))" "$warn"
  fi
  exit 0
fi

exit 0
