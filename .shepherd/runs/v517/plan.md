# v5.1.7 — SQLite-canonical operational state — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:dispatching-parallel-agents` to fan this plan out across waves. Each Task is a single agent dispatch. Wave-1 tasks fire in parallel (file-disjoint). Wave-2 tasks fire in parallel after Wave-1 completes. Wave-3 fires after Wave-2.

**Goal:** Make `.artifacts/root.db` the canonical store for ephemeral operational state (teammate liveness, heartbeats, mailbox, escalations, deliverables, structured findings) and reduce markdown-file production to operator-authored durable artifacts only. Resolve the v5.1.5/v5.1.6 defect cluster (#43, #44, #49, #50, #51, #52) via the same canonicalization shift.

**Architecture:** Additive schema migration 0007 introduces 7 new tables + 3 views under existing WAL-mode SQLite. New `shctx` subcommands wrap CRUD on those tables. Agent profile amendments switch ephemeral-state writes from markdown to `shctx <X> insert`. New `/shepherd:cleanup` slash command + `deliverable_check.sh` hook close the operator workflow loop.

**Tech Stack:** SQLite 3 (WAL mode, foreign keys on), bash 4+, jq, sqlite3 CLI, gh CLI, existing `skills/context/scripts/shctx` dispatcher.

**Spec:** `.artifacts/docs/specs/2026-05-20-v517-canonical-state-design.md`

**Dispatch shape:** Via `superpowers:dispatching-parallel-agents` (Agent tool subagents). No `/shepherd:*` invocations — we are building shepherd, not running it.

---

## File Structure

**Created (new files):**
- `skills/context/schema/0007_canonical_state.sql`
- `skills/context/schema/migrations/0007.md`
- `skills/shepherd/doctrines/sqlite-canonical-state.md`
- `skills/context/scripts/cmd_teammate.sh`
- `skills/context/scripts/cmd_mailbox.sh`
- `skills/context/scripts/cmd_escalate.sh`
- `skills/context/scripts/cmd_deliverable.sh`
- `skills/context/scripts/cmd_report.sh`
- `skills/context/scripts/cmd_discovery.sh` (or extend if exists)
- `skills/context/scripts/cmd_audit.sh` (or extend if exists)
- `skills/context/scripts/hooks/teammate_idle.sh`
- `skills/context/scripts/hooks/deliverable_check.sh`
- `skills/context/tests/test_cmd_teammate.sh`
- `skills/context/tests/test_cmd_mailbox.sh`
- `skills/context/tests/test_cmd_escalate.sh`
- `skills/context/tests/test_cmd_deliverable.sh`
- `skills/context/tests/test_cmd_report.sh`
- `skills/context/tests/test_schema_0007.sh`
- `commands/cleanup.md`
- `.artifacts/docs/handoffs/2026-05-20-old-issue-triage.md`

**Modified (existing files):**
- `skills/context/scripts/shctx` (dispatcher — register new commands)
- `skills/context/scripts/hooks/subagent_telemetry.sh` (extend with heartbeat emission)
- `agents/discovery.md` (Hard Prohibition + insert contract)
- `agents/critic.md` (deliverable promise/complete contract)
- `agents/auditor.md` (deliverable contract + intro-mode extras gate)
- `agents/conductor.md` (cargo discipline section)
- `agents/shepherd.md` (TEAMMATE-CRASHED halt code)
- `commands/spawn.md` (cargo discipline brief block)
- `.claude-plugin/plugin.json` (cleanup command entry; version stays 5.1.7)
- `.claude-plugin/marketplace.json` (version + cleanup command)
- `.claude-plugin/hooks.json` (new hook entries)
- `skills/shepherd/SKILL.md` (cleanup command + version)
- `skills/context/SKILL.md` (version)
- `README.md` (version banner if present)
- `CHANGELOG.md` (v5.1.7 section)

---

## Wave 1 — Foundation (6 parallel lanes)

All file-disjoint. Worker lanes (W1, W2) are IO-bound; A-lanes are file-write.

---

### Task A1: Schema migration 0007

**Lane brief context:** This adds 7 new tables (teammates, heartbeats, mailbox, escalations, deliverables, discovery_findings, audit_findings) and 3 views to the project SQLite registry. All additive — no ALTER on existing tables.

**Files:**
- Create: `skills/context/schema/0007_canonical_state.sql`
- Create: `skills/context/schema/migrations/0007.md`
- Create: `skills/context/tests/test_schema_0007.sh`

**[FILE-SCOPE]** Only the 3 paths above. Do NOT touch `0001_init.sql`, existing migrations, or any `.sh` outside the test file.

- [ ] **Step A1.1: Verify migration sequence**

Run: `ls skills/context/schema/migrations/ | sort | tail -5`
Expected: confirm latest existing migration number (`0006` per v5.1.3 cache-telemetry); new file is `0007`.

- [ ] **Step A1.2: Write the test first**

Create `skills/context/tests/test_schema_0007.sh`:

```bash
#!/usr/bin/env bash
# Test: 0007 migration applies clean and creates all 7 tables + 3 views.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"

TMPDB="$(mktemp -t shepherd-test-0007.XXXXXX.db)"
trap "rm -f $TMPDB ${TMPDB}-wal ${TMPDB}-shm" EXIT

# Bootstrap with all prior migrations (mirror cmd_init.sh ordering)
for f in "$ROOT/skills/context/schema/0001_init.sql" \
         "$ROOT/skills/context/schema/migrations/"*.sql; do
  sqlite3 "$TMPDB" < "$f"
done

# Apply 0007
sqlite3 "$TMPDB" < "$ROOT/skills/context/schema/0007_canonical_state.sql"

# Assert tables present
for t in teammates heartbeats mailbox escalations deliverables \
         discovery_findings audit_findings; do
  count=$(sqlite3 "$TMPDB" "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='$t';")
  [[ "$count" == "1" ]] || { echo "FAIL: table $t missing"; exit 1; }
done

# Assert views present
for v in v_teammates_live v_mailbox_unread_per_recipient v_escalations_open; do
  count=$(sqlite3 "$TMPDB" "SELECT count(*) FROM sqlite_master WHERE type='view' AND name='$v';")
  [[ "$count" == "1" ]] || { echo "FAIL: view $v missing"; exit 1; }
done

# Assert schema_versions row
ver=$(sqlite3 "$TMPDB" "SELECT version FROM schema_versions ORDER BY version DESC LIMIT 1;")
[[ "$ver" == "7" ]] || { echo "FAIL: schema_versions max != 7 (got: $ver)"; exit 1; }

# Assert WAL still on
mode=$(sqlite3 "$TMPDB" "PRAGMA journal_mode;")
[[ "$mode" == "wal" ]] || { echo "FAIL: journal_mode not wal (got: $mode)"; exit 1; }

# Assert json_valid CHECK on metadata enforced
if sqlite3 "$TMPDB" "INSERT INTO teammates (id, project_id, team_name, teammate_name, agent_type, spawned_at, last_seen_at, status, metadata) VALUES ('t1','p1','team','name','type',1,1,'active','not-json');" 2>/dev/null; then
  echo "FAIL: bad JSON in teammates.metadata was accepted"; exit 1
fi

echo "PASS: test_schema_0007"
```

Make executable: `chmod +x skills/context/tests/test_schema_0007.sh`

- [ ] **Step A1.3: Run test to verify it fails**

Run: `bash skills/context/tests/test_schema_0007.sh`
Expected: FAIL — file `0007_canonical_state.sql` does not exist yet.

- [ ] **Step A1.4: Write the migration SQL**

Create `skills/context/schema/0007_canonical_state.sql` with the full schema verbatim from the spec (Section 2). Compute and embed the actual SHA-256 of the file contents in the `schema_versions` INSERT:

After writing the file with `<sha256>` placeholder, compute:
```bash
SHA=$(shasum -a 256 skills/context/schema/0007_canonical_state.sql | awk '{print $1}')
# Then edit the INSERT line to replace <sha256> with the real value.
```

Use bash sed if shasum exists, else openssl:
```bash
sed -i.bak "s/<sha256>/$SHA/" skills/context/schema/0007_canonical_state.sql && rm skills/context/schema/0007_canonical_state.sql.bak
```

Full file contents — copy the SQL block verbatim from `.artifacts/docs/specs/2026-05-20-v517-canonical-state-design.md` Component §1. Wrap in:

```sql
-- skills/context/schema/0007_canonical_state.sql
-- shepherd v5.1.7 — SQLite-canonical operational state.
-- Adds teammates, heartbeats, mailbox, escalations, deliverables,
-- discovery_findings, audit_findings + 3 hot-query views.
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

<SCHEMA-BODY-FROM-SPEC>
```

- [ ] **Step A1.5: Run test to verify it passes**

Run: `bash skills/context/tests/test_schema_0007.sh`
Expected: `PASS: test_schema_0007`

- [ ] **Step A1.6: Write migration notes**

Create `skills/context/schema/migrations/0007.md`:

```markdown
# Migration 0007 — Canonical operational state

Adds 7 tables + 3 views supporting v5.1.7's SQLite-canonical operational
state shift. Replaces ephemeral-state markdown files (teammate liveness,
heartbeats, mailbox payloads, escalations, deliverable promises, structured
discovery/audit findings) with queryable rows.

## Tables added

| Table | Purpose | Indexed for |
|---|---|---|
| teammates | identity + liveness + status | project+status, last_seen_at |
| heartbeats | per-tool-call ticks | (teammate_id, ts DESC) |
| mailbox | cross-agent messages | (recipient_name) WHERE unread |
| escalations | teammate→root surface | (project_id, resolved_at) WHERE open |
| deliverables | promise/complete ledger | (project_id, status) WHERE pending |
| discovery_findings | structured discovery output | (project, sprint_branch, run) |
| audit_findings | structured audit output | (project, sprint_branch, severity) |

## Views added

- `v_teammates_live` — non-crashed/retired with ms_since_seen
- `v_mailbox_unread_per_recipient` — count + oldest per recipient
- `v_escalations_open` — open escalations joined with teammate info

## Back-compat

- All existing tables, views, indexes unchanged
- All existing `shctx` subcommands continue to work unchanged
- `mem_entries`, `logs_events`, `artifacts`, `locks_history`,
  `index_{symbols,concepts,issues,prs,releases,milestones}` untouched

## Rollback

`DROP VIEW v_escalations_open; DROP VIEW v_mailbox_unread_per_recipient;
DROP VIEW v_teammates_live;` then `DROP TABLE` each new table in reverse
dependency order. Then `DELETE FROM schema_versions WHERE version = 7;`

## Field origin

v5.1.5/v5.1.6 spawn defect cluster (#43 inline-only reports, #49 silent
crashes, #52 stall-loop, #53 file-based heartbeat proposal). Operator
diagnosis 2026-05-20: "why do we continue producing so many artifacts
when we have a sqlite instance specifically to help eliminate the need".
```

- [ ] **Step A1.7: Commit**

```bash
git add skills/context/schema/0007_canonical_state.sql \
        skills/context/schema/migrations/0007.md \
        skills/context/tests/test_schema_0007.sh
git commit -m "feat(v5.1.7/A1): schema migration 0007 — canonical operational state

Adds teammates, heartbeats, mailbox, escalations, deliverables,
discovery_findings, audit_findings tables + 3 hot-query views.
WAL mode preserved. All additive — no ALTER on existing tables.

Test: bash skills/context/tests/test_schema_0007.sh"
```

---

### Task A2: Doctrine — sqlite-canonical-state

**Files:**
- Create: `skills/shepherd/doctrines/sqlite-canonical-state.md`

**[FILE-SCOPE]** Only the doctrine file. Do NOT amend agents (B-lane work) or `doctrines/README.md` index (handled at sprint close).

- [ ] **Step A2.1: Read sibling doctrines to match style**

Read `skills/shepherd/doctrines/cargo-sequential-gates.md` and `skills/shepherd/doctrines/context-registry.md` (2 files). Match frontmatter shape + section convention.

- [ ] **Step A2.2: Write the doctrine**

Create `skills/shepherd/doctrines/sqlite-canonical-state.md`:

```markdown
---
title: SQLite-canonical operational state
slug: sqlite-canonical-state
status: binding
since: v5.1.7
---

# SQLite-canonical operational state

## Rule

`.artifacts/root.db` is the canonical store for operational and ephemeral
state. The filesystem is canonical only for human-authored durable artifacts.
Markdown reports are materialized views over DB rows, generated on demand
via `shctx report <kind>`.

## Allow-list

### SQLite-canonical (rows, queryable)

- Teammate identity, liveness, heartbeats (`teammates`, `heartbeats`)
- Inter-agent messages including heartbeat payloads (`mailbox`)
- Escalations: teammate → root surface points (`escalations`)
- Per-agent deliverable promise/complete ledger (`deliverables`)
- Structured discovery findings (`discovery_findings`)
- Structured audit findings (`audit_findings`)
- Hook events (`logs_events`, existing)
- Locks (`locks_history`, existing)
- Memory entries — doctrines/notes/decisions/incidents (`mem_entries`, existing)

### File-canonical (version-controlled, human-edited)

- `CLAUDE.md`, project doc roots
- `agents/*.md`, `commands/*.md`, `skills/**/*.md`, `doctrines/*.md`
- `.artifacts/docs/specs/*.md` (design specs)
- `.artifacts/docs/plans/*.md` (sprint plans)
- `.artifacts/docs/seeds/*.seed.md` (sprint seeds)
- `CHANGELOG.md`, `README.md`
- `skills/context/schema/*.sql` (the schema itself)

### Disposable (materialized on demand)

- Audit reports → `shctx report audit --sprint=<branch>`
- Discovery handoffs → `shctx report discovery --run=<id>`
- Sprint close reports → `shctx report close --sprint=<branch>`
- Operator-facing status pages → `shctx report teammates --team=<name>`

Disposable views may be written to `.artifacts/cache/` (gitignored) when
operators want a stable file path. Re-rendering from rows is idempotent.

## Why this exists

v5.1.5/v5.1.6 surfaced a defect cluster (#43, #49, #52, #53) where
ephemeral state was file-bound, causing:

- Opaque "did the write happen?" failures (no atomic commit)
- Invisible silent crashes (no liveness index)
- Filesystem-locked heartbeat protocols (no concurrent-write primitive)
- Markdown-paraphrase drift in cross-references (no schema)
- Operator-visible git churn from generated reports

SQLite gives atomicity, WAL concurrency, queryable structured state, and
indexable liveness. The shift to row-canonical eliminates the entire
class.

## Anti-patterns

1. **Inventing a new artifact path that isn't a `shctx <X> insert` call.**
   If a new operational-state kind needs storage, propose a schema migration
   first, then a `cmd_<sub>.sh`, then use it. Do not invent
   `.artifacts/<new-thing>/`.

2. **Writing a markdown report as the canonical output.** The report is a
   view. The rows are the truth. If an agent writes only markdown, the next
   agent has nothing to query.

3. **Reading the markdown view to "verify" rows landed.** Query the rows
   directly: `sqlite3 .artifacts/root.db "SELECT count(*) FROM <table>
   WHERE <filter>;"`

4. **Locking the markdown file to coordinate writes.** Use SQLite WAL +
   transactional inserts. The DB handles concurrency.

5. **Treating `shctx report` output as source-of-truth.** It's a snapshot.
   If state changes, re-render.

## Migration guidance (back-compat)

Existing markdown reporting flows continue to work without change in v5.1.7.
NEW flows added in v5.1.7+ MUST canonicalize via shctx. When an existing
markdown-report flow is touched for an unrelated reason, opportunistically
migrate it to the row-canonical pattern.

## Cited from

- `agents/discovery.md` (closes #43 via row-write contract)
- `agents/critic.md` (closes #52 via deliverable promise/complete)
- `agents/auditor.md` (closes #52, #44 via same pattern + intro-extras)
- `agents/conductor.md` (closes #50; references this doctrine in dispatch)
- `agents/shepherd.md` (closes #49 via liveness polling)

## Field origin

> Operator diagnosis, 2026-05-20: "consider why we continue producing so
> many artifacts when we have a sqlite instance specifically to help
> eliminate the need ... disk updates are a little slower than a database
> ... sqlite and databases have built in parallel / concurrent access
> protections unlike files."
```

- [ ] **Step A2.3: Verify the doctrine is referenced from agents (forward-looking)**

This step is just a self-check — agent profiles will cite this doctrine in B-lane work. No action needed here; B-lanes own the citations.

- [ ] **Step A2.4: Commit**

```bash
git add skills/shepherd/doctrines/sqlite-canonical-state.md
git commit -m "feat(v5.1.7/A2): doctrine — sqlite-canonical-state

Binding rule: .artifacts/root.db canonical for operational/ephemeral state;
filesystem canonical for human-authored durable artifacts; markdown reports
are materialized views. Closes architectural gap that caused the v5.1.5/
v5.1.6 defect cluster (#43, #49, #52, #53)."
```

---

### Task A3: shctx core subcommands (teammate, mailbox, escalate, deliverable, report)

**Files:**
- Create: `skills/context/scripts/cmd_teammate.sh`
- Create: `skills/context/scripts/cmd_mailbox.sh`
- Create: `skills/context/scripts/cmd_escalate.sh`
- Create: `skills/context/scripts/cmd_deliverable.sh`
- Create: `skills/context/scripts/cmd_report.sh`
- Modify: `skills/context/scripts/shctx` (dispatcher — only if new subcommands need explicit registration; otherwise the `*) echo "cmd_$1.sh"` fallback covers them per `2026-05-19-v513-cleanup-report.md`)
- Create: `skills/context/tests/test_cmd_teammate.sh`
- Create: `skills/context/tests/test_cmd_mailbox.sh`
- Create: `skills/context/tests/test_cmd_escalate.sh`
- Create: `skills/context/tests/test_cmd_deliverable.sh`
- Create: `skills/context/tests/test_cmd_report.sh`

**[FILE-SCOPE]** Only the 5 cmd files + 5 test files + (conditionally) dispatcher. Do NOT touch other cmd_*.sh files.

- [ ] **Step A3.1: Read existing cmd_*.sh for style match**

Read `skills/context/scripts/cmd_mem.sh` and `skills/context/scripts/cmd_query.sh` (these are the closest stylistic matches — both are CRUD-on-SQLite). Match: `set -euo pipefail`, sourcing of `lib_db.sh` if it exists, error reporting convention, exit codes.

Also read `skills/context/scripts/shctx` to confirm dispatcher behavior — verify the `*) echo "cmd_$1.sh"` fallback is intact (per cleanup report it is). New `cmd_*.sh` files will be automatically reachable without registration.

- [ ] **Step A3.2: Write `cmd_teammate.sh`**

Create `skills/context/scripts/cmd_teammate.sh`:

```bash
#!/usr/bin/env bash
# shctx teammate — register/heartbeat/status/liveness/prune/retire
# Per doctrines/sqlite-canonical-state.md: teammates table is canonical
# store for teammate identity + liveness.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Resolve DB path: prefer .artifacts/root.db relative to project root.
DB="${SHCTX_DB:-$(git rev-parse --show-toplevel 2>/dev/null)/.artifacts/root.db}"
[[ -f "$DB" ]] || { echo "ERR: registry DB not found at $DB" >&2; exit 1; }

now_ms() { echo $(($(date +%s) * 1000)); }
project_id() {
  # Match cmd_init.sh convention: project id = project root path SHA-prefix.
  # For now, use a literal default; cmd_init populated the row.
  sqlite3 "$DB" "SELECT id FROM projects LIMIT 1;"
}

usage() {
  cat <<'USAGE'
shctx teammate register <name> --team=<t> --type=<role> [--session=<uuid>] [--pane=<id>]
shctx teammate heartbeat <name> [--phase=<p>] [--tool=<t>] [--note=<n>]
shctx teammate status <name>
shctx teammate liveness [--stale-mins=<n>]
shctx teammate prune --confirm [--name=<n>|--crashed]
shctx teammate retire <name>
USAGE
}

sub="${1:-}"; shift || true
case "$sub" in
  register)
    name="$1"; shift
    team=""; type=""; session=""; pane=""
    while [[ $# -gt 0 ]]; do case "$1" in
      --team=*)    team="${1#*=}";;
      --type=*)    type="${1#*=}";;
      --session=*) session="${1#*=}";;
      --pane=*)    pane="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    [[ -n "$team" && -n "$type" ]] || { usage; exit 2; }
    pid="$(project_id)"
    id="$(uuidgen 2>/dev/null || python3 -c 'import uuid;print(uuid.uuid4())')"
    ts="$(now_ms)"
    sqlite3 "$DB" "INSERT INTO teammates (id, project_id, team_name, teammate_name, agent_type, session_id, tmux_pane_id, spawned_at, last_seen_at, status) VALUES ('$id','$pid','$team','$name','$type',NULLIF('$session',''),NULLIF('$pane',''),$ts,$ts,'booting');"
    echo "$id"
    ;;
  heartbeat)
    name="$1"; shift
    phase=""; tool=""; note=""
    while [[ $# -gt 0 ]]; do case "$1" in
      --phase=*) phase="${1#*=}";;
      --tool=*)  tool="${1#*=}";;
      --note=*)  note="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    ts="$(now_ms)"
    tid=$(sqlite3 "$DB" "SELECT id FROM teammates WHERE teammate_name='$name' ORDER BY spawned_at DESC LIMIT 1;")
    [[ -n "$tid" ]] || { echo "ERR: no teammate named $name" >&2; exit 1; }
    sqlite3 "$DB" "UPDATE teammates SET last_seen_at=$ts, status=CASE WHEN status='booting' THEN 'active' ELSE status END WHERE id='$tid'; INSERT INTO heartbeats (teammate_id, ts, phase, tool_name, note) VALUES ('$tid', $ts, NULLIF('$phase',''), NULLIF('$tool',''), NULLIF('$note',''));"
    ;;
  status)
    name="$1"
    sqlite3 -json "$DB" "SELECT * FROM teammates WHERE teammate_name='$name' ORDER BY spawned_at DESC LIMIT 1;"
    ;;
  liveness)
    stale=5
    while [[ $# -gt 0 ]]; do case "$1" in
      --stale-mins=*) stale="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    threshold_ms=$((stale * 60 * 1000))
    sqlite3 -header -column "$DB" "SELECT teammate_name, agent_type, status, ms_since_seen/1000 AS sec_since_seen, CASE WHEN ms_since_seen > $threshold_ms AND status IN ('booting','active') THEN 'presumed-crashed' ELSE 'ok' END AS verdict FROM v_teammates_live ORDER BY ms_since_seen DESC;"
    ;;
  prune)
    confirm=0; name=""; crashed=0
    while [[ $# -gt 0 ]]; do case "$1" in
      --confirm)  confirm=1;;
      --name=*)   name="${1#*=}";;
      --crashed)  crashed=1;;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    [[ "$confirm" == "1" ]] || { echo "refusing prune without --confirm" >&2; exit 2; }
    where="1=1"
    [[ -n "$name" ]] && where="teammate_name='$name'"
    [[ "$crashed" == "1" ]] && where="status = 'crashed'"
    n=$(sqlite3 "$DB" "SELECT count(*) FROM teammates WHERE $where;")
    sqlite3 "$DB" "DELETE FROM teammates WHERE $where;"
    echo "pruned $n teammate(s)"
    ;;
  retire)
    name="$1"
    sqlite3 "$DB" "UPDATE teammates SET status='retired' WHERE teammate_name='$name';"
    ;;
  ""|help|--help|-h) usage;;
  *) echo "unknown subcommand: $sub" >&2; usage; exit 2;;
esac
```

Make executable: `chmod +x skills/context/scripts/cmd_teammate.sh`

- [ ] **Step A3.3: Write `test_cmd_teammate.sh`**

Create `skills/context/tests/test_cmd_teammate.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"

TMPDIR_T="$(mktemp -d -t shepherd-test-teammate.XXXXXX)"
trap "rm -rf $TMPDIR_T" EXIT
export SHCTX_DB="$TMPDIR_T/root.db"

# Bootstrap schema
for f in "$ROOT/skills/context/schema/0001_init.sql" \
         "$ROOT/skills/context/schema/migrations/"*.sql \
         "$ROOT/skills/context/schema/0007_canonical_state.sql"; do
  sqlite3 "$SHCTX_DB" < "$f"
done
sqlite3 "$SHCTX_DB" "INSERT INTO projects (id, name, created_at, updated_at) VALUES ('test-proj', 'test', $(date +%s)000, $(date +%s)000);"

CMD="bash $ROOT/skills/context/scripts/cmd_teammate.sh"

# register
id=$($CMD register conductor-test --team=team-a --type=conductor --pane='%5')
[[ -n "$id" ]] || { echo "FAIL: register returned empty id"; exit 1; }

# heartbeat moves status booting → active
$CMD heartbeat conductor-test --phase=wave-1 --tool=Read
status=$(sqlite3 "$SHCTX_DB" "SELECT status FROM teammates WHERE id='$id';")
[[ "$status" == "active" ]] || { echo "FAIL: status after heartbeat: $status"; exit 1; }

# heartbeat row inserted
hb=$(sqlite3 "$SHCTX_DB" "SELECT count(*) FROM heartbeats WHERE teammate_id='$id';")
[[ "$hb" == "1" ]] || { echo "FAIL: heartbeat row count: $hb"; exit 1; }

# liveness shows table
$CMD liveness --stale-mins=10 | grep -q "conductor-test" || { echo "FAIL: liveness missing conductor-test"; exit 1; }

# status returns JSON
$CMD status conductor-test | grep -q '"teammate_name":"conductor-test"' || { echo "FAIL: status JSON shape"; exit 1; }

# retire sets status
$CMD retire conductor-test
status=$(sqlite3 "$SHCTX_DB" "SELECT status FROM teammates WHERE id='$id';")
[[ "$status" == "retired" ]] || { echo "FAIL: status after retire: $status"; exit 1; }

# prune --confirm --name removes
$CMD prune --confirm --name=conductor-test | grep -q "pruned 1" || { echo "FAIL: prune output"; exit 1; }
remaining=$(sqlite3 "$SHCTX_DB" "SELECT count(*) FROM teammates;")
[[ "$remaining" == "0" ]] || { echo "FAIL: rows remain: $remaining"; exit 1; }

# prune refuses without --confirm
if $CMD prune --crashed 2>/dev/null; then
  echo "FAIL: prune ran without --confirm"; exit 1
fi

echo "PASS: test_cmd_teammate"
```

Make executable: `chmod +x skills/context/tests/test_cmd_teammate.sh`

- [ ] **Step A3.4: Run test to verify it passes**

Run: `bash skills/context/tests/test_cmd_teammate.sh`
Expected: `PASS: test_cmd_teammate`

- [ ] **Step A3.5: Write `cmd_mailbox.sh` (similar pattern)**

Create `skills/context/scripts/cmd_mailbox.sh`:

```bash
#!/usr/bin/env bash
# shctx mailbox — send/recv/ack/stale
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB="${SHCTX_DB:-$(git rev-parse --show-toplevel 2>/dev/null)/.artifacts/root.db}"
[[ -f "$DB" ]] || { echo "ERR: registry DB not found at $DB" >&2; exit 1; }
now_ms() { echo $(($(date +%s) * 1000)); }
project_id() { sqlite3 "$DB" "SELECT id FROM projects LIMIT 1;"; }

usage() { cat <<'U'
shctx mailbox send --to=<name> --kind=<k> [--target-file=<p>] [--requires-ack] <<<payload-json
shctx mailbox recv --as=<name> [--unread-only] [--mark-read]
shctx mailbox ack <id>
shctx mailbox stale [--mins=<n>]
U
}

sub="${1:-}"; shift || true
case "$sub" in
  send)
    to=""; kind="generic"; target=""; ack=0
    while [[ $# -gt 0 ]]; do case "$1" in
      --to=*)          to="${1#*=}";;
      --kind=*)        kind="${1#*=}";;
      --target-file=*) target="${1#*=}";;
      --requires-ack)  ack=1;;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    [[ -n "$to" ]] || { usage; exit 2; }
    payload="$(cat)"
    # Validate payload JSON
    echo "$payload" | python3 -c 'import sys,json;json.loads(sys.stdin.read())' >/dev/null 2>&1 \
      || { echo "ERR: payload not valid JSON" >&2; exit 1; }
    pid="$(project_id)"
    sender="${CLAUDE_TEAMMATE_NAME:-root}"
    ts="$(now_ms)"
    # Escape single quotes in payload
    safe_payload="${payload//\'/\'\'}"
    safe_target="${target//\'/\'\'}"
    id=$(sqlite3 "$DB" "INSERT INTO mailbox (project_id, sender_id, recipient_name, kind, payload, target_file, requires_ack, sent_at) VALUES ('$pid','$sender','$to','$kind','$safe_payload',NULLIF('$safe_target',''),$ack,$ts) RETURNING id;")
    echo "$id"
    ;;
  recv)
    as=""; unread=0; mark=0
    while [[ $# -gt 0 ]]; do case "$1" in
      --as=*)        as="${1#*=}";;
      --unread-only) unread=1;;
      --mark-read)   mark=1;;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    [[ -n "$as" ]] || { usage; exit 2; }
    where="recipient_name='$as'"
    [[ "$unread" == "1" ]] && where="$where AND read_at IS NULL"
    sqlite3 -json "$DB" "SELECT * FROM mailbox WHERE $where ORDER BY sent_at;"
    if [[ "$mark" == "1" ]]; then
      sqlite3 "$DB" "UPDATE mailbox SET read_at=$(now_ms) WHERE $where AND read_at IS NULL;"
    fi
    ;;
  ack)
    id="$1"
    sqlite3 "$DB" "UPDATE mailbox SET acked_at=$(now_ms) WHERE id=$id;"
    ;;
  stale)
    mins=30
    while [[ $# -gt 0 ]]; do case "$1" in
      --mins=*) mins="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    cutoff=$(( $(now_ms) - mins*60*1000 ))
    sqlite3 -header -column "$DB" "SELECT id, recipient_name, kind, sent_at FROM mailbox WHERE requires_ack=1 AND acked_at IS NULL AND sent_at < $cutoff ORDER BY sent_at;"
    ;;
  ""|help|--help|-h) usage;;
  *) echo "unknown subcommand: $sub" >&2; usage; exit 2;;
esac
```

Make executable: `chmod +x skills/context/scripts/cmd_mailbox.sh`

- [ ] **Step A3.6: Write `test_cmd_mailbox.sh`**

Create `skills/context/tests/test_cmd_mailbox.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
TMPDIR_T="$(mktemp -d -t shepherd-test-mailbox.XXXXXX)"
trap "rm -rf $TMPDIR_T" EXIT
export SHCTX_DB="$TMPDIR_T/root.db"

for f in "$ROOT/skills/context/schema/0001_init.sql" \
         "$ROOT/skills/context/schema/migrations/"*.sql \
         "$ROOT/skills/context/schema/0007_canonical_state.sql"; do
  sqlite3 "$SHCTX_DB" < "$f"
done
sqlite3 "$SHCTX_DB" "INSERT INTO projects (id, name, created_at, updated_at) VALUES ('test-proj', 'test', 1, 1);"

CMD="bash $ROOT/skills/context/scripts/cmd_mailbox.sh"

# send with valid JSON payload
id=$(echo '{"line":"pub mod volume;"}' | $CMD send --to=obs-init --kind=heartbeat_payload --target-file=crates/config/src/lib.rs --requires-ack)
[[ -n "$id" ]] || { echo "FAIL: send returned no id"; exit 1; }

# recv as recipient finds the message
$CMD recv --as=obs-init --unread-only | grep -q '"recipient_name":"obs-init"' || { echo "FAIL: recv missing message"; exit 1; }

# recv with --mark-read flips read_at
$CMD recv --as=obs-init --mark-read >/dev/null
read_at=$(sqlite3 "$SHCTX_DB" "SELECT read_at FROM mailbox WHERE id=$id;")
[[ -n "$read_at" && "$read_at" != "" ]] || { echo "FAIL: read_at not set"; exit 1; }

# ack flips acked_at
$CMD ack $id
acked=$(sqlite3 "$SHCTX_DB" "SELECT acked_at FROM mailbox WHERE id=$id;")
[[ -n "$acked" && "$acked" != "" ]] || { echo "FAIL: acked_at not set"; exit 1; }

# send refuses invalid JSON
if echo 'not-json' | $CMD send --to=x --kind=generic 2>/dev/null; then
  echo "FAIL: send accepted invalid JSON"; exit 1
fi

echo "PASS: test_cmd_mailbox"
```

Make executable, run: `bash skills/context/tests/test_cmd_mailbox.sh`
Expected: `PASS: test_cmd_mailbox`

- [ ] **Step A3.7: Write `cmd_escalate.sh`**

Create `skills/context/scripts/cmd_escalate.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB="${SHCTX_DB:-$(git rev-parse --show-toplevel 2>/dev/null)/.artifacts/root.db}"
[[ -f "$DB" ]] || { echo "ERR: registry DB not found at $DB" >&2; exit 1; }
now_ms() { echo $(($(date +%s) * 1000)); }
project_id() { sqlite3 "$DB" "SELECT id FROM projects LIMIT 1;"; }

usage() { cat <<'U'
shctx escalate --role=<r> --question=<q> [--blocking] [--phase=<p>] [--context=<json>]
shctx escalate list [--open-only]
shctx escalate resolve <id> --reply=<text>
U
}

sub="${1:-}"
# If sub is a known subcommand, shift; otherwise treat top-level as create.
case "$sub" in
  list|resolve|help|--help|-h|"") shift || true ;;
  *) sub="create" ;;  # top-level create form
esac

case "$sub" in
  create)
    role=""; q=""; blocking=1; phase=""; ctx=""
    while [[ $# -gt 0 ]]; do case "$1" in
      --role=*)     role="${1#*=}";;
      --question=*) q="${1#*=}";;
      --blocking)   blocking=1;;
      --phase=*)    phase="${1#*=}";;
      --context=*)  ctx="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    [[ -n "$role" && -n "$q" ]] || { usage; exit 2; }
    [[ -n "$ctx" ]] && echo "$ctx" | python3 -c 'import sys,json;json.loads(sys.stdin.read())' >/dev/null 2>&1 || ctx=""
    pid="$(project_id)"
    tname="${CLAUDE_TEAMMATE_NAME:-}"
    tid=""
    [[ -n "$tname" ]] && tid=$(sqlite3 "$DB" "SELECT id FROM teammates WHERE teammate_name='$tname' ORDER BY spawned_at DESC LIMIT 1;")
    ts="$(now_ms)"
    safe_q="${q//\'/\'\'}"; safe_ctx="${ctx//\'/\'\'}"
    id=$(sqlite3 "$DB" "INSERT INTO escalations (project_id, teammate_id, role, phase, question, blocking, context_refs, raised_at) VALUES ('$pid', NULLIF('$tid',''), '$role', NULLIF('$phase',''), '$safe_q', $blocking, NULLIF('$safe_ctx',''), $ts) RETURNING id;")
    echo "$id"
    ;;
  list)
    open_only=0
    while [[ $# -gt 0 ]]; do case "$1" in
      --open-only) open_only=1;;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    if [[ "$open_only" == "1" ]]; then
      sqlite3 -header -column "$DB" "SELECT * FROM v_escalations_open;"
    else
      sqlite3 -header -column "$DB" "SELECT id, role, phase, blocking, raised_at, resolved_at FROM escalations ORDER BY raised_at DESC;"
    fi
    ;;
  resolve)
    id="$1"; shift
    reply=""
    while [[ $# -gt 0 ]]; do case "$1" in
      --reply=*) reply="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    [[ -n "$reply" ]] || { echo "ERR: --reply required" >&2; exit 2; }
    safe="${reply//\'/\'\'}"
    sqlite3 "$DB" "UPDATE escalations SET resolved_at=$(now_ms), resolution='$safe' WHERE id=$id;"
    ;;
  ""|help|--help|-h) usage;;
esac
```

Make executable: `chmod +x skills/context/scripts/cmd_escalate.sh`

- [ ] **Step A3.8: Write `test_cmd_escalate.sh`**

Create `skills/context/tests/test_cmd_escalate.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
TMPDIR_T="$(mktemp -d -t shepherd-test-escalate.XXXXXX)"
trap "rm -rf $TMPDIR_T" EXIT
export SHCTX_DB="$TMPDIR_T/root.db"
for f in "$ROOT/skills/context/schema/0001_init.sql" \
         "$ROOT/skills/context/schema/migrations/"*.sql \
         "$ROOT/skills/context/schema/0007_canonical_state.sql"; do
  sqlite3 "$SHCTX_DB" < "$f"
done
sqlite3 "$SHCTX_DB" "INSERT INTO projects (id, name, created_at, updated_at) VALUES ('p', 't', 1, 1);"

CMD="bash $ROOT/skills/context/scripts/cmd_escalate.sh"

id=$($CMD --role=engineer --question='serde rotation needs operator call' --blocking)
[[ -n "$id" ]] || { echo "FAIL: escalate create returned no id"; exit 1; }

$CMD list --open-only | grep -q "engineer" || { echo "FAIL: list --open-only missing role"; exit 1; }

$CMD resolve $id --reply='use serde 1.0.220'
resolved=$(sqlite3 "$SHCTX_DB" "SELECT resolved_at FROM escalations WHERE id=$id;")
[[ -n "$resolved" && "$resolved" != "" ]] || { echo "FAIL: resolved_at not set"; exit 1; }

echo "PASS: test_cmd_escalate"
```

Run: `bash skills/context/tests/test_cmd_escalate.sh`
Expected: PASS

- [ ] **Step A3.9: Write `cmd_deliverable.sh`**

Create `skills/context/scripts/cmd_deliverable.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB="${SHCTX_DB:-$(git rev-parse --show-toplevel 2>/dev/null)/.artifacts/root.db}"
[[ -f "$DB" ]] || { echo "ERR: registry DB not found at $DB" >&2; exit 1; }
now_ms() { echo $(($(date +%s) * 1000)); }
project_id() { sqlite3 "$DB" "SELECT id FROM projects LIMIT 1;"; }

usage() { cat <<'U'
shctx deliverable promise --kind=<k> --target=<ref> [--role=<r>]
shctx deliverable complete <id>
shctx deliverable stalled [--since-mins=<n>]
U
}

sub="${1:-}"; shift || true
case "$sub" in
  promise)
    kind=""; target=""; role=""
    while [[ $# -gt 0 ]]; do case "$1" in
      --kind=*)   kind="${1#*=}";;
      --target=*) target="${1#*=}";;
      --role=*)   role="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    [[ -n "$kind" && -n "$target" ]] || { usage; exit 2; }
    pid="$(project_id)"
    session="${CLAUDE_SESSION_ID:-unknown}"
    role="${role:-${CLAUDE_AGENT_ROLE:-unknown}}"
    ts="$(now_ms)"
    safe_t="${target//\'/\'\'}"
    id=$(sqlite3 "$DB" "INSERT INTO deliverables (project_id, agent_session, agent_role, kind, target_ref, promised_at, status) VALUES ('$pid','$session','$role','$kind','$safe_t',$ts,'pending') RETURNING id;")
    echo "$id"
    ;;
  complete)
    id="$1"
    sqlite3 "$DB" "UPDATE deliverables SET status='delivered', delivered_at=$(now_ms) WHERE id=$id;"
    ;;
  stalled)
    since=10
    while [[ $# -gt 0 ]]; do case "$1" in
      --since-mins=*) since="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    cutoff=$(( $(now_ms) - since*60*1000 ))
    sqlite3 -header -column "$DB" "SELECT id, agent_role, kind, target_ref, promised_at FROM deliverables WHERE status='pending' AND promised_at < $cutoff ORDER BY promised_at;"
    ;;
  ""|help|--help|-h) usage;;
  *) echo "unknown subcommand: $sub" >&2; usage; exit 2;;
esac
```

Make executable: `chmod +x skills/context/scripts/cmd_deliverable.sh`

- [ ] **Step A3.10: Write `test_cmd_deliverable.sh`**

Create `skills/context/tests/test_cmd_deliverable.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
TMPDIR_T="$(mktemp -d -t shepherd-test-deliverable.XXXXXX)"
trap "rm -rf $TMPDIR_T" EXIT
export SHCTX_DB="$TMPDIR_T/root.db"
for f in "$ROOT/skills/context/schema/0001_init.sql" \
         "$ROOT/skills/context/schema/migrations/"*.sql \
         "$ROOT/skills/context/schema/0007_canonical_state.sql"; do
  sqlite3 "$SHCTX_DB" < "$f"
done
sqlite3 "$SHCTX_DB" "INSERT INTO projects (id, name, created_at, updated_at) VALUES ('p', 't', 1, 1);"
CMD="bash $ROOT/skills/context/scripts/cmd_deliverable.sh"

id=$(CLAUDE_AGENT_ROLE=critic CLAUDE_SESSION_ID=sess1 $CMD promise --kind=row --target='audit_findings:code-quality')
[[ -n "$id" ]] || { echo "FAIL: promise returned no id"; exit 1; }

st=$(sqlite3 "$SHCTX_DB" "SELECT status FROM deliverables WHERE id=$id;")
[[ "$st" == "pending" ]] || { echo "FAIL: status not pending"; exit 1; }

$CMD complete $id
st=$(sqlite3 "$SHCTX_DB" "SELECT status FROM deliverables WHERE id=$id;")
[[ "$st" == "delivered" ]] || { echo "FAIL: status not delivered"; exit 1; }

echo "PASS: test_cmd_deliverable"
```

Run: PASS expected.

- [ ] **Step A3.11: Write `cmd_report.sh` (markdown materializer)**

Create `skills/context/scripts/cmd_report.sh`:

```bash
#!/usr/bin/env bash
# shctx report <kind> [filters]
# Materializes markdown views from canonical SQLite rows.
# Kinds: discovery, audit, escalation, close, teammates
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB="${SHCTX_DB:-$(git rev-parse --show-toplevel 2>/dev/null)/.artifacts/root.db}"
[[ -f "$DB" ]] || { echo "ERR: registry DB not found at $DB" >&2; exit 1; }

usage() { cat <<'U'
shctx report discovery --run=<id> [--sprint=<branch>]
shctx report audit --sprint=<branch> [--concern=<c>] [--severity=<s>]
shctx report escalation [--open-only]
shctx report close --sprint=<branch>
shctx report teammates [--team=<name>] [--stale-mins=<n>]
U
}

kind="${1:-}"; shift || true
case "$kind" in
  discovery)
    run=""; sprint=""
    while [[ $# -gt 0 ]]; do case "$1" in
      --run=*)    run="${1#*=}";;
      --sprint=*) sprint="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    [[ -n "$run" ]] || { usage; exit 2; }
    echo "# Discovery report — run \`$run\`"
    [[ -n "$sprint" ]] && echo "Sprint: \`$sprint\`"
    echo
    sqlite3 -separator '|' "$DB" "SELECT section, title, body, sources FROM discovery_findings WHERE discovery_run='$run'$([ -n "$sprint" ] && echo " AND sprint_branch='$sprint'") ORDER BY section, created_at;" \
      | while IFS='|' read -r section title body sources; do
          echo "## ${section:-General} — $title"
          echo
          echo "$body"
          [[ -n "$sources" && "$sources" != "" ]] && echo -e "\n_sources_: \`$sources\`"
          echo
        done
    ;;
  audit)
    sprint=""; concern=""; sev=""
    while [[ $# -gt 0 ]]; do case "$1" in
      --sprint=*)   sprint="${1#*=}";;
      --concern=*)  concern="${1#*=}";;
      --severity=*) sev="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    [[ -n "$sprint" ]] || { usage; exit 2; }
    where="sprint_branch='$sprint'"
    [[ -n "$concern" ]] && where="$where AND concern='$concern'"
    [[ -n "$sev" ]]     && where="$where AND severity='$sev'"
    echo "# Audit report — sprint \`$sprint\`"
    echo
    sqlite3 -separator '|' "$DB" "SELECT concern, severity, hypothesis, falsification, confidence, finding, gh_issue FROM audit_findings WHERE $where ORDER BY CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 WHEN 'low' THEN 4 ELSE 5 END, created_at;" \
      | while IFS='|' read -r concern severity hypothesis falsification confidence finding gh; do
          echo "### [$severity / $concern] $hypothesis"
          [[ -n "$gh" && "$gh" != "" ]] && echo "(filed as #$gh)"
          echo
          echo "**Finding:** $finding"
          [[ -n "$falsification" && "$falsification" != "" ]] && echo -e "\n**Falsification attempt:** $falsification"
          [[ -n "$confidence" && "$confidence" != "" ]] && echo -e "\n**Confidence:** $confidence"
          echo
        done
    ;;
  escalation)
    open=0
    while [[ $# -gt 0 ]]; do case "$1" in
      --open-only) open=1;;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    echo "# Escalations"
    echo
    if [[ "$open" == "1" ]]; then
      sqlite3 -separator '|' "$DB" "SELECT id, role, phase, question, raised_at FROM v_escalations_open;" \
        | while IFS='|' read -r id role phase q raised; do
            echo "- **#$id [$role/${phase:-?}]** $q (raised: $raised)"
          done
    else
      sqlite3 -separator '|' "$DB" "SELECT id, role, question, raised_at, resolved_at FROM escalations ORDER BY raised_at DESC;" \
        | while IFS='|' read -r id role q raised resolved; do
            status="OPEN"; [[ -n "$resolved" && "$resolved" != "" ]] && status="RESOLVED"
            echo "- **#$id [$role/$status]** $q"
          done
    fi
    ;;
  close)
    sprint=""
    while [[ $# -gt 0 ]]; do case "$1" in
      --sprint=*) sprint="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    [[ -n "$sprint" ]] || { usage; exit 2; }
    echo "# Close report — \`$sprint\`"
    echo
    echo "## Audit findings"
    "$HERE/cmd_report.sh" audit --sprint="$sprint"
    echo
    echo "## Open escalations"
    "$HERE/cmd_report.sh" escalation --open-only
    echo
    echo "## Teammate roster"
    "$HERE/cmd_report.sh" teammates
    ;;
  teammates)
    team=""; stale=5
    while [[ $# -gt 0 ]]; do case "$1" in
      --team=*)       team="${1#*=}";;
      --stale-mins=*) stale="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    echo "# Teammates"
    echo
    where="1=1"
    [[ -n "$team" ]] && where="team_name='$team'"
    sqlite3 -separator '|' "$DB" "SELECT teammate_name, agent_type, status, last_seen_at FROM teammates WHERE $where ORDER BY spawned_at DESC;" \
      | while IFS='|' read -r name type status seen; do
          echo "- **$name** ($type) — status: $status — last seen: $seen"
        done
    ;;
  ""|help|--help|-h) usage;;
  *) echo "unknown kind: $kind" >&2; usage; exit 2;;
esac
```

Make executable: `chmod +x skills/context/scripts/cmd_report.sh`

- [ ] **Step A3.12: Write `test_cmd_report.sh`**

Create `skills/context/tests/test_cmd_report.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
TMPDIR_T="$(mktemp -d -t shepherd-test-report.XXXXXX)"
trap "rm -rf $TMPDIR_T" EXIT
export SHCTX_DB="$TMPDIR_T/root.db"
for f in "$ROOT/skills/context/schema/0001_init.sql" \
         "$ROOT/skills/context/schema/migrations/"*.sql \
         "$ROOT/skills/context/schema/0007_canonical_state.sql"; do
  sqlite3 "$SHCTX_DB" < "$f"
done
sqlite3 "$SHCTX_DB" "INSERT INTO projects (id, name, created_at, updated_at) VALUES ('p', 't', 1, 1);"
sqlite3 "$SHCTX_DB" "INSERT INTO discovery_findings (project_id, sprint_branch, discovery_run, section, title, body, created_at) VALUES ('p','v5.1.7','D-TEST','confirmed','Auth flow works','Detailed body',1);"
sqlite3 "$SHCTX_DB" "INSERT INTO audit_findings (project_id, sprint_branch, concern, severity, hypothesis, finding, created_at) VALUES ('p','v5.1.7','code-quality','high','spawn brief duplicates cargo discipline','duplicate found in 2 files',1);"

CMD="bash $ROOT/skills/context/scripts/cmd_report.sh"

$CMD discovery --run=D-TEST | grep -q "Auth flow works" || { echo "FAIL: discovery report missing finding"; exit 1; }
$CMD audit --sprint=v5.1.7 | grep -q "spawn brief duplicates" || { echo "FAIL: audit report missing finding"; exit 1; }
$CMD audit --sprint=v5.1.7 --severity=high | grep -q "high" || { echo "FAIL: audit report severity filter"; exit 1; }
$CMD teammates >/dev/null || { echo "FAIL: teammates report errored"; exit 1; }

echo "PASS: test_cmd_report"
```

Run: PASS expected.

- [ ] **Step A3.13: Verify dispatcher reachability for all new subcommands**

Run:
```bash
for sub in teammate mailbox escalate deliverable report; do
  bash skills/context/scripts/shctx $sub help >/dev/null 2>&1 && echo "OK: $sub" || echo "FAIL: $sub not reachable"
done
```
Expected: 5 OK lines (the dispatcher fallback `*) echo "cmd_$1.sh"` per cleanup-report makes new files automatically reachable).

If any FAIL: open `skills/context/scripts/shctx` and verify the fallback case is present. Do not modify unless missing.

- [ ] **Step A3.14: Commit**

```bash
git add skills/context/scripts/cmd_teammate.sh \
        skills/context/scripts/cmd_mailbox.sh \
        skills/context/scripts/cmd_escalate.sh \
        skills/context/scripts/cmd_deliverable.sh \
        skills/context/scripts/cmd_report.sh \
        skills/context/tests/test_cmd_teammate.sh \
        skills/context/tests/test_cmd_mailbox.sh \
        skills/context/tests/test_cmd_escalate.sh \
        skills/context/tests/test_cmd_deliverable.sh \
        skills/context/tests/test_cmd_report.sh
git commit -m "feat(v5.1.7/A3): shctx core subcommands — teammate, mailbox, escalate, deliverable, report

CRUD wrappers for the v5.1.7 canonical-state tables. Each round-trips
via sqlite3, respects the existing shctx dispatcher fallback. Test
coverage per-subcommand under skills/context/tests/."
```

---

### Task A4: shctx insert subcommands (discovery, audit)

**Files:**
- Create or extend: `skills/context/scripts/cmd_discovery.sh` (per cleanup report, an existing one exists for `shctx discovery` — extend with `insert` subverb)
- Create: `skills/context/scripts/cmd_audit.sh` (extend if exists)

**[FILE-SCOPE]** Only these two files.

- [ ] **Step A4.1: Check whether `cmd_discovery.sh` and `cmd_audit.sh` exist**

Run: `ls skills/context/scripts/cmd_discovery.sh skills/context/scripts/cmd_audit.sh 2>&1`
- If both exist: extend in-place, preserving existing top-level subcommands.
- If new: create from scratch.

- [ ] **Step A4.2: Extend `cmd_discovery.sh` with `insert`**

Add this subcommand handler. If the file already has a case statement on `$1`, add `insert` as a new case arm. If new, follow the pattern of A3 commands (`set -euo pipefail`, DB path resolution, etc.):

```bash
  insert)
    run=""; section=""; title=""; sources=""; sprint=""
    while [[ $# -gt 0 ]]; do case "$1" in
      --run=*)     run="${1#*=}";;
      --section=*) section="${1#*=}";;
      --title=*)   title="${1#*=}";;
      --sources=*) sources="${1#*=}";;
      --sprint=*)  sprint="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    [[ -n "$run" && -n "$title" ]] || { echo "ERR: --run and --title required" >&2; exit 2; }
    body="$(cat)"
    pid="$(sqlite3 "$DB" "SELECT id FROM projects LIMIT 1;")"
    ts=$(($(date +%s) * 1000))
    safe_title="${title//\'/\'\'}"; safe_body="${body//\'/\'\'}"
    safe_sec="${section//\'/\'\'}"; safe_src="${sources//\'/\'\'}"; safe_sp="${sprint//\'/\'\'}"
    id=$(sqlite3 "$DB" "INSERT INTO discovery_findings (project_id, sprint_branch, discovery_run, section, title, body, sources, created_at) VALUES ('$pid', NULLIF('$safe_sp',''), '$run', NULLIF('$safe_sec',''), '$safe_title', '$safe_body', NULLIF('$safe_src',''), $ts) RETURNING id;")
    echo "$id"
    ;;
```

- [ ] **Step A4.3: Extend `cmd_audit.sh` with `insert`**

Add similar handler:

```bash
  insert)
    concern=""; severity=""; hypothesis=""; falsification=""; confidence=""
    evidence=""; gh=""; sprint=""
    while [[ $# -gt 0 ]]; do case "$1" in
      --concern=*)       concern="${1#*=}";;
      --severity=*)      severity="${1#*=}";;
      --hypothesis=*)    hypothesis="${1#*=}";;
      --falsification=*) falsification="${1#*=}";;
      --confidence=*)    confidence="${1#*=}";;
      --evidence=*)      evidence="${1#*=}";;
      --gh-issue=*)      gh="${1#*=}";;
      --sprint=*)        sprint="${1#*=}";;
      *) echo "unknown flag: $1" >&2; exit 2;;
    esac; shift; done
    [[ -n "$concern" && -n "$severity" && -n "$hypothesis" ]] || { echo "ERR: --concern, --severity, --hypothesis required" >&2; exit 2; }
    finding="$(cat)"
    [[ -n "$evidence" ]] && echo "$evidence" | python3 -c 'import sys,json;json.loads(sys.stdin.read())' >/dev/null 2>&1 || evidence=""
    pid="$(sqlite3 "$DB" "SELECT id FROM projects LIMIT 1;")"
    ts=$(($(date +%s) * 1000))
    safe_hyp="${hypothesis//\'/\'\'}"; safe_fal="${falsification//\'/\'\'}"
    safe_fin="${finding//\'/\'\'}"; safe_ev="${evidence//\'/\'\'}"
    safe_sp="${sprint//\'/\'\'}"
    id=$(sqlite3 "$DB" "INSERT INTO audit_findings (project_id, sprint_branch, concern, severity, hypothesis, falsification, confidence, finding, evidence_refs, gh_issue, created_at) VALUES ('$pid', NULLIF('$safe_sp',''), '$concern', '$severity', '$safe_hyp', NULLIF('$safe_fal',''), NULLIF('$confidence',''), '$safe_fin', NULLIF('$safe_ev',''), NULLIF('$gh',''), $ts) RETURNING id;")
    echo "$id"
    ;;
```

- [ ] **Step A4.4: Smoke-test insert paths**

```bash
# Bootstrap a tmp DB
TMP="$(mktemp -t shctx-A4.XXXXXX.db)"; trap "rm -f $TMP*" EXIT
export SHCTX_DB="$TMP"
for f in skills/context/schema/0001_init.sql \
         skills/context/schema/migrations/*.sql \
         skills/context/schema/0007_canonical_state.sql; do
  sqlite3 "$SHCTX_DB" < "$f"
done
sqlite3 "$SHCTX_DB" "INSERT INTO projects (id, name, created_at, updated_at) VALUES ('p','t',1,1);"

# Insert
id=$(echo "Found auth bug" | bash skills/context/scripts/cmd_discovery.sh insert --run=D-AUTH --section=confirmed --title='Auth probe')
[[ -n "$id" ]] || { echo "FAIL: discovery insert"; exit 1; }

id=$(echo "Stall pattern in critic" | bash skills/context/scripts/cmd_audit.sh insert --concern=code-quality --severity=high --hypothesis='critic stalls on Write')
[[ -n "$id" ]] || { echo "FAIL: audit insert"; exit 1; }

echo "A4 smoke PASS"
```

- [ ] **Step A4.5: Commit**

```bash
git add skills/context/scripts/cmd_discovery.sh skills/context/scripts/cmd_audit.sh
git commit -m "feat(v5.1.7/A4): shctx discovery/audit insert subverbs

Extend cmd_discovery.sh and cmd_audit.sh with 'insert' subcommand.
Reads body from stdin, validates flags, inserts row, prints id.
Closes #43 (discovery row contract) and #52 (audit deliverable
contract) at the surface layer; agent profile amendments (B1) tie
the agents to these commands."
```

---

### Task W1: Old-issue triage worker

**Lane brief context:** IO-bound — uses `gh` MCP/CLI to walk #18–#39 (22 issues). Classify each as superseded / still-valid / close-as-stale, post one summary comment per issue, write a triage report. NO code changes outside the report file.

**Files:**
- Create: `.artifacts/docs/handoffs/2026-05-20-old-issue-triage.md`
- Side effect: `gh issue comment` on each of #18–#39

**[FILE-SCOPE]** Only the handoff markdown. All other "writes" are GitHub side effects via `gh` CLI.

- [ ] **Step W1.1: Dispatch as a worker**

This task is dispatched to a `general-purpose` subagent with the following brief:

```
[OBJECTIVE]
Triage open issues #18-#39 in FL03/shepherd. For each, decide one of:
- SUPERSEDED: a v5.0.10-v5.1.6 change has resolved it (cite commit/PR)
- STILL-VALID: confirms current behavior; recommend keeping open
- CLOSE-AS-STALE: low-value, no longer relevant
Post a one-paragraph triage comment on each issue. DO NOT close any
issue programmatically (operator reviews triage report before close).

[FILE-SCOPE]
Write ONLY:
- .artifacts/docs/handoffs/2026-05-20-old-issue-triage.md (one section per issue)

GitHub side effects allowed:
- `gh issue comment <n> --body "..."` on each of #18-#39

[CONTEXT-INVENTORY]
- Recent commit log: git log --oneline v5.0.9..HEAD
- Current agent profiles: agents/{conductor,planter,shepherd,coder,
  critic,auditor,worker,discovery,engineer}.md
- Doctrines: skills/shepherd/doctrines/*.md
- Spec for current sprint: .artifacts/docs/specs/2026-05-20-v517-canonical-state-design.md

[ACCEPTANCE]
- Report exists at the path above with one ## section per issue #N
- Each section: title, current state, recommendation, evidence
- Each issue has exactly one new comment from this triage run
- Final summary: counts of {superseded, still-valid, close-as-stale}

[SKILLS]
- gh CLI for issue read + comment
- git log + grep for change-history grounding

[OUTPUT]
Single message to dispatcher with:
- absolute path to triage report
- count summary
- list of issues recommended for operator close
```

- [ ] **Step W1.2: Commit (report only, no auto-close)**

```bash
git add .artifacts/docs/handoffs/2026-05-20-old-issue-triage.md
git commit -m "chore(v5.1.7/W1): triage old issues #18-#39

Worker walked 22 open issues from v5.0.9-v5.1.1 era. Each received
one triage comment classifying as superseded / still-valid /
close-as-stale. Operator review pending before close.

Report: .artifacts/docs/handoffs/2026-05-20-old-issue-triage.md"
```

---

### Task W2: v5.1.6-fix verification worker

**Files:**
- Side effect only: `gh issue comment` on #45 and #46

**[FILE-SCOPE]** No file writes. GitHub side effects only.

- [ ] **Step W2.1: Dispatch as a worker**

```
[OBJECTIVE]
Verify the v5.1.6 fixes for issues #45 (dispatch tier separation) and
#46 (in-process Agent tool restriction). For each, confirm the cited
fix is present in tree, post a verification comment, and recommend
close (operator does the final close).

[FILE-SCOPE]
No file writes. GitHub side effects only:
- `gh issue comment 45 --body "..."`
- `gh issue comment 46 --body "..."`

[CONTEXT-INVENTORY]
For #45: verify
  - grep -n "WRONG-TIER-DISPATCH" agents/engineer.md agents/critic.md
  - grep -n "NEVER dispatch \`@engineer\`\|NEVER dispatch \`@critic\`" agents/conductor.md
  - file exists: agents/shepherd.md
  - file exists: skills/shepherd/doctrines/dispatch-tier-separation.md
  - commands/spawn.md references agents/shepherd.md

For #46: verify
  - commands/spawn.md contains "[WARN]" preflight on in-process mode
  - cited section §Platform compatibility or similar exists

[ACCEPTANCE]
- One verification comment per issue, with grep evidence
- Recommendation: close (or keep open with rationale)

[OUTPUT]
Single message to dispatcher with the grep evidence + recommendation.
```

- [ ] **Step W2.2: No commit (no file writes)**

This task produces GitHub-side-only effects.

---

## Wave 2 — Surface integration (4 parallel lanes)

All Wave 1 tasks must complete before Wave 2 starts (Wave 2 depends on schema + shctx commands being live).

---

### Task B1: Agent profile amendments — discovery, critic, auditor

**Files:**
- Modify: `agents/discovery.md`
- Modify: `agents/critic.md`
- Modify: `agents/auditor.md`

**[FILE-SCOPE]** Exactly these 3 files. Do not touch `conductor.md`, `shepherd.md`, `coder.md`, `worker.md`, `engineer.md`.

- [ ] **Step B1.1: Read each target file first**

Read all 3 files in parallel. Identify the existing `## Hard prohibitions` section in each; the new clauses are appended (not replaced).

- [ ] **Step B1.2: Amend `agents/discovery.md` — close #43**

Add a new Hard Prohibition (numbered, after existing prohibitions). Find the existing prohibitions block; append:

```markdown
N. **Inline-only reports are CONTRACT VIOLATION.** You MUST end your turn
   with one or more `shctx discovery insert --run=<RUN_ID>` calls — one row
   per finding. Returning report content inline-only causes the conductor to
   paraphrase rather than query, and breaks the discovery_capture hook. The
   `<RUN_ID>` is passed in your brief; if absent, halt with
   `MISSING-RUN-ID`. See `doctrines/sqlite-canonical-state.md`.
```

Also amend the `## Output to main chat` section (or equivalent) so the expected report shape becomes:

```markdown
## Output to main chat

```
## DISCOVERY REPORT
- inserted: <N> rows under run=<RUN_ID>
- materialized view: shctx report discovery --run=<RUN_ID>
- summary: <one-line summary of findings>
```
```

- [ ] **Step B1.3: Amend `agents/critic.md` — close #52 (stall-loop)**

After existing `## Mandatory protocol` section, insert a new step (or append to existing Step 0/1):

```markdown
## Step 0: Register deliverable promise

Before reading the plan, call:

```bash
DELIV_ID=$(shctx deliverable promise --kind=row --target=audit_findings:critic --role=critic)
```

Record the returned `$DELIV_ID`. At end of turn, after writing your verdict
rows via `shctx audit insert`, call:

```bash
shctx deliverable complete "$DELIV_ID"
```

If you end your turn without calling `complete`, the `deliverable_check.sh`
hook marks the row as `stalled` and the dispatcher will re-spawn with a
tightened brief. The verdict ROWS are canonical; the markdown verdict in
your message is a courtesy summary. See `doctrines/sqlite-canonical-state.md`.
```

Update `## Output to main chat` to include `- deliverable: <ID> (status: delivered)` line.

- [ ] **Step B1.4: Amend `agents/auditor.md` — close #52 + #44**

Two amendments:

(a) Same `## Step 0: Register deliverable promise` block as critic, but with
`--target=audit_findings:<concern>` and `--role=auditor`.

(b) Find the intro-mode section (look for `intro-mode` or `regression-from-prior-dev`).
Add the canonical-gates extras block:

```markdown
### Canonical gates (intro-mode regression)

1. Run the 4 check-class canonical gates as today.
2. **For EACH `[gates].extra` entry** in `.claude/shepherd.toml`:
   - Set `CARGO_TARGET_DIR=target/.lanes/intro-extra-<name>`.
   - Run the entry's `cmd` line.
   - Record ONE `audit_findings` row per extra:
     ```
     shctx audit insert \
       --concern=regression-extras \
       --severity=<high-on-fail|info-on-pass> \
       --hypothesis="extras gate <name>" \
       --falsification="ran <cmd> against HEAD" \
       --confidence=high \
       --sprint=<branch> \
       <<<"<first 20 lines of failure OR 'pass'>"
     ```
3. The materialized report (`shctx report audit --sprint=<branch>
   --concern=regression-extras`) MUST list 'extras run' + 'extras skipped'
   explicitly.

Closes #44 (silent test-class regression in intro audit).
```

Also append in `## Hard prohibitions`:

```markdown
N. **Skipping `[gates].extra` in intro-mode is CONTRACT VIOLATION.**
   See Canonical gates section above.
```

- [ ] **Step B1.5: Verify with grep**

```bash
grep -q "shctx discovery insert" agents/discovery.md || { echo "FAIL discovery"; exit 1; }
grep -q "shctx deliverable promise" agents/critic.md  || { echo "FAIL critic"; exit 1; }
grep -q "shctx deliverable promise" agents/auditor.md || { echo "FAIL auditor"; exit 1; }
grep -q "Canonical gates (intro-mode regression)" agents/auditor.md || { echo "FAIL intro extras"; exit 1; }
grep -q "doctrines/sqlite-canonical-state.md" agents/discovery.md  || { echo "FAIL discovery doctrine"; exit 1; }
grep -q "doctrines/sqlite-canonical-state.md" agents/critic.md     || { echo "FAIL critic doctrine"; exit 1; }
grep -q "doctrines/sqlite-canonical-state.md" agents/auditor.md    || { echo "FAIL auditor doctrine"; exit 1; }
echo "B1 grep PASS"
```

- [ ] **Step B1.6: Commit**

```bash
git add agents/discovery.md agents/critic.md agents/auditor.md
git commit -m "feat(v5.1.7/B1): agent amendments — discovery/critic/auditor

- discovery: Hard Prohibition + row-write contract (closes #43)
- critic: deliverable promise/complete protocol (closes #52)
- auditor: deliverable contract + intro-mode extras gate (closes #52, #44)
- All three cite doctrines/sqlite-canonical-state.md"
```

---

### Task B2: Agent profile amendments — conductor, shepherd, spawn

**Files:**
- Modify: `agents/conductor.md`
- Modify: `agents/shepherd.md`
- Modify: `commands/spawn.md`

**[FILE-SCOPE]** Exactly these 3 files.

- [ ] **Step B2.1: Read each file**

Identify the existing `## Hard prohibitions` and Halt codes sections.

- [ ] **Step B2.2: Amend `agents/conductor.md` — close #50**

Add a new section after the existing `## Mandatory protocol` (or wherever cargo discipline currently lives — check for existing cargo section first):

```markdown
## Cargo discipline (binding under spawn)

Every cargo invocation in your flock — including your own and every coder/
worker subagent you dispatch — MUST use:

```
CARGO_TARGET_DIR=target/.lanes/<lane-slug> cargo <subcmd> ... --frozen
```

Where `<lane-slug>` is the kebab-case suffix of your teammate name (e.g.
`conductor-obs-init` → `obs-init`). When dispatching coder/worker subagents,
your brief MUST include this prefix in any cargo example you provide.

Root cleanup removes `target/.lanes/` at sprint close.

Closes #50. References `doctrines/cargo-sequential-gates.md`.
```

- [ ] **Step B2.3: Amend `agents/shepherd.md` — close #49**

Add a new Halt code to the Halt codes table:

```markdown
| TEAMMATE-CRASHED | A spawned teammate's `last_seen_at` is stale beyond threshold. Root polls `shctx teammate liveness --stale-mins=5` and surfaces `presumed-crashed` rows. Offer re-spawn via `shctx mailbox` of the archived initial brief. |
```

Add a new section:

```markdown
## Crashed-teammate detection (closes #49)

During spawn, poll `shctx teammate liveness --stale-mins=5` after each
wave-gate. Any teammate with `verdict=presumed-crashed` should be:

1. Surfaced to the operator with the failed teammate's name, agent_type,
   and last_seen_at delta.
2. Offered for re-spawn — the operator confirms; root then dispatches a
   fresh teammate with the same brief (retrieved from the original
   spawn record).
3. If operator declines re-spawn, mark `shctx teammate retire <name>` and
   continue without that lane (escalate any blocked dependencies).

See `doctrines/sqlite-canonical-state.md`.
```

- [ ] **Step B2.4: Amend `commands/spawn.md` — cargo discipline block**

Find the conductor brief template section (typically "Brief assembled for teammate" or similar). Add this block to the template that the spawner emits:

```markdown
## Cargo discipline (binding)

- `--frozen` on EVERY cargo invocation. No exceptions.
- `CARGO_TARGET_DIR=target/.lanes/<your-lane-slug>` on EVERY cargo invocation
  (yours + every coder/worker subagent you dispatch).
- Cargo gates SERIAL only (per `doctrines/cargo-sequential-gates.md`).
- `cargo fix` FORBIDDEN.

Your lane-slug is `<derived from teammate_name>`.
```

The spawner substitutes the actual lane-slug at brief-emit time.

- [ ] **Step B2.5: Verify with grep**

```bash
grep -q "Cargo discipline (binding under spawn)" agents/conductor.md || { echo "FAIL conductor cargo"; exit 1; }
grep -q "TEAMMATE-CRASHED" agents/shepherd.md || { echo "FAIL shepherd halt"; exit 1; }
grep -q "Crashed-teammate detection" agents/shepherd.md || { echo "FAIL shepherd detection"; exit 1; }
grep -q "Cargo discipline (binding)" commands/spawn.md || { echo "FAIL spawn brief"; exit 1; }
grep -q "doctrines/sqlite-canonical-state.md" agents/conductor.md || { echo "FAIL conductor doctrine cite"; exit 1; }
grep -q "doctrines/sqlite-canonical-state.md" agents/shepherd.md || { echo "FAIL shepherd doctrine cite"; exit 1; }
echo "B2 grep PASS"
```

- [ ] **Step B2.6: Commit**

```bash
git add agents/conductor.md agents/shepherd.md commands/spawn.md
git commit -m "feat(v5.1.7/B2): conductor/shepherd/spawn amendments

- conductor: cargo discipline section binds CARGO_TARGET_DIR + --frozen (closes #50)
- shepherd: TEAMMATE-CRASHED halt + crashed-teammate detection (closes #49)
- spawn: Cargo discipline (binding) block injected into conductor brief"
```

---

### Task B3: New `/shepherd:cleanup` command

**Files:**
- Create: `commands/cleanup.md`
- Modify: `.claude-plugin/plugin.json` (commands array — only if it explicitly lists commands; if it's discovery-by-directory, no change needed)
- Modify: `.claude-plugin/marketplace.json` (same condition)
- Modify: `skills/shepherd/SKILL.md` (command table)

**[FILE-SCOPE]** Exactly these 4 paths (the plugin.json/marketplace.json edits are conditional — confirm by reading them first).

- [ ] **Step B3.1: Check plugin.json + marketplace.json for explicit command listings**

```bash
jq '.commands // null' .claude-plugin/plugin.json
jq '.. | objects | select(has("commands")) | .commands' .claude-plugin/marketplace.json 2>/dev/null
```

If `.commands` is `null` or absent, commands are discovered by directory scan; no edit needed. If a literal commands array exists, append `"cleanup"` (or full path).

- [ ] **Step B3.2: Write `commands/cleanup.md`**

```markdown
---
name: cleanup
description: Prune stale or crashed teammate entries from the team config + canonical state.
model: sonnet
allowed-tools:
  - Bash
  - Read
---

# /shepherd:cleanup

**Use when**: a spawned teammate has crashed silently (see #49 / #51) and
its team-config entry is polluting status displays, OR after a sprint to
prune retired teammate entries.

## Mandatory protocol

### Step 1: Show current teammate liveness

```bash
bash skills/context/scripts/shctx teammate liveness --stale-mins=5
```

Identify rows with `verdict=presumed-crashed` or `status=retired`.

### Step 2: Confirm with operator

Surface the to-be-pruned list. If 0 rows, exit with "nothing to prune."

### Step 3: Prune

For each confirmed entry:

```bash
bash skills/context/scripts/shctx teammate prune --confirm --name=<name>
```

OR bulk:

```bash
bash skills/context/scripts/shctx teammate prune --confirm --crashed
```

### Step 4: Materialize cleanup report

```bash
bash skills/context/scripts/shctx report teammates --stale-mins=5 \
  > .artifacts/cache/teammate-cleanup-$(date +%Y%m%d-%H%M%S).md
```

The cache file is gitignored; the canonical state is in
`teammates` table.

### Step 5: PAUSE

Report to operator: number pruned, final liveness state.

## Hard prohibitions

1. NEVER prune without `--confirm`.
2. NEVER prune `status='active'` rows without operator override.
3. NEVER auto-respawn without operator confirmation.

## Closes

#51 — /shepherd:cleanup command to prune stale/crashed teammate entries
```

- [ ] **Step B3.3: Amend `skills/shepherd/SKILL.md` command table**

Find the command table (looks like `| Command | Model | What it does |`). Add a row:

```markdown
| `/shepherd:cleanup` | Sonnet | Prune stale/crashed teammate entries from the canonical-state registry (closes #51). Operator-confirmed; never auto-prune live entries. |
```

- [ ] **Step B3.4: If plugin.json/marketplace.json need updates**

Only edit if Step B3.1 found explicit commands arrays. Add `"cleanup"` entry matching existing convention.

- [ ] **Step B3.5: Verify**

```bash
test -f commands/cleanup.md || { echo "FAIL cleanup.md missing"; exit 1; }
grep -q "/shepherd:cleanup" skills/shepherd/SKILL.md || { echo "FAIL SKILL.md table"; exit 1; }
grep -q "shctx teammate prune" commands/cleanup.md || { echo "FAIL cleanup body"; exit 1; }
echo "B3 grep PASS"
```

- [ ] **Step B3.6: Commit**

```bash
git add commands/cleanup.md skills/shepherd/SKILL.md
[[ -n "$(git diff --cached --name-only -- .claude-plugin/)" ]] && git add .claude-plugin/
git commit -m "feat(v5.1.7/B3): /shepherd:cleanup command — closes #51

New slash command wraps shctx teammate liveness + prune. Operator-
confirmed; never auto-prunes live entries. Materializes cleanup
report into gitignored .artifacts/cache/."
```

---

### Task B4: Hook integration

**Files:**
- Modify: `skills/context/scripts/hooks/subagent_telemetry.sh` (extend with heartbeat emission)
- Create: `skills/context/scripts/hooks/teammate_idle.sh`
- Create: `skills/context/scripts/hooks/deliverable_check.sh`
- Modify: `.claude-plugin/hooks.json` (or wherever shepherd registers hooks — check)

**[FILE-SCOPE]** Exactly these 4 paths.

- [ ] **Step B4.1: Locate hooks config**

```bash
ls -la .claude-plugin/hooks.json hooks.json hooks/ 2>&1
```

Identify the canonical hooks config. If `.claude-plugin/hooks.json` exists, that's it.

- [ ] **Step B4.2: Read `subagent_telemetry.sh` (existing, from v5.1.3)**

Read the file to understand current structure. Extension: at the end of the existing logic, add the heartbeat emission. Only fires when `$CLAUDE_TEAMMATE_NAME` is set (i.e., we're inside a teammate session, not the lead).

Append to existing file (do not rewrite):

```bash
# v5.1.7: emit teammate heartbeat if running inside a teammate session.
if [[ -n "${CLAUDE_TEAMMATE_NAME:-}" ]] && [[ -f "${PROJECT_ROOT:-.}/.artifacts/root.db" ]]; then
  bash "${PROJECT_ROOT:-.}/skills/context/scripts/cmd_teammate.sh" \
    heartbeat "$CLAUDE_TEAMMATE_NAME" \
    --tool="${CLAUDE_TOOL_NAME:-unknown}" 2>/dev/null || true
fi
```

- [ ] **Step B4.3: Write `teammate_idle.sh`**

Create `skills/context/scripts/hooks/teammate_idle.sh`:

```bash
#!/usr/bin/env bash
# TeammateIdle hook — runs in the LEAD's context when a teammate signals idle.
# Marks teammate status, scans unresolved escalations + stalled deliverables,
# surfaces warnings to operator via stderr (non-blocking).
set -euo pipefail

# Hook payload arrives on stdin as JSON per Claude Code hooks API.
PAYLOAD="$(cat || true)"
TEAMMATE="$(echo "$PAYLOAD" | jq -r '.teammate_name // empty' 2>/dev/null || true)"
[[ -z "$TEAMMATE" ]] && exit 0

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo .)"
[[ -f "$ROOT/.artifacts/root.db" ]] || exit 0

# Mark teammate idle
bash "$ROOT/skills/context/scripts/cmd_teammate.sh" \
  heartbeat "$TEAMMATE" --note='idle' 2>/dev/null || true
sqlite3 "$ROOT/.artifacts/root.db" \
  "UPDATE teammates SET status='idle' WHERE teammate_name='$TEAMMATE' AND status NOT IN ('crashed','retired');" 2>/dev/null || true

# Surface open escalations + stalled deliverables
ESC=$(bash "$ROOT/skills/context/scripts/cmd_escalate.sh" list --open-only 2>/dev/null | wc -l)
STALLED=$(bash "$ROOT/skills/context/scripts/cmd_deliverable.sh" stalled --since-mins=10 2>/dev/null | wc -l)

if [[ "$ESC" -gt 1 ]] || [[ "$STALLED" -gt 1 ]]; then
  echo "[shctx] teammate $TEAMMATE idle | open-escalations=$((ESC-1)) | stalled-deliverables=$((STALLED-1))" >&2
fi

exit 0
```

Make executable: `chmod +x skills/context/scripts/hooks/teammate_idle.sh`

- [ ] **Step B4.4: Write `deliverable_check.sh`**

Create `skills/context/scripts/hooks/deliverable_check.sh`:

```bash
#!/usr/bin/env bash
# PreToolUse/Stop hook — detect "promised but never delivered" stalls.
# Inspects pending deliverables; marks any pending > N minutes as 'stalled'.
# Non-blocking — emits warn to stderr only.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo .)"
[[ -f "$ROOT/.artifacts/root.db" ]] || exit 0

# Cutoff: 10 minutes
CUTOFF=$(( $(date +%s) * 1000 - 10*60*1000 ))

STALE=$(sqlite3 "$ROOT/.artifacts/root.db" \
  "SELECT count(*) FROM deliverables WHERE status='pending' AND promised_at < $CUTOFF;" 2>/dev/null || echo 0)

if [[ "$STALE" -gt 0 ]]; then
  sqlite3 "$ROOT/.artifacts/root.db" \
    "UPDATE deliverables SET status='stalled' WHERE status='pending' AND promised_at < $CUTOFF;" 2>/dev/null || true
  echo "[shctx] $STALE deliverable(s) auto-marked stalled (> 10 min pending)" >&2
fi

exit 0
```

Make executable: `chmod +x skills/context/scripts/hooks/deliverable_check.sh`

- [ ] **Step B4.5: Register hooks in `.claude-plugin/hooks.json`**

Read existing structure first. If hooks are registered as arrays-of-objects per event, append new entries. Example shape (adjust to actual file):

```json
{
  "PostToolUse": [
    { "matcher": "*", "command": "${CLAUDE_PLUGIN_ROOT}/skills/context/scripts/hooks/subagent_telemetry.sh" }
  ],
  "TeammateIdle": [
    { "matcher": "*", "command": "${CLAUDE_PLUGIN_ROOT}/skills/context/scripts/hooks/teammate_idle.sh" }
  ],
  "Stop": [
    { "matcher": "*", "command": "${CLAUDE_PLUGIN_ROOT}/skills/context/scripts/hooks/deliverable_check.sh" }
  ]
}
```

The `subagent_telemetry.sh` entry should already exist (v5.1.3); only ADD `TeammateIdle` and `Stop` entries.

- [ ] **Step B4.6: Smoke-test each hook in isolation**

```bash
# teammate_idle (provide a fake payload via stdin)
TMP="$(mktemp -t hook-test.XXXXXX.db)"
trap "rm -f $TMP*" EXIT
export SHCTX_DB="$TMP"
for f in skills/context/schema/0001_init.sql skills/context/schema/migrations/*.sql skills/context/schema/0007_canonical_state.sql; do
  sqlite3 "$SHCTX_DB" < "$f"
done
sqlite3 "$SHCTX_DB" "INSERT INTO projects (id, name, created_at, updated_at) VALUES ('p','t',1,1);"
echo '{"teammate_name":"conductor-test"}' | bash skills/context/scripts/hooks/teammate_idle.sh
echo "teammate_idle: OK"

# deliverable_check
bash skills/context/scripts/hooks/deliverable_check.sh
echo "deliverable_check: OK"
```

- [ ] **Step B4.7: Commit**

```bash
git add skills/context/scripts/hooks/teammate_idle.sh \
        skills/context/scripts/hooks/deliverable_check.sh \
        skills/context/scripts/hooks/subagent_telemetry.sh \
        .claude-plugin/hooks.json
git commit -m "feat(v5.1.7/B4): hook integration — heartbeat + idle + deliverable-check

- subagent_telemetry: extended to emit teammate heartbeat when
  CLAUDE_TEAMMATE_NAME is set
- teammate_idle: marks status=idle, surfaces open escalations +
  stalled deliverables to lead
- deliverable_check: auto-marks promises stalled after 10 min
- hooks.json: registers TeammateIdle and Stop entries

Closes #52 (stall detection at hook layer)."
```

---

## Wave 3 — Close

Both tasks dispatched after Wave 2 completes.

---

### Task C1: Close audit swarm (concern-split, parallel)

**Lane brief context:** Three concern-split auditors run in parallel via Agent tool. Each writes findings via `shctx audit insert`. Operator reviews materialized `shctx report audit --sprint=v5.1.7`.

**Files:** No file writes by auditors themselves (rows-only). Materialized report cached after close.

- [ ] **Step C1.1: Dispatch 3 concern-split auditors in parallel**

Three Agent subagent calls in one batch:

**Auditor #1 — code-quality:**
```
[OBJECTIVE]
Review v5.1.7 sprint diff for code-quality issues: dead code, unused imports
in new shctx scripts, sed/awk/echo overuse vs proper tools, missing
chmod +x on shell scripts, missing set -euo pipefail.

[FILE-SCOPE] Read-only audit. Findings via shctx audit insert.

[CONTEXT]
- Sprint diff: git diff main...v5.1.7
- New files: cmd_{teammate,mailbox,escalate,deliverable,report}.sh +
  hooks/{teammate_idle,deliverable_check}.sh + cleanup.md +
  schema/0007_canonical_state.sql

[ACCEPTANCE] One audit_findings row per finding, severity per
hypothesis-driven discipline (auditor-hypothesis-driven doctrine).

[OUTPUT]
- Number of findings inserted with breakdown by severity
- Recommendation: pass / hold for fix
```

**Auditor #2 — data-flow (DB ↔ agents):**
```
[OBJECTIVE]
Trace data flow between shctx subcommands and the agents that call them.
Verify: (a) agent profile amendments cite the right shctx commands; (b)
the deliverable promise/complete contract is end-to-end; (c) hook scripts
update the same tables agents read; (d) report materializers query the
same data agents insert.

[FILE-SCOPE] Read-only.

[CONTEXT]
- agents/{discovery,critic,auditor,conductor,shepherd}.md
- skills/context/scripts/cmd_{teammate,mailbox,escalate,deliverable,
  report,discovery,audit}.sh
- skills/context/scripts/hooks/{teammate_idle,deliverable_check,
  subagent_telemetry}.sh
- schema/0007_canonical_state.sql

[ACCEPTANCE] One audit_findings row per data-flow anomaly.
```

**Auditor #3 — completeness:**
```
[OBJECTIVE]
Verify the spec's "closes" list is honored. For each issue (#43, #44, #49,
#50, #51, #52), find the implementation evidence in tree and confirm the
fix is realized (not just claimed). Verify the v5.1.6-verification W2 lane
posted comments on #45 and #46.

[FILE-SCOPE] Read-only.

[ACCEPTANCE] One audit_findings row per closes-item; severity=critical for
any unfulfilled close-claim.

[OUTPUT] Closure ledger:
- #43: realized=yes/no | evidence=<grep result>
- #44: realized=yes/no | evidence
- ... etc
```

- [ ] **Step C1.2: Materialize the close report**

After all 3 auditors return:

```bash
bash skills/context/scripts/shctx report audit --sprint=v5.1.7 \
  > .artifacts/cache/2026-05-20-v517-close-audit.md
cat .artifacts/cache/2026-05-20-v517-close-audit.md
```

The cache file is gitignored; the rows are the canonical state. If the operator wants to track the close report in git, copy the cache file to `.artifacts/docs/handoffs/2026-05-20-v517-close.md` (operator choice).

- [ ] **Step C1.3: Conditional hotfix wave**

If any auditor returned `critical` or `high` severity findings, dispatch a single targeted coder lane to address. Otherwise proceed to C2.

- [ ] **Step C1.4: No commit unless hotfix**

C1 produces rows in the DB, not files. Commit only if the materialized report is copied to a tracked path or a hotfix lane fires.

---

### Task C2: Version + CHANGELOG sync

**Files:**
- Verify/Modify: `.claude-plugin/plugin.json` (already at 5.1.7 from prior chore)
- Verify/Modify: `.claude-plugin/marketplace.json`
- Verify/Modify: `skills/shepherd/SKILL.md` (frontmatter version)
- Verify/Modify: `skills/context/SKILL.md` (frontmatter version)
- Verify: `README.md`
- Modify: `CHANGELOG.md` (new v5.1.7 entry)

**[FILE-SCOPE]** Exactly these 6 paths.

- [ ] **Step C2.1: Check current version values**

```bash
echo "plugin.json:        $(jq -r '.version' .claude-plugin/plugin.json)"
echo "marketplace.json:   $(jq -r '..|objects|select(has("version"))|.version' .claude-plugin/marketplace.json 2>/dev/null | head -1)"
echo "shepherd SKILL.md:  $(head -20 skills/shepherd/SKILL.md | awk '/^version:/{print $2}')"
echo "context SKILL.md:   $(head -20 skills/context/SKILL.md  | awk '/^version:/{print $2}')"
echo "README:             $(grep -E '^\\*\\*Version\\*\\*' README.md 2>/dev/null || echo '(no version banner)')"
echo "CHANGELOG latest:   $(grep -E '^## v' CHANGELOG.md | head -1)"
```

- [ ] **Step C2.2: Bring all to 5.1.7**

Any file showing < 5.1.7 → edit. Use `sed -i.bak 's/5\.1\.6/5.1.7/g' <file> && rm <file>.bak` per file, then visually verify (don't blanket-replace across the repo; only the version-source-of-truth files).

- [ ] **Step C2.3: Write CHANGELOG entry**

Prepend a new section to `CHANGELOG.md` (after the title, before existing v5.1.6 entry):

```markdown
## v5.1.7 — 2026-05-20

### SQLite-canonical operational state

Architectural shift: `.artifacts/root.db` becomes canonical for ephemeral
operational state (teammate liveness, heartbeats, mailbox, escalations,
deliverables, structured discovery/audit findings). Markdown reports are
materialized views over rows. File-canonical store is reserved for
human-authored durable artifacts (specs, plans, seeds, agent profiles,
doctrines, CHANGELOG, README).

#### Schema (Lane A1)
- New migration `0007_canonical_state.sql` adds 7 tables + 3 views:
  `teammates`, `heartbeats`, `mailbox`, `escalations`, `deliverables`,
  `discovery_findings`, `audit_findings`. Additive — no existing tables
  altered. WAL mode preserved.

#### Doctrine (Lane A2)
- New `doctrines/sqlite-canonical-state.md` — binding rule + allow-list
  + anti-patterns + migration guidance.

#### shctx surface (Lanes A3, A4)
- New subcommands: `shctx teammate {register,heartbeat,status,liveness,
  prune,retire}`, `shctx mailbox {send,recv,ack,stale}`, `shctx escalate
  {create,list,resolve}`, `shctx deliverable {promise,complete,stalled}`,
  `shctx report <kind>`.
- Extended: `shctx discovery insert`, `shctx audit insert`.
- Tests under `skills/context/tests/test_cmd_*.sh` + `test_schema_0007.sh`.

#### Agent profile amendments (Lanes B1, B2)
- `agents/discovery.md`: row-write Hard Prohibition (closes #43)
- `agents/critic.md`: deliverable promise/complete contract (closes #52)
- `agents/auditor.md`: deliverable contract + intro-mode [gates].extra (closes #52, #44)
- `agents/conductor.md`: cargo discipline section (closes #50)
- `agents/shepherd.md`: TEAMMATE-CRASHED halt + crashed-teammate detection (closes #49)
- `commands/spawn.md`: cargo discipline block injected into conductor brief

#### New command (Lane B3)
- `/shepherd:cleanup` — prune stale/crashed teammates from canonical state (closes #51)

#### Hook integration (Lane B4)
- `hooks/subagent_telemetry.sh`: extended to emit teammate heartbeats
- `hooks/teammate_idle.sh`: new TeammateIdle hook
- `hooks/deliverable_check.sh`: new Stop hook auto-marks stalled deliverables

#### Triage (Lane W1, W2)
- 22 old issues #18–#39 triaged (superseded / still-valid / close-as-stale)
- #45 (v5.1.6 dispatch-tier separation) verified in tree
- #46 (upstream Claude Code #31977) confirmed handled via [WARN] preflight

### Known gaps / deferred to v5.2.0+
- #47 cross-patch `--scope=minor/version` enumeration
- #53 SendMessage `heartbeat_payload` first-class runtime primitive
  (shctx infrastructure ready; upstream-dependent)
- #54 per-package feature-coverage CI gate (axiom-specific, ships as
  doctrine guidance)
```

- [ ] **Step C2.4: Verify all in sync**

```bash
for f in .claude-plugin/plugin.json .claude-plugin/marketplace.json \
         skills/shepherd/SKILL.md skills/context/SKILL.md; do
  grep -c "5.1.7" "$f" || true
done
grep -c "^## v5.1.7" CHANGELOG.md
```

All non-zero, all == 5.1.7.

- [ ] **Step C2.5: Commit**

```bash
git add -p .claude-plugin/plugin.json .claude-plugin/marketplace.json \
           skills/shepherd/SKILL.md skills/context/SKILL.md \
           README.md CHANGELOG.md
# OR (if no partial adds needed):
git add .claude-plugin/{plugin,marketplace}.json \
        skills/{shepherd,context}/SKILL.md \
        CHANGELOG.md
# Add README only if it changed:
git diff --quiet README.md || git add README.md
git commit -m "chore(v5.1.7): version + CHANGELOG sync

All 6 version-source-of-truth files aligned at v5.1.7.
CHANGELOG entry covers the canonicalization shift + per-issue
close summary (closes #43, #44, #49, #50, #51, #52; verifies #45, #46;
defers #47, #53, #54 to v5.2.0+)."
```

---

## Final: Run full test suite, push, PR

- [ ] **Step F1: Run all v5.1.7 tests**

```bash
bash skills/context/tests/test_schema_0007.sh
bash skills/context/tests/test_cmd_teammate.sh
bash skills/context/tests/test_cmd_mailbox.sh
bash skills/context/tests/test_cmd_escalate.sh
bash skills/context/tests/test_cmd_deliverable.sh
bash skills/context/tests/test_cmd_report.sh
```

All must PASS. Also run pre-existing test suite (if `skills/context/tests/run.sh` exists):

```bash
[[ -x skills/context/tests/run.sh ]] && bash skills/context/tests/run.sh
```

- [ ] **Step F2: Final acceptance grep sweep**

```bash
# Doctrine cited from all amended agent profiles
for f in agents/{discovery,critic,auditor,conductor,shepherd}.md; do
  grep -q "doctrines/sqlite-canonical-state.md" "$f" || { echo "FAIL doctrine cite in $f"; exit 1; }
done

# /shepherd:cleanup registered
test -f commands/cleanup.md
grep -q "/shepherd:cleanup" skills/shepherd/SKILL.md

# Hooks present and executable
for h in teammate_idle deliverable_check; do
  test -x "skills/context/scripts/hooks/${h}.sh" || { echo "FAIL hook $h"; exit 1; }
done

# All version sources aligned
ver=$(jq -r '.version' .claude-plugin/plugin.json)
[[ "$ver" == "5.1.7" ]] || { echo "FAIL plugin.json version: $ver"; exit 1; }

echo "FINAL ACCEPTANCE: PASS"
```

- [ ] **Step F3: Push branch + open PR**

```bash
git push -u origin v5.1.7
```

Then open PR:

```bash
gh pr create --title "v5.1.7" --body "$(cat <<'EOF'
## Summary

- Schema migration 0007: SQLite-canonical operational state (7 tables, 3 views)
- New doctrine `sqlite-canonical-state.md` — binding rule + allow-list
- New shctx subcommands: teammate, mailbox, escalate, deliverable, report (+ discovery/audit insert)
- Agent profile amendments closing the v5.1.5/v5.1.6 defect cluster
- New `/shepherd:cleanup` command (closes #51)
- Hook integration: heartbeat, idle, deliverable-check

## Closes

#43, #44, #49, #50, #51, #52

## Verifies (recommends close)

#45 (v5.1.6 dispatch-tier separation in tree)
#46 (upstream Claude Code #31977 — handled via [WARN] preflight)

## Defers to v5.2.0+

#47, #53, #54

## Triage

22 old issues #18–#39 triaged with one comment each.

## Test plan

- [x] bash skills/context/tests/test_schema_0007.sh
- [x] bash skills/context/tests/test_cmd_*.sh (5 tests)
- [x] grep sweep for doctrine cites, command registration, version alignment
- [ ] Operator reviews triage report + close-audit before merging
EOF
)"
```

---

## Self-Review

**Spec coverage check.** Every spec requirement maps to a task:
- Schema → A1 ✓
- Doctrine → A2 ✓
- shctx subcommands (teammate/mailbox/escalate/deliverable/report) → A3 ✓
- shctx insert subcommands (discovery/audit) → A4 ✓
- Agent profile amendments (discovery/critic/auditor) → B1 ✓
- Agent profile amendments (conductor/shepherd/spawn) → B2 ✓
- /shepherd:cleanup command → B3 ✓
- Hook integration → B4 ✓
- Old-issue triage → W1 ✓
- v5.1.6 fix verification → W2 ✓
- Close audit swarm → C1 ✓
- Version + CHANGELOG sync → C2 ✓

**Placeholder scan.** Searched for "TBD", "TODO", "implement later", "similar to". One intentional template `<SCHEMA-BODY-FROM-SPEC>` in A1.4 — engineer copies the SQL from the spec verbatim, this is a deliberate cross-reference not a placeholder.

**Type consistency.** `shctx <sub>` naming is consistent across all tasks. Table column names match between schema (A1) and CRUD wrappers (A3, A4) and report materializers (A3.11). Hook script paths are consistent.

**Plan complete.** Saved to `.artifacts/docs/plans/2026-05-20-v517-canonical-state.plan.md`.
