#!/usr/bin/env bash
# hooks/tests/test_gates_ledger.sh — the #59 gates-ran ledger (v6.5.0).
#
# Two legs of the deterministic gates-invocation record:
#   • bash_post.sh appends one JSONL row {ts, gate, command} to
#     <ns>/tmp/gates-ran-<session>.jsonl when the Bash command CONTAINS a
#     configured gate string — [gates].check, [gates].lint, or a
#     [gates.extra] entry — and stays silent for everything else.
#   • close_finalize_check.sh, once a sprint-slug close report is committed,
#     warns ONCE per session on stderr for every [gates.extra] entry with no
#     recorded invocation (never a block; the block contract is untouched).
# `shepherd doctor`'s gates section reads the same ledger (pytest-covered in
# services/cli/tests/test_doctor.py).
#
# Conventions mirror hooks/tests/test_coordinate_drive_guard.sh.

set -eu -o pipefail
cd "$(dirname "$0")"
HOOKS_DIR="$(cd .. && pwd)/scripts"

fails=0
total=0
pass()  { printf '  PASS  %s\n' "$1"; }
fail()  { printf '  FAIL  %s — %s\n' "$1" "$2"; fails=$((fails+1)); }

# ---------------------------------------------------------------------------
# Ephemeral shepherd-flagged repo with a [gates] config.
# ---------------------------------------------------------------------------
tmp=$(mktemp -d -t shep-gates-test.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q .
git config user.email t@t
git config user.name t
git -c commit.gpgsign=false commit -q --allow-empty -m init
mkdir -p .claude .shepherd
cat > .claude/shepherd.toml <<'TOML'
[gates]
check  = "jq empty plugin.json"
lint   = "./lint.sh"
format = ""

[gates.extra]
hook_tests = "bash hooks/tests/run.sh"
ctx_tests  = "bash skills/context/tests/run.sh"
TOML

LEDGER=".shepherd/tmp/gates-ran-s1.jsonl"
post() { # post <session> <command>
  printf '{"session_id":"%s","tool_name":"Bash","tool_input":{"command":"%s"},"tool_response":{"content":"ok"}}' "$1" "$2" \
    | bash "$HOOKS_DIR/bash_post.sh" >/dev/null 2>&1 || true
}

# ---------------------------------------------------------------------------
# 1. A command containing the configured [gates].check string → one row.
# ---------------------------------------------------------------------------
total=$((total+1))
post s1 "jq empty plugin.json && echo checked"
if [[ -f "$LEDGER" ]] && grep -qE '"gate":[[:space:]]*"check"' "$LEDGER"; then
  pass "check gate recorded (substring match through a && wrapper)"
else
  fail "check gate recorded" "ledger=$(cat "$LEDGER" 2>/dev/null || echo MISSING)"
fi

# ---------------------------------------------------------------------------
# 2. A [gates.extra] entry, invoked via an absolute-ish wrapper → extra:<key> row.
# ---------------------------------------------------------------------------
total=$((total+1))
post s1 "cd /repo && bash hooks/tests/run.sh"
if grep -qE '"gate":[[:space:]]*"extra:hook_tests"' "$LEDGER" 2>/dev/null; then
  pass "extra:hook_tests recorded"
else
  fail "extra:hook_tests recorded" "ledger=$(cat "$LEDGER" 2>/dev/null || echo MISSING)"
fi

# ---------------------------------------------------------------------------
# 3. An unrelated command → NO new row (row count stable).
# ---------------------------------------------------------------------------
total=$((total+1))
BEFORE=$(grep -c . "$LEDGER" 2>/dev/null || echo 0)
post s1 "ls -la"
AFTER=$(grep -c . "$LEDGER" 2>/dev/null || echo 0)
if [[ "$AFTER" == "$BEFORE" ]]; then
  pass "unrelated command: no ledger row"
else
  fail "unrelated command: no ledger row" "before=$BEFORE after=$AFTER"
fi

# ---------------------------------------------------------------------------
# 4. An empty-valued gate ([gates].format = "") NEVER matches (an empty
#    substring would match every command).
# ---------------------------------------------------------------------------
total=$((total+1))
if ! grep -qE '"gate":[[:space:]]*"format"' "$LEDGER" 2>/dev/null; then
  pass "empty-valued gate never records"
else
  fail "empty-valued gate never records" "$(cat "$LEDGER")"
fi

# ---------------------------------------------------------------------------
# 5. The ledger is per-session: a second session writes its own file.
# ---------------------------------------------------------------------------
total=$((total+1))
post s2 "./lint.sh"
if grep -qE '"gate":[[:space:]]*"lint"' ".shepherd/tmp/gates-ran-s2.jsonl" 2>/dev/null \
   && ! grep -qE '"gate":[[:space:]]*"lint"' "$LEDGER" 2>/dev/null; then
  pass "per-session ledgers: s2's lint lands in s2's file only"
else
  fail "per-session ledgers" "s1=$(cat "$LEDGER" 2>/dev/null) s2=$(cat .shepherd/tmp/gates-ran-s2.jsonl 2>/dev/null || echo MISSING)"
fi

# ---------------------------------------------------------------------------
# close_finalize_check.sh leg — needs a sprint branch + committed close report.
# ---------------------------------------------------------------------------
git checkout -q -b v1.0.0-dev.3
mkdir -p .shepherd/reports
echo "close" > .shepherd/reports/2026-08-03-v100-dev3-close.md
git add .shepherd/reports/2026-08-03-v100-dev3-close.md .claude/shepherd.toml
git -c commit.gpgsign=false commit -q -m "close report"

stop() { # stop <session> — echoes the hook's STDERR
  printf '{"session_id":"%s","hook_event_name":"Stop"}' "$1" \
    | bash "$HOOKS_DIR/close_finalize_check.sh" 2>&1 >/dev/null || true
}

# ---------------------------------------------------------------------------
# 6. Close report committed + extras never ran → ONE stderr warn naming the
#    missing [gates.extra] keys; a second Stop in the same session is silent
#    (marker-bounded), and the hook still exits 0 both times.
# ---------------------------------------------------------------------------
total=$((total+1))
ERR1=$(stop sess-close)
ERR2=$(stop sess-close)
if printf '%s' "$ERR1" | grep -q 'gates.extra' \
   && printf '%s' "$ERR1" | grep -q 'hook_tests' \
   && printf '%s' "$ERR1" | grep -q 'ctx_tests' \
   && ! printf '%s' "$ERR2" | grep -q 'gates.extra'; then
  pass "close-finalize warns once on un-run extras, then stays silent"
else
  fail "close-finalize extras warn" "err1=${ERR1:0:120} err2=${ERR2:0:120}"
fi

# ---------------------------------------------------------------------------
# 7. With every extra recorded in the session's ledger → no warn at all.
# ---------------------------------------------------------------------------
total=$((total+1))
post sess-green "bash hooks/tests/run.sh"
post sess-green "bash skills/context/tests/run.sh"
ERR3=$(stop sess-green)
if ! printf '%s' "$ERR3" | grep -q 'gates.extra'; then
  pass "close-finalize silent when every extra has a recorded invocation"
else
  fail "close-finalize silent when extras ran" "err=${ERR3:0:150}"
fi

# ---------------------------------------------------------------------------
# 8. The warn never blocks: stdout carries no {"decision":"block"} from the
#    gates leg alone (no origin remote → Signal B empty → the block contract
#    exits before any block emission).
# ---------------------------------------------------------------------------
total=$((total+1))
OUT=$(printf '{"session_id":"sess-out","hook_event_name":"Stop"}' \
  | bash "$HOOKS_DIR/close_finalize_check.sh" 2>/dev/null || true)
if ! printf '%s' "$OUT" | grep -q '"decision"'; then
  pass "gates warn is stderr-only — never a Stop block by itself"
else
  fail "gates warn never blocks" "out=${OUT:0:150}"
fi

echo "—— $((total-fails))/$total passed ——"
exit "$fails"
