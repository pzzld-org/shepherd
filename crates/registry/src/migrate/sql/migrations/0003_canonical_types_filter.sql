-- 0003_canonical_types_filter.sql — v5.0.3
-- Field origin: shepherd v5.0.1 conductor feedback §2.2.
--
-- The v_canonical_types view in 0001_init.sql returned every public symbol
-- (consts, fns, modules, impls, traits, structs, enums, ...). Conductors
-- consuming `shctx query canonical-types --md` got 5,000+ rows per repo —
-- which is "the symbol index", not "the canonical-types catalog".
--
-- Fix: tighten v_canonical_types to the actual canonical-types semantic
-- (kind ∈ {struct, enum, trait} + visibility pub). Add a separate
-- v_canonical_symbols view for the broad query.
--
-- Also add the lane_closures table (v5.0.3 §2.7 — `shctx close-lane`).

BEGIN;

-- Recreate v_canonical_types with kind + visibility filters.
DROP VIEW IF EXISTS v_canonical_types;
CREATE VIEW v_canonical_types AS
  SELECT s.project_id, s.package, s.kind, s.name, s.signature, s.doc_summary,
         s.file_path, s.line, c.concept, c.aliases_to_avoid
  FROM index_symbols s
  LEFT JOIN index_concepts c ON c.canonical_symbol_id = s.id
  WHERE s.kind IN ('struct','enum','trait','class','interface','type-alias')
    AND s.visibility IN ('pub','pub(crate)','export')
  ORDER BY s.package, s.name;

-- New broad-query view: every public symbol (the previous v_canonical_types
-- semantic). Use this for "list every public thing in the workspace" — but
-- not for "what's the canonical home of ConceptX".
CREATE VIEW v_canonical_symbols AS
  SELECT s.project_id, s.package, s.kind, s.name, s.signature, s.doc_summary,
         s.file_path, s.line, c.concept, c.aliases_to_avoid
  FROM index_symbols s
  LEFT JOIN index_concepts c ON c.canonical_symbol_id = s.id
  WHERE s.visibility IN ('pub','pub(crate)','export')
  ORDER BY s.package, s.kind, s.name;

-- lane_closures — per-lane mid-sprint closure log. Conductor inserts a row
-- via `shctx close-lane <lane-id>` after each WAVE-GATE per lane. Auditor's
-- completeness concern reads this to verify carry-forward refresh discipline.
CREATE TABLE lane_closures (
  id              TEXT PRIMARY KEY,
  project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  sprint_branch   TEXT NOT NULL,
  lane_id         TEXT NOT NULL,
  closed_at       INTEGER NOT NULL,
  resolved_issues TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(resolved_issues)),
  acceptance_log  TEXT,                                 -- captured [ACCEPTANCE] block as markdown
  status          TEXT NOT NULL CHECK(status IN ('clean','partial','failed')),
  notes           TEXT,
  UNIQUE(project_id, sprint_branch, lane_id)
);
CREATE INDEX idx_lane_closures_project_sprint ON lane_closures(project_id, sprint_branch);

-- schema_versions row is inserted by cmd_migrate.sh after this script runs.
COMMIT;
