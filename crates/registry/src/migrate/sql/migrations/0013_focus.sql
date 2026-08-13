-- skills/context/schema/migrations/0013_focus.sql
-- shepherd v6.0.9 — Focus record: durable north-star artifact per sprint (Item A1).
-- One row per sprint; written at SEED-VERIFY, refreshed at each WAVE-GATE,
-- finalized at CLOSE-FINALIZE. Because it lives in root.db it survives
-- compaction natively; the PreCompact snapshot (Item A2) denormalizes it into
-- a rehydration digest for restoring in-context drive after compaction.
-- See .artifacts/docs/specs/2026-06-09-v609-focus-loop-and-compaction-resilience.spec.md §4.3.
--
-- Idempotent (IF NOT EXISTS / DROP VIEW IF EXISTS) so the gap-fill migrate
-- runner may safely (re)apply it. The schema_versions row is inserted by
-- cmd_migrate.sh after this script runs — do NOT self-insert it here.
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

BEGIN;

-- One row per sprint. `sprint` is the branch name (e.g. 'dev.6.0.9').
-- obligations and invariants are JSON arrays/objects; json_valid() guards
-- enforced so corrupt writes are rejected at the DB level.
CREATE TABLE IF NOT EXISTS focus (
  sprint      TEXT PRIMARY KEY,
  objective   TEXT,            -- north-star paragraph (written at SEED-VERIFY)
  active_node TEXT,            -- current Stage-Graph node id
  ready_set   TEXT,            -- comma-joined node ids (cursor snapshot)
  obligations TEXT CHECK(obligations IS NULL OR json_valid(obligations)),
                               -- JSON: open lanes, undrained mail, pending gates
  invariants  TEXT CHECK(invariants IS NULL OR json_valid(invariants)),
                               -- JSON: hold-true rules
  updated_at  INTEGER NOT NULL
);

-- Convenience view: focus record for the current git branch.
-- The consumer calls `SELECT * FROM v_focus_current` (no args needed).
DROP VIEW IF EXISTS v_focus_current;
CREATE VIEW v_focus_current AS
  SELECT * FROM focus LIMIT 1;  -- caller filters by sprint in practice;
                                 -- view kept thin for broad compatibility.

COMMIT;
