-- skills/context/schema/migrations/0012_loop_state.sql
-- shepherd v6.0.9 — Loop-Until-Done persistent state (Discovery 1 / Item A0).
-- Backs `shctx loop init|status|record|close|list` called by `/shepherd:loop`
-- and the new FOCUS-LOOP runtime. Loop state is canonical: it survives
-- compaction natively (only the conversation window is truncated — the DB
-- is untouched), which is why SQLite backing is non-optional for focus loops.
-- See .artifacts/docs/specs/2026-06-09-v609-focus-loop-and-compaction-resilience.spec.md §4.2.
--
-- Idempotent (IF NOT EXISTS / DROP VIEW IF EXISTS) so the gap-fill migrate
-- runner may safely (re)apply it. The schema_versions row is inserted by
-- cmd_migrate.sh after this script runs — do NOT self-insert it here.
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

BEGIN;

-- One row per loop lifecycle (init → records → close).
-- id format: 'loop-YYYYMMDD-NNN' (zero-padded sequence per day).
CREATE TABLE IF NOT EXISTS loops (
  id              TEXT PRIMARY KEY,
  project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  kind            TEXT CHECK(kind IS NULL OR kind IN ('focus','convergence','watch','generic')),
  task            TEXT,
  agent           TEXT,        -- 'worker' | 'discovery' | 'orchestrator'
  max_iterations  INTEGER NOT NULL CHECK(max_iterations > 0),
  until_field     TEXT    NOT NULL DEFAULT 'new_findings',
  interval        TEXT,        -- e.g. '5m', '1h'; NULL = in-session drive
  status          TEXT    NOT NULL DEFAULT 'active'
                    CHECK(status IN ('active','converged','cap-reached','aborted')),
  created_at      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_loops_project_status
  ON loops(project_id, status, created_at DESC);

-- One row per iteration recorded within a loop.
CREATE TABLE IF NOT EXISTS loop_iterations (
  loop_id      TEXT    NOT NULL REFERENCES loops(id) ON DELETE CASCADE,
  iteration    INTEGER NOT NULL CHECK(iteration > 0),
  new_findings INTEGER CHECK(new_findings IS NULL OR new_findings IN (0, 1)),
  summary      TEXT,
  recorded_at  INTEGER NOT NULL,
  UNIQUE(loop_id, iteration)
);
CREATE INDEX IF NOT EXISTS idx_loop_iterations_loop
  ON loop_iterations(loop_id, iteration);

-- Hot-query view: active loops with iteration counts + latest summary.
DROP VIEW IF EXISTS v_loops_active;
CREATE VIEW v_loops_active AS
  SELECT
    l.id,
    l.project_id,
    l.kind,
    l.task,
    l.agent,
    l.max_iterations,
    l.until_field,
    l.interval,
    l.status,
    l.created_at,
    COUNT(li.iteration)        AS iterations_recorded,
    MAX(li.iteration)          AS latest_iteration,
    SUM(li.new_findings)       AS total_findings,
    MAX(li.recorded_at)        AS last_recorded_at
  FROM loops l
  LEFT JOIN loop_iterations li ON li.loop_id = l.id
  WHERE l.status = 'active'
  GROUP BY l.id;

COMMIT;
