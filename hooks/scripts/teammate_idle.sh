#!/usr/bin/env bash
# shepherd hook — TeammateIdle: lead-side reaction when a teammate idles (v5.1.7).
#
# Runs in the LEAD's context when a teammate signals idle. Marks the teammate's
# status in the canonical SQLite store, then scans for unresolved escalations
# and stalled deliverables and surfaces a single-line warning to stderr.
#
# Discipline:
#   • Never block.    Exit 0 unconditionally; any DB/IO failure is swallowed.
#   • Non-blocking.   Output is stderr only — operators see the warning inline,
#                     but the agent loop is not affected.
#
# Input  (stdin): TeammateIdle JSON
#   { "teammate_name": "<name>", ... }
#
# Output (stdout): silent.
# Output (stderr): one-line `[shctx] teammate <name> idle | open-escalations=N | stalled-deliverables=N`
set -euo pipefail

# Hook payload arrives on stdin as JSON per Claude Code hooks API.
PAYLOAD="$(cat || true)"
TEAMMATE="$(echo "$PAYLOAD" | jq -r '.teammate_name // empty' 2>/dev/null || true)"
[[ -z "$TEAMMATE" ]] && exit 0

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo .)"
[[ -f "$ROOT/.artifacts/root.db" ]] || exit 0

# Mark teammate idle (heartbeat carries the note; UPDATE flips status unless
# the teammate is already crashed or retired).
bash "$ROOT/skills/context/scripts/cmd_teammate.sh" \
  heartbeat "$TEAMMATE" --note='idle' 2>/dev/null || true
sqlite3 "$ROOT/.artifacts/root.db" \
  "UPDATE teammates SET status='idle' WHERE teammate_name='$TEAMMATE' AND status NOT IN ('crashed','retired');" 2>/dev/null || true

# Surface open escalations + stalled deliverables. `wc -l` includes the header
# row from sqlite3 -header, so subtract 1 to get the data-row count.
ESC=$(bash "$ROOT/skills/context/scripts/cmd_escalate.sh" list --open-only 2>/dev/null | wc -l)
STALLED=$(bash "$ROOT/skills/context/scripts/cmd_deliverable.sh" stalled --since-mins=10 2>/dev/null | wc -l)

if [[ "$ESC" -gt 1 ]] || [[ "$STALLED" -gt 1 ]]; then
  echo "[shctx] teammate $TEAMMATE idle | open-escalations=$((ESC-1)) | stalled-deliverables=$((STALLED-1))" >&2
fi

exit 0
