-- skills/context/schema/migrations/0009_locks_mode_sprint.sql
-- shepherd v6.0.3 (passover HIGH): `shctx sprint open` failed with SQLite rc=19
-- on every call because cmd_sprint.sh acquires the lock with --mode=sprint, but
-- the locks_history CHECK only permitted (autorun,parallel,start,plant,context).
-- SQLite cannot ALTER a CHECK in place, so recreate the table with 'sprint' and
-- 'spawn' added, preserving existing rows. schema_versions row is inserted by
-- cmd_migrate.sh after this runs.
PRAGMA foreign_keys = OFF;

BEGIN;

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

-- Rebind the view to the recreated table (resolves by name; recreate defensively).
DROP VIEW IF EXISTS v_active_locks;
CREATE VIEW v_active_locks AS
  SELECT * FROM locks_history WHERE released_at IS NULL ORDER BY acquired_at DESC;

COMMIT;

PRAGMA foreign_keys = ON;
