-- 0004_fts_search.sql — v5.0.3
-- Field origin: shepherd v5.0.1 conductor feedback §3 ("sqlite vs vectorized").
--
-- SQLite's built-in FTS5 covers ~80% of the value of vector embeddings at 0%
-- of the embedding-model cost. Two virtual tables: one over symbols
-- (name + signature + doc_summary), one over artifacts (path + title +
-- content). Triggers keep them synced to source tables.
--
-- A separate v5.x story may add embeddings on top of FTS5 if natural-language
-- queries need it; FTS5 ships first because it solves the typical conductor
-- query ("which crate has the BookSnapshot type?") well enough.
--
-- NB: artifacts.content is a NEW column added here so FTS has substrate.
-- refresh-artifacts.sh will populate it in v5.0.3+; pre-existing artifact
-- rows stay NULL until next refresh, which is correct (no false matches).

BEGIN;

-- Add content column to artifacts for FTS substrate.
ALTER TABLE artifacts ADD COLUMN content TEXT;

-- FTS5 over public symbols.
CREATE VIRTUAL TABLE index_fts_symbols USING fts5(
  name,
  signature,
  doc_summary,
  content='index_symbols',
  content_rowid='rowid',
  tokenize='unicode61 remove_diacritics 2'
);

-- FTS5 over artifact content.
CREATE VIRTUAL TABLE index_fts_artifacts USING fts5(
  path,
  title,
  content,
  content='artifacts',
  content_rowid='rowid',
  tokenize='unicode61 remove_diacritics 2'
);

-- Sync triggers — symbols.
CREATE TRIGGER index_symbols_ai AFTER INSERT ON index_symbols BEGIN
  INSERT INTO index_fts_symbols(rowid, name, signature, doc_summary)
  VALUES (new.rowid, new.name, COALESCE(new.signature, ''), COALESCE(new.doc_summary, ''));
END;

CREATE TRIGGER index_symbols_ad AFTER DELETE ON index_symbols BEGIN
  INSERT INTO index_fts_symbols(index_fts_symbols, rowid, name, signature, doc_summary)
  VALUES ('delete', old.rowid, old.name, COALESCE(old.signature, ''), COALESCE(old.doc_summary, ''));
END;

CREATE TRIGGER index_symbols_au AFTER UPDATE ON index_symbols BEGIN
  INSERT INTO index_fts_symbols(index_fts_symbols, rowid, name, signature, doc_summary)
  VALUES ('delete', old.rowid, old.name, COALESCE(old.signature, ''), COALESCE(old.doc_summary, ''));
  INSERT INTO index_fts_symbols(rowid, name, signature, doc_summary)
  VALUES (new.rowid, new.name, COALESCE(new.signature, ''), COALESCE(new.doc_summary, ''));
END;

-- Sync triggers — artifacts.
CREATE TRIGGER artifacts_ai AFTER INSERT ON artifacts BEGIN
  INSERT INTO index_fts_artifacts(rowid, path, title, content)
  VALUES (new.rowid, new.path, COALESCE(new.title, ''), COALESCE(new.content, ''));
END;

CREATE TRIGGER artifacts_ad AFTER DELETE ON artifacts BEGIN
  INSERT INTO index_fts_artifacts(index_fts_artifacts, rowid, path, title, content)
  VALUES ('delete', old.rowid, old.path, COALESCE(old.title, ''), COALESCE(old.content, ''));
END;

CREATE TRIGGER artifacts_au AFTER UPDATE ON artifacts BEGIN
  INSERT INTO index_fts_artifacts(index_fts_artifacts, rowid, path, title, content)
  VALUES ('delete', old.rowid, old.path, COALESCE(old.title, ''), COALESCE(old.content, ''));
  INSERT INTO index_fts_artifacts(rowid, path, title, content)
  VALUES (new.rowid, new.path, COALESCE(new.title, ''), COALESCE(new.content, ''));
END;

-- Backfill FTS from existing rows (covers projects upgrading from 0001/0002).
INSERT INTO index_fts_symbols(rowid, name, signature, doc_summary)
SELECT rowid, name, COALESCE(signature, ''), COALESCE(doc_summary, '')
FROM index_symbols;

INSERT INTO index_fts_artifacts(rowid, path, title, content)
SELECT rowid, path, COALESCE(title, ''), COALESCE(content, '')
FROM artifacts;

-- schema_versions row is inserted by cmd_migrate.sh after this script runs.
COMMIT;
