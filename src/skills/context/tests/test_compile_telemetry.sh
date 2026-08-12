#!/usr/bin/env bash
# test_compile_telemetry.sh — deliberate-degradation test for the
# "## Compile-down telemetry" close-report subsection (v6.0.9, #87).
#
# Strategy:
#   1. Spin up a throwaway DB via SHEPHERD_WORKDIR (never touches .artifacts/shepherd.db).
#   2. Apply schema through migration 0014 (compile_runs).
#   3. Seed one clean compile-run row (CLOSE-SWARM, no degradation) and one
#      deliberately degraded row (WAVE-1-IMPL: injected runtime failure + direct-
#      dispatch fallback that recovered successfully).
#   4. Assert `shctx adapt report --compile-telemetry` reflects:
#      a. both segments appear in the markdown output
#      b. the degraded segment's degradation_events = 1, recovered_events = 1
#      c. the degradation-detail block ("Degradation events") is emitted
#      d. the cause string is present
#   5. Assert --json parity: same data in machine-readable form.
#   6. Verify graceful-empty: a fresh sprint with no rows emits nothing.
#
# Run standalone:
#   bash skills/context/tests/test_compile_telemetry.sh
# Or via the suite (auto-registered by run.sh glob `test_*.sh`):
#   bash skills/context/tests/run.sh
#
# DOES NOT edit the repo's .artifacts/shepherd.db — SHEPHERD_WORKDIR is always
# pointed at a mktemp-created throwaway directory.

source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"

# ---- throwaway namespace (never touches .artifacts/shepherd.db) -----------------
THROWAWAY_ROOT="$(mktemp -d -t compile-tel.XXXXXX)"
trap 'rm -rf "$THROWAWAY_ROOT"' EXIT
export SHEPHERD_WORKDIR="${THROWAWAY_ROOT}/.shepherd"

SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"

# We need a git repo so shctx_repo_root() doesn't fall back to pwd unexpectedly.
shctx_test_repo   # sets up $SHCTX_TEST_TMP as a git repo + cd's there
# But our SHEPHERD_WORKDIR is the throwaway, not $SHCTX_TEST_TMP/.shepherd.
mkdir -p "$SHEPHERD_WORKDIR"

"$SHCTX" init --shepherd >/dev/null          # init in SHEPHERD_WORKDIR
"$SHCTX" migrate >/dev/null                  # applies all migrations including 0014
DB="${SHEPHERD_WORKDIR}/shepherd.db"

# ---- verify migration 0014 was applied --------------------------------------
assert_table "$DB" "compile_runs"

# ---- seed project + sprint context -----------------------------------------
PID=$(sqlite3 "$DB" "SELECT id FROM projects LIMIT 1;")
SPRINT="dev.6.0.9-tel-test"

# ---- seed a clean compile run (CLOSE-SWARM, no degradation) ----------------
sqlite3 "$DB" "INSERT OR IGNORE INTO compile_runs
  (project_id, run_id, sprint, segment, segment_node_count, total_agents,
   peak_concurrency, concurrency_ceiling,
   faithfulness_soundness, faithfulness_completeness, faithfulness_determinism,
   faithfulness_ok, seam_export_present, seam_export_consumed,
   degraded, degradation_cause, recovered,
   script_sha256, compiled_at, run_started_at, run_finished_at)
VALUES
  ('$PID','run-teltest-001','$SPRINT','CLOSE-SWARM',3,5,
   5,16,
   'PASS','PASS','PASS',1,1,1,
   0,NULL,NULL,
   'abc123',$(date +%s),$(date +%s),$(date +%s));"

# ---- DELIBERATE DEGRADATION: inject a segment runtime failure ---------------
# Represents: WAVE-1-IMPL runtime was unavailable; conductor fell back to
# direct in-context dispatch which completed successfully (recovered = 1).
# This is the acceptance clause from #87 — "the deliberately-triggered
# degradation path has a passing test."
sqlite3 "$DB" "INSERT OR IGNORE INTO compile_runs
  (project_id, run_id, sprint, segment, segment_node_count, total_agents,
   peak_concurrency, concurrency_ceiling,
   faithfulness_soundness, faithfulness_completeness, faithfulness_determinism,
   faithfulness_ok, seam_export_present, seam_export_consumed,
   degraded, degradation_cause, recovered,
   script_sha256, compiled_at, run_started_at, run_finished_at)
VALUES
  ('$PID','run-teltest-002','$SPRINT','WAVE-1-IMPL',4,6,
   0,16,
   'PASS','PASS','PASS',1,1,1,
   1,'runtime_unavailable',1,
   'def456',$(date +%s),$(date +%s),$(date +%s));"

# ---- set the sprint branch so current_sprint() matches our seeded sprint ----
# The aggregator calls current_sprint() (git rev-parse --abbrev-ref HEAD).
# We create the branch in the test repo so the aggregator finds it.
git checkout -qb "$SPRINT" 2>/dev/null || git checkout -q "$SPRINT" 2>/dev/null

# ---- assert: markdown output contains both segments -------------------------
out=$("$SHCTX" adapt report --compile-telemetry --md)

assert_contains "md-has-close-swarm"  "$out" "CLOSE-SWARM"
assert_contains "md-has-wave-1-impl"  "$out" "WAVE-1-IMPL"

# ---- assert: degradation detail block is emitted (deg_count > 0 path) ------
assert_contains "md-degrade-header"   "$out" "Degradation events"
assert_contains "md-degrade-segment"  "$out" "WAVE-1-IMPL"
assert_contains "md-degrade-cause"    "$out" "runtime_unavailable"
assert_contains "md-degrade-recovery" "$out" "1/1 recovered"

# ---- assert: clean segment shows no degradation event in table row ----------
# The CLOSE-SWARM row should have '0' in the degrade column and no cause.
assert_contains "md-clean-zero-deg" "$out" "| 0 |"

# ---- assert: JSON parity ----------------------------------------------------
out_json=$("$SHCTX" adapt report --compile-telemetry --json)

assert_contains "json-segment"          "$out_json" '"segment"'
assert_contains "json-degradation"      "$out_json" '"degradation_events"'
assert_contains "json-recovered"        "$out_json" '"recovered_events"'
assert_contains "json-cause"            "$out_json" '"runtime_unavailable"'
assert_contains "json-faithfulness"     "$out_json" '"faithfulness_pass_rate"'

# Degradation event count for WAVE-1-IMPL must be 1
assert_contains "json-deg-count-1"      "$out_json" '"degradation_events":1'
# Recovered count must be 1 (direct-dispatch fallback recovered)
assert_contains "json-rec-count-1"      "$out_json" '"recovered_events":1'

# ---- assert: graceful-empty on a sprint with no compile_runs rows -----------
# Switch to a different branch that has no seeded data.
git checkout -qb "dev.6.0.9-empty-sprint" 2>/dev/null \
  || git checkout -q "dev.6.0.9-empty-sprint" 2>/dev/null
empty_out=$("$SHCTX" adapt report --compile-telemetry --md)
assert_eq "graceful-empty" "$empty_out" ""

# ---- assert: graceful when migration is absent (table doesn't exist) --------
# Create a brand-new DB with only the baseline schema (no 0014 migration).
BARE_WD="$(mktemp -d -t compile-tel-bare.XXXXXX)"
trap 'rm -rf "$BARE_WD"' EXIT
export SHEPHERD_WORKDIR="${BARE_WD}/.shepherd"
mkdir -p "${BARE_WD}/.shepherd"
"$SHCTX" init --shepherd >/dev/null
# Do NOT run migrate — table is absent.
# current_sprint still points at the empty-sprint branch.
bare_out=$("$SHCTX" adapt report --compile-telemetry --md 2>&1 || true)
assert_eq "graceful-no-migration" "$bare_out" ""

echo "test_compile_telemetry.sh: ok"
