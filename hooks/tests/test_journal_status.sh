#!/usr/bin/env bash
# hooks/tests/test_journal_status.sh — regression guard for scripts/journal-status.sh (GH #213).
#
# Fixtures match the observed Dynamic-Workflow journal schema (started/result
# records keyed by content-hash). Asserts the deterministic wave-return counts,
# PASS/REDO verdict extraction, and the three exit codes (absent / pending / done).

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/../../scripts/journal-status.sh"
fails=0
note() { printf '  %s\n' "$*"; }

[[ -f "$SCRIPT" ]] || { note "FAIL: scripts/journal-status.sh missing"; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# --- Fixture A: 3 spawned, 2 returned (one PASS string, one REDO object), 1 pending.
cat > "$TMP/mixed.jsonl" <<'EOF'
{"type":"started","key":"v2:aaaaaaaa1111","agentId":"a1"}
{"type":"started","key":"v2:bbbbbbbb2222","agentId":"a2"}
{"type":"started","key":"v2:cccccccc3333","agentId":"a3"}
{"type":"result","key":"v2:aaaaaaaa1111","agentId":"a1","result":"## WAVE-REVIEW VERDICT\nreview_verdict: PASS"}
{"type":"result","key":"v2:bbbbbbbb2222","agentId":"a2","result":{"review_verdict":"REDO","scope":"x"}}
EOF

OUT_A="$(bash "$SCRIPT" "$TMP/mixed.jsonl")"; RC_A=$?
check() { # <needle> <label> <haystack>
  if printf '%s\n' "$3" | grep -qF -- "$1"; then note "PASS  $2"; else note "FAIL  $2 — expected: $1"; fails=$((fails+1)); fi
}
check "steps=3 returned=2 pass=1 redo=1 pending=1" "mixed: counts + verdicts" "$OUT_A"
check "aaaaaaaa a1 returned PASS" "mixed: PASS step line" "$OUT_A"
check "bbbbbbbb a2 returned REDO" "mixed: REDO step line" "$OUT_A"
check "cccccccc a3 pending"       "mixed: pending step line" "$OUT_A"
if [[ "$RC_A" -eq 4 ]]; then note "PASS  mixed: exit 4 (pending)"; else note "FAIL  mixed: exit $RC_A, want 4"; fails=$((fails+1)); fi

# --- Fixture B: all returned → exit 0.
cat > "$TMP/done.jsonl" <<'EOF'
{"type":"started","key":"v2:dddddddd4444","agentId":"d1"}
{"type":"result","key":"v2:dddddddd4444","agentId":"d1","result":"review_verdict: PASS"}
EOF
OUT_B="$(bash "$SCRIPT" "$TMP/done.jsonl")"; RC_B=$?
check "steps=1 returned=1 pass=1 redo=0 pending=0" "done: all returned" "$OUT_B"
if [[ "$RC_B" -eq 0 ]]; then note "PASS  done: exit 0 (complete)"; else note "FAIL  done: exit $RC_B, want 0"; fails=$((fails+1)); fi

# --- Fixture C: absent journal → exit 3.
bash "$SCRIPT" "$TMP/nope.jsonl" >/dev/null 2>&1; RC_C=$?
if [[ "$RC_C" -eq 3 ]]; then note "PASS  absent: exit 3"; else note "FAIL  absent: exit $RC_C, want 3"; fails=$((fails+1)); fi

# --- Fixture D: malformed/blank lines tolerated, not counted.
cat > "$TMP/dirty.jsonl" <<'EOF'

not json at all
{"type":"started","key":"v2:eeeeeeee5555","agentId":"e1"}
{"type":"noise","key":"v2:ffff","agentId":"z"}
{"type":"result","key":"v2:eeeeeeee5555","agentId":"e1","result":"PASS"}
EOF
OUT_D="$(bash "$SCRIPT" "$TMP/dirty.jsonl")"; RC_D=$?
check "steps=1 returned=1 pass=1 redo=0 pending=0" "dirty: tolerant parse" "$OUT_D"
if [[ "$RC_D" -eq 0 ]]; then note "PASS  dirty: exit 0"; else note "FAIL  dirty: exit $RC_D, want 0"; fails=$((fails+1)); fi

if [[ "$fails" -gt 0 ]]; then
  printf '  FAIL  %d journal-status assertion(s) failed\n' "$fails" >&2
  exit 1
fi
printf '  PASS  journal-status.sh reports wave-return deterministically (counts, verdicts, exit codes)\n'
