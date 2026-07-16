#!/usr/bin/env bash
# Staged-handoff seed-ready round-trip over the dedicated signal channel
# (v6.1.7 feature; migrated off the retired mailbox to `shctx signal` in v6.3.7 #206).
# Exercises the exact seam skills/shepherd/references/spawn-flags.md §--staged relies on:
#   planter (Session B):  shctx signal send --to=spawn-<slug> --kind=seed-ready
#   staged spawn (A):     shctx signal poll --as=... --kind=seed-ready --consume --json
# Confirms the durable signal survives across two independent sessions and that
# --consume gives one-shot semantics (a re-nudged Session A never re-processes it).
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
DB="$SHCTX_TEST_TMP/.shepherd/shepherd.db"

command -v python3 >/dev/null || { echo "skip: python3 not installed"; exit 0; }

"$SHCTX" init >/dev/null
"$SHCTX" migrate >/dev/null     # 0007 creates canonical tables; 0020 drops mailbox, adds session_signals

slug="v637-dev0"
recipient="spawn-${slug}"

# --- the mailbox is GONE (#206): the generic surface must not resolve ---------
if "$SHCTX" mailbox recv --as="$recipient" >/dev/null 2>&1; then
  echo "FAIL: 'shctx mailbox' still resolves — the generic surface was not removed (#206)" >&2; exit 1
fi
# The dropped table must be absent and the dedicated one present after full migrate.
has_mailbox=$(sqlite3 "$DB" "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='mailbox';")
has_signals=$(sqlite3 "$DB" "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='session_signals';")
assert_eq "staged.mailbox_dropped"  "$has_mailbox"  "0"
assert_eq "staged.signals_present"  "$has_signals"  "1"

# --- Session B (planter) emits seed-ready at close ----------------------------
id=$(printf '%s' "{\"event\":\"seed-ready\",\"sprint_slug\":\"$slug\",\"seed_path\":\".shepherd/docs/plans/$slug.seed.md\"}" \
  | "$SHCTX" signal send --to="$recipient" --kind=seed-ready)
[[ "$id" =~ ^[0-9]+$ ]] || { echo "FAIL: send did not return a numeric id (got '$id')" >&2; exit 1; }

# --- a non-destructive peek (no --consume) sees it but does NOT clear it -------
peek=$("$SHCTX" signal poll --as="$recipient" --kind=seed-ready --json)
seed_evt=$(printf '%s' "$peek" | jq -r '.[] | select(.kind=="seed-ready")')
assert_contains "staged.peek.kind"  "$seed_evt" "seed-ready"
assert_contains "staged.peek.slug"  "$seed_evt" "$slug"

# --- Session A (staged spawn) consumes at its wait gate — durable across the
#     independent session boundary; --consume stamps consumed_at (one-shot). ---
recv=$("$SHCTX" signal poll --as="$recipient" --kind=seed-ready --consume --json)
rid=$(printf '%s' "$recv" | jq -r '.[] | select(.kind=="seed-ready") | .id')
assert_eq "staged.recv.id" "$rid" "$id"
consumed=$(sqlite3 "$DB" "SELECT consumed_at IS NOT NULL FROM session_signals WHERE id=$rid;")
assert_eq "staged.consumed" "$consumed" "1"

# --- a second poll returns no rows (one-shot: a re-nudged Session A won't
#     re-process the seed signal). sqlite3 -json emits "" for zero rows. --------
recv2=$("$SHCTX" signal poll --as="$recipient" --kind=seed-ready --json)
if [[ -z "$recv2" ]]; then n2=0; else n2=$(printf '%s' "$recv2" | jq 'length'); fi
assert_eq "staged.reread.empty" "$n2" "0"

echo "test_staged_handoff: all assertions passed"
