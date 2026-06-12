#!/usr/bin/env bash
# loop_lifecycle.sh — shctx loop init→record×2→close→list round-trip (v6.0.9)
#
# Uses a THROWAWAY db: SHEPHERD_WORKDIR is set to a temp dir so the repo's
# .artifacts/shepherd.db is NEVER touched. Applies only the migrations we need
# directly (same pattern as shctx_test_db in _setup.sh) so the test is not
# derailed by optional build-time features (e.g. FTS5) unavailable in the
# CI environment.
#
# Run: bash skills/context/tests/loop_lifecycle.sh
# (Also registered by skills/context/tests/run.sh when present.)

source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo

SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
MIGDIR="$SHCTX_SKILL_ROOT/schema/migrations"

# Bootstrap: init (creates .shepherd/ and the base 0001 schema), then apply
# the migrations our loop tables depend on, directly rather than via
# `shctx migrate` (which aborts on FTS5 if the sqlite3 build lacks it).
"$SHCTX" init >/dev/null 2>&1
DB="$SHCTX_TEST_TMP/.shepherd/shepherd.db"

_apply() {
  local n="$1"
  local f
  f=$(ls "$MIGDIR/${n}_"*.sql 2>/dev/null | head -1)
  [[ -n "$f" ]] || { echo "FAIL: migration $n not found in $MIGDIR" >&2; exit 1; }
  sqlite3 "$DB" < "$f" >/dev/null 2>&1 \
    || { echo "FAIL: migration $(basename "$f") failed" >&2; exit 1; }
}

# Apply the chain our new tables need (0007 for FK parent tables, 0012/0013 for loops/focus).
_apply 0005
_apply 0006
_apply 0007
_apply 0008
_apply 0009
_apply 0010
_apply 0011
_apply 0012
_apply 0013

# Verify that the migrations created the expected tables.
assert_table "$DB" loops
assert_table "$DB" loop_iterations
assert_table "$DB" focus

# ---------------------------------------------------------------------------
# init — register a loop, capture the emitted loop-id
# ---------------------------------------------------------------------------
loop_id=$("$SHCTX" loop init \
  --task="find all TODO comments" \
  --max=5 \
  --kind=convergence \
  --agent=discovery)

assert_contains "init-id-prefix" "$loop_id" "loop-"

# The id must have the expected format: loop-YYYYMMDD-NNN
[[ "$loop_id" =~ ^loop-[0-9]{8}-[0-9]{3}$ ]] \
  || { echo "FAIL: loop-id format unexpected: $loop_id" >&2; exit 1; }

# Row must be in DB with status='active'
row_status=$(sqlite3 "$DB" "SELECT status FROM loops WHERE id='$loop_id';")
assert_eq "init-status" "$row_status" "active"

row_max=$(sqlite3 "$DB" "SELECT max_iterations FROM loops WHERE id='$loop_id';")
assert_eq "init-max" "$row_max" "5"

row_kind=$(sqlite3 "$DB" "SELECT kind FROM loops WHERE id='$loop_id';")
assert_eq "init-kind" "$row_kind" "convergence"

# ---------------------------------------------------------------------------
# status — text and json output before any iterations
# ---------------------------------------------------------------------------
out=$("$SHCTX" loop status --id="$loop_id")
assert_contains "status-id"     "$out" "$loop_id"
assert_contains "status-active" "$out" "active"

out_json=$("$SHCTX" loop status --id="$loop_id" --json)
assert_contains "status-json-id"     "$out_json" "\"$loop_id\""
assert_contains "status-json-status" "$out_json" "active"
assert_contains "status-json-iters"  "$out_json" "iterations"

# ---------------------------------------------------------------------------
# record — two iterations
# ---------------------------------------------------------------------------
"$SHCTX" loop record \
  --id="$loop_id" \
  --iteration=1 \
  --new_findings=true \
  --summary="found 3 TODO comments" >/dev/null

"$SHCTX" loop record \
  --id="$loop_id" \
  --iteration=2 \
  --new_findings=false \
  --summary="no new findings" >/dev/null

iter_count=$(sqlite3 "$DB" "SELECT COUNT(*) FROM loop_iterations WHERE loop_id='$loop_id';")
assert_eq "record-count" "$iter_count" "2"

nf1=$(sqlite3 "$DB" "SELECT new_findings FROM loop_iterations WHERE loop_id='$loop_id' AND iteration=1;")
assert_eq "record-nf1" "$nf1" "1"

nf2=$(sqlite3 "$DB" "SELECT new_findings FROM loop_iterations WHERE loop_id='$loop_id' AND iteration=2;")
assert_eq "record-nf2" "$nf2" "0"

# status --md now shows the two iterations
out_md=$("$SHCTX" loop status --id="$loop_id" --md)
assert_contains "status-md-iter1" "$out_md" "true"
assert_contains "status-md-iter2" "$out_md" "false"
assert_contains "status-md-summ"  "$out_md" "found 3 TODO"

# ---------------------------------------------------------------------------
# idempotent re-record (INSERT OR REPLACE on same iteration)
# ---------------------------------------------------------------------------
"$SHCTX" loop record \
  --id="$loop_id" \
  --iteration=1 \
  --new_findings=false \
  --summary="re-recorded" >/dev/null

iter_count2=$(sqlite3 "$DB" "SELECT COUNT(*) FROM loop_iterations WHERE loop_id='$loop_id';")
assert_eq "record-idempotent-count" "$iter_count2" "2"   # still 2, not 3

nf1b=$(sqlite3 "$DB" "SELECT new_findings FROM loop_iterations WHERE loop_id='$loop_id' AND iteration=1;")
assert_eq "record-idempotent-replaced" "$nf1b" "0"       # value updated

# ---------------------------------------------------------------------------
# close — finalize with status=converged
# ---------------------------------------------------------------------------
close_out=$("$SHCTX" loop close --id="$loop_id" --status=converged)
assert_contains "close-output"  "$close_out" "converged"
assert_contains "close-output2" "$close_out" "$loop_id"

closed_status=$(sqlite3 "$DB" "SELECT status FROM loops WHERE id='$loop_id';")
assert_eq "close-status" "$closed_status" "converged"

# ---------------------------------------------------------------------------
# list — default (active only): converged loop must NOT appear
# ---------------------------------------------------------------------------
out_list=$("$SHCTX" loop list)
# The converged loop should not appear in the active list.
if grep -qF "$loop_id" <<< "$out_list"; then
  echo "FAIL: list-active: converged loop '$loop_id' appeared in active-only listing" >&2
  exit 1
fi

# --all: must appear
out_all=$("$SHCTX" loop list --all)
assert_contains "list-all" "$out_all" "$loop_id"

# --json output
out_json_all=$("$SHCTX" loop list --all --json)
assert_contains "list-json-all" "$out_json_all" "\"$loop_id\""

# ---------------------------------------------------------------------------
# focus upsert + show (migration 0013 round-trip)
# ---------------------------------------------------------------------------
upsert_out=$("$SHCTX" loop focus upsert \
  --sprint=dev.6.0.9 \
  --objective="Ship loop foundation + focus record for v6.0.9" \
  --active-node=SEED-VERIFY \
  --ready-set=SEED-VERIFY \
  --obligations='["lane-1 pending"]' \
  --invariants='["no teammate git integration"]')

assert_contains "focus-upsert-created" "$upsert_out" "dev.6.0.9"

fr_sprint=$(sqlite3 "$DB" "SELECT sprint FROM focus WHERE sprint='dev.6.0.9';")
assert_eq "focus-sprint" "$fr_sprint" "dev.6.0.9"

fr_node=$(sqlite3 "$DB" "SELECT active_node FROM focus WHERE sprint='dev.6.0.9';")
assert_eq "focus-node" "$fr_node" "SEED-VERIFY"

# show --md
show_out=$("$SHCTX" loop focus show --sprint=dev.6.0.9 --md)
assert_contains "focus-show-md-sprint"    "$show_out" "dev.6.0.9"
assert_contains "focus-show-md-objective" "$show_out" "Ship loop foundation"
assert_contains "focus-show-md-node"      "$show_out" "SEED-VERIFY"

# show --json
show_json=$("$SHCTX" loop focus show --sprint=dev.6.0.9 --json)
assert_contains "focus-show-json-sprint" "$show_json" "dev.6.0.9"
assert_contains "focus-show-json-oblig"  "$show_json" "lane-1 pending"

# refresh (second upsert patches only supplied columns)
"$SHCTX" loop focus upsert \
  --sprint=dev.6.0.9 \
  --active-node=WAVE-GATE-1 >/dev/null

fr_node2=$(sqlite3 "$DB" "SELECT active_node FROM focus WHERE sprint='dev.6.0.9';")
assert_eq "focus-refresh-node" "$fr_node2" "WAVE-GATE-1"

fr_obj2=$(sqlite3 "$DB" "SELECT objective FROM focus WHERE sprint='dev.6.0.9';")
assert_contains "focus-refresh-obj-preserved" "$fr_obj2" "Ship loop foundation"

# ---------------------------------------------------------------------------
# second loop for day-sequence uniqueness (NNN increments)
# ---------------------------------------------------------------------------
loop_id2=$("$SHCTX" loop init \
  --task="second loop same day" \
  --max=3 \
  --kind=watch)

[[ "$loop_id2" != "$loop_id" ]] \
  || { echo "FAIL: day-sequence: two inits on same day produced identical ids" >&2; exit 1; }
assert_contains "second-loop-prefix" "$loop_id2" "loop-"

echo "loop_lifecycle: ok"
