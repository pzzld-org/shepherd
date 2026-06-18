-- 0016_mailbox_kind_relax.sql — v6.1.8
--
-- Relax the mailbox.kind CHECK from a closed enum to non-empty-string.
--
-- WHY: 0007 pinned kind to ('heartbeat_payload','escalation','ack','status',
-- 'generic'). Every doctrine that later introduced a new routing tag therefore
-- failed CLOSED at the schema — silently. v6.1.7's staged-handoff
-- (doctrines/staged-handoff.md) sends `--kind=seed-ready`; the INSERT was
-- rejected with "CHECK constraint failed: kind IN (...)", so the feature had
-- NEVER worked end-to-end (caught by test_staged_handoff.sh). `kind` is a
-- free-form routing/filter tag (consumers do `select(.kind=="…")`) and
-- `recipient_name` is already free-form — the enum bought typo-catching at the
-- cost of silently breaking every new signal type. Relax it to the root-cause
-- fix: NOT NULL + non-empty, so new doctrines add a kind without a migration.
--
-- SQLite cannot ALTER a CHECK; rebuild the table (12-step), preserving columns,
-- data, the FK, both partial indexes, and the unread-per-recipient view.

PRAGMA foreign_keys=OFF;
BEGIN;

CREATE TABLE mailbox_new (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  sender_id       TEXT NOT NULL,
  recipient_name  TEXT NOT NULL,
  kind            TEXT NOT NULL CHECK(kind <> ''),
  payload         TEXT NOT NULL CHECK(json_valid(payload)),
  target_file     TEXT,
  requires_ack    INTEGER NOT NULL DEFAULT 0,
  sent_at         INTEGER NOT NULL,
  read_at         INTEGER,
  acked_at        INTEGER,
  expires_at      INTEGER
);

INSERT INTO mailbox_new
  (id, project_id, sender_id, recipient_name, kind, payload, target_file,
   requires_ack, sent_at, read_at, acked_at, expires_at)
  SELECT id, project_id, sender_id, recipient_name, kind, payload, target_file,
         requires_ack, sent_at, read_at, acked_at, expires_at
  FROM mailbox;

-- Drop the dependent view BEFORE the table: the subsequent RENAME makes SQLite
-- re-parse every view, and a view left dangling over the dropped table errors.
DROP VIEW IF EXISTS v_mailbox_unread_per_recipient;
DROP TABLE mailbox;
ALTER TABLE mailbox_new RENAME TO mailbox;

CREATE INDEX IF NOT EXISTS idx_mailbox_recipient_unread ON mailbox(recipient_name, read_at)
  WHERE read_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_mailbox_ack_pending      ON mailbox(requires_ack, acked_at)
  WHERE requires_ack = 1 AND acked_at IS NULL;

CREATE VIEW v_mailbox_unread_per_recipient AS
  SELECT recipient_name, COUNT(*) AS unread_count, MIN(sent_at) AS oldest_sent
  FROM mailbox
  WHERE read_at IS NULL
  GROUP BY recipient_name;

COMMIT;
PRAGMA foreign_keys=ON;
