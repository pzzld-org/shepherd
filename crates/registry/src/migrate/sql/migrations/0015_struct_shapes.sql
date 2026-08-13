-- 0015_struct_shapes.sql — v6.1.8 (#157)
-- Field-shape fingerprint corpus for `shctx dups`.
--
-- Name-matching (index_symbols + dedup-check.sql + dedup_write_guard.sh) catches
-- a duplicate ONLY when the second definition reuses the first one's name. It is
-- useless against the rename-to-evade-dedup shadow: a second type for an existing
-- concept under a DIFFERENT name. Those compile green, so no clippy/test gate
-- catches them — the duplicate just accumulates and drifts.
--
-- index_struct_shapes stores the FIELD SHAPE of every public struct/enum so
-- `shctx dups` can cluster same-shape/different-name types (weighted Jaccard over
-- (field_name, normalized_type) pairs). This is the third leg of the mechanical
-- shape-gate set, alongside dep-hygiene (cross-tier edges) and check-impls-defs
-- (defs-in-impls). Populated by `shctx dups scan --update` (and `shctx refresh
-- --scope=shapes`); read by `shctx dups check` for the PreToolUse authoring gate.
--
-- IF NOT EXISTS so the dups engine can self-heal the table on a DB that predates
-- this migration (same pattern as 0007_canonical_state.sql operational tables);
-- the migration remains the canonical schema source of truth.

CREATE TABLE IF NOT EXISTS index_struct_shapes (
  id           TEXT PRIMARY KEY,
  project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  name         TEXT NOT NULL,
  kind         TEXT NOT NULL,                                   -- struct | enum
  package      TEXT NOT NULL,
  file_path    TEXT NOT NULL,
  line         INTEGER,
  visibility   TEXT,
  language     TEXT NOT NULL DEFAULT 'rust',
  fields       TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(fields)),       -- [{"n":name,"t":normalized_type}, ...]
  field_names  TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(field_names)),  -- sorted unique field names
  field_count  INTEGER NOT NULL DEFAULT 0,
  shape_hash   TEXT NOT NULL,                                   -- sha256 of sorted "n:t" pairs (exact-shape key)
  doc_summary  TEXT,
  refreshed_at INTEGER NOT NULL,
  UNIQUE(project_id, name, package, kind)
);
CREATE INDEX IF NOT EXISTS idx_struct_shapes_project       ON index_struct_shapes(project_id);
CREATE INDEX IF NOT EXISTS idx_struct_shapes_project_hash  ON index_struct_shapes(project_id, shape_hash);
