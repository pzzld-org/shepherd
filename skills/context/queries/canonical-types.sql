-- usage: shctx query canonical-types
SELECT package, kind, name, signature, file_path, line, concept,
       json(aliases_to_avoid) AS aliases
FROM v_canonical_types
WHERE project_id = :project_id
ORDER BY package, name;
