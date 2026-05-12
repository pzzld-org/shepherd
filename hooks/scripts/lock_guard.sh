#!/usr/bin/env bash
# shepherd hook — sprint lock conflict warning (concurrent conductor safety)
#
# Fires at PreToolUse(Write|Edit). Reads .artifacts/shepherd.lock (or
# .shepherd/shepherd.lock) and injects a warning into Claude's context when
# the lock is held by a different session ID. Does NOT block — the operator
# decides whether to proceed.
#
# Input (stdin): PreToolUse JSON payload { session_id, tool_name, tool_input, ... }
# Output: {"additionalContext":"..."} warning, or exit 0 if lock is clean.

set -euo pipefail

input=$(cat)

# Skip if not a shepherd project
[[ -f ".claude/shepherd.toml" ]] || exit 0

# Locate the lock file (support both .artifacts/ and .shepherd/ namespaces)
lock_file=""
for candidate in ".artifacts/shepherd.lock" ".shepherd/shepherd.lock"; do
  [[ -f "$candidate" ]] && { lock_file="$candidate"; break; }
done
[[ -n "$lock_file" ]] || exit 0  # No lock — safe

# Parse session IDs
if command -v jq &>/dev/null; then
  current_session=$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null || true)
  lock_session=$(jq -r '.session_id // empty' "$lock_file" 2>/dev/null || true)
  lock_sprint=$(jq -r '.sprint // empty' "$lock_file" 2>/dev/null || true)
else
  current_session=$(printf '%s' "$input" | python3 -c \
    "import json,sys; print(json.load(sys.stdin).get('session_id',''))" 2>/dev/null || true)
  lock_session=$(python3 -c \
    "import json; d=json.load(open('$lock_file')); print(d.get('session_id',''))" 2>/dev/null || true)
  lock_sprint=$(python3 -c \
    "import json; d=json.load(open('$lock_file')); print(d.get('sprint',''))" 2>/dev/null || true)
fi

# Same session or unparseable lock — no conflict
[[ -z "$lock_session" || "$lock_session" == "$current_session" ]] && exit 0

# Different session holds the lock — warn
sprint_hint=""
[[ -n "$lock_sprint" ]] && sprint_hint=" (sprint: $lock_sprint)"
msg="[shepherd] sprint lock conflict: $lock_file is held by session ${lock_session}${sprint_hint}."$'\n'
msg+="A concurrent conductor session may be active. Verify before writing."$'\n'
msg+="If the prior session is dead, delete $lock_file to release the lock."

if command -v jq &>/dev/null; then
  jq -n --arg ctx "$msg" '{"additionalContext": $ctx}'
else
  python3 -c "import json,sys; print(json.dumps({'additionalContext': sys.argv[1]}))" "$msg"
fi
