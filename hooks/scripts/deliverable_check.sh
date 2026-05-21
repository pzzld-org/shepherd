#!/usr/bin/env bash
# shepherd hook — Stop: stalled-deliverable detector (v5.1.7).
#
# Fires at Stop (end-of-turn). Inspects the deliverables table; any row whose
# status is still 'pending' more than 10 minutes after its promise timestamp
# is auto-marked 'stalled'. Non-blocking — emits a single-line warn to stderr.
#
# Discipline:
#   • Never block.    Exit 0 unconditionally; DB/IO failures swallowed.
#   • Idempotent.     UPDATE is a no-op when nothing has stalled.
#
# Input  (stdin): Stop JSON (ignored — no per-payload fields needed).
# Output (stdout): silent.
# Output (stderr): `[shctx] N deliverable(s) auto-marked stalled (> 10 min pending)`
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo .)"
[[ -f "$ROOT/.artifacts/root.db" ]] || exit 0

# Cutoff: 10 minutes (in ms, matching cmd_teammate / cmd_deliverable convention).
CUTOFF=$(( $(date +%s) * 1000 - 10*60*1000 ))

STALE=$(sqlite3 "$ROOT/.artifacts/root.db" \
  "SELECT count(*) FROM deliverables WHERE status='pending' AND promised_at < $CUTOFF;" 2>/dev/null || echo 0)

if [[ "$STALE" -gt 0 ]]; then
  sqlite3 "$ROOT/.artifacts/root.db" \
    "UPDATE deliverables SET status='stalled' WHERE status='pending' AND promised_at < $CUTOFF;" 2>/dev/null || true
  echo "[shctx] $STALE deliverable(s) auto-marked stalled (> 10 min pending)" >&2
fi

exit 0
