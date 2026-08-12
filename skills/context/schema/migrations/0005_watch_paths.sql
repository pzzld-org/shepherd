-- 0005_watch_paths.sql — v5.1.1
-- Field origin: 2026-05-16 operator request — "watcher that allows us to create
-- some hash of specific directories so an agent or session can have actual
-- expectations about specific contents without having to re-read every time."
--
-- A watch_paths table tracks directory/file content hashes so consumers can
-- ask "has this path changed since last marked?" — avoiding redundant reads.
--
-- Hash sources:
--   git — `git rev-parse HEAD:<path>` returns tree object hash. Cheap.
--   fs  — `find ... -type f -exec sha256sum {} + | sort | sha256sum` for
--         untracked content (.shepherd/runs/, .shepherd/discoveries/, etc.)
--
-- Consumer pattern:
--   1. Agent reads a watched path → marks it with `shctx watch mark <path>`
--   2. Next session checks `shctx watch status <path>` — unchanged → skip re-read
--   3. If changed → re-ingest and re-mark
--
-- The table is project-scoped (via projects.id FK) but for v5.1.1 we keep it
-- simple: one row per path, single-project assumption. Multi-project schemas
-- can extend with a project_id FK in v5.2.x if needed.

BEGIN;

CREATE TABLE IF NOT EXISTS watch_paths (
  path             TEXT PRIMARY KEY,        -- relative to repo root (e.g., ".shepherd/ctx" or "skills/shepherd/doctrines")
  label            TEXT,                    -- optional human-readable name
  source           TEXT NOT NULL,           -- 'git' (tracked) | 'fs' (untracked)
  current_hash     TEXT,                    -- recomputed by `shctx watch status`; NULL until first computation
  last_marked_hash TEXT,                    -- the hash a consumer last marked as "seen"; NULL until first mark
  last_marked_at   INTEGER,                 -- unix ts of last mark
  last_marked_by   TEXT,                    -- optional agent/role that marked (provenance)
  created_at       INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
  updated_at       INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),

  CHECK (source IN ('git', 'fs'))
);

CREATE INDEX IF NOT EXISTS idx_watch_paths_label ON watch_paths(label) WHERE label IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_watch_paths_source ON watch_paths(source);

-- Trigger: keep updated_at fresh
CREATE TRIGGER IF NOT EXISTS trg_watch_paths_updated_at
AFTER UPDATE ON watch_paths
FOR EACH ROW
BEGIN
  UPDATE watch_paths SET updated_at = strftime('%s', 'now') WHERE path = OLD.path;
END;

COMMIT;
