-- skills/context/schema/migrations/0010_sprint_metrics.sql
-- shepherd v6.0.4 — adaptation metrics priors (#94). One row per sprint close,
-- written by `shctx adapt roll` at CLOSE-FINALIZE; read by
-- `shctx adapt priors --metrics` (spawn Check 8 + engineer lane guidance).
-- Replaces the static avg_sprint_minutes=90 / avg_api=200 dispatch defaults
-- with measured per-project averages. Empty store ⇒ unchanged behavior.
-- See skills/shepherd/doctrines/adaptation-loop.md (SQLite-canonical).
--
-- Idempotent (IF NOT EXISTS / DROP VIEW IF EXISTS) so the gap-fill migrate
-- runner may safely (re)apply it. The schema_versions row is inserted by
-- cmd_migrate.sh after this script runs — do NOT self-insert it here.
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS sprint_metrics (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  sprint_branch TEXT NOT NULL,
  grade         TEXT,
  sprint_size   TEXT CHECK(sprint_size IS NULL OR sprint_size IN ('XS','S','M','L','XL')),
  lane_count    INTEGER,
  wave_count    INTEGER,
  loc_add       INTEGER,
  loc_del       INTEGER,
  wall_minutes  REAL,
  api_calls     INTEGER,
  findings_json TEXT CHECK(findings_json IS NULL OR json_valid(findings_json)),
  created_at    INTEGER NOT NULL,
  UNIQUE(project_id, sprint_branch)
);
CREATE INDEX IF NOT EXISTS idx_sprint_metrics_project
  ON sprint_metrics(project_id, created_at DESC);

DROP VIEW IF EXISTS v_sprint_metrics_avg;
CREATE VIEW v_sprint_metrics_avg AS
  SELECT project_id,
         COUNT(*)              AS n,
         AVG(wall_minutes)     AS avg_wall_minutes,
         AVG(api_calls)        AS avg_api_calls,
         AVG(lane_count)       AS avg_lane_count,
         AVG(loc_add + loc_del) AS avg_loc_delta
  FROM sprint_metrics GROUP BY project_id;

COMMIT;
