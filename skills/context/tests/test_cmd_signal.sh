#!/usr/bin/env bash
# test_cmd_signal.sh — unit tests for `shctx signal` (v6.3.7, #206).
#
# The dedicated CROSS-SESSION handoff channel that replaced the retired mailbox.
# Covers: send returns a numeric id; poll peeks non-destructively; --kind filters;
# --consume is one-shot; recipient scoping; and the two usage/validation errors.
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
DB="$SHCTX_TEST_TMP/.shepherd/shepherd.db"

command -v python3 >/dev/null || { echo "skip: python3 not installed"; exit 0; }

"$SHCTX" init >/dev/null
"$SHCTX" migrate >/dev/null

# --- send returns a numeric id ------------------------------------------------
id=$(printf '%s' '{"event":"seed-ready","v":1}' | "$SHCTX" signal send --to="spawn-a" --kind=seed-ready)
[[ "$id" =~ ^[0-9]+$ ]] || { echo "FAIL: send id not numeric (got '$id')" >&2; exit 1; }

# --- poll peeks non-destructively (no --consume leaves consumed_at NULL) -------
peek=$("$SHCTX" signal poll --as="spawn-a" --kind=seed-ready --json)
assert_contains "signal.peek" "$(printf '%s' "$peek" | jq -r '.[0].kind')" "seed-ready"
still=$(sqlite3 "$DB" "SELECT consumed_at IS NULL FROM session_signals WHERE id=$id;")
assert_eq "signal.peek.unconsumed" "$still" "1"

# --- recipient scoping: a different recipient sees nothing ---------------------
other=$("$SHCTX" signal poll --as="spawn-b" --json)
[[ -z "$other" ]] && nb=0 || nb=$(printf '%s' "$other" | jq 'length')
assert_eq "signal.scope.other-empty" "$nb" "0"

# --- --kind filters: a non-matching kind sees nothing -------------------------
wrongkind=$("$SHCTX" signal poll --as="spawn-a" --kind=other-kind --json)
[[ -z "$wrongkind" ]] && nk=0 || nk=$(printf '%s' "$wrongkind" | jq 'length')
assert_eq "signal.kind.filter" "$nk" "0"

# --- --consume is one-shot: consumes, then a re-poll is empty ------------------
"$SHCTX" signal poll --as="spawn-a" --kind=seed-ready --consume --json >/dev/null
consumed=$(sqlite3 "$DB" "SELECT consumed_at IS NOT NULL FROM session_signals WHERE id=$id;")
assert_eq "signal.consume.stamped" "$consumed" "1"
again=$("$SHCTX" signal poll --as="spawn-a" --kind=seed-ready --json)
[[ -z "$again" ]] && na=0 || na=$(printf '%s' "$again" | jq 'length')
assert_eq "signal.consume.oneshot" "$na" "0"

# --- validation: invalid JSON payload → exit 1 --------------------------------
if printf '%s' 'not-json' | "$SHCTX" signal send --to="spawn-c" --kind=x >/dev/null 2>&1; then
  echo "FAIL: send accepted invalid JSON payload" >&2; exit 1
fi

# --- usage: missing --kind (or --to) → exit 2 ---------------------------------
# `|| rc=$?` keeps the expected non-zero from tripping the suite's `set -e`.
rc=0; printf '%s' '{}' | "$SHCTX" signal send --to="spawn-c" >/dev/null 2>&1 || rc=$?
assert_eq "signal.usage.missing-kind" "$rc" "2"

echo "test_cmd_signal: all assertions passed"
