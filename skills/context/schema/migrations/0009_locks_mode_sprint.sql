-- skills/context/schema/migrations/0009_locks_mode_sprint.sql
-- shepherd v6.0.3 (passover HIGH): `shctx sprint open` failed with SQLite rc=19
-- on every call because cmd_sprint.sh acquires the lock with --mode=sprint, but
-- the locks_history CHECK only permitted (autorun,parallel,start,plant,context).
-- SQLite cannot ALTER a CHECK in place, so recreate the table with 'sprint' and
-- 'spawn' added, preserving existing rows. schema_versions row is inserted by
-- cmd_migrate.sh after this runs.
PRAGMA foreign_keys = OFF;

BEGIN;

-- Drop the dependent view BEFORE the table swap. On SQLite >= 3.25.0,
-- `ALTER TABLE ... RENAME` validates every view/trigger in the schema; if
-- `v_active_locks` still references `locks_history` while we drop+rename it, the
-- RENAME aborts with "error in view v_active_locks: no such table:
-- main.locks_history" and the whole migration chain halts (0010/0011 never
-- apply, `shctx sprint open` breaks on SQLite >= 3.25). Drop first, recreate
-- after the rename. (shepherd v6.0.6 debug-session fix; 0011 had the same bug.)
DROP VIEW IF EXISTS v_active_locks;

CREATE TABLE locks_history_new (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  session_id   TEXT NOT NULL,
  mode         TEXT NOT NULL CHECK(mode IN
                 ('autorun','parallel','start','plant','context','sprint','spawn')),
  acquired_at  INTEGER NOT NULL,
  released_at  INTEGER,
  released_by  TEXT CHECK(released_by IS NULL OR released_by IN ('normal','reap','force')),
  metadata     TEXT CHECK(metadata IS NULL OR json_valid(metadata))
);

INSERT INTO locks_history_new
  SELECT id, project_id, session_id, mode, acquired_at, released_at, released_by, metadata
  FROM locks_history;

DROP TABLE locks_history;
ALTER TABLE locks_history_new RENAME TO locks_history;

-- Recreate the view on the renamed table (it was dropped at the top of the txn).
CREATE VIEW v_active_locks AS
  SELECT * FROM locks_history WHERE released_at IS NULL ORDER BY acquired_at DESC;

COMMIT;

PRAGMA foreign_keys = ON;
