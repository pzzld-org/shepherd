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

# --- recommend: with ≥1 sprint of history, emits measured lane/size guidance ---
out=$("$SHCTX" adapt recommend --md)
assert_contains "recommend-md-lanes" "$out" "suggested lanes"
assert_contains "recommend-md-band"  "$out" "t-shirt band"
out=$("$SHCTX" adapt recommend --json)
assert_contains "recommend-json" "$out" "suggested_lanes"
assert_contains "recommend-json-band" "$out" "size_band"

# --- trends: <3 sprints ⇒ graceful empty (nothing fires) ---
out=$("$SHCTX" adapt report --trends)
assert_eq "trends-insufficient" "$out" ""

# --- seed 3 sprints with a recurring HIGH concern + worsening grade + rising
#     cost, so all three §VI signals fire. dup-by-title means one prior; the
#     recurrence path refreshes its last-seen and never re-harvests. ---
for s in s1 s2 s3; do
  echo "duplicated helper across two lanes" | "$SHCTX" audit insert \
    --concern=duplication --severity=high --hypothesis="recurs" --sprint=$s >/dev/null
done
"$SHCTX" adapt roll --sprint=s1 --grade=A --lanes=3 --wall-min=60  --api=100 >/dev/null
"$SHCTX" adapt roll --sprint=s2 --grade=B --lanes=4 --wall-min=90  --api=150 >/dev/null
"$SHCTX" adapt roll --sprint=s3 --grade=C --lanes=5 --wall-min=140 --api=260 >/dev/null

out=$("$SHCTX" adapt report --trends)
assert_contains "trends-fires"   "$out" "TREND ALERT"
assert_contains "trends-concern" "$out" "duplication"
assert_contains "trends-grade"   "$out" "trending DOWN"
out=$("$SHCTX" adapt report --trends --json)
assert_contains "trends-json" "$out" "grade_trending_down\":true"

# --- decay: a stale unpinned prior (updated_at far in the past, never re-seen)
#     is pruned on the next roll; a pinned prior is NOT. Window K=1 sprint so
#     the measured inter-sprint gap makes the cutoff bite immediately. ---
PID=$(sqlite3 "$DB" "SELECT id FROM projects LIMIT 1;")
sqlite3 "$DB" "INSERT INTO mem_entries (id,project_id,kind,title,body,tags,pinned,created_at,updated_at)
               VALUES ('stale-0001','$PID','prior','prior: stale-concern','old','[\"stale-concern\"]',0,1,1);"
sqlite3 "$DB" "INSERT INTO mem_entries (id,project_id,kind,title,body,tags,pinned,created_at,updated_at)
               VALUES ('pinned-0001','$PID','prior','prior: pinned-concern','keep','[\"pinned-concern\"]',1,1,1);"
SHCTX_ADAPT_DECAY_SPRINTS=1 "$SHCTX" adapt roll --sprint=s3 --grade=C --wall-min=140 --api=260 >/dev/null
gone=$(sqlite3 "$DB" "SELECT count(*) FROM mem_entries WHERE id='stale-0001';")
assert_eq "decay-pruned-stale" "$gone" "0"
kept=$(sqlite3 "$DB" "SELECT count(*) FROM mem_entries WHERE id='pinned-0001';")
assert_eq "decay-kept-pinned" "$kept" "1"

# --- exit-code regression (v6.0.8): a healthy alert/recommendation must exit 0
#     even when the LAST optional `[[ ]] && echo` line does not fire — the
#     trailing-`&&` hazard under `set -e`. Captured set -e-safe via `|| rc=$?`. ---
# trends: concern recurs but grade + cost are FLAT, so cost_up (the last signal)
# is false; the function must still exit 0 while emitting the alert.
for s in t1 t2 t3; do
  echo "recurring concern only" | "$SHCTX" audit insert \
    --concern=flaky --severity=high --hypothesis="recurs" --sprint=$s >/dev/null
  "$SHCTX" adapt roll --sprint=$s --grade=B --wall-min=60 --api=100 >/dev/null
done
rc=0; "$SHCTX" adapt report --trends >/dev/null || rc=$?
assert_eq "trends-exit0-concern-only" "$rc" "0"
# recommend: history present but NO watch-concerns (priors cleared) — the last
# optional line is skipped, so the function must still exit 0.
sqlite3 "$DB" "DELETE FROM mem_entries WHERE kind='prior';"
rc=0; "$SHCTX" adapt recommend --md >/dev/null || rc=$?
assert_eq "recommend-exit0-no-concerns" "$rc" "0"

echo "test_cmd_adapt: ok"
