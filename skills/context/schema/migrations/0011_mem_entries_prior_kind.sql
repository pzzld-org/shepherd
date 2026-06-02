-- skills/context/schema/migrations/0011_mem_entries_prior_kind.sql
-- shepherd v6.0.4 (#95): self-improvement harvests HIGH/CRITICAL audit_findings
-- into mem_entries as kind='prior' lessons, fed forward at /shepherd:plant and
-- engineer Phase-0. The 0001 baseline CHECK only permitted
-- (doctrine,note,decision,incident,session), so every `kind='prior'` insert
-- failed. SQLite cannot ALTER a CHECK in place — recreate the table with
-- 'prior' added, preserving existing rows, both indexes, and the
-- v_mem_recent_7d view (cf. 0009_locks_mode_sprint.sql). The schema_versions
-- row is inserted by cmd_migrate.sh after this runs.
PRAGMA foreign_keys = OFF;

BEGIN;

-- Drop the dependent view BEFORE the table swap. On SQLite >= 3.25.0,
-- `ALTER TABLE ... RENAME` validates every view in the schema; if
-- `v_mem_recent_7d` still references `mem_entries` while we drop+rename it, the
-- RENAME aborts with "error in view v_mem_recent_7d: no such table:
-- main.mem_entries". Drop first, recreate after the rename. (shepherd v6.0.6
-- debug-session fix; same antipattern as the original 0009.)
DROP VIEW IF EXISTS v_mem_recent_7d;

CREATE TABLE mem_entries_new (
  id          TEXT PRIMARY KEY,
  project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  kind        TEXT NOT NULL CHECK(kind IN
                ('doctrine','note','decision','incident','session','prior')),
  title       TEXT NOT NULL,
  body        TEXT NOT NULL,
  tags        TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(tags)),
  pinned      INTEGER NOT NULL DEFAULT 0,
  source_path TEXT,
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL
);

INSERT INTO mem_entries_new
  SELECT id, project_id, kind, title, body, tags, pinned, source_path, created_at, updated_at
  FROM mem_entries;

DROP TABLE mem_entries;
ALTER TABLE mem_entries_new RENAME TO mem_entries;

-- Indexes die with the dropped table; recreate them on the renamed table.
CREATE INDEX idx_mem_project_kind   ON mem_entries(project_id, kind);
CREATE INDEX idx_mem_project_pinned ON mem_entries(project_id, pinned) WHERE pinned = 1;

-- Recreate the view on the renamed table (it was dropped at the top of the txn).
CREATE VIEW v_mem_recent_7d AS
  SELECT * FROM mem_entries
  WHERE created_at >= unixepoch() - 7 * 86400 OR pinned = 1
  ORDER BY pinned DESC, created_at DESC;

COMMIT;

PRAGMA foreign_keys = ON;
