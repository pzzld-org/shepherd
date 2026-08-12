-- skills/context/schema/migrations/0014_compile_runs.sql
-- shepherd v6.0.9 — Compile-down telemetry (Item C, GH #87). Per compiled
-- segment per run: segment size, peak concurrency vs the global ceiling, the
-- §IV faithfulness-diff result (soundness/completeness/determinism + ok flag),
-- seam-handoff outcome (export present/consumed), and every degradation-to-
-- direct-dispatch event with cause.
--
-- Source data is written by the conductor at CLOSE-FINALIZE; the aggregator
-- `shctx adapt report --compile-telemetry` (backed by v_compile_runs_sprint)
-- emits the "## Compile-down telemetry" close-report subsection — mirroring
-- the "## Cache telemetry" precedent over v_cache_usage (migration 0006).
--
-- The UNIQUE(project_id, run_id, segment) constraint makes inserts idempotent:
-- replaying the same row is a no-op via INSERT OR IGNORE.
--
-- The companion view v_compile_runs_sprint rolls up per segment across a sprint,
-- keeping the aggregator query simple. Rows with parse_error IS NOT NULL surface
-- in the raw table (visible via direct `shctx query`) but are excluded from the
-- rollup — the same "honest measurements only" pattern from v_cache_usage.
--
-- Idempotent (IF NOT EXISTS / DROP VIEW IF EXISTS) so the gap-fill migrate
-- runner may safely (re)apply it. The schema_versions row is inserted by
-- cmd_migrate.sh after this script runs — do NOT self-insert it here.
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS compile_runs (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id          TEXT    NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  run_id              TEXT    NOT NULL,             -- conductor-assigned run identifier (e.g. sprint + epoch)
  sprint              TEXT,                         -- git branch at compile time
  segment             TEXT    NOT NULL,             -- segment label (e.g. 'CLOSE-SWARM', 'WAVE-1-IMPL')
  segment_node_count  INTEGER,                      -- size of the compiled segment (node count)
  total_agents        INTEGER,                      -- total agent spawns in this segment
  peak_concurrency    INTEGER,                      -- actual peak concurrent agents observed at runtime
  concurrency_ceiling INTEGER NOT NULL DEFAULT 16,  -- MAX_CONCURRENT at compile time (doctrine §III)

  -- §IV faithfulness-diff result (from `shctx graph compile --verify`)
  faithfulness_soundness    TEXT CHECK(faithfulness_soundness    IS NULL OR faithfulness_soundness    IN ('PASS','FAIL')),
  faithfulness_completeness TEXT CHECK(faithfulness_completeness IS NULL OR faithfulness_completeness IN ('PASS','FAIL')),
  faithfulness_determinism  TEXT CHECK(faithfulness_determinism  IS NULL OR faithfulness_determinism  IN ('PASS','FAIL')),
  faithfulness_ok           INTEGER CHECK(faithfulness_ok IS NULL OR faithfulness_ok IN (0,1)),
                                                    -- 1 = all three PASS; 0 = any FAIL; NULL = not verified

  -- Seam-handoff outcome (WAVE-GATE export present / consumed at the conductor)
  seam_export_present   INTEGER CHECK(seam_export_present  IS NULL OR seam_export_present  IN (0,1)),
  seam_export_consumed  INTEGER CHECK(seam_export_consumed IS NULL OR seam_export_consumed IN (0,1)),

  -- Degradation-to-direct-dispatch event (NULL = no degradation; filled on fallback)
  degraded             INTEGER NOT NULL DEFAULT 0 CHECK(degraded IN (0,1)),
                                                    -- 1 = runtime failed / unavailable; fell back to in-context
  degradation_cause    TEXT,                        -- free-text cause (e.g. 'runtime_unavailable', 'faithfulness_fail')
  recovered            INTEGER CHECK(recovered IS NULL OR recovered IN (0,1)),
                                                    -- 1 = direct-dispatch fallback completed successfully

  script_sha256        TEXT,                        -- sha256 of the compiled workflow script
  compiled_at          INTEGER,                     -- unix epoch when compile() was called
  run_started_at       INTEGER,                     -- unix epoch when the segment runtime began
  run_finished_at      INTEGER,                     -- unix epoch when the segment runtime returned
  parse_error          TEXT,                        -- nullable; set when the conductor could not record cleanly

  UNIQUE(project_id, run_id, segment)
);

CREATE INDEX IF NOT EXISTS idx_compile_runs_sprint
  ON compile_runs(project_id, sprint, compiled_at DESC);
CREATE INDEX IF NOT EXISTS idx_compile_runs_segment
  ON compile_runs(project_id, segment, compiled_at DESC);

-- Per-segment rollup over a sprint, consumed by the "## Compile-down telemetry"
-- close-report subsection. Excludes parse_error rows (honest measurements only,
-- mirroring the v_cache_usage precedent from migration 0006).
-- For each segment: run count, aggregate faithfulness pass rates, seam-handoff
-- rate, degradation count, recovery rate, and average concurrency utilisation.
DROP VIEW IF EXISTS v_compile_runs_sprint;
CREATE VIEW v_compile_runs_sprint AS
  SELECT
    project_id,
    sprint,
    segment,
    COUNT(*)                                                             AS runs,
    MAX(segment_node_count)                                              AS node_count,
    MAX(total_agents)                                                    AS max_agents,
    AVG(peak_concurrency)                                                AS avg_peak_concurrency,
    MAX(concurrency_ceiling)                                             AS concurrency_ceiling,
    -- faithfulness pass rates (1.0 = all runs passed, 0.0 = none passed, NULL = not verified)
    AVG(CASE WHEN faithfulness_ok IS NOT NULL THEN faithfulness_ok ELSE NULL END) AS faithfulness_pass_rate,
    SUM(CASE WHEN faithfulness_soundness    = 'FAIL' THEN 1 ELSE 0 END) AS soundness_failures,
    SUM(CASE WHEN faithfulness_completeness = 'FAIL' THEN 1 ELSE 0 END) AS completeness_failures,
    SUM(CASE WHEN faithfulness_determinism  = 'FAIL' THEN 1 ELSE 0 END) AS determinism_failures,
    -- seam handoff
    SUM(CASE WHEN seam_export_present  = 1 THEN 1 ELSE 0 END)           AS seam_exports_present,
    SUM(CASE WHEN seam_export_consumed = 1 THEN 1 ELSE 0 END)           AS seam_exports_consumed,
    -- degradation
    SUM(degraded)                                                        AS degradation_events,
    SUM(CASE WHEN degraded = 1 AND recovered = 1 THEN 1 ELSE 0 END)     AS recovered_events,
    -- group_concat of distinct degradation causes (NULL = none)
    NULLIF(GROUP_CONCAT(DISTINCT CASE WHEN degraded = 1 THEN degradation_cause ELSE NULL END), '') AS degradation_causes
  FROM compile_runs
  WHERE parse_error IS NULL
  GROUP BY project_id, sprint, segment;

COMMIT;
