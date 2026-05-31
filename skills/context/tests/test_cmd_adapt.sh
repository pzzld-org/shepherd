#!/usr/bin/env bash
# test_cmd_adapt.sh — shctx adapt (v6.0.4 #94/#95)
#   roll    writes one sprint_metrics row + harvests HIGH/CRITICAL audit_findings
#           into mem_entries(kind='prior')
#   priors  reads metrics averages (Check 8) + lesson priors (brief inject)
#   report  renders the SQLite-canonical sprint-patterns view
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init
"$SHCTX" migrate >/dev/null            # applies 0010 (sprint_metrics) + 0011 (mem 'prior' kind)
DB="$SHCTX_TEST_TMP/.shepherd/root.db"

# --- graceful empty: no metrics yet ⇒ priors --metrics emits nothing (caller
#     falls back to static defaults). Empty store == today's behavior. ---
out=$("$SHCTX" adapt priors --metrics)
assert_eq "empty-metrics" "$out" ""

# --- seed audit_findings for sprint 'test': two harvestable (high/critical),
#     one low that must NOT be harvested ---
echo "duplicated helper across two lanes" | "$SHCTX" audit insert \
  --concern=duplication --severity=high --hypothesis="two lanes wrote the same fn" --sprint=test >/dev/null
echo "user string reached the sql string" | "$SHCTX" audit insert \
  --concern=injection --severity=critical --hypothesis="unsanitized interpolation" --sprint=test >/dev/null
echo "trailing whitespace" | "$SHCTX" audit insert \
  --concern=style --severity=low --hypothesis="cosmetic" --sprint=test >/dev/null

# --- roll: metrics row + harvest ---
out=$("$SHCTX" adapt roll --sprint=test --grade=B --lanes=4 --waves=2 --wall-min=70 --api=150)
assert_contains "roll-summary" "$out" "adapt roll"

n=$(sqlite3 "$DB" "SELECT count(*) FROM sprint_metrics WHERE sprint_branch='test';")
assert_eq "metrics-row" "$n" "1"
lanes=$(sqlite3 "$DB" "SELECT lane_count FROM sprint_metrics WHERE sprint_branch='test';")
assert_eq "lane_count" "$lanes" "4"
wall=$(sqlite3 "$DB" "SELECT CAST(wall_minutes AS INTEGER) FROM sprint_metrics WHERE sprint_branch='test';")
assert_eq "wall_minutes" "$wall" "70"

vn=$(sqlite3 "$DB" "SELECT n FROM v_sprint_metrics_avg;")
assert_eq "view-n" "$vn" "1"

# exactly the two high/critical findings became priors; low is skipped
p=$(sqlite3 "$DB" "SELECT count(*) FROM mem_entries WHERE kind='prior';")
assert_eq "priors-harvested" "$p" "2"

# --- idempotent: re-roll same sprint replaces the row, harvests no duplicate priors ---
"$SHCTX" adapt roll --sprint=test --grade=A --lanes=5 --wall-min=80 --api=160 >/dev/null
n2=$(sqlite3 "$DB" "SELECT count(*) FROM sprint_metrics WHERE sprint_branch='test';")
assert_eq "metrics-idempotent" "$n2" "1"
g2=$(sqlite3 "$DB" "SELECT grade FROM sprint_metrics WHERE sprint_branch='test';")
assert_eq "metrics-replaced" "$g2" "A"
p2=$(sqlite3 "$DB" "SELECT count(*) FROM mem_entries WHERE kind='prior';")
assert_eq "priors-dedup" "$p2" "2"

# --- priors --metrics now emits real averages (the spawn Check-8 / engineer feed) ---
out=$("$SHCTX" adapt priors --metrics --json)
assert_contains "metrics-json-min" "$out" "avg_sprint_minutes"
assert_contains "metrics-json-api" "$out" "avg_api_per_sprint"

out=$("$SHCTX" adapt priors --metrics)
assert_contains "metrics-kv" "$out" "avg_sprint_minutes="

# --- priors --lessons --md surfaces harvested priors for brief injection ---
out=$("$SHCTX" adapt priors --lessons --md)
assert_contains "lessons-md" "$out" "prior:"

# --- report renders the materialized sprint-patterns view ---
out=$("$SHCTX" adapt report --md)
assert_contains "report" "$out" "test"

echo "test_cmd_adapt: ok"
