-- 0017_focus_lane.sql — shepherd v6.2.3
--
-- Per-lane focus records: change the focus PK from (sprint) to (sprint, lane).
--
-- WHY: 0013 keyed focus by sprint alone — one row per sprint. But a teammate-
-- conductor runs a LANE across waves + compaction and needs its OWN durable,
-- compaction-surviving north-star (objective + invariants), distinct from the
-- sprint-level record. `agents/conductor.md` already issues
-- `shctx loop focus upsert --sprint=<s> --lane=<l>`, but neither the table nor
-- the cmd_loop.sh parser had a lane concept, so that call errored ("unknown arg")
-- and per-lane focus was unstorable. Add a `lane` column (default '' = the
-- sprint-level record, preserving every 0013 behavior) and key on (sprint, lane).
--
-- SQLite cannot ALTER a PRIMARY KEY; rebuild the table (preserving columns, data,
-- the JSON CHECKs, and the convenience view), mapping every existing row to
-- lane=''. Applied once by the version-gated migrate runner (schema_versions).
PRAGMA foreign_keys = OFF;

BEGIN;

CREATE TABLE focus_new (
  sprint      TEXT NOT NULL,
  lane        TEXT NOT NULL DEFAULT '',  -- '' = sprint-level record; else the lane id
  objective   TEXT,            -- north-star paragraph (written at SEED-VERIFY)
  active_node TEXT,            -- current Stage-Graph node id
  ready_set   TEXT,            -- comma-joined node ids (cursor snapshot)
  obligations TEXT CHECK(obligations IS NULL OR json_valid(obligations)),
                               -- JSON: open lanes, undrained mail, pending gates
  invariants  TEXT CHECK(invariants IS NULL OR json_valid(invariants)),
                               -- JSON: hold-true rules
  updated_at  INTEGER NOT NULL,
  PRIMARY KEY (sprint, lane)
);

-- Existing rows are sprint-level: map them to lane=''.
INSERT INTO focus_new (sprint,lane,objective,active_node,ready_set,obligations,invariants,updated_at)
  SELECT sprint, '', objective, active_node, ready_set, obligations, invariants, updated_at
  FROM focus;

DROP TABLE focus;
ALTER TABLE focus_new RENAME TO focus;

-- Convenience view: the sprint-level focus record for the current branch.
-- (lane='' is the sprint-level row; per-lane rows are read explicitly with --lane.)
DROP VIEW IF EXISTS v_focus_current;
CREATE VIEW v_focus_current AS
  SELECT * FROM focus WHERE lane = '' LIMIT 1;

COMMIT;

PRAGMA foreign_keys = ON;
