-- reference copy only; not applied (canonical definition lives in
-- skills/context/schema/migrations/0003_canonical_types_filter.sql).
CREATE VIEW IF NOT EXISTS v_canonical_types AS
  SELECT s.project_id, s.package, s.kind, s.name, s.signature, s.doc_summary,
         s.file_path, s.line, c.concept, c.aliases_to_avoid
  FROM index_symbols s
  LEFT JOIN index_concepts c ON c.canonical_symbol_id = s.id
  WHERE s.kind IN ('struct','enum','trait','class','interface','type-alias')
    AND s.visibility IN ('pub','pub(crate)','export')
  ORDER BY s.package, s.name;
