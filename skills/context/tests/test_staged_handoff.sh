#!/usr/bin/env bash
# Staged-handoff seed-ready round-trip (v6.1.7 feature, verified v6.1.8).
# Exercises the exact mailbox seam doctrines/staged-handoff.md relies on:
#   planter (Session B):  shctx mailbox send --to=shepherd-spawn-<slug> --kind=seed-ready
#   staged spawn (A):     shctx mailbox recv --as=... --unread-only --mark-read | jq '.[]|select(.kind=="seed-ready")'
#                         shctx mailbox ack <id>
# Confirms the durable signal survives (recv works even though the two are
# independent sessions) and the corrected `.[]` jq iteration finds it.
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
DB="$SHCTX_TEST_TMP/.shepherd/shepherd.db"

command -v python3 >/dev/null || { echo "skip: python3 not installed"; exit 0; }

"$SHCTX" init >/dev/null
"$SHCTX" migrate >/dev/null     # 0007 adds the mailbox table

slug="v618-dev0"
recipient="shepherd-spawn-${slug}"

# Session B (planter) emits seed-ready at close.
id=$(printf '%s' "{\"event\":\"seed-ready\",\"sprint_slug\":\"$slug\",\"seed_path\":\".shepherd/docs/plans/$slug.seed.md\"}" \
  | "$SHCTX" mailbox send --to="$recipient" --kind=seed-ready)
[[ "$id" =~ ^[0-9]+$ ]] || { echo "FAIL: send did not return a numeric id (got '$id')" >&2; exit 1; }

# Session A (staged spawn) consumes at its seed-wait gate — durable even though
# B has "ended". The corrected doctrine snippet iterates the JSON array with .[].
recv=$("$SHCTX" mailbox recv --as="$recipient" --unread-only --mark-read)
seed_evt=$(printf '%s' "$recv" | jq -r '.[] | select(.kind=="seed-ready")')
assert_contains "staged.recv.kind"  "$seed_evt" "seed-ready"
assert_contains "staged.recv.slug"  "$seed_evt" "$slug"

# The matched row carries the numeric id used for ack.
rid=$(printf '%s' "$recv" | jq -r '.[] | select(.kind=="seed-ready") | .id')
assert_eq "staged.recv.id" "$rid" "$id"
"$SHCTX" mailbox ack "$rid"
acked=$(sqlite3 "$DB" "SELECT acked_at IS NOT NULL FROM mailbox WHERE id=$rid;")
assert_eq "staged.acked" "$acked" "1"

# Second consume with --unread-only returns no rows (mark-read worked → durable,
# one-shot semantics; a re-nudged Session A won't re-process the seed signal).
# Note: sqlite3 -json emits an EMPTY string (not "[]") for zero rows.
recv2=$("$SHCTX" mailbox recv --as="$recipient" --unread-only)
if [[ -z "$recv2" ]]; then n2=0; else n2=$(printf '%s' "$recv2" | jq 'length'); fi
assert_eq "staged.reread.empty" "$n2" "0"

echo "test_staged_handoff: all assertions passed"
