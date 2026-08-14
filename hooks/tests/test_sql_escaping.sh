#!/usr/bin/env bash
# hooks/tests/test_sql_escaping.sh — regression test for #285
# (SQL quote-escaping, duplicated + broken in cmd_adapt.sh / cmd_loop.sh).
#
# `skills/context/scripts/cmd_adapt.sh` and `skills/context/scripts/cmd_loop.sh`
# escaped SQL text literals with the bash parameter-expansion form
# `${v//\'/\'\'}` (each file's `_txt()` helper, both at line 101 pre-fix). That
# form does NOT double a single quote on bash 3.2 — the REPLACEMENT side keeps
# its backslash literally instead of using it purely as an escape marker, so
# one apostrophe becomes four raw characters (`\'\'`) instead of the two SQLite
# wants (`''`). That truncates the SQL string literal early and leaves a bare
# backslash as the next token, which SQLite's parser rejects. Both call sites
# interpolate FREE-TEXT fields (a grade note, a loop task, a reflection) —
# exactly where an apostrophe lives in ordinary use — and NEITHER call site
# denies on a bad write (no exit-code check wraps the INSERT), so an
# exit-code-only assertion would have passed whether or not the row landed.
# This suite proves the fix by writing an apostrophe-bearing value THROUGH
# each call site into a real sqlite3 DB, then SELECTing it back and asserting
# the retrieved string equals the input EXACTLY — plus an adversarial
# DROP-TABLE-shaped payload per site, asserting both the exact round-trip and
# that the targeted table still exists afterward.
#
# Fix: both files now define the proven-correct esc() idiom already present in
# cmd_teammate.sh (`sed "s/'/''/g"`) and route every SQL text literal through
# it, replacing the broken hand-rolled parameter expansion everywhere it
# appeared in both files (not only at the two named line-101 sites).
#
# Call sites exercised (both route text VERBATIM through `_txt()`/esc(), so
# "equals the input exactly" is the correct assertion — no template wrapping):
#   - cmd_adapt.sh: `adapt roll --grade=<text>` → sprint_metrics.grade
#   - cmd_loop.sh:  `loop init --task=<text>`   → loops.task
#
# House style: exit 0 = pass, non-zero + message = fail (mirrors
# test_teammate_git_guard.sh).

set -eu -o pipefail
cd "$(dirname "$0")"
SCRIPTS_DIR="$(cd ../../skills/context/scripts && pwd)"

fails=0
total=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s — %s\n' "$1" "$2"; fails=$((fails+1)); }
skip() { printf '  SKIP  %s — %s\n' "$1" "$2"; }

if ! command -v sqlite3 >/dev/null 2>&1 || ! command -v jq >/dev/null 2>&1; then
  skip "all cases" "sqlite3 and/or jq binary missing"
  echo "—— 0/0 passed ——"
  exit 0
fi

# ---------------------------------------------------------------------------
# Ephemeral project: a fresh git repo + a real, fully-migrated shctx namespace
# (via the actual `shctx init`), so both call sites run against the same
# schema production does rather than a hand-rolled subset of it.
# ---------------------------------------------------------------------------
tmp=$(mktemp -d -t shep-sqlesc-test.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q .
git config user.email t@t
git config user.name t
git -c commit.gpgsign=false commit -q --allow-empty -m init

init_out=$(bash "$SCRIPTS_DIR/shctx" init --shepherd 2>&1) || {
  echo "FATAL: shctx init failed: $init_out" >&2
  exit 1
}

# shellcheck source=/dev/null
source "$SCRIPTS_DIR/_lib.sh"
DB="$(shctx_db_path)"
if [[ ! -f "$DB" ]]; then
  echo "FATAL: expected DB at $DB after 'shctx init' — got: $init_out" >&2
  exit 1
fi

table_exists() {
  local n
  n=$(sqlite3 "$DB" "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='$1';")
  [[ "${n:-0}" == "1" ]]
}

# ===========================================================================
# cmd_adapt.sh — `adapt roll --grade=<free text>` stores $grade VERBATIM into
# sprint_metrics.grade via _txt() (the fixed cmd_adapt.sh:101 site).
# ===========================================================================

# --- A1: apostrophe value round-trips exactly -------------------------------
total=$((total+1))
A1_GRADE="it's a fine grade"
out=$(bash "$SCRIPTS_DIR/cmd_adapt.sh" roll --sprint=sqlesc-a1 --grade="$A1_GRADE" 2>&1) || true
got=$(sqlite3 "$DB" "SELECT grade FROM sprint_metrics WHERE sprint_branch='sqlesc-a1';")
if [[ "$got" == "$A1_GRADE" ]]; then
  pass "A1 cmd_adapt.sh 'roll --grade' apostrophe value round-trips exactly"
else
  fail "A1 cmd_adapt.sh 'roll --grade' apostrophe value round-trips exactly" \
    "want=[$A1_GRADE] got=[$got] cmd_out=${out:0:200}"
fi

# --- A2: adversarial DROP-TABLE-shaped value round-trips, table survives ---
total=$((total+1))
A2_GRADE="pwned'); DROP TABLE sprint_metrics;--"
out=$(bash "$SCRIPTS_DIR/cmd_adapt.sh" roll --sprint=sqlesc-a2 --grade="$A2_GRADE" 2>&1) || true
if table_exists sprint_metrics; then
  got=$(sqlite3 "$DB" "SELECT grade FROM sprint_metrics WHERE sprint_branch='sqlesc-a2';")
  if [[ "$got" == "$A2_GRADE" ]]; then
    pass "A2 cmd_adapt.sh 'roll --grade' DROP-TABLE-shaped value round-trips exactly, table survives"
  else
    fail "A2 cmd_adapt.sh 'roll --grade' DROP-TABLE-shaped value round-trips exactly, table survives" \
      "want=[$A2_GRADE] got=[$got] cmd_out=${out:0:200}"
  fi
else
  fail "A2 cmd_adapt.sh 'roll --grade' DROP-TABLE-shaped value round-trips exactly, table survives" \
    "sprint_metrics TABLE WAS DROPPED — cmd_out=${out:0:300}"
fi

# ===========================================================================
# cmd_loop.sh — `loop init --task=<free text>` stores $task VERBATIM into
# loops.task via _txt() (the fixed cmd_loop.sh:101 site).
# ===========================================================================

# --- L1: apostrophe value round-trips exactly -------------------------------
total=$((total+1))
L1_TASK="reviewer's note: don't merge yet"
loop_id1=$(bash "$SCRIPTS_DIR/cmd_loop.sh" init --max=3 --task="$L1_TASK" 2>&1) || true
got=$(sqlite3 "$DB" "SELECT task FROM loops WHERE id='$loop_id1';")
if [[ "$got" == "$L1_TASK" ]]; then
  pass "L1 cmd_loop.sh 'loop init --task' apostrophe value round-trips exactly"
else
  fail "L1 cmd_loop.sh 'loop init --task' apostrophe value round-trips exactly" \
    "want=[$L1_TASK] got=[$got] loop_id_out=${loop_id1:0:200}"
fi

# --- L2: adversarial DROP-TABLE-shaped value round-trips, table survives ---
total=$((total+1))
L2_TASK="pwned'); DROP TABLE loops;--"
loop_id2=$(bash "$SCRIPTS_DIR/cmd_loop.sh" init --max=3 --task="$L2_TASK" 2>&1) || true
if table_exists loops; then
  got=$(sqlite3 "$DB" "SELECT task FROM loops WHERE id='$loop_id2';")
  if [[ "$got" == "$L2_TASK" ]]; then
    pass "L2 cmd_loop.sh 'loop init --task' DROP-TABLE-shaped value round-trips exactly, table survives"
  else
    fail "L2 cmd_loop.sh 'loop init --task' DROP-TABLE-shaped value round-trips exactly, table survives" \
      "want=[$L2_TASK] got=[$got] loop_id_out=${loop_id2:0:200}"
  fi
else
  fail "L2 cmd_loop.sh 'loop init --task' DROP-TABLE-shaped value round-trips exactly, table survives" \
    "loops TABLE WAS DROPPED — loop_id_out=${loop_id2:0:300}"
fi

echo "—— $((total-fails))/$total passed ——"
exit "$fails"
