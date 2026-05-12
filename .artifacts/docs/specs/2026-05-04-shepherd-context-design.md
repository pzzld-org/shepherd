# Shepherd Context Registry — Design Spec

| Field | Value |
|---|---|
| Spec ID | `2026-05-04-shepherd-context` |
| Status | **Approved for implementation** |
| Author | FL03 (operator) + conductor (Opus 4.7, brainstorming session) |
| Date | 2026-05-04 |
| Plugin | `plugins/shepherd` |
| Target version | `v5.0.0` (MAJOR — closed-flock contract change) |
| Target branch | `v5.0.0-dev.0` (cut at implementation start) |
| Phasing | Milestone (c) ships in `v5.0.0-dev.0..N`; milestone (d) ships in `v5.0.0-dev.{N+1}..` |

---

## 1. Problem statement

Shepherd's flock currently re-derives context every sprint:

- The engineer's Phase 0 mesh re-runs the same MCP/CLI queries every sprint and writes a fresh markdown report.
- The conductor's DEDUP-GATE relies on hand-typed `[DO-NOT-DUPLICATE]` greps populated by the engineer per lane.
- `{paths.ctx}/canonical-types.md` is the workspace's authoritative type catalog but is hand-maintained markdown — it goes stale, the engineer skips it, the auditor catches the drift after the duplicate has shipped.
- Cross-sprint state (grade history, chronic-deferral counts, stage-graph walk traces) is reconstructed from `.artifacts/reports/*.md` files at sprint open via filesystem walks.
- Project memories live in an external plugin (`remember`) with its own `.remember/` directory, hooks, and Python scripts — one more system to maintain.

**Operator's bar (verbatim from `doctrines/zero-duplicate-tolerance.md`):** *"If I see another line of duplicate code I will uninstall Claude Code immediately."* The current model is markdown-as-truth, which scales poorly past ~15 packages or ~5 sprints of accumulated context.

**Goal:** introduce a per-project SQLite registry as the single queryable source of context, replace `canonical-types.md` with structured rows, fold sprint metadata into the same store, and absorb the memory/journal surface so shepherd is self-contained.

## 2. Non-goals

- Not building a new MCP server. The DB is queried by agents via `sqlite3` CLI and the bundled `shctx` shell wrapper.
- Not rewriting the seed/plan/close/walk markdown documents. Those remain canonical for human reading; the DB references their paths and indexes their structure.
- Not introducing tree-sitter or LSP-based symbol extraction in v5.0.0. Symbol extraction uses grep + `cargo metadata` (Rust) for v5.0.0; richer extraction is v5.x.
- Not auto-committing the DB to git. Default posture: gitignored. Consumers may opt to commit.
- Not building a multi-project global DB in v5.0.0. The `projects` table is the backbone for forward-compat, but each consumer project ships exactly one row.
- Not adding Sentry / Supabase / Fly state caches in v5.0.0. The `index_*` namespace is extensible; only GitHub lands first.
- Not rewriting `/shepherd:start`, `/shepherd:autorun`, `/shepherd:parallel`, or `/shepherd:plant`. Those commands gain optional DB hooks; their existing flow remains valid.

## 3. Architecture overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      Consumer project repo                      │
│                                                                 │
│  .claude/shepherd.toml ───────────────► [context] section       │
│                                                                 │
│  .artifacts/                                                    │
│    root.db ◄──────── /shepherd:context ──────► sqlite3 / shctx  │
│    shepherd.lock                                                │
│    CONVENTIONS.md                                               │
│    ctx/  plans/  reports/  docs/{handoffs,specs,diagrams,journal}│
│    logs/  tmp/  profiles/                                       │
│                                                                 │
│  Flock agents (engineer, critic, coder, auditor, worker)        │
│      │                                                          │
│      └──► sqlite3 .artifacts/root.db "SELECT …"                 │
│                       (or shctx query <name>)                   │
└─────────────────────────────────────────────────────────────────┘
```

**Two truth zones:**

| Zone | Where | Mode | Examples |
|---|---|---|---|
| Cache (derived) | DB `index_*`, `logs_events` rows | Rebuildable from source/MCP at any time | code symbols, GH issues/PRs/releases, last-N event log |
| Canonical | DB `projects`, `sessions`, `profiles_*`, `mem_*`, `sprints_*`, `artifacts`, `schema_versions`, `locks_history` + filesystem markdown under `docs/`, `plans/`, `reports/` | Not recoverable from elsewhere; persistence required | host project identity, sprint runs, grade trajectory, profiles, memories, design specs (this file), seeds, plans, close reports |

The DB **points at** filesystem markdown via the `artifacts` table (path + hash). The markdown remains the human-readable source; the DB indexes it.

## 4. Filesystem layout

The plugin's `init` subcommand scaffolds this tree in any consumer project:

```
.artifacts/
  root.db                       # SQLite registry (gitignored by default)
  shepherd.lock                 # JSON lock file (gitignored)
  CONVENTIONS.md                # auto-scaffolded; documents naming rules
  project.json                  # { "id": "<UUIDv7>", "scaffolded_at": <epoch> }
  ctx/                          # existing — markdown knowledge silo
  plans/                        # existing — *.plan.md, *.seed.md
  reports/                      # existing — *.phase0.md, *.close.md, *.walk.md
  docs/
    handoffs/                   # existing handoffs relocated here
    specs/                      # NEW — *.spec.md, *.design.md (this file lives here)
    diagrams/                   # NEW — *.svg, *.png, *.dot
    journal/                    # NEW — YYYY-MM-DD.md (one file per day, append-mode)
  logs/                         # NEW — events-YYYY-MM-DD.jsonl (append-only)
  tmp/                          # NEW — *.jsonl scratch (cleared on init / age-out)
  profiles/                     # NEW — *.toml profile defs (sync into profiles_* tables)
```

**Naming conventions** (enforced by `/shepherd:context lint`, configurable in `[context.naming]`):

| Pattern | Used for |
|---|---|
| `*.seed.md` | Sprint or patch seeds |
| `*.plan.md` | Sprint plans |
| `*.phase0.md` | Phase 0 mesh reports |
| `*.close.md` | Sprint close reports |
| `*.walk.md` | Stage Graph walk traces |
| `*.handoff.md` | Sprint handoff docs |
| `*.spec.md` | Design specs (after brainstorming) |
| `*.design.md` | Design documents |
| `YYYY-MM-DD.md` | Daily journal entries (in `docs/journal/`) — one file per day, sections within for multiple events |
| `events-YYYY-MM-DD.jsonl` | Daily event log (in `logs/`) — append-only |

**Date-only filenames** for human-editable artifacts (journal, daily reports). **Timestamped filenames** (`YYYY-MM-DDTHH-MM-SS.*`) reserved for machine-generated temp/cache/log artifacts in `tmp/` and `logs/`.

## 5. Multi-project backbone

```sql
CREATE TABLE projects (
  id          TEXT PRIMARY KEY,                  -- UUIDv7 (sortable, time-prefixed)
  name        TEXT NOT NULL DEFAULT '',
  scope       TEXT NOT NULL DEFAULT '[]'         -- JSON array of dirs/repos/domains
              CHECK(json_valid(scope)),
  metadata    TEXT CHECK(metadata IS NULL OR json_valid(metadata)),
  tags        TEXT NOT NULL DEFAULT '[]'
              CHECK(json_valid(tags)),
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL
);
```

On `init`, exactly one row is inserted (UUIDv7 generated, persisted to `.artifacts/project.json`). Every subsequent table carries `project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE`. SQLite's JSON1 extension is used for array/object queries on `scope`/`tags`/`metadata`.

Forward-compat: a future v6.x global DB simply unions per-project DBs by copying rows; FK semantics unchanged.

## 6. Schema (v5.0.0 — `schema/0001_init.sql`)

### 6.1 Migration tracking

```sql
CREATE TABLE schema_versions (
  version    INTEGER PRIMARY KEY,
  applied_at INTEGER NOT NULL,
  checksum   TEXT NOT NULL                       -- SHA256 of migration file content
);
```

Every DB carries its own version. `/shepherd:context migrate` reads the bundled `schema/migrations/*.sql`, applies any whose `version` is not yet present, and inserts a row.

### 6.2 Sessions

```sql
CREATE TABLE sessions (
  id            TEXT PRIMARY KEY,                -- Claude session ID or UUIDv7
  project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  started_at    INTEGER NOT NULL,
  ended_at      INTEGER,
  agent_role    TEXT,                            -- 'conductor' | 'engineer' | 'coder' | …
  sprint_branch TEXT,
  metadata      TEXT CHECK(metadata IS NULL OR json_valid(metadata))
);
CREATE INDEX idx_sessions_project_branch ON sessions(project_id, sprint_branch);
```

### 6.3 Profiles

```sql
CREATE TABLE profiles_defs (
  id          TEXT PRIMARY KEY,
  project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  name        TEXT NOT NULL,
  kind        TEXT NOT NULL,                     -- 'modifier' | 'extension' | 'override'
  config      TEXT NOT NULL CHECK(json_valid(config)),
  source_path TEXT,                              -- filesystem TOML path if synced
  active      INTEGER NOT NULL DEFAULT 1,
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL,
  UNIQUE(project_id, name)
);
```

Profiles are pluggable behavior overlays. A `modifier` adjusts existing flock behavior (e.g., "skip critic for XS sprints"); an `extension` adds new behavior (e.g., "run a custom security scan after every coder wave"); an `override` replaces a default (e.g., custom DEDUP-GATE recommendations).

Profiles live both as filesystem TOMLs in `.artifacts/profiles/*.toml` (human-edited) and as `profiles_defs` rows (queried by conductor). `/shepherd:context profile sync` reconciles the two — TOML is canonical for human edits, DB is canonical for runtime queries.

### 6.4 Memories (replaces external `remember` plugin)

```sql
CREATE TABLE mem_entries (
  id          TEXT PRIMARY KEY,                  -- UUIDv7
  project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  kind        TEXT NOT NULL,                     -- 'doctrine' | 'note' | 'decision' | 'incident' | 'session'
  title       TEXT NOT NULL,
  body        TEXT NOT NULL,
  tags        TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(tags)),
  pinned      INTEGER NOT NULL DEFAULT 0,
  source_path TEXT,                              -- nullable — points at md file if memory has a doc form
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL
);
CREATE INDEX idx_mem_project_kind ON mem_entries(project_id, kind);
CREATE INDEX idx_mem_project_pinned ON mem_entries(project_id, pinned) WHERE pinned = 1;
```

Mapping from external `remember` artifacts:

| `remember` artifact | shepherd equivalent |
|---|---|
| `now.md` (session buffer) | `sessions` row + `tmp/session-{id}.jsonl` |
| `today-*.md` | `logs/events-YYYY-MM-DD.jsonl` + `docs/journal/YYYY-MM-DD.md` |
| `recent.md` (7d) | View `v_mem_recent_7d` |
| `archive.md` | `mem_entries` rows older than 30 days |
| `core-memories.md` | `mem_entries` where `kind='doctrine'` AND `pinned=1` |

### 6.5 Index tables (the cache layer)

```sql
-- Code symbols (replaces canonical-types.md as a queryable table; phase d makes md a view)
CREATE TABLE index_symbols (
  id            TEXT PRIMARY KEY,                -- UUIDv7
  project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  name          TEXT NOT NULL,                   -- 'DriftCircuit'
  kind          TEXT NOT NULL,                   -- 'struct' | 'trait' | 'fn' | 'enum' | 'const' | 'mod' | 'class' | 'def' | …
  package       TEXT NOT NULL,                   -- 'crates/circuits' | 'src/auth' | …
  file_path     TEXT NOT NULL,
  line          INTEGER,
  visibility    TEXT,                            -- 'pub' | 'pub(crate)' | 'private' | 'export' | …
  signature     TEXT,
  doc_summary   TEXT,
  language      TEXT NOT NULL,
  hash          TEXT NOT NULL,                   -- content hash (declaration line + signature)
  refreshed_at  INTEGER NOT NULL,
  UNIQUE(project_id, name, package, kind)
);
CREATE INDEX idx_symbols_project_name ON index_symbols(project_id, name);
CREATE INDEX idx_symbols_project_pkg  ON index_symbols(project_id, package);

-- Concepts (the dedup index — "Drift detection -> DriftCircuit; AVOID DriftDetector, DriftHandler")
CREATE TABLE index_concepts (
  id                  TEXT PRIMARY KEY,
  project_id          TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  concept             TEXT NOT NULL,
  canonical_symbol_id TEXT NOT NULL REFERENCES index_symbols(id) ON DELETE CASCADE,
  aliases_to_avoid    TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(aliases_to_avoid)),
  notes               TEXT,
  UNIQUE(project_id, concept)
);

-- GitHub state caches
CREATE TABLE index_issues (
  id           TEXT PRIMARY KEY,                 -- 'github:owner/repo#NNN'
  project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  source       TEXT NOT NULL,                    -- 'github'
  number       INTEGER NOT NULL,
  title        TEXT NOT NULL,
  state        TEXT NOT NULL,                    -- 'open' | 'closed'
  labels       TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(labels)),
  milestone    TEXT,
  assignees    TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(assignees)),
  body         TEXT,
  url          TEXT NOT NULL,
  created_at   INTEGER NOT NULL,
  updated_at   INTEGER NOT NULL,
  refreshed_at INTEGER NOT NULL
);
CREATE INDEX idx_issues_project_state     ON index_issues(project_id, state);
CREATE INDEX idx_issues_project_milestone ON index_issues(project_id, milestone);

CREATE TABLE index_prs (
  id           TEXT PRIMARY KEY,
  project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  source       TEXT NOT NULL,
  number       INTEGER NOT NULL,
  title        TEXT NOT NULL,
  state        TEXT NOT NULL,                    -- 'open' | 'closed' | 'merged'
  base_branch  TEXT NOT NULL,
  head_branch  TEXT NOT NULL,
  labels       TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(labels)),
  url          TEXT NOT NULL,
  created_at   INTEGER NOT NULL,
  updated_at   INTEGER NOT NULL,
  merged_at    INTEGER,
  refreshed_at INTEGER NOT NULL
);
CREATE INDEX idx_prs_project_state ON index_prs(project_id, state);

CREATE TABLE index_releases (
  id           TEXT PRIMARY KEY,
  project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  source       TEXT NOT NULL,
  tag          TEXT NOT NULL,
  name         TEXT,
  prerelease   INTEGER NOT NULL DEFAULT 0,
  draft        INTEGER NOT NULL DEFAULT 0,
  body         TEXT,
  url          TEXT NOT NULL,
  published_at INTEGER,
  refreshed_at INTEGER NOT NULL,
  UNIQUE(project_id, source, tag)
);

CREATE TABLE index_milestones (
  id           TEXT PRIMARY KEY,
  project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  source       TEXT NOT NULL,
  number       INTEGER NOT NULL,
  title        TEXT NOT NULL,
  state        TEXT NOT NULL,
  due_on       INTEGER,
  description  TEXT,
  url          TEXT NOT NULL,
  refreshed_at INTEGER NOT NULL,
  UNIQUE(project_id, source, number)
);
```

### 6.6 Logs

```sql
CREATE TABLE logs_events (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  ts            INTEGER NOT NULL,
  level         TEXT NOT NULL,                   -- 'info' | 'warn' | 'error' | 'gate' | 'audit'
  source        TEXT NOT NULL,                   -- 'conductor' | 'engineer' | …
  event         TEXT NOT NULL,                   -- 'dispatch' | 'gate-pass' | 'dedup-block' | …
  payload       TEXT CHECK(payload IS NULL OR json_valid(payload)),
  sprint_branch TEXT,
  session_id    TEXT
);
CREATE INDEX idx_logs_project_ts ON logs_events(project_id, ts);
```

`logs_events` holds the last 10K events for fast `/shepherd:context status` queries. The full append-only stream lives at `logs/events-YYYY-MM-DD.jsonl`. Rotation: when `logs_events` exceeds 10K rows for a project, the oldest 1K are flushed to that day's JSONL and deleted.

### 6.7 Artifacts (filesystem-pointer table)

```sql
CREATE TABLE artifacts (
  id            TEXT PRIMARY KEY,                -- UUIDv7
  project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  kind          TEXT NOT NULL,                   -- 'seed' | 'plan' | 'phase0' | 'close' | 'walk' | 'handoff' | 'spec' | 'design' | 'diagram' | 'journal'
  path          TEXT NOT NULL,                   -- relative to repo root
  sprint_branch TEXT,
  title         TEXT,
  hash          TEXT NOT NULL,
  created_at    INTEGER NOT NULL,
  updated_at    INTEGER NOT NULL,
  UNIQUE(project_id, path)
);
CREATE INDEX idx_artifacts_project_kind ON artifacts(project_id, kind);
CREATE INDEX idx_artifacts_sprint       ON artifacts(project_id, sprint_branch);
```

The DB references markdown files; markdown remains canonical content. `hash` is recomputed during `/shepherd:context refresh --scope=artifacts`; mismatches surface as drift in `status`.

### 6.8 Locks (audit trail for the file-based lock)

```sql
CREATE TABLE locks_history (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  session_id   TEXT NOT NULL,
  mode         TEXT NOT NULL,                    -- 'autorun' | 'parallel' | 'start' | 'plant' | 'context'
  acquired_at  INTEGER NOT NULL,
  released_at  INTEGER,
  released_by  TEXT,                             -- 'normal' | 'reap' | 'force'
  metadata     TEXT CHECK(metadata IS NULL OR json_valid(metadata))
);
```

The live lock is `.artifacts/shepherd.lock` (file-locked via `flock(2)`); `locks_history` records acquisition/release events for audit.

### 6.9 Sprint metadata (deferred to milestone d)

```sql
-- Phase d (sprints_*) schema sketch — formal DDL in v5.0.0-dev.{N+1}+ spec
sprints_runs        (sprint_branch, started_at, closed_at, grade, t_shirt, …)
sprints_lanes       (sprint_run_id, lane_id, file_scope_json, skills_json, …)
sprints_findings    (sprint_run_id, severity, concern, body, …)
sprints_stage_graph (sprint_run_id, node_id, predicates_json, edges_json, …)
```

Schema `0002_sprints.sql` ships in milestone (d). `/shepherd:context migrate` applies it forward.

## 7. Views (pre-built SQL — `schema/views/*.sql`)

Bundled views so skills don't ship raw SQL templates:

```sql
-- Open issues with milestone, ordered for Phase 0 ledger sweep
CREATE VIEW v_open_issues AS
  SELECT project_id, number, title, state, labels, milestone, assignees, url, updated_at
  FROM index_issues WHERE state = 'open' ORDER BY updated_at DESC;

-- canonical-types replacement (markdown-renderable)
CREATE VIEW v_canonical_types AS
  SELECT s.project_id, s.package, s.kind, s.name, s.signature, s.doc_summary, s.file_path, s.line,
         c.concept, c.aliases_to_avoid
  FROM index_symbols s
  LEFT JOIN index_concepts c ON c.canonical_symbol_id = s.id
  WHERE s.visibility IN ('pub', 'pub(crate)', 'export')
  ORDER BY s.package, s.name;

-- Drift-risk queue (open CRITICAL/HIGH issues outside the current milestone)
CREATE VIEW v_drift_risk AS
  SELECT i.project_id, i.number, i.title, i.milestone, i.labels
  FROM index_issues i
  WHERE i.state = 'open'
    AND (i.labels LIKE '%"critical"%' OR i.labels LIKE '%"high"%');

-- Recent memories (last 7 days)
CREATE VIEW v_mem_recent_7d AS
  SELECT * FROM mem_entries
  WHERE created_at >= unixepoch() - 7 * 86400 OR pinned = 1
  ORDER BY pinned DESC, created_at DESC;

-- Active locks
CREATE VIEW v_active_locks AS
  SELECT * FROM locks_history WHERE released_at IS NULL ORDER BY acquired_at DESC;
```

Plus `queries/dedup-check.sql` — a parameterized SQL template (SQLite views can't take parameters) bound at call time by the wrapper: `shctx query dedup-check --name=<symbol>`. Returns rows where `index_symbols.name = ?` for the active `project_id`.

## 8. Command surface — `/shepherd:context`

The command is a SKILL (per current plugin convention) at `plugins/shepherd/skills/context/SKILL.md`. Subcommands:

| Subcommand | Purpose |
|---|---|
| `init` | Scaffold `.artifacts/` tree, create `root.db`, generate UUIDv7, insert host project row, write `CONVENTIONS.md`, write `.artifacts/.gitignore` |
| `status` | Row counts per table, refresh staleness, lock state, naming-convention violations |
| `refresh [--scope=symbols\|github\|artifacts\|all]` | Idempotent rebuild of cache tables |
| `query <name> [--json\|--md]` | Run a pre-baked named query from `queries/<name>.sql` |
| `inject <role>` | Emit a `[DB-CONTEXT]` block tailored to an agent role for inclusion in a brief |
| `profile <list\|show\|enable\|disable\|sync>` | Manage profile rows; `sync` reconciles `profiles/*.toml` ↔ `profiles_defs` |
| `mem <add\|search\|list\|pin\|unpin>` | Memory CRUD — replaces `remember` plugin surface |
| `lock <show\|acquire\|release\|reap>` | Coordinate `.artifacts/shepherd.lock` (used by `/shepherd:autorun` and `/shepherd:parallel`) |
| `lint` | Naming-convention check against `[context.naming]` |
| `migrate` | Apply pending schema migrations |
| `export <kind> [--out=path]` | Dump tables/views as md or json |

**Tooling invariants:**
- Agents may call `sqlite3 .artifacts/root.db "<sql>"` directly. No new runtime dependency beyond `sqlite3` CLI.
- A wrapper at `plugins/shepherd/skills/context/scripts/shctx` provides ergonomic shortcuts (`shctx query open-issues`, `shctx inject coder`, etc.). Wrapper is a thin shell script; raw SQL always works.
- All write paths take the advisory lock (`/shepherd:context lock acquire --mode=context`) before mutating; release on exit.

## 9. Refresh model

**Symbols (Rust, v5.0.0):**
1. Run `cargo metadata --format-version 1 --no-deps` to enumerate packages.
2. For each package, walk `src/**/*.rs` and grep declarations: `^(\s*pub(?:\([^)]+\))?\s+)?(fn|struct|trait|enum|const|static|type|mod)\s+(\w+)`.
3. Hash each `(name, kind, package, signature)` tuple; upsert into `index_symbols`.
4. Stamp `refreshed_at`. Mark rows older than this run's start time AND whose `(project_id, name, package, kind)` no longer appears in source as stale; soft-delete via DELETE in same txn.

Other languages (`python`, `typescript`, `go`) ship as stub extractors in v5.0.0 (table accepts rows but no extractor; v5.x introduces real extraction).

**External state (GitHub):**
- Use `gh` CLI when `[cli].gh = true` (preferred); fall back to `mcp__plugin_github_github__*` if `[mcp].github = true`.
- Endpoints: `gh issue list`, `gh pr list`, `gh release list`, `gh api repos/:owner/:repo/milestones`.
- Upsert by stable `id` (`github:<owner>/<repo>#<num>` for issues/PRs, `github:<owner>/<repo>:tag:<tag>` for releases).
- TTL: `[context.refresh].ttl_minutes` (default 30). `status` shows staleness.

**Artifacts:**
- Walk `.artifacts/{plans,reports,docs}/**/*.md`, classify by filename pattern, hash content, upsert into `artifacts`.

All refresh modes are **idempotent**. Running `refresh --scope=all` twice produces identical DB state.

## 10. Lock model

`.artifacts/shepherd.lock` is a JSON file managed via `flock(2)`:

```json
{
  "holder_session_id": "01HK…",
  "mode": "autorun",
  "branch": "v0.2.9-dev.5",
  "worktree": "/abs/path/to/worktree",
  "acquired_at": 1714824000,
  "pid": 12345,
  "children": ["session-id-1", "session-id-2"]
}
```

Acquisition matrix:

| Caller | Mode | Behavior on conflict |
|---|---|---|
| `/shepherd:start` | `start` | Block, surface holder; operator may force-release |
| `/shepherd:autorun` | `autorun` | Block (autorun is the umbrella holder; nested `start` runs are children) |
| `/shepherd:parallel` | `parallel` | Allow multiple holders simultaneously, one per worktree, recorded in `children` |
| `/shepherd:plant` | `plant` | Compatible with all; short-lived |
| `/shepherd:context` (refresh write) | `context` | Short-lived; serialized within a single project |

Stale locks: PID dead OR `acquired_at` older than `[context.lock].stale_minutes` (default 60) → reap on next `init`/`status` if `[context.lock].reap_on_init = true`. Reap inserts a `released_by='reap'` row in `locks_history`.

## 11. Integration with the flock

### 11.1 Phase 1 (milestone c — additive)

- **`engineer.md`**: Phase 0 mesh row 12 ("workspace knowledge silo") gains a fast-path: query `v_canonical_types` if DB present; fall back to `canonical-types.md` otherwise. Row 1 ("open-issue ledger") gains a fast-path via `v_open_issues`. Behavior unchanged when DB absent.
- **`flock.md` → @coder**: optional `[DB-CONTEXT]` block in coder briefs. Engineer populates via `/shepherd:context inject coder`. Block contains: relevant `index_symbols` rows for `[CONTEXT-INVENTORY]`, dedup-check results for `[DO-NOT-DUPLICATE]`.
- **Conductor DEDUP-GATE** (per `doctrines/zero-duplicate-tolerance.md`): Layer 2 (conductor pre-dispatch gate) gains a SQL fast-path. Conductor runs `queries/dedup-check.sql` against `index_symbols` BEFORE running the slower per-lane grep. If symbol exists in DB, BLOCK immediately with the same recommendation block. The grep remains the source of truth (Layer 2 contract unchanged); the SQL fast-path catches duplications cheaply when the cache is fresh.
- **New doctrine**: `plugins/shepherd/skills/shepherd/doctrines/context-registry.md` — introduces the registry, defines cache vs canonical zones, defines the fall-back-when-absent contract (DB is optional in milestone c).

### 11.2 Phase 2 (milestone d — contract change, justifies MAJOR bump)

- `canonical-types.md` becomes auto-generated from `v_canonical_types` (markdown rendered by `/shepherd:context export canonical-types --out=ctx/canonical-types.md`). Hand edits are flagged as drift.
- Phase 0 mesh report becomes a SQL-backed view export; `.phase0.md` is regenerated from the DB.
- Sprint close writes structured rows to `sprints_*` in addition to `*.close.md`.
- Auditor's stage-graph-violation check, grade-trajectory query, and chronic-issue detection use `sprints_*` queries instead of filesystem walks.
- `[DB-CONTEXT]` block becomes **required** in coder briefs; auditor `completeness` enforces.
- New doctrine: `plugins/shepherd/skills/shepherd/doctrines/registry-as-truth.md`.

## 12. `shepherd.toml` additions

```toml
[paths]
plans    = ".artifacts/plans"
reports  = ".artifacts/reports"
docs     = ".artifacts/docs"
ctx      = ".artifacts/ctx"
logs     = ".artifacts/logs"          # NEW
tmp      = ".artifacts/tmp"           # NEW
profiles = ".artifacts/profiles"      # NEW

[context]
enabled         = true
db_path         = ".artifacts/root.db"
lock_path       = ".artifacts/shepherd.lock"
project_id_path = ".artifacts/project.json"
auto_refresh    = ["on-sprint-open"]

[context.refresh]
symbols_languages = ["rust"]
github_scope      = ["issues", "prs", "releases", "milestones"]
ttl_minutes       = 30

[context.lock]
stale_minutes = 60
reap_on_init  = true

[context.naming]
seed     = "*.seed.md"
plan     = "*.plan.md"
phase0   = "*.phase0.md"
close    = "*.close.md"
walk     = "*.walk.md"
handoff  = "*.handoff.md"
spec     = "*.spec.md"
design   = "*.design.md"
journal  = "????-??-??.md"
```

`[context]` is parsed but `enabled = false` is a valid configuration in milestone c (DB-optional). In milestone d, `enabled = false` is rejected by `migrate`/`status` — DB is mandatory.

## 13. Version bump scope

Files touched at v5.0.0:

| File | Change |
|---|---|
| `plugins/shepherd/.claude-plugin/plugin.json` | `version: "4.2.0"` → `"5.0.0"`; description appended |
| `plugins/shepherd/skills/shepherd/SKILL.md` | frontmatter `version` + body version refs + new §X for context registry |
| `plugins/shepherd/README.md` | version refs in header, install commands; new "Context Registry" section |
| `plugins/shepherd/CHANGELOG.md` | new `## v5.0.0 — 2026-05-XX` entry |
| `.claude-plugin/marketplace.json` | shepherd entry version bumped |
| `plugins/fl03-skills/skills/shepherd/SKILL.md` | quick-reference version bumped (if it carries one) |
| `plugins/fl03-skills/.claude-plugin/plugin.json` | bumped only if version tracks shepherd; check first |
| `skills/skills/*.zip`, `skills/shepherd.zip` | re-pack manually per `CLAUDE.md` |

Bump rationale per `CLAUDE.md`'s SemVer policy: "MAJOR = closed-flock contract change". v5.0.0 introduces the context registry as a new contract (briefs gain `[DB-CONTEXT]`, conductor gains DEDUP-GATE Layer 2.5, milestone d makes `[DB-CONTEXT]` mandatory). MAJOR.

## 14. Phasing & deferred work

**Milestone (c) — `v5.0.0-dev.0..N` (multiple sprints expected):**
- Schema `0001_init.sql` (projects, sessions, profiles_defs, mem_entries, index_*, logs_events, artifacts, locks_history, schema_versions) + views.
- Skill `plugins/shepherd/skills/context/` with all subcommands (`init`, `status`, `refresh`, `query`, `inject`, `profile`, `mem`, `lock`, `lint`, `migrate`, `export`).
- `gh`-CLI-backed external refresh.
- Rust symbol extraction (other languages stubbed).
- `shepherd.toml` `[context]`, `[context.refresh]`, `[context.lock]`, `[context.naming]` parsing (optional in milestone c).
- Engineer/coder/auditor briefs add OPTIONAL `[DB-CONTEXT]` preamble.
- New doctrine `context-registry.md`.
- README, CHANGELOG, version bumps.
- `.gitignore` updates: add `.artifacts/shepherd.lock`, `.artifacts/project.json` to ignore list.
- Self-host: scaffold `.artifacts/` in this repo (eat own dog food).

**Milestone (d) — `v5.0.0-dev.{N+1}..`:**
- Schema `0002_sprints.sql` (`sprints_runs`, `sprints_lanes`, `sprints_findings`, `sprints_stage_graph`).
- `canonical-types.md` becomes a generated view export.
- Phase 0 mesh report becomes generated.
- Sprint close writes structured rows.
- `[DB-CONTEXT]` block becomes required (contract change).
- New doctrine `registry-as-truth.md`.

**Deferred to v5.x (out of v5.0.0 scope):**
- Tree-sitter / LSP-based symbol extraction.
- Sentry / Supabase / Fly state caches (additional `index_*` tables).
- Multi-project global DB (`projects` table is the forward-compat hook).
- `SessionStart`/`Stop` hook integration for automatic session capture.
- VS Code / JetBrains editor integration.
- Profile marketplace / shared profile distribution.

## 15. Migration & backward compatibility

- **Existing projects without `.artifacts/root.db`** continue to work in milestone c — DB is optional; absence triggers fall-back to markdown reads. Milestone d tightens this (operator-visible warning if DB absent).
- **`canonical-types.md`**: in milestone c, hand-maintained version remains valid. In milestone d, file becomes generated; hand-edits are flagged via hash mismatch.
- **`shepherd.toml [context]` absent**: defaults applied as documented above; warning emitted.
- **Schema migrations**: forward-only. `0001_init.sql` is the v5.0.0 baseline. Each subsequent migration is a numbered file in `schema/migrations/`. `migrate` is idempotent.
- **No data migration needed** for milestone c — `init` is the bootstrap. For milestone d, `migrate` adds new tables; existing rows untouched.

## 16. Risks & mitigations

| Risk | Mitigation |
|---|---|
| `sqlite3` CLI not installed on operator system | Pre-flight check in `init`; clear error message; macOS/Linux ship with it; document Windows install |
| DB corruption mid-write | All writes wrapped in transactions; `PRAGMA journal_mode=WAL` for crash safety; `.gitignore` covers `*-wal`/`*-shm` |
| Schema drift between plugin versions and consumer DB | `schema_versions` table + bundled migrations; `status` warns on missing migrations |
| `gh` CLI rate-limit during refresh | TTL-based caching; `refresh` only fetches if stale; respect rate-limit headers |
| Symbol extraction false positives (grep-based) | Document in `references/schema.md`; mark v5.0.0 extraction as best-effort; tree-sitter migration in v5.x |
| Lock file orphaned by killed process | Stale-lock reaper (PID liveness check + age threshold); `lock reap` operator command |
| Profile TOML / DB row divergence | `profile sync` operator command; `status` flags divergence |
| Multi-process write contention | SQLite WAL mode handles readers concurrent with writer; advisory file lock serializes writers |

## 17. Open questions

None blocking implementation. Items deferred to milestone (d) spec:

- Exact `sprints_*` schema (sketched in §6.9; finalized when (d) is planned).
- Whether `[DB-CONTEXT]` block format is JSON, markdown, or YAML — likely markdown for human-diffability, but TBD when coder brief contract is rewritten.
- Whether profile TOML or DB row wins on `sync` conflict — current default is "TOML wins, DB updates"; revisit if operators want bidirectional merge.

## 18. Acceptance criteria

Milestone (c) is shippable when:

1. `/shepherd:context init` scaffolds `.artifacts/` tree with `root.db`, `CONVENTIONS.md`, `project.json` in a clean repo.
2. `/shepherd:context refresh --scope=all` populates `index_symbols` (Rust), `index_issues`, `index_prs`, `index_releases`, `index_milestones`, `artifacts`.
3. `/shepherd:context query canonical-types` returns the same data `canonical-types.md` would, in markdown form.
4. `/shepherd:context inject coder` emits a `[DB-CONTEXT]` block usable in a coder brief.
5. Lock acquisition/release works across `/shepherd:start`, `/shepherd:autorun`, `/shepherd:parallel` simulations.
6. `/shepherd:context migrate` applies `0001_init.sql` cleanly on an empty DB and is no-op on a current DB.
7. All four existing commands (`/shepherd:plant`, `/shepherd:start`, `/shepherd:autorun`, `/shepherd:parallel`) continue to work with `enabled=false` (regression check).
8. This repo has `.artifacts/root.db` scaffolded and at least one design spec (this file) registered as an `artifacts` row.
9. Plugin version is `5.0.0` across all manifests, README, CHANGELOG, marketplace.json.
10. New doctrine `context-registry.md` exists and is referenced from `SKILL.md`.

---

## Appendix A — Reference file inventory

To be created at implementation time:

```
plugins/shepherd/skills/context/
  SKILL.md                                    # entry point, all subcommands documented
  schema/
    0001_init.sql                             # v5.0.0 baseline DDL
    views/
      canonical-types.sql
      drift-risk.sql
      mem-recent-7d.sql
      open-issues.sql
      active-locks.sql
      dedup-check.sql
    migrations/                               # forward-only; populated as schema evolves
      .gitkeep
  scripts/
    shctx                                     # ergonomic wrapper (shell)
    scaffold.sh                               # called by `init`
    refresh-symbols.sh                        # Rust extractor
    refresh-github.sh                         # gh-CLI wrapper
  queries/                                    # pre-baked SELECT templates
    canonical-types.sql
    dedup-check.sql
    drift-risk.sql
    open-issues.sql
    open-prs.sql
    recent-releases.sql
    mem-search.sql
  references/
    schema.md                                 # human-readable schema doc
    profiles.md                               # profile model and TOML format
    naming-conventions.md                     # CONVENTIONS.md template content
  examples/
    inject-coder.md                           # example [DB-CONTEXT] block
    profile-modifier.toml
    profile-extension.toml
    journal-entry.md
```

## Appendix B — Updated repository invariants (CLAUDE.md additions)

To be appended to `CLAUDE.md` at v5.0.0:

- `.artifacts/root.db` is the per-project SQLite registry. Schema lives in `plugins/shepherd/skills/context/schema/`.
- `.artifacts/shepherd.lock` coordinates concurrent shepherd sessions (autorun, parallel, start). Always JSON; never edit by hand.
- `.artifacts/docs/specs/*.spec.md` and `*.design.md` are design documents; track in git. Per-spec naming: `YYYY-MM-DD-<topic>-design.md` for designs, `YYYY-MM-DD-<topic>-spec.md` for finalized specs.
- `.artifacts/docs/journal/YYYY-MM-DD.md` are operator-editable daily notes; one file per day, append-mode.
- `.artifacts/logs/events-YYYY-MM-DD.jsonl` are append-only event streams; gitignored.
- `.artifacts/tmp/` and `.artifacts/logs/` are gitignored. `.artifacts/profiles/`, `.artifacts/docs/`, `.artifacts/plans/`, `.artifacts/reports/`, `.artifacts/ctx/` are tracked.

---

**End of spec.**
