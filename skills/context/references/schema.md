# Schema reference — `schema/0001_init.sql` + migrations

Per-project SQLite registry; `0001_init.sql` is the baseline, migrations
`0002`+ layer on top. WAL mode, FK enforcement on.
Every non-`projects` table carries `project_id TEXT NOT NULL REFERENCES
projects(id) ON DELETE CASCADE ON UPDATE CASCADE`. `unixepoch()` integers
throughout. Every JSON1 column carries `CHECK(json_valid(...))`.

---

## Backbone

- **`projects`** — one row per consumer project; inserted by `shctx init`, UUIDv7
  `id` persisted to `.shepherd/project.json` (legacy `.artifacts/project.json`).
  `name`, `scope` (JSON array of dirs/repos/domains), `metadata` (nullable JSON),
  `tags` (JSON array), `created_at`/`updated_at`.
- **`schema_versions`** — migration tracking: `version INTEGER PK`, `applied_at`,
  `checksum` (SHA256 of the migration file). Every applied migration writes one row.
- **`sessions`** — Claude session log, written on first agent dispatch: `id TEXT PK`
  (session ID or UUIDv7), `project_id` (FK), `started_at`/`ended_at` (end
  nullable), `agent_role` (`conductor|engineer|coder|...`), `sprint_branch`,
  nullable JSON `metadata`. Index: `idx_sessions_project_branch(project_id,
  sprint_branch)`.

---

## Profiles (canonical)

### `profiles_defs`

Behavior overlays, TOML-backed, DB-queried. `id` (UUIDv7 PK), `project_id` (FK),
`name` (unique per project), `kind` — CHECK `'modifier' | 'extension' |
'override'`, `config` (JSON), `source_path` (TOML path if synced), `active`
(0/1), `created_at`/`updated_at`. Constraint: `UNIQUE(project_id, name)`. See
`references/profiles.md` for the kind taxonomy.

---

## Memories (canonical) — replaces external `remember` plugin

### `mem_entries`

`id` (UUIDv7 PK), `project_id` (FK), `kind` — CHECK `'doctrine' | 'note' |
'decision' | 'incident' | 'session'`, `title`/`body`, `tags` (JSON array),
`pinned` (0/1), `source_path` (optional pointer to backing markdown),
`created_at`/`updated_at`. Indexes: `idx_mem_project_kind(project_id, kind)`,
`idx_mem_project_pinned(project_id, pinned) WHERE pinned = 1`.

`remember`-equivalent mapping: `now.md` → `sessions` + `tmp/session-{id}.jsonl`;
`today-*.md` → `logs/events-YYYY-MM-DD.jsonl` + `docs/journal/YYYY-MM-DD.md`;
`recent.md` → view `v_mem_recent_7d`; `archive.md` → rows older than 30 days;
`core-memories.md` → `kind='doctrine' AND pinned=1`.

---

## Index tables (cache zone — rebuildable)

### `index_symbols`

Code symbols. Rust via `cargo metadata` + `syn`; other languages via tree-sitter
(or skipped). Replaces hand-maintained `canonical-types.md`.

`id` (UUIDv7 PK), `project_id` (FK), `name` (e.g. `DriftCircuit`), `kind` —
`'struct' | 'trait' | 'fn' | 'enum' | 'const' | 'mod' | 'class' | 'def' | ...`,
`package` (e.g. `crates/circuits`), `file_path`/`line`, `visibility` — `'pub' |
'pub(crate)' | 'private' | 'export' | ...`, `signature`/`doc_summary`,
`language`, `hash` (content hash of declaration line + signature),
`refreshed_at`. Constraints: `UNIQUE(project_id, name, package, kind)`. Indexes:
`idx_symbols_project_name`, `idx_symbols_project_pkg`.

### `index_concepts`

The dedup index — "Drift detection -> `DriftCircuit`; AVOID `DriftDetector`,
`DriftHandler`". Columns: `id` (PK), `project_id` (FK), `concept TEXT NOT NULL`,
`canonical_symbol_id` (FK → `index_symbols(id)`), `aliases_to_avoid TEXT DEFAULT
'[]'` (JSON array), `notes TEXT`. Constraint: `UNIQUE(project_id, concept)`.

### `index_issues`, `index_prs`, `index_releases`, `index_milestones`

GitHub state caches, refreshed via `shctx refresh --scope=github` (uses `gh`). All
four carry `source`, `refreshed_at`, and indexes on `(project_id, state)` or
`(project_id, source, ...)`.

- `index_issues` — `id = 'github:owner/repo#NNN'`; `state ∈ {'open','closed'}`.
- `index_prs` — `state ∈ {'open','closed','merged'}`; `base_branch`, `head_branch`.
- `index_releases` — `tag`, `prerelease`/`draft`, `published_at`.
  `UNIQUE(project_id, source, tag)`.
- `index_milestones` — `number`, `title`, `state`, `due_on`.
  `UNIQUE(project_id, source, number)`.

### `index_cache_usage` (migration `0006_cache_telemetry.sql`)

One row per subagent dispatch — cache zone, rebuildable from the JSONL event
log. Backs the completeness auditor's verification that the brief-cache-
discipline ordering rule produces real cache-read wins.

`id` (autoinc PK), `project_id` (FK), `ts`/`session_id`/`agent_id`/`sprint`
(dispatch identity), `role` — `engineer|critic|coder|auditor|worker|
discovery|unknown`, `turns` (assistant turns observed), `input_tokens`/
`output_tokens`, `cache_read_input_tokens`/`cache_creation_input_tokens`,
`ephemeral_5m_input_tokens`/`ephemeral_1h_input_tokens` (cache-creation
subsets by TTL), `hit_rate` — `cache_read / (cache_read + cache_creation +
input)`, NULL when undefined, `parse_error` (nullable; set when the hook
could not aggregate). Constraint: `UNIQUE(session_id, agent_id, ts)` — makes
`shctx refresh --scope=telemetry` idempotent via `INSERT OR IGNORE`. Indexes:
`idx_cache_usage_sprint`, `idx_cache_usage_role_ts`.

**View `v_cache_usage`** — per-sprint × role rollup: `dispatches`,
`avg_hit_rate`, `total_input`, `total_cache_read`, `total_cache_creation`,
`avg_first_turn_creation` (single-turn-dispatch cache-creation average, the
cleanest proxy for cacheable system-prefix size per role). Filters
`parse_error IS NULL` so degraded rows never pollute the auditor's aggregate.

---

## Logs (cache zone)

### `logs_events`

Last 10K events; rotates to `logs/events-YYYY-MM-DD.jsonl` on overflow.
`id` (autoinc PK), `project_id` (FK), `ts`, `level` — CHECK `'info' | 'warn' |
'error' | 'gate' | 'audit'`, `source` (`'conductor' | 'engineer' | ...`),
`event` (`'dispatch' | 'gate-pass' | 'dedup-block' | ...`), `payload` (nullable
JSON), `sprint_branch`/`session_id`. Index: `idx_logs_project_ts(project_id,
ts)`. Past 10K rows per project, the oldest 1K flush to that day's JSONL and
are deleted.

---

## Artifacts (canonical pointer)

### `artifacts`

Filesystem-pointer table; markdown remains canonical content, the DB indexes
it. `id` (UUIDv7 PK), `project_id` (FK), `kind` — `'seed' | 'plan' | 'phase0' |
'close' | 'walk' | 'handoff' | 'spec' | 'design' | 'diagram' | 'journal'`,
`path` (relative to repo root), `sprint_branch`/`title`, `hash` (recomputed by
`refresh --scope=artifacts`; mismatch surfaces as drift in `status`),
`created_at`/`updated_at`. Constraint: `UNIQUE(project_id, path)`. Indexes:
`idx_artifacts_project_kind`, `idx_artifacts_sprint`.

---

## Locks (canonical audit trail)

### `locks_history`

The live lock is `.shepherd/shepherd.lock` (`flock(2)`; legacy
`.artifacts/shepherd.lock`); this table records acquisition/release events.
Autoinc `id`, `project_id` (FK), `session_id`, `mode` — CHECK
`{'autorun','parallel','start','plant','context'}`, `acquired_at`/
`released_at` (release nullable), `released_by` — CHECK
`{'normal','reap','force'}`, nullable JSON `metadata`.

---

## Sprint metadata (NOT IMPLEMENTED)

`sprints_runs`, `sprints_lanes`, `sprints_findings`, `sprints_stage_graph` were
planned but never implemented. Migration `0003` is `0003_canonical_types_filter.sql`
— no `0003_sprints.sql` exists. The `sprints_*` tables do NOT exist at any current
migration level; do not reference them.

---

## Operational state (migration `0007_canonical_state.sql`)

Seven tables, all canonical — not recoverable from source, persistence
required.

- **`teammates`** — one row per spawned teammate-conductor: `sprint_branch`,
  `lane_id`, `session_id`, `status` — CHECK `{'active','idle','completed',
  'crashed','removed'}`, `task_id`, `spawned_at`, `last_heartbeat_at`,
  `metadata`. Index: `idx_teammates_sprint_lane`.
- **`heartbeats`** — `teammate_id` (FK), `ts`, `status`, `payload`. Index:
  `idx_heartbeats_teammate_ts`.
- **`mailbox`** — SendMessage envelopes: `from_session`, `to_session`,
  `message_type`, `payload`, `sent_at`, `delivered_at`, `ack_at`. Index:
  `idx_mailbox_to_session`.
- **`escalations`** — `teammate_id` (FK), `halt_code`, `tier` — CHECK
  `{'CRITICAL','BLOCKING','NOTIFY'}`, `payload`, `raised_at`, `resolved_at`,
  `resolved_by`, `resolution`. Index: `idx_escalations_project_open ...
  WHERE resolved_at IS NULL`.
- **`deliverables`** — `teammate_id` (FK), `kind` — CHECK `{'artifact',
  'carry-forward','wave-complete','close'}`, `payload`, `submitted_at`,
  `materialized_at`, `materialized_by`. Index: `idx_deliverables_teammate_kind`.
- **`discovery_findings`** / **`audit_findings`** — same shape:
  `sprint_branch`, `lane_id`, `severity` — CHECK `{'CRITICAL','HIGH','MEDIUM',
  'LOW'}`, `title`, `body`, `source_file`, `gh_issue_id`, `filed_at`;
  `audit_findings` adds `concern` (`code-quality`, `data-flow`,
  `dependency-topology`, `datastore-state`, `completeness`, `regression`).

Views: `v_active_teammates` (`status IN ('active','idle')`),
`v_open_escalations` (`resolved_at IS NULL`), `v_pending_deliverables`
(`materialized_at IS NULL`).

---

## Eval store (migration `0018_eval_runs.sql`)

### `eval_runs`

One row per quality eval of a latent agent output (a reflection, a discovery
report, a seed, …). Written by `shctx eval run --record`: builds a judge
prompt from a rubric, routes it through the local-Claude-Code LLM service,
parses per-dimension scores, computes a deterministic overall score against
the rubric threshold. The judge's per-dimension scores are latent; the
prompt build, the weighted overall, and the threshold verdict are
deterministic.

`id` (UUIDv7 PK), `project_id` (FK), `kind` (rubric kind:
`reflection|discovery|seed|...`), `subject_ref` (what was scored — sprint
branch, mem id, path), `score` (overall 0-100, weighted, deterministic),
`threshold` (pass line in force at run time), `passed` — CHECK `IN (0,1)`,
`model` (judge model alias), `scores_json` (per-dimension `{dim: 1..scale}`;
`CHECK(json_valid(...))`), `rationale` (judge's one-line justification),
`created_at`. Index: `idx_eval_runs_project(project_id, kind, created_at
DESC)`.

**View `v_eval_latest`** — one row per `(project_id, kind, subject_ref)`: the
latest run, tie-broken `created_at DESC, id DESC` (uuid7 `id` is
time-prefixed, so the later run wins the tiebreak too). This is the row the
dash and `shctx eval report` read. Empty store ⇒ unchanged behavior
everywhere.

---

## Views (`schema/views/*.sql` + inline in `0001_init.sql`)

| View | Definition (paraphrased) |
|---|---|
| `v_open_issues` | Open issues, `updated_at DESC` — Phase 0 ledger sweep. |
| `v_canonical_types` | Public `index_symbols` joined to `index_concepts`; visibility filter `IN ('pub','pub(crate)','export')`. Replaces `canonical-types.md`. |
| `v_drift_risk` | Open issues whose `labels` JSON contains `"critical"` or `"high"`. |
| `v_mem_recent_7d` | `mem_entries` from last 7 days OR `pinned = 1`. |
| `v_active_locks` | `locks_history WHERE released_at IS NULL`. |

**Parameterized queries** (`queries/*.sql`, bind at call time — SQLite views take
no parameters): `dedup-check.sql` (`WHERE name = :name AND project_id =
:project_id` — backs `shctx query dedup-check`, DEDUP-GATE Layer 2);
`open-issues.sql`, `open-prs.sql`, `canonical-types.sql`, `drift-risk.sql`,
`mem-search.sql`, `recent-releases.sql`.

## JSON1 query patterns

Array containment: `labels LIKE '%"critical"%'` (used in `v_drift_risk`) — prefer
`LIKE` over `json_each()` for flat-array membership tests. Object access:
`json_extract(col, '$.path')`. Validity guards
(`CHECK(<col> IS NULL OR json_valid(<col>))`) reject mis-shaped writes at
`INSERT` time.
