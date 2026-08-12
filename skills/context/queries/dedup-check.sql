-- usage: shctx query dedup-check --name=DriftCircuit
SELECT name, kind, package, file_path, line, signature
FROM index_symbols
WHERE project_id = :project_id AND name = :name;
