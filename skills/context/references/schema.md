# Schema reference — `schema/0001_init.sql`

Per-project SQLite registry, shepherd v5.0.0 baseline. WAL mode, FK enforcement on. Every non-`projects` table carries `project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE`.

`unixepoch()` integers throughout (seconds since epoch). JSON1 used for array/object columns; every JSON column has a `CHECK(json_valid(...))` constraint.

---

## Backbone

### `projects`

One row per consumer project. Inserted by `shctx init`; UUIDv7 persisted to `.shepherd/project.json` (legacy: `.artifacts/project.json` for projects initialized with `--artifacts`).

| Column | Type | Notes |
|---|---|---|
| `id` | `TEXT PRIMARY KEY` | UUIDv7 (sortable, time-prefixed). |
| `name` | `TEXT NOT NULL DEFAULT ''` | Display name. |
| `scope` | `TEXT NOT NULL DEFAULT '[]'` | JSON array of dirs/repos/domains. |
| `metadata` | `TEXT` | Nullable JSON object. |
| `tags` | `TEXT NOT NULL DEFAULT '[]'` | JSON array. |
| `created_at`, `updated_at` | `INTEGER NOT NULL` | unixepoch. |

### `schema_versions`

Migration tracking. Columns: `version INTEGER PK` (ordinal), `applied_at INTEGER` (unixepoch), `checksum TEXT` (SHA256 of migration file). Every applied migration writes one row.

### `sessions`

Claude session log. Written on first agent dispatch. Columns: `id TEXT PK` (Claude session ID or UUIDv7), `project_id` (FK), `started_at`/`ended_at INTEGER` (end nullable), `agent_role TEXT` (`conductor|engineer|coder|...`), `sprint_branch TEXT`, nullable JSON `metadata`. Index: `idx_sessions_project_branch(project_id, sprint_branch)`.

---

## Profiles (canonical)

### `profiles_defs`

Pluggable behavior overlays. TOML-backed, DB-queried.

| Column | Type | Notes |
|---|---|---|
| `id` | `TEXT PRIMARY KEY` | UUIDv7. |
| `project_id` | FK | |
| `name` | `TEXT NOT NULL` | Unique per project. |
| `kind` | `TEXT NOT NULL` | CHECK: `'modifier' \| 'extension' \| 'override'`. |
| `config` | `TEXT NOT NULL` | JSON object. |
| `source_path` | `TEXT` | Filesystem TOML path if synced. |
| `active` | `INTEGER NOT NULL DEFAULT 1` | 0/1. |
| `created_at`, `updated_at` | `INTEGER NOT NULL` | |

Constraint: `UNIQUE(project_id, name)`. See `references/profiles.md` for the kind taxonomy.

---

## Memories (canonical) — replaces external `remember` plugin

### `mem_entries`

| Column | Type | Notes |
|---|---|---|
| `id` | `TEXT PRIMARY KEY` | UUIDv7. |
| `project_id` | FK | |
| `kind` | `TEXT NOT NULL` | CHECK: `'doctrine' \| 'note' \| 'decision' \| 'incident' \| 'session'`. |
| `title`, `body` | `TEXT NOT NULL` | |
| `tags` | `TEXT NOT NULL DEFAULT '[]'` | JSON array. |
| `pinned` | `INTEGER NOT NULL DEFAULT 0` | 0/1. |
| `source_path` | `TEXT` | Optional pointer to backing markdown. |
| `created_at`, `updated_at` | `INTEGER NOT NULL` | |

Indexes: `idx_mem_project_kind(project_id, kind)`, `idx_mem_project_pinned(project_id, pinned) WHERE pinned = 1`.

`remember`-equivalent mapping: `now.md` → `sessions` + `tmp/session-{id}.jsonl`; `today-*.md` → `logs/events-YYYY-MM-DD.jsonl` + `docs/journal/YYYY-MM-DD.md`; `recent.md` → view `v_mem_recent_7d`; `archive.md` → rows older than 30 days; `core-memories.md` → `kind='doctrine' AND pinned=1`.

---

## Index tables (cache zone — rebuildable)

### `index_symbols`

Code symbols. Rust extraction via `cargo metadata` + `syn`; other languages via tree-sitter (or skipped). Replaces hand-maintained `canonical-types.md`.

| Column | Type | Notes |
|---|---|---|
| `id` | `TEXT PRIMARY KEY` | UUIDv7. |
| `project_id` | FK | |
| `name` | `TEXT NOT NULL` | e.g. `DriftCircuit`. |
| `kind` | `TEXT NOT NULL` | `'struct' \| 'trait' \| 'fn' \| 'enum' \| 'const' \| 'mod' \| 'class' \| 'def' \| ...` |
| `package` | `TEXT NOT NULL` | e.g. `crates/circuits` or `src/auth`. |
| `file_path`, `line` | `TEXT, INTEGER` | |
| `visibility` | `TEXT` | `'pub' \| 'pub(crate)' \| 'private' \| 'export' \| ...` |
| `signature`, `doc_summary` | `TEXT` | |
| `language` | `TEXT NOT NULL` | |
| `hash` | `TEXT NOT NULL` | Content hash (declaration line + signature). |
| `refreshed_at` | `INTEGER NOT NULL` | |

Constraints: `UNIQUE(project_id, name, package, kind)`. Indexes: `idx_symbols_project_name`, `idx_symbols_project_pkg`.

### `index_concepts`

The dedup index — "Drift detection -> `DriftCircuit`; AVOID `DriftDetector`, `DriftHandler`". Columns: `id` (PK), `project_id` (FK), `concept TEXT NOT NULL`, `canonical_symbol_id` (FK → `index_symbols(id)`), `aliases_to_avoid TEXT DEFAULT '[]'` (JSON array), `notes TEXT`. Constraint: `UNIQUE(project_id, concept)`.

### `index_issues`, `index_prs`, `index_releases`, `index_milestones`

GitHub state caches. Refreshed via `shctx refresh --scope=github` (uses `gh`). All four carry `source`, `refreshed_at`, JSON `labels`-style arrays where applicable, and per-table indexes on `(project_id, state)` or `(project_id, source, ...)`.

- `index_issues` — `id = 'github:owner/repo#NNN'`; `state ∈ {'open','closed'}`; nullable `body`; indexes on `(project_id, state)` and `(project_id, milestone)`.
- `index_prs` — `state ∈ {'open','closed','merged'}`; `base_branch`, `head_branch`, `merged_at`.
- `index_releases` — `tag`, booleans `prerelease`/`draft`, `published_at`. `UNIQUE(project_id, source, tag)`.
- `index_milestones` — `number`, `title`, `state`, `due_on`, `description`. `UNIQUE(project_id, source, number)`.

---

## Logs (cache zone)

### `logs_events`

Last 10K events; rotates to `logs/events-YYYY-MM-DD.jsonl` on overflow.

| Column | Type | Notes |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | |
| `project_id` | FK | |
| `ts` | `INTEGER NOT NULL` | unixepoch. |
| `level` | `TEXT NOT NULL` | CHECK: `'info' \| 'warn' \| 'error' \| 'gate' \| 'audit'`. |
| `source` | `TEXT NOT NULL` | `'conductor' \| 'engineer' \| ...` |
| `event` | `TEXT NOT NULL` | `'dispatch' \| 'gate-pass' \| 'dedup-block' \| ...` |
| `payload` | `TEXT` | Nullable JSON. |
| `sprint_branch`, `session_id` | `TEXT` | |

Index: `idx_logs_project_ts(project_id, ts)`. When the per-project row count exceeds 10K, the oldest 1K are flushed to that day's JSONL and deleted.

---

## Artifacts (canonical pointer)

### `artifacts`

Filesystem-pointer table. Markdown remains canonical content; the DB indexes it.

| Column | Type | Notes |
|---|---|---|
| `id` | `TEXT PRIMARY KEY` | UUIDv7. |
| `project_id` | FK | |
| `kind` | `TEXT NOT NULL` | `'seed' \| 'plan' \| 'phase0' \| 'close' \| 'walk' \| 'handoff' \| 'spec' \| 'design' \| 'diagram' \| 'journal'`. |
| `path` | `TEXT NOT NULL` | Relative to repo root. |
| `sprint_branch`, `title` | `TEXT` | |
| `hash` | `TEXT NOT NULL` | Recomputed during `refresh --scope=artifacts`; mismatch surfaces as drift in `status`. |
| `created_at`, `updated_at` | `INTEGER NOT NULL` | |

Constraint: `UNIQUE(project_id, path)`. Indexes: `idx_artifacts_project_kind`, `idx_artifacts_sprint`.

---

## Locks (canonical audit trail)

### `locks_history`

The live lock is `.shepherd/shepherd.lock` (file-locked via `flock(2)`; legacy: `.artifacts/shepherd.lock`); this table records acquisition/release events. Columns: autoinc `id`, `project_id` (FK), `session_id TEXT NOT NULL`, `mode` CHECK in `{'autorun','parallel','start','plant','context'}`, `acquired_at`/`released_at INTEGER` (release nullable), `released_by` CHECK in `{'normal','reap','force'}`, nullable JSON `metadata`.

---

## Sprint metadata (NOT IMPLEMENTED — deferred)

`sprints_runs`, `sprints_lanes`, `sprints_findings`, `sprints_stage_graph` were planned but never implemented. The referenced migration `0003_sprints.sql` does not exist (migration 0003 is `0003_canonical_types_filter.sql`). The `sprints_*` tables do not exist and are not expected at any current migration level.

---

## Operational state (v5.1.7+)

Seven tables added by migration `0007_canonical_state.sql` (in `schema/migrations/`). All are canonical — not recoverable from source; persistence required.

### `teammates`

One row per spawned teammate-conductor. Columns: `id TEXT PK` (UUIDv7), `project_id` (FK), `sprint_branch TEXT NOT NULL`, `lane_id TEXT NOT NULL`, `session_id TEXT`, `status TEXT NOT NULL` CHECK in `{'active','idle','completed','crashed','removed'}`, `task_id TEXT`, `spawned_at INTEGER NOT NULL`, `last_heartbeat_at INTEGER`, `metadata TEXT` (JSON). Index: `idx_teammates_sprint_lane(project_id, sprint_branch, lane_id)`.

### `heartbeats`

Periodic liveness signals from active teammates. Columns: `id INTEGER PK AUTOINCREMENT`, `project_id` (FK), `teammate_id TEXT NOT NULL` (FK → `teammates`), `ts INTEGER NOT NULL`, `status TEXT`, `payload TEXT` (JSON). Index: `idx_heartbeats_teammate_ts(teammate_id, ts)`.

### `mailbox`

SendMessage envelope store. Columns: `id TEXT PK` (UUIDv7), `project_id` (FK), `from_session TEXT NOT NULL`, `to_session TEXT NOT NULL`, `message_type TEXT NOT NULL`, `payload TEXT NOT NULL` (JSON), `sent_at INTEGER NOT NULL`, `delivered_at INTEGER`, `ack_at INTEGER`. Index: `idx_mailbox_to_session(to_session, delivered_at)`.

### `escalations`

Halt-code escalations from teammate-conductors to root. Columns: `id TEXT PK` (UUIDv7), `project_id` (FK), `teammate_id TEXT NOT NULL` (FK → `teammates`), `halt_code TEXT NOT NULL`, `tier TEXT NOT NULL` CHECK in `{'CRITICAL','BLOCKING','NOTIFY'}`, `payload TEXT` (JSON), `raised_at INTEGER NOT NULL`, `resolved_at INTEGER`, `resolved_by TEXT`, `resolution TEXT`. Index: `idx_escalations_project_open(project_id, resolved_at) WHERE resolved_at IS NULL`.

### `deliverables`

Structured payload returns from teammate-conductors (artifact writes, carry-forward, etc.). Columns: `id TEXT PK` (UUIDv7), `project_id` (FK), `teammate_id TEXT NOT NULL` (FK → `teammates`), `kind TEXT NOT NULL` CHECK in `{'artifact','carry-forward','wave-complete','close'}`, `payload TEXT NOT NULL` (JSON), `submitted_at INTEGER NOT NULL`, `materialized_at INTEGER`, `materialized_by TEXT`. Index: `idx_deliverables_teammate_kind(teammate_id, kind)`.

### `discovery_findings`

Findings emitted by `@discovery` lanes. Columns: `id TEXT PK` (UUIDv7), `project_id` (FK), `sprint_branch TEXT NOT NULL`, `lane_id TEXT`, `severity TEXT NOT NULL` CHECK in `{'CRITICAL','HIGH','MEDIUM','LOW'}`, `title TEXT NOT NULL`, `body TEXT NOT NULL`, `source_file TEXT`, `gh_issue_id TEXT`, `filed_at INTEGER NOT NULL`. Index: `idx_discovery_sprint_severity(project_id, sprint_branch, severity)`.

### `audit_findings`

Findings emitted by `@auditor` lanes. Same column set as `discovery_findings` with an additional `concern TEXT NOT NULL` (auditor concern type: `code-quality`, `data-flow`, `dependency-topology`, `datastore-state`, `completeness`, `regression`). Index: `idx_audit_sprint_concern(project_id, sprint_branch, concern)`.

### Views added by `0007_canonical_state.sql`

| View | Definition (paraphrased) |
|---|---|
| `v_active_teammates` | `teammates WHERE status IN ('active','idle') ORDER BY spawned_at ASC` |
| `v_open_escalations` | `escalations WHERE resolved_at IS NULL ORDER BY raised_at ASC` |
| `v_pending_deliverables` | `deliverables WHERE materialized_at IS NULL ORDER BY submitted_at ASC` |

---

## Views (`schema/views/*.sql` and inline in `0001_init.sql`)

Bundled so skills don't ship raw SQL templates.

| View | Definition (paraphrased) |
|---|---|
| `v_open_issues` | `SELECT … FROM index_issues WHERE state = 'open' ORDER BY updated_at DESC` — Phase 0 ledger sweep. |
| `v_canonical_types` | Public `index_symbols` joined to `index_concepts`; ordered by `(package, name)`. Visibility filter: `IN ('pub','pub(crate)','export')`. Replaces `canonical-types.md`. |
| `v_drift_risk` | Open issues whose `labels` JSON contains `"critical"` or `"high"` (string LIKE on JSON text — fast and correct under JSON1 conventions). |
| `v_mem_recent_7d` | `mem_entries` from last 7 days OR `pinned = 1`; ordered `pinned DESC, created_at DESC`. |
| `v_active_locks` | `locks_history WHERE released_at IS NULL ORDER BY acquired_at DESC`. |

### Parameterized queries

SQLite views can't take parameters. Parameterized queries live in `queries/*.sql` and bind at call time via the wrapper:

- `queries/dedup-check.sql` — `WHERE name = :name AND project_id = :project_id`. Backs `shctx query dedup-check --name=<symbol>` (DEDUP-GATE Layer 2).
- `queries/open-issues.sql`, `queries/open-prs.sql`, `queries/canonical-types.sql`, `queries/drift-risk.sql`, `queries/mem-search.sql`, `queries/recent-releases.sql` — wrappers around the views with optional filter args (`--milestone`, `--label`, `--kind`, `--since`).

---

## JSON1 query patterns

JSON1 is on by default in modern SQLite builds. The schema uses it for: array containment via `labels LIKE '%"critical"%'` (used in `v_drift_risk`); object access via `json_extract(col, '$.path')`; and validity guards (`CHECK(<col> IS NULL OR json_valid(<col>))`) that fail mis-shaped writes at `INSERT` time. Prefer LIKE over `json_each()` for membership tests on flat string arrays.
