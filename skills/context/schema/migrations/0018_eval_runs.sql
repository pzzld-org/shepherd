-- skills/context/schema/migrations/0018_eval_runs.sql
-- shepherd v6.2.3 — eval harness store (the standing follow-up from v6.2.0).
--
-- One row per quality eval of a LATENT agent output (a conductor reflection, a
-- discovery report, a seed, …). Written by `shctx eval run --record`, which
-- builds a judge prompt from a rubric, routes it through the local-Claude-Code
-- LLM service (services/llm), parses the per-dimension scores, and computes a
-- deterministic overall score vs the rubric threshold. The latent/deterministic
-- split this very plugin teaches: the judge's per-dimension scores are latent;
-- the prompt build, the weighted overall, the threshold verdict, and this row
-- are deterministic.
--
-- Read by `shctx eval report`, the dash EVAL row, and (future) adapt trends.
-- Empty store ⇒ unchanged behavior everywhere (omit-if-empty surfaces).
-- See services/eval/README.md and docs/configuration.md §[eval].
--
-- Idempotent (IF NOT EXISTS / DROP VIEW IF EXISTS) so the gap-fill migrate
-- runner may safely (re)apply it. The schema_versions row is inserted by
-- cmd_migrate.sh after this script runs — do NOT self-insert it here.
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE IF NOT EXISTS eval_runs (
  id          TEXT PRIMARY KEY,                       -- uuid7
  project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  kind        TEXT NOT NULL,                          -- rubric kind (reflection|discovery|seed|…)
  subject_ref TEXT,                                   -- what was scored (sprint branch, mem id, path)
  score       INTEGER NOT NULL,                       -- overall 0..100 (weighted, deterministic)
  threshold   INTEGER NOT NULL,                       -- pass line in force at run time
  passed      INTEGER NOT NULL CHECK(passed IN (0,1)),
  model       TEXT,                                   -- judge model alias used
  scores_json TEXT CHECK(scores_json IS NULL OR json_valid(scores_json)),
                                                      -- per-dimension {dim: 1..scale}
  rationale   TEXT,                                   -- judge's one-line justification
  created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eval_runs_project
  ON eval_runs(project_id, kind, created_at DESC);

-- Latest eval per (project, kind, subject_ref) — the row the dash + report read.
-- created_at DESC, id DESC tiebreak keeps it deterministic when two runs share a
-- second (id is a time-prefixed uuid7, so the later run wins the tiebreak too).
DROP VIEW IF EXISTS v_eval_latest;
CREATE VIEW v_eval_latest AS
  SELECT e.*
  FROM eval_runs e
  WHERE e.id = (
    SELECT e2.id FROM eval_runs e2
    WHERE e2.project_id = e.project_id
      AND e2.kind = e.kind
      AND IFNULL(e2.subject_ref,'') = IFNULL(e.subject_ref,'')
    ORDER BY e2.created_at DESC, e2.id DESC
    LIMIT 1
  );

COMMIT;
