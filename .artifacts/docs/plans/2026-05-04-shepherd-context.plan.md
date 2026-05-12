# Shepherd v5.0.0 Context Registry — Implementation Plan (milestone c)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `/shepherd:context` and the per-project `.artifacts/root.db` SQLite registry as v5.0.0 (milestone c — additive cache layer; milestone d ships in a follow-up plan).

**Architecture:** New skill at `plugins/shepherd/skills/context/` with bundled schema, queries, views, and shell scripts. New command shim at `plugins/shepherd/commands/context.md`. Database access via `sqlite3` CLI; ergonomic wrapper at `scripts/shctx`. Refresh via `gh` CLI for GitHub state and `cargo metadata` + grep for Rust symbols. Test harness is hand-rolled bash with assert helpers; tests run against tmp dirs and tmp DBs.

**Tech Stack:** SQLite 3 (with JSON1 + WAL), bash, `gh` CLI, `cargo metadata`, `flock(2)`, `jq`, UUIDv7 (generated via shell).

**Spec:** `.artifacts/docs/specs/2026-05-04-shepherd-context-design.md` (commit `b7b1e7d`).

**Scope:** This plan covers milestone (c) only. Milestone (d) — `sprints_*` schema, mandatory `[DB-CONTEXT]`, generated `canonical-types.md` — gets a separate plan once (c) ships.

---

## File structure

```
plugins/shepherd/
  .claude-plugin/plugin.json                  # MODIFY — version 4.2.0 → 5.0.0
  README.md                                   # MODIFY — version refs, new section
  CHANGELOG.md                                # MODIFY — append v5.0.0 entry
  commands/
    context.md                                # CREATE — slash-command shim
  skills/
    shepherd/
      SKILL.md                                # MODIFY — version, ref to context skill
      doctrines/
        context-registry.md                   # CREATE — new doctrine
    context/                                  # CREATE — full new skill tree
      SKILL.md
      schema/
        0001_init.sql
        views/{open-issues,canonical-types,drift-risk,mem-recent-7d,active-locks}.sql
        migrations/.gitkeep
      queries/
        canonical-types.sql
        dedup-check.sql
        drift-risk.sql
        open-issues.sql
        open-prs.sql
        recent-releases.sql
        mem-search.sql
      scripts/
        shctx                                  # main wrapper
        _lib.sh                                # shared helpers
        scaffold.sh                            # init internals
        refresh-symbols.sh
        refresh-github.sh
      references/
        schema.md
        profiles.md
        naming-conventions.md
      examples/
        inject-coder.md
        profile-modifier.toml
        profile-extension.toml
        journal-entry.md
      tests/
        run.sh                                 # test runner
        _setup.sh                              # tmpdir + tmpdb scaffolding
        _assert.sh                             # assertion helpers
        test_init.sh
        test_migrate.sh
        test_status.sh
        test_refresh_symbols.sh
        test_refresh_github.sh
        test_refresh_artifacts.sh
        test_query.sh
        test_inject.sh
        test_export.sh
        test_lint.sh
        test_mem.sh
        test_profile.sh
        test_lock.sh

plugins/fl03-skills/
  skills/shepherd/SKILL.md                    # MODIFY — version (if it carries one)
  .claude-plugin/plugin.json                  # MODIFY — only if version tracks shepherd

.claude-plugin/marketplace.json               # MODIFY — shepherd entry version
.gitignore                                    # MODIFY — add .artifacts/shepherd.lock, project.json
CLAUDE.md                                     # MODIFY — Appendix B additions
.artifacts/                                   # CREATE (self-host)
  root.db
  shepherd.lock
  CONVENTIONS.md
  project.json
  (full tree per spec §4)
```

---

## Task 1: Bootstrap skill skeleton + test harness

**Files:**
- Create: `plugins/shepherd/skills/context/SKILL.md` (frontmatter only for now)
- Create: `plugins/shepherd/skills/context/scripts/_lib.sh`
- Create: `plugins/shepherd/skills/context/tests/run.sh`
- Create: `plugins/shepherd/skills/context/tests/_setup.sh`
- Create: `plugins/shepherd/skills/context/tests/_assert.sh`

- [ ] **Step 1: Create the directory tree**

```bash
cd plugins/shepherd/skills
mkdir -p context/{schema/{views,migrations},queries,scripts,references,examples,tests}
touch context/schema/migrations/.gitkeep
```

- [ ] **Step 2: Write `SKILL.md` frontmatter (body filled out in Task 16)**

```markdown
---
name: shepherd-context
slug: shepherd-context
version: 5.0.0
description: |
  Per-project SQLite registry for the shepherd flock. Backs /shepherd:context.
  Indexes code symbols, GitHub state (issues, PRs, releases, milestones),
  artifacts (markdown reports), memories, profiles, locks, and event logs.
  See plugins/shepherd/skills/shepherd/doctrines/context-registry.md for the
  cache-vs-canonical model.
metadata:
  triggers:
    - "/shepherd:context"
---

# /shepherd:context — Per-project Context Registry

Body authored in Task 16.
```

- [ ] **Step 3: Write `scripts/_lib.sh`**

```bash
#!/usr/bin/env bash
# Shared helpers for /shepherd:context subcommands.
# Sourced by every script in scripts/. Never executed directly.

set -eu -o pipefail

# Resolve repo root (where shepherd.toml lives).
shctx_repo_root() {
  git rev-parse --show-toplevel 2>/dev/null || pwd
}

# Resolve config values from .claude/shepherd.toml. For milestone c we hard-code
# defaults; full TOML parsing is upstreamed into a pluggable parser later.
shctx_db_path()         { echo "$(shctx_repo_root)/.artifacts/root.db"; }
shctx_lock_path()       { echo "$(shctx_repo_root)/.artifacts/shepherd.lock"; }
shctx_project_id_path() { echo "$(shctx_repo_root)/.artifacts/project.json"; }
shctx_artifacts_root()  { echo "$(shctx_repo_root)/.artifacts"; }
shctx_skill_root()      { echo "${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"; }

# UUIDv7 generator (timestamp-prefixed, sortable). Pure-bash; uses /dev/urandom.
shctx_uuid7() {
  local ts ms hi lo rand a b c d e
  ts=$(date +%s%3N)
  hi=$(printf '%012x' "$ts")
  rand=$(od -An -tx1 -N10 /dev/urandom | tr -d ' \n')
  a=${hi:0:8}; b=${hi:8:4}
  c="7${rand:0:3}"
  d=$(printf '%04x' $((0x8000 | 0x${rand:3:3}0)))
  e=${rand:6:12}
  echo "${a}-${b}-${c}-${d:0:4}-${e}"
}

# Lookup the host project_id. Errors if .artifacts/project.json missing.
shctx_project_id() {
  local p; p=$(shctx_project_id_path)
  if [[ ! -f "$p" ]]; then
    echo "ERROR: $p missing — run 'shctx init' first" >&2
    return 1
  fi
  jq -r '.id' "$p"
}

# Run sqlite3 against the project DB.
shctx_sql() {
  sqlite3 -bail "$(shctx_db_path)" "$@"
}

# Now-epoch (seconds).
shctx_now() { date +%s; }
```

- [ ] **Step 4: Write `tests/_setup.sh` and `tests/_assert.sh`**

```bash
# tests/_setup.sh — sourced by every test file
set -eu -o pipefail

SHCTX_TEST_TMP="$(mktemp -d -t shctx-test.XXXXXX)"
trap 'rm -rf "$SHCTX_TEST_TMP"' EXIT

# Stand up a fake repo root with .artifacts skeleton.
shctx_test_repo() {
  cd "$SHCTX_TEST_TMP"
  git init -q .
  git config user.email t@t
  git config user.name t
  echo "test" > README.md
  git add README.md && git commit -qm init
}

# Produce a fresh, empty DB initialized with schema 0001.
shctx_test_db() {
  local db="$SHCTX_TEST_TMP/.artifacts/root.db"
  mkdir -p "$SHCTX_TEST_TMP/.artifacts"
  sqlite3 "$db" < "$SHCTX_SKILL_ROOT/schema/0001_init.sql"
  echo "$db"
}

export SHCTX_SKILL_ROOT="${SHCTX_SKILL_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
```

```bash
# tests/_assert.sh
assert_eq() {
  if [[ "$2" != "$3" ]]; then
    echo "FAIL: $1: expected '$3' got '$2'" >&2; exit 1
  fi
}
assert_contains() {
  if ! grep -qF "$3" <<< "$2"; then
    echo "FAIL: $1: '$2' did not contain '$3'" >&2; exit 1
  fi
}
assert_file() {
  [[ -f "$1" ]] || { echo "FAIL: file missing: $1" >&2; exit 1; }
}
assert_table() {
  local db="$1" table="$2"
  sqlite3 "$db" ".schema $table" | grep -q "CREATE TABLE.*$table" \
    || { echo "FAIL: table missing: $table" >&2; exit 1; }
}
```

- [ ] **Step 5: Write `tests/run.sh` runner**

```bash
#!/usr/bin/env bash
set -eu -o pipefail
cd "$(dirname "$0")"
shopt -s nullglob
fails=0; total=0
for f in test_*.sh; do
  total=$((total+1))
  echo "[run] $f"
  if bash "$f"; then
    echo "  PASS"
  else
    echo "  FAIL"; fails=$((fails+1))
  fi
done
echo "—— $((total-fails))/$total passed ——"
exit "$fails"
```

```bash
chmod +x plugins/shepherd/skills/context/scripts/_lib.sh
chmod +x plugins/shepherd/skills/context/tests/run.sh
```

- [ ] **Step 6: Commit**

```bash
git add plugins/shepherd/skills/context/
git commit -m "feat(shepherd-context): bootstrap skill skeleton + test harness"
```

---

## Task 2: Schema 0001_init.sql + views

**Files:**
- Create: `plugins/shepherd/skills/context/schema/0001_init.sql`
- Create: `plugins/shepherd/skills/context/schema/views/open-issues.sql`
- Create: `plugins/shepherd/skills/context/schema/views/canonical-types.sql`
- Create: `plugins/shepherd/skills/context/schema/views/drift-risk.sql`
- Create: `plugins/shepherd/skills/context/schema/views/mem-recent-7d.sql`
- Create: `plugins/shepherd/skills/context/schema/views/active-locks.sql`
- Create: `plugins/shepherd/skills/context/tests/test_schema.sh`

- [ ] **Step 1: Write the failing test**

```bash
# plugins/shepherd/skills/context/tests/test_schema.sh
#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
db=$(shctx_test_db)

# All v5.0.0 tables must exist.
for t in projects sessions profiles_defs mem_entries \
         index_symbols index_concepts index_issues index_prs \
         index_releases index_milestones logs_events artifacts \
         locks_history schema_versions; do
  assert_table "$db" "$t"
done

# All views must exist.
for v in v_open_issues v_canonical_types v_drift_risk v_mem_recent_7d v_active_locks; do
  sqlite3 "$db" "SELECT 1 FROM $v LIMIT 1;" >/dev/null \
    || { echo "FAIL: view missing or broken: $v" >&2; exit 1; }
done

# WAL journal mode + foreign keys ON.
mode=$(sqlite3 "$db" "PRAGMA journal_mode;")
assert_eq "journal_mode" "$mode" "wal"
fk=$(sqlite3 "$db" "PRAGMA foreign_keys;")
assert_eq "foreign_keys" "$fk" "1"

# JSON CHECK constraints reject invalid JSON.
if sqlite3 "$db" "INSERT INTO projects (id,name,scope,tags,created_at,updated_at) VALUES ('x','t','not-json','[]',0,0);" 2>/dev/null; then
  echo "FAIL: invalid JSON accepted in projects.scope" >&2; exit 1
fi

# Schema-version row written.
v=$(sqlite3 "$db" "SELECT version FROM schema_versions ORDER BY version DESC LIMIT 1;")
assert_eq "schema_version" "$v" "1"
```

```bash
chmod +x plugins/shepherd/skills/context/tests/test_schema.sh
```

- [ ] **Step 2: Run test, confirm fail**

```bash
bash plugins/shepherd/skills/context/tests/test_schema.sh
# Expected: FAIL on first assert_table (schema file missing)
```

- [ ] **Step 3: Write `schema/0001_init.sql`**

```sql
-- plugins/shepherd/skills/context/schema/0001_init.sql
-- shepherd v5.0.0 baseline schema.
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE schema_versions (
  version    INTEGER PRIMARY KEY,
  applied_at INTEGER NOT NULL,
  checksum   TEXT NOT NULL
);

CREATE TABLE projects (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL DEFAULT '',
  scope       TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(scope)),
  metadata    TEXT CHECK(metadata IS NULL OR json_valid(metadata)),
  tags        TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(tags)),
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL
);

CREATE TABLE sessions (
  id            TEXT PRIMARY KEY,
  project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  started_at    INTEGER NOT NULL,
  ended_at      INTEGER,
  agent_role    TEXT,
  sprint_branch TEXT,
  metadata      TEXT CHECK(metadata IS NULL OR json_valid(metadata))
);
CREATE INDEX idx_sessions_project_branch ON sessions(project_id, sprint_branch);

CREATE TABLE profiles_defs (
  id          TEXT PRIMARY KEY,
  project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  name        TEXT NOT NULL,
  kind        TEXT NOT NULL CHECK(kind IN ('modifier','extension','override')),
  config      TEXT NOT NULL CHECK(json_valid(config)),
  source_path TEXT,
  active      INTEGER NOT NULL DEFAULT 1,
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL,
  UNIQUE(project_id, name)
);

CREATE TABLE mem_entries (
  id          TEXT PRIMARY KEY,
  project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  kind        TEXT NOT NULL CHECK(kind IN ('doctrine','note','decision','incident','session')),
  title       TEXT NOT NULL,
  body        TEXT NOT NULL,
  tags        TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(tags)),
  pinned      INTEGER NOT NULL DEFAULT 0,
  source_path TEXT,
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL
);
CREATE INDEX idx_mem_project_kind   ON mem_entries(project_id, kind);
CREATE INDEX idx_mem_project_pinned ON mem_entries(project_id, pinned) WHERE pinned = 1;

CREATE TABLE index_symbols (
  id            TEXT PRIMARY KEY,
  project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  name          TEXT NOT NULL,
  kind          TEXT NOT NULL,
  package       TEXT NOT NULL,
  file_path     TEXT NOT NULL,
  line          INTEGER,
  visibility    TEXT,
  signature     TEXT,
  doc_summary   TEXT,
  language      TEXT NOT NULL,
  hash          TEXT NOT NULL,
  refreshed_at  INTEGER NOT NULL,
  UNIQUE(project_id, name, package, kind)
);
CREATE INDEX idx_symbols_project_name ON index_symbols(project_id, name);
CREATE INDEX idx_symbols_project_pkg  ON index_symbols(project_id, package);

CREATE TABLE index_concepts (
  id                  TEXT PRIMARY KEY,
  project_id          TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  concept             TEXT NOT NULL,
  canonical_symbol_id TEXT NOT NULL REFERENCES index_symbols(id) ON DELETE CASCADE,
  aliases_to_avoid    TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(aliases_to_avoid)),
  notes               TEXT,
  UNIQUE(project_id, concept)
);

CREATE TABLE index_issues (
  id           TEXT PRIMARY KEY,
  project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  source       TEXT NOT NULL,
  number       INTEGER NOT NULL,
  title        TEXT NOT NULL,
  state        TEXT NOT NULL,
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
  state        TEXT NOT NULL,
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

CREATE TABLE logs_events (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  ts            INTEGER NOT NULL,
  level         TEXT NOT NULL CHECK(level IN ('info','warn','error','gate','audit')),
  source        TEXT NOT NULL,
  event         TEXT NOT NULL,
  payload       TEXT CHECK(payload IS NULL OR json_valid(payload)),
  sprint_branch TEXT,
  session_id    TEXT
);
CREATE INDEX idx_logs_project_ts ON logs_events(project_id, ts);

CREATE TABLE artifacts (
  id            TEXT PRIMARY KEY,
  project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  kind          TEXT NOT NULL,
  path          TEXT NOT NULL,
  sprint_branch TEXT,
  title         TEXT,
  hash          TEXT NOT NULL,
  created_at    INTEGER NOT NULL,
  updated_at    INTEGER NOT NULL,
  UNIQUE(project_id, path)
);
CREATE INDEX idx_artifacts_project_kind ON artifacts(project_id, kind);
CREATE INDEX idx_artifacts_sprint       ON artifacts(project_id, sprint_branch);

CREATE TABLE locks_history (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  session_id   TEXT NOT NULL,
  mode         TEXT NOT NULL CHECK(mode IN ('autorun','parallel','start','plant','context')),
  acquired_at  INTEGER NOT NULL,
  released_at  INTEGER,
  released_by  TEXT CHECK(released_by IS NULL OR released_by IN ('normal','reap','force')),
  metadata     TEXT CHECK(metadata IS NULL OR json_valid(metadata))
);

-- Views
CREATE VIEW v_open_issues AS
  SELECT project_id, number, title, state, labels, milestone, assignees, url, updated_at
  FROM index_issues WHERE state = 'open' ORDER BY updated_at DESC;

CREATE VIEW v_canonical_types AS
  SELECT s.project_id, s.package, s.kind, s.name, s.signature, s.doc_summary,
         s.file_path, s.line, c.concept, c.aliases_to_avoid
  FROM index_symbols s
  LEFT JOIN index_concepts c ON c.canonical_symbol_id = s.id
  WHERE s.visibility IN ('pub','pub(crate)','export')
  ORDER BY s.package, s.name;

CREATE VIEW v_drift_risk AS
  SELECT project_id, number, title, milestone, labels
  FROM index_issues
  WHERE state = 'open'
    AND (labels LIKE '%"critical"%' OR labels LIKE '%"high"%');

CREATE VIEW v_mem_recent_7d AS
  SELECT * FROM mem_entries
  WHERE created_at >= unixepoch() - 7 * 86400 OR pinned = 1
  ORDER BY pinned DESC, created_at DESC;

CREATE VIEW v_active_locks AS
  SELECT * FROM locks_history WHERE released_at IS NULL ORDER BY acquired_at DESC;

INSERT INTO schema_versions (version, applied_at, checksum)
VALUES (1, unixepoch(), 'baseline-v5.0.0');

COMMIT;
```

- [ ] **Step 4: Write the standalone view files (mirror baseline so they can be re-applied independently)**

Each file is a `CREATE VIEW IF NOT EXISTS` statement copied from the section above. Example for `views/open-issues.sql`:

```sql
CREATE VIEW IF NOT EXISTS v_open_issues AS
  SELECT project_id, number, title, state, labels, milestone, assignees, url, updated_at
  FROM index_issues WHERE state = 'open' ORDER BY updated_at DESC;
```

Repeat the pattern for `canonical-types.sql`, `drift-risk.sql`, `mem-recent-7d.sql`, `active-locks.sql` using the corresponding view body.

- [ ] **Step 5: Run test, confirm pass**

```bash
bash plugins/shepherd/skills/context/tests/test_schema.sh
# Expected: passes silently (no FAIL output)
```

- [ ] **Step 6: Commit**

```bash
git add plugins/shepherd/skills/context/schema plugins/shepherd/skills/context/tests/test_schema.sh
git commit -m "feat(shepherd-context): schema 0001 + views + schema test"
```

---

## Task 3: `scripts/shctx` dispatcher (subcommand router)

**Files:**
- Create: `plugins/shepherd/skills/context/scripts/shctx`
- Create: `plugins/shepherd/skills/context/tests/test_dispatch.sh`

- [ ] **Step 1: Write the failing test**

```bash
# tests/test_dispatch.sh
#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"

# `shctx help` exits 0 and lists every subcommand.
out=$("$SHCTX" help)
for sub in init status refresh query inject profile mem lock lint migrate export; do
  assert_contains "help.$sub" "$out" "$sub"
done

# Unknown subcommand exits non-zero.
if "$SHCTX" notarealthing 2>/dev/null; then
  echo "FAIL: unknown subcommand should exit non-zero" >&2; exit 1
fi
```

```bash
chmod +x plugins/shepherd/skills/context/tests/test_dispatch.sh
```

- [ ] **Step 2: Run test, confirm fail**

```bash
bash plugins/shepherd/skills/context/tests/test_dispatch.sh
# Expected: FAIL (script not present)
```

- [ ] **Step 3: Write `scripts/shctx`**

```bash
#!/usr/bin/env bash
# /shepherd:context dispatcher.
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
export SHCTX_SKILL_ROOT="${SHCTX_SKILL_ROOT:-$(cd "$HERE/.." && pwd)}"
source "$HERE/_lib.sh"

usage() {
  cat <<'EOF'
shctx — shepherd context registry CLI

Usage: shctx <subcommand> [args]

Subcommands:
  init                    Scaffold .artifacts/ tree, create root.db, register host project
  status                  Row counts, refresh staleness, lock state, lint summary
  refresh [--scope=...]   Rebuild caches (symbols|github|artifacts|all)
  query <name> [--json|--md]
                          Run a pre-baked named query
  inject <role>           Emit a [DB-CONTEXT] block for an agent brief
  profile <list|show|enable|disable|sync> [args]
  mem <add|search|list|pin|unpin> [args]
  lock <show|acquire|release|reap> [args]
  lint                    Naming-convention check
  migrate                 Apply pending schema migrations
  export <kind> [--out=path]
  help                    Print this message
EOF
}

cmd="${1:-help}"; shift || true
case "$cmd" in
  help|-h|--help) usage ;;
  init|status|refresh|query|inject|profile|mem|lock|lint|migrate|export)
    impl="$HERE/cmd_${cmd}.sh"
    if [[ ! -f "$impl" ]]; then
      echo "ERROR: $cmd not yet implemented (missing $impl)" >&2; exit 2
    fi
    bash "$impl" "$@"
    ;;
  *)
    echo "ERROR: unknown subcommand: $cmd" >&2
    usage >&2
    exit 1 ;;
esac
```

```bash
chmod +x plugins/shepherd/skills/context/scripts/shctx
```

- [ ] **Step 4: Run test, confirm pass**

```bash
bash plugins/shepherd/skills/context/tests/test_dispatch.sh
```

- [ ] **Step 5: Commit**

```bash
git add plugins/shepherd/skills/context/scripts/shctx plugins/shepherd/skills/context/tests/test_dispatch.sh
git commit -m "feat(shepherd-context): shctx dispatcher"
```

---

## Task 4: `init` subcommand

**Files:**
- Create: `plugins/shepherd/skills/context/scripts/cmd_init.sh`
- Create: `plugins/shepherd/skills/context/scripts/scaffold.sh`
- Create: `plugins/shepherd/skills/context/tests/test_init.sh`

- [ ] **Step 1: Write the failing test**

```bash
# tests/test_init.sh
#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"

"$SHCTX" init

assert_file "$SHCTX_TEST_TMP/.artifacts/root.db"
assert_file "$SHCTX_TEST_TMP/.artifacts/project.json"
assert_file "$SHCTX_TEST_TMP/.artifacts/CONVENTIONS.md"
assert_file "$SHCTX_TEST_TMP/.artifacts/.gitignore"
for d in ctx plans reports docs/handoffs docs/specs docs/diagrams docs/journal logs tmp profiles; do
  [[ -d "$SHCTX_TEST_TMP/.artifacts/$d" ]] || { echo "FAIL: missing dir: $d" >&2; exit 1; }
done

# Exactly one project row, with id matching project.json.
pid=$(jq -r '.id' "$SHCTX_TEST_TMP/.artifacts/project.json")
db_pid=$(sqlite3 "$SHCTX_TEST_TMP/.artifacts/root.db" "SELECT id FROM projects;")
assert_eq "project_id" "$db_pid" "$pid"

# Idempotent: second init does NOT overwrite project.json.
"$SHCTX" init
pid2=$(jq -r '.id' "$SHCTX_TEST_TMP/.artifacts/project.json")
assert_eq "project_id_stable" "$pid2" "$pid"
```

- [ ] **Step 2: Write `scripts/scaffold.sh` and `scripts/cmd_init.sh`**

```bash
# scripts/scaffold.sh
#!/usr/bin/env bash
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

root="$(shctx_artifacts_root)"
mkdir -p "$root"/{ctx,plans,reports,docs/{handoffs,specs,diagrams,journal},logs,tmp,profiles}

# Per-project .gitignore (idempotent — only writes if absent).
gi="$root/.gitignore"
if [[ ! -f "$gi" ]]; then
  cat > "$gi" <<'EOF'
# shepherd context registry — gitignored by default.
# Remove these lines to commit the registry to the repo.
root.db
root.db-journal
root.db-wal
root.db-shm
shepherd.lock
project.json
tmp/
logs/
EOF
fi

# CONVENTIONS.md (idempotent).
conv="$root/CONVENTIONS.md"
if [[ ! -f "$conv" ]]; then
  cp "$(shctx_skill_root)/references/naming-conventions.md" "$conv"
fi
```

```bash
# scripts/cmd_init.sh
#!/usr/bin/env bash
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

bash "$HERE/scaffold.sh"

db="$(shctx_db_path)"
pidfile="$(shctx_project_id_path)"

# Apply schema if DB absent.
if [[ ! -f "$db" ]]; then
  sqlite3 "$db" < "$(shctx_skill_root)/schema/0001_init.sql"
fi

# Insert the host project row exactly once. Persist the UUID to project.json.
if [[ -f "$pidfile" ]]; then
  pid=$(jq -r '.id' "$pidfile")
else
  pid=$(shctx_uuid7)
  name=$(basename "$(shctx_repo_root)")
  scope_json=$(jq -nc --arg p "$(shctx_repo_root)" '[$p]')
  now=$(shctx_now)
  shctx_sql "INSERT OR IGNORE INTO projects (id,name,scope,tags,created_at,updated_at)
             VALUES ('$pid', '$name', '$scope_json', '[]', $now, $now);"
  jq -nc --arg id "$pid" --argjson at "$(shctx_now)" \
    '{id:$id, scaffolded_at:$at}' > "$pidfile"
fi

echo "shctx: initialized .artifacts/ at $(shctx_artifacts_root)"
echo "shctx: project_id = $pid"
```

```bash
chmod +x plugins/shepherd/skills/context/scripts/{scaffold.sh,cmd_init.sh} \
         plugins/shepherd/skills/context/tests/test_init.sh
```

Note: `references/naming-conventions.md` is created in Task 16; for this task's test to pass, write a minimal stub now: `echo "# Naming Conventions (stub — filled in Task 16)" > plugins/shepherd/skills/context/references/naming-conventions.md` and stage it with the commit.

- [ ] **Step 3: Run test, confirm pass**

```bash
bash plugins/shepherd/skills/context/tests/test_init.sh
```

- [ ] **Step 4: Commit**

```bash
git add plugins/shepherd/skills/context/scripts/{scaffold.sh,cmd_init.sh} \
        plugins/shepherd/skills/context/tests/test_init.sh \
        plugins/shepherd/skills/context/references/naming-conventions.md
git commit -m "feat(shepherd-context): init subcommand + scaffold"
```

---

## Task 5: `migrate` subcommand

**Files:**
- Create: `plugins/shepherd/skills/context/scripts/cmd_migrate.sh`
- Create: `plugins/shepherd/skills/context/tests/test_migrate.sh`

- [ ] **Step 1: Write the failing test**

```bash
# tests/test_migrate.sh
#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init

# 0001 already applied → migrate is a no-op.
out=$("$SHCTX" migrate)
assert_contains "noop" "$out" "no migrations pending"

# Drop a fake 0002.sql; migrate applies it.
mig="$SHCTX_SKILL_ROOT/schema/migrations/0002_test.sql"
trap 'rm -f "$mig"' EXIT
cat > "$mig" <<'SQL'
CREATE TABLE _migrate_probe (id INTEGER PRIMARY KEY);
SQL

out=$("$SHCTX" migrate)
assert_contains "applied" "$out" "0002"

v=$(sqlite3 "$SHCTX_TEST_TMP/.artifacts/root.db" "SELECT MAX(version) FROM schema_versions;")
assert_eq "max_version" "$v" "2"

# Idempotent: re-run is a no-op.
out=$("$SHCTX" migrate)
assert_contains "noop2" "$out" "no migrations pending"
```

- [ ] **Step 2: Write `scripts/cmd_migrate.sh`**

```bash
#!/usr/bin/env bash
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

migdir="$(shctx_skill_root)/schema/migrations"
[[ -d "$migdir" ]] || { echo "no migrations dir"; exit 0; }

current=$(shctx_sql "SELECT COALESCE(MAX(version),0) FROM schema_versions;")
applied=0
shopt -s nullglob
for f in "$migdir"/[0-9][0-9][0-9][0-9]_*.sql; do
  fname=$(basename "$f")
  num=${fname:0:4}
  v=$((10#$num))
  (( v > current )) || continue
  echo "shctx migrate: applying $fname"
  sum=$(shasum -a 256 "$f" | awk '{print $1}')
  sqlite3 "$(shctx_db_path)" < "$f"
  shctx_sql "INSERT INTO schema_versions (version, applied_at, checksum)
             VALUES ($v, $(shctx_now), '$sum');"
  applied=$((applied+1))
done
if (( applied == 0 )); then
  echo "shctx migrate: no migrations pending (at version $current)"
else
  echo "shctx migrate: applied $applied migration(s)"
fi
```

```bash
chmod +x plugins/shepherd/skills/context/scripts/cmd_migrate.sh \
         plugins/shepherd/skills/context/tests/test_migrate.sh
```

- [ ] **Step 3: Run test, confirm pass**

```bash
bash plugins/shepherd/skills/context/tests/test_migrate.sh
```

- [ ] **Step 4: Commit**

```bash
git add plugins/shepherd/skills/context/scripts/cmd_migrate.sh \
        plugins/shepherd/skills/context/tests/test_migrate.sh
git commit -m "feat(shepherd-context): migrate subcommand"
```

---

## Task 6: `status` subcommand

**Files:**
- Create: `plugins/shepherd/skills/context/scripts/cmd_status.sh`
- Create: `plugins/shepherd/skills/context/tests/test_status.sh`

- [ ] **Step 1: Write the failing test**

```bash
# tests/test_status.sh
#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init

out=$("$SHCTX" status)
for tok in "Schema version" "Tables" "projects" "index_symbols" "Lock"; do
  assert_contains "status.$tok" "$out" "$tok"
done
```

- [ ] **Step 2: Write `scripts/cmd_status.sh`**

```bash
#!/usr/bin/env bash
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

db="$(shctx_db_path)"
[[ -f "$db" ]] || { echo "ERROR: no DB at $db — run 'shctx init'" >&2; exit 1; }

echo "Schema version: $(shctx_sql 'SELECT MAX(version) FROM schema_versions;')"
echo
echo "Tables (rows):"
for t in projects sessions profiles_defs mem_entries \
         index_symbols index_concepts index_issues index_prs \
         index_releases index_milestones logs_events artifacts \
         locks_history; do
  n=$(shctx_sql "SELECT COUNT(*) FROM $t;")
  printf "  %-20s %s\n" "$t" "$n"
done
echo
echo "Refresh staleness:"
for t in index_symbols index_issues index_prs index_releases index_milestones; do
  last=$(shctx_sql "SELECT COALESCE(MAX(refreshed_at),0) FROM $t;")
  if [[ "$last" -eq 0 ]]; then
    age="never"
  else
    age="$(( ($(shctx_now) - last) / 60 )) min ago"
  fi
  printf "  %-20s %s\n" "$t" "$age"
done
echo
lock="$(shctx_lock_path)"
if [[ -f "$lock" ]]; then
  echo "Lock: held"
  jq . "$lock"
else
  echo "Lock: free"
fi
```

- [ ] **Step 3: Run test, confirm pass; commit**

```bash
chmod +x plugins/shepherd/skills/context/scripts/cmd_status.sh \
         plugins/shepherd/skills/context/tests/test_status.sh
bash plugins/shepherd/skills/context/tests/test_status.sh
git add plugins/shepherd/skills/context/scripts/cmd_status.sh \
        plugins/shepherd/skills/context/tests/test_status.sh
git commit -m "feat(shepherd-context): status subcommand"
```

---

## Task 7: `refresh --scope=symbols` (Rust extractor)

**Files:**
- Create: `plugins/shepherd/skills/context/scripts/cmd_refresh.sh`
- Create: `plugins/shepherd/skills/context/scripts/refresh-symbols.sh`
- Create: `plugins/shepherd/skills/context/tests/test_refresh_symbols.sh`

- [ ] **Step 1: Write the failing test (small fake Rust crate inside the test repo)**

```bash
# tests/test_refresh_symbols.sh
#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init

# Create a fake Rust crate (no cargo build needed — only `cargo metadata` is invoked).
mkdir -p src
cat > Cargo.toml <<'EOF'
[package]
name = "probe"
version = "0.0.1"
edition = "2021"
EOF
cat > src/lib.rs <<'EOF'
pub struct DriftCircuit;
pub trait Tick {}
pub fn allocate() {}
EOF

command -v cargo >/dev/null || { echo "skip: cargo not installed"; exit 0; }

"$SHCTX" refresh --scope=symbols

count=$(sqlite3 "$SHCTX_TEST_TMP/.artifacts/root.db" \
  "SELECT COUNT(*) FROM index_symbols WHERE language='rust';")
[[ "$count" -ge 3 ]] || { echo "FAIL: expected ≥3 symbols, got $count" >&2; exit 1; }
sqlite3 "$SHCTX_TEST_TMP/.artifacts/root.db" \
  "SELECT name FROM index_symbols WHERE name='DriftCircuit';" \
  | grep -q DriftCircuit || { echo "FAIL: DriftCircuit not indexed" >&2; exit 1; }
```

- [ ] **Step 2: Write `scripts/refresh-symbols.sh`**

```bash
#!/usr/bin/env bash
# Rust symbol extractor — best-effort grep-based (v5.0.0). Tree-sitter in v5.x.
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

command -v cargo >/dev/null || { echo "shctx: cargo not installed; skipping rust symbols"; exit 0; }
project_id=$(shctx_project_id)
now=$(shctx_now)

# Enumerate workspace packages via `cargo metadata`.
mapfile -t pkgs < <(cargo metadata --format-version 1 --no-deps 2>/dev/null \
  | jq -r '.packages[] | "\(.name)\t\(.manifest_path)"')

(( ${#pkgs[@]} > 0 )) || { echo "shctx: no rust packages found"; exit 0; }

shctx_sql "BEGIN;"
for row in "${pkgs[@]}"; do
  name=${row%%$'\t'*}
  manifest=${row##*$'\t'}
  pkg_dir=$(dirname "$manifest")
  rel_pkg=${pkg_dir#$(shctx_repo_root)/}

  while IFS= read -r -d '' f; do
    rel=${f#$(shctx_repo_root)/}
    grep -nE '^[[:space:]]*(pub(\([^)]+\))?[[:space:]]+)?(fn|struct|trait|enum|const|static|type|mod)[[:space:]]+[A-Za-z_][A-Za-z0-9_]*' "$f" \
      | while IFS=: read -r line content; do
          # Parse: visibility, kind, name, signature.
          vis="private"; kind=""; sym=""
          if [[ "$content" =~ ^[[:space:]]*(pub(\([^\)]+\))?)[[:space:]]+(fn|struct|trait|enum|const|static|type|mod)[[:space:]]+([A-Za-z_][A-Za-z0-9_]*) ]]; then
            vis=${BASH_REMATCH[1]}
            kind=${BASH_REMATCH[3]}
            sym=${BASH_REMATCH[4]}
          elif [[ "$content" =~ ^[[:space:]]*(fn|struct|trait|enum|const|static|type|mod)[[:space:]]+([A-Za-z_][A-Za-z0-9_]*) ]]; then
            kind=${BASH_REMATCH[1]}
            sym=${BASH_REMATCH[2]}
          else
            continue
          fi
          sig=$(echo "$content" | sed -e 's/^[[:space:]]*//' -e "s/'/''/g")
          hash=$(printf '%s' "$rel:$line:$sig" | shasum -a 256 | awk '{print $1}')
          uid=$(shctx_uuid7)
          shctx_sql "INSERT INTO index_symbols
            (id, project_id, name, kind, package, file_path, line, visibility, signature, doc_summary, language, hash, refreshed_at)
            VALUES ('$uid','$project_id','$sym','$kind','$rel_pkg','$rel',$line,'$vis','$sig',NULL,'rust','$hash',$now)
            ON CONFLICT(project_id,name,package,kind) DO UPDATE SET
              file_path=excluded.file_path, line=excluded.line,
              visibility=excluded.visibility, signature=excluded.signature,
              hash=excluded.hash, refreshed_at=excluded.refreshed_at;"
        done
  done < <(find "$pkg_dir/src" -type f -name '*.rs' -print0 2>/dev/null)
done

# Sweep stale rows (rust only) older than this run.
shctx_sql "DELETE FROM index_symbols WHERE project_id='$project_id' AND language='rust' AND refreshed_at<$now;"
shctx_sql "COMMIT;"
echo "shctx refresh symbols: ok"
```

- [ ] **Step 3: Write `scripts/cmd_refresh.sh` (dispatcher; symbols only for now)**

```bash
#!/usr/bin/env bash
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

scope="all"
for arg in "$@"; do
  case "$arg" in
    --scope=*) scope="${arg#--scope=}" ;;
    *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
  esac
done

case "$scope" in
  symbols)   bash "$HERE/refresh-symbols.sh" ;;
  github)    bash "$HERE/refresh-github.sh" ;;
  artifacts) bash "$HERE/refresh-artifacts.sh" ;;
  all)
    bash "$HERE/refresh-symbols.sh"
    bash "$HERE/refresh-github.sh" || true
    bash "$HERE/refresh-artifacts.sh"
    ;;
  *) echo "ERROR: unknown --scope: $scope" >&2; exit 1 ;;
esac
```

- [ ] **Step 4: Run test, confirm pass; commit**

```bash
chmod +x plugins/shepherd/skills/context/scripts/{cmd_refresh.sh,refresh-symbols.sh} \
         plugins/shepherd/skills/context/tests/test_refresh_symbols.sh
bash plugins/shepherd/skills/context/tests/test_refresh_symbols.sh
git add plugins/shepherd/skills/context/scripts/{cmd_refresh.sh,refresh-symbols.sh} \
        plugins/shepherd/skills/context/tests/test_refresh_symbols.sh
git commit -m "feat(shepherd-context): refresh --scope=symbols (rust)"
```

---

## Task 8: `refresh --scope=github`

**Files:**
- Create: `plugins/shepherd/skills/context/scripts/refresh-github.sh`
- Create: `plugins/shepherd/skills/context/tests/test_refresh_github.sh`

- [ ] **Step 1: Write the failing test (uses `gh` mock)**

```bash
# tests/test_refresh_github.sh
#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init

# Mock `gh` with a shim on PATH.
mock_dir="$SHCTX_TEST_TMP/mock"
mkdir -p "$mock_dir"
cat > "$mock_dir/gh" <<'SH'
#!/usr/bin/env bash
case "$* " in
  *"issue list"*)    cat <<EOF
[{"number":1,"title":"first","state":"OPEN","labels":[{"name":"bug"}],"milestone":null,"assignees":[],"body":"b","url":"u","createdAt":"2025-01-01T00:00:00Z","updatedAt":"2025-01-02T00:00:00Z"}]
EOF
;;
  *"pr list"*)       echo '[]' ;;
  *"release list"*)  echo '[]' ;;
  *"api"*"milestones"*) echo '[]' ;;
  *"repo view"*)     echo '{"nameWithOwner":"acme/probe"}' ;;
  *) echo '[]' ;;
esac
SH
chmod +x "$mock_dir/gh"
PATH="$mock_dir:$PATH" "$SHCTX" refresh --scope=github

n=$(sqlite3 "$SHCTX_TEST_TMP/.artifacts/root.db" "SELECT COUNT(*) FROM index_issues;")
assert_eq "issue_count" "$n" "1"
title=$(sqlite3 "$SHCTX_TEST_TMP/.artifacts/root.db" "SELECT title FROM index_issues;")
assert_eq "issue_title" "$title" "first"
```

- [ ] **Step 2: Write `scripts/refresh-github.sh`**

```bash
#!/usr/bin/env bash
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

command -v gh >/dev/null || { echo "shctx: gh CLI not installed; skipping github refresh"; exit 0; }
command -v jq >/dev/null || { echo "shctx: jq required"; exit 1; }

project_id=$(shctx_project_id)
now=$(shctx_now)
repo=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || echo "unknown/unknown")

epoch_iso() { date -j -f "%Y-%m-%dT%H:%M:%SZ" "$1" +%s 2>/dev/null || date -d "$1" +%s 2>/dev/null || echo 0; }

shctx_sql "BEGIN;"

# Issues
gh issue list --state all --limit 500 \
  --json number,title,state,labels,milestone,assignees,body,url,createdAt,updatedAt \
  | jq -c '.[]' | while read -r row; do
  num=$(jq -r .number <<<"$row")
  id="github:$repo#$num"
  title=$(jq -r .title <<<"$row" | sed "s/'/''/g")
  state=$(jq -r '.state | ascii_downcase' <<<"$row")
  labels=$(jq -c '[.labels[].name]' <<<"$row")
  milestone=$(jq -r '.milestone.title // empty' <<<"$row")
  assignees=$(jq -c '[.assignees[].login]' <<<"$row")
  body=$(jq -r .body <<<"$row" | sed "s/'/''/g")
  url=$(jq -r .url <<<"$row")
  ca=$(epoch_iso "$(jq -r .createdAt <<<"$row")")
  ua=$(epoch_iso "$(jq -r .updatedAt <<<"$row")")
  shctx_sql "INSERT INTO index_issues
    (id, project_id, source, number, title, state, labels, milestone, assignees, body, url, created_at, updated_at, refreshed_at)
    VALUES ('$id','$project_id','github',$num,'$title','$state','$labels','${milestone:-NULL}','$assignees','$body','$url',$ca,$ua,$now)
    ON CONFLICT(id) DO UPDATE SET
      title=excluded.title, state=excluded.state, labels=excluded.labels,
      milestone=excluded.milestone, assignees=excluded.assignees, body=excluded.body,
      url=excluded.url, updated_at=excluded.updated_at, refreshed_at=excluded.refreshed_at;"
done

# PRs
gh pr list --state all --limit 500 \
  --json number,title,state,baseRefName,headRefName,labels,url,createdAt,updatedAt,mergedAt \
  | jq -c '.[]' | while read -r row; do
  num=$(jq -r .number <<<"$row")
  id="github:$repo#pr$num"
  title=$(jq -r .title <<<"$row" | sed "s/'/''/g")
  state=$(jq -r '.state | ascii_downcase' <<<"$row")
  base=$(jq -r .baseRefName <<<"$row")
  head=$(jq -r .headRefName <<<"$row")
  labels=$(jq -c '[.labels[].name]' <<<"$row")
  url=$(jq -r .url <<<"$row")
  ca=$(epoch_iso "$(jq -r .createdAt <<<"$row")")
  ua=$(epoch_iso "$(jq -r .updatedAt <<<"$row")")
  ma=$(jq -r '.mergedAt // empty' <<<"$row")
  ma_e=$([[ -n "$ma" ]] && epoch_iso "$ma" || echo NULL)
  shctx_sql "INSERT INTO index_prs
    (id, project_id, source, number, title, state, base_branch, head_branch, labels, url, created_at, updated_at, merged_at, refreshed_at)
    VALUES ('$id','$project_id','github',$num,'$title','$state','$base','$head','$labels','$url',$ca,$ua,$ma_e,$now)
    ON CONFLICT(id) DO UPDATE SET
      title=excluded.title, state=excluded.state, labels=excluded.labels,
      url=excluded.url, updated_at=excluded.updated_at, merged_at=excluded.merged_at, refreshed_at=excluded.refreshed_at;"
done

# Releases
gh release list --limit 200 --json tagName,name,isDraft,isPrerelease,publishedAt,url \
  | jq -c '.[]' | while read -r row; do
  tag=$(jq -r .tagName <<<"$row")
  id="github:$repo:tag:$tag"
  name=$(jq -r '.name // empty' <<<"$row" | sed "s/'/''/g")
  draft=$(jq -r 'if .isDraft then 1 else 0 end' <<<"$row")
  pre=$(jq -r 'if .isPrerelease then 1 else 0 end' <<<"$row")
  url=$(jq -r .url <<<"$row")
  pa=$(jq -r '.publishedAt // empty' <<<"$row")
  pa_e=$([[ -n "$pa" ]] && epoch_iso "$pa" || echo NULL)
  shctx_sql "INSERT INTO index_releases
    (id, project_id, source, tag, name, prerelease, draft, body, url, published_at, refreshed_at)
    VALUES ('$id','$project_id','github','$tag','$name',$pre,$draft,NULL,'$url',$pa_e,$now)
    ON CONFLICT(project_id,source,tag) DO UPDATE SET
      name=excluded.name, prerelease=excluded.prerelease, draft=excluded.draft,
      url=excluded.url, published_at=excluded.published_at, refreshed_at=excluded.refreshed_at;"
done

# Milestones (REST API)
gh api "repos/$repo/milestones?state=all&per_page=100" 2>/dev/null \
  | jq -c '.[]?' | while read -r row; do
  num=$(jq -r .number <<<"$row")
  id="github:$repo:ms:$num"
  title=$(jq -r .title <<<"$row" | sed "s/'/''/g")
  state=$(jq -r .state <<<"$row")
  due=$(jq -r '.due_on // empty' <<<"$row")
  due_e=$([[ -n "$due" ]] && epoch_iso "$due" || echo NULL)
  desc=$(jq -r '.description // empty' <<<"$row" | sed "s/'/''/g")
  url=$(jq -r .html_url <<<"$row")
  shctx_sql "INSERT INTO index_milestones
    (id, project_id, source, number, title, state, due_on, description, url, refreshed_at)
    VALUES ('$id','$project_id','github',$num,'$title','$state',$due_e,'$desc','$url',$now)
    ON CONFLICT(project_id,source,number) DO UPDATE SET
      title=excluded.title, state=excluded.state, due_on=excluded.due_on,
      description=excluded.description, url=excluded.url, refreshed_at=excluded.refreshed_at;"
done

shctx_sql "COMMIT;"
echo "shctx refresh github: ok"
```

- [ ] **Step 3: Run test; commit**

```bash
chmod +x plugins/shepherd/skills/context/scripts/refresh-github.sh \
         plugins/shepherd/skills/context/tests/test_refresh_github.sh
bash plugins/shepherd/skills/context/tests/test_refresh_github.sh
git add plugins/shepherd/skills/context/scripts/refresh-github.sh \
        plugins/shepherd/skills/context/tests/test_refresh_github.sh
git commit -m "feat(shepherd-context): refresh --scope=github (gh CLI)"
```

---

## Task 9: `refresh --scope=artifacts` and `--scope=all`

**Files:**
- Create: `plugins/shepherd/skills/context/scripts/refresh-artifacts.sh`
- Create: `plugins/shepherd/skills/context/tests/test_refresh_artifacts.sh`

- [ ] **Step 1: Write the failing test**

```bash
# tests/test_refresh_artifacts.sh
#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init

mkdir -p .artifacts/plans .artifacts/reports .artifacts/docs/specs
echo "# seed" > .artifacts/plans/v0.0.1-dev.0.seed.md
echo "# plan" > .artifacts/plans/v0.0.1-dev.0.plan.md
echo "# close" > .artifacts/reports/2026-01-01-v0.0.1-dev.0.close.md
echo "# spec" > .artifacts/docs/specs/2026-01-01-foo.spec.md

"$SHCTX" refresh --scope=artifacts

for k in seed plan close spec; do
  n=$(sqlite3 "$SHCTX_TEST_TMP/.artifacts/root.db" "SELECT COUNT(*) FROM artifacts WHERE kind='$k';")
  [[ "$n" -ge 1 ]] || { echo "FAIL: kind=$k not indexed (got $n)" >&2; exit 1; }
done
```

- [ ] **Step 2: Write `scripts/refresh-artifacts.sh`**

```bash
#!/usr/bin/env bash
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

project_id=$(shctx_project_id)
now=$(shctx_now)
root="$(shctx_artifacts_root)"

classify() {
  local f="$1"
  case "$f" in
    *.seed.md)    echo seed ;;
    *.plan.md)    echo plan ;;
    *.phase0.md)  echo phase0 ;;
    *.close.md)   echo close ;;
    *.walk.md)    echo walk ;;
    *.handoff.md) echo handoff ;;
    *.spec.md)    echo spec ;;
    *.design.md)  echo design ;;
    */docs/diagrams/*) echo diagram ;;
    */docs/journal/*)  echo journal ;;
    *) echo "" ;;
  esac
}

shctx_sql "BEGIN;"
while IFS= read -r -d '' f; do
  rel=${f#$(shctx_repo_root)/}
  kind=$(classify "$f")
  [[ -n "$kind" ]] || continue
  hash=$(shasum -a 256 "$f" | awk '{print $1}')
  title=$(head -1 "$f" | sed -E 's/^#+ //;s/'\''/''/g' | head -c 200)
  uid=$(shctx_uuid7)
  shctx_sql "INSERT INTO artifacts
    (id, project_id, kind, path, sprint_branch, title, hash, created_at, updated_at)
    VALUES ('$uid','$project_id','$kind','$rel',NULL,'$title','$hash',$now,$now)
    ON CONFLICT(project_id, path) DO UPDATE SET
      kind=excluded.kind, title=excluded.title, hash=excluded.hash, updated_at=excluded.updated_at;"
done < <(find "$root" -type f -name '*.md' -print0)
shctx_sql "COMMIT;"
echo "shctx refresh artifacts: ok"
```

- [ ] **Step 3: Run test; commit**

```bash
chmod +x plugins/shepherd/skills/context/scripts/refresh-artifacts.sh \
         plugins/shepherd/skills/context/tests/test_refresh_artifacts.sh
bash plugins/shepherd/skills/context/tests/test_refresh_artifacts.sh
git add plugins/shepherd/skills/context/scripts/refresh-artifacts.sh \
        plugins/shepherd/skills/context/tests/test_refresh_artifacts.sh
git commit -m "feat(shepherd-context): refresh --scope=artifacts + --scope=all"
```

---

## Task 10: `query`, `inject`, `export`, `lint` subcommands

**Files:**
- Create: `plugins/shepherd/skills/context/queries/{canonical-types,dedup-check,drift-risk,open-issues,open-prs,recent-releases,mem-search}.sql`
- Create: `plugins/shepherd/skills/context/scripts/cmd_{query,inject,export,lint}.sh`
- Create: `plugins/shepherd/skills/context/tests/test_{query,inject,export,lint}.sh`

- [ ] **Step 1: Write query SQL files**

`queries/canonical-types.sql`:
```sql
-- usage: shctx query canonical-types
SELECT package, kind, name, signature, file_path, line, concept,
       json(aliases_to_avoid) AS aliases
FROM v_canonical_types
WHERE project_id = :project_id
ORDER BY package, name;
```

`queries/dedup-check.sql`:
```sql
-- usage: shctx query dedup-check --name=DriftCircuit
SELECT name, kind, package, file_path, line, signature
FROM index_symbols
WHERE project_id = :project_id AND name = :name;
```

`queries/drift-risk.sql`:
```sql
SELECT number, title, milestone, json(labels) AS labels
FROM v_drift_risk WHERE project_id = :project_id;
```

`queries/open-issues.sql`:
```sql
SELECT number, title, state, json(labels) AS labels, milestone, url, updated_at
FROM v_open_issues WHERE project_id = :project_id;
```

`queries/open-prs.sql`:
```sql
SELECT number, title, state, head_branch, base_branch, url, updated_at
FROM index_prs WHERE project_id = :project_id AND state = 'open' ORDER BY updated_at DESC;
```

`queries/recent-releases.sql`:
```sql
SELECT tag, name, prerelease, draft, url, published_at
FROM index_releases WHERE project_id = :project_id
ORDER BY published_at DESC LIMIT 25;
```

`queries/mem-search.sql`:
```sql
-- usage: shctx query mem-search --q=<term>
SELECT id, kind, title, body, json(tags) AS tags, pinned, created_at
FROM mem_entries
WHERE project_id = :project_id AND (title LIKE :q OR body LIKE :q)
ORDER BY pinned DESC, created_at DESC LIMIT 50;
```

- [ ] **Step 2: Write `scripts/cmd_query.sh`**

```bash
#!/usr/bin/env bash
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

name="${1:-}"; shift || true
[[ -n "$name" ]] || { echo "ERROR: usage: shctx query <name> [--json|--md] [--key=val ...]" >&2; exit 1; }

fmt="md"
declare -A bind=()
for a in "$@"; do
  case "$a" in
    --json) fmt=json ;;
    --md)   fmt=md ;;
    --*=*)  k=${a%%=*}; k=${k#--}; v=${a#*=}; bind[$k]="$v" ;;
    *) echo "ERROR: bad arg: $a" >&2; exit 1 ;;
  esac
done

f="$(shctx_skill_root)/queries/$name.sql"
[[ -f "$f" ]] || { echo "ERROR: query not found: $name" >&2; exit 1; }

project_id=$(shctx_project_id)
sql=$(cat "$f")
sql=${sql//:project_id/\'$project_id\'}
for k in "${!bind[@]}"; do
  v=${bind[$k]//\'/\'\'}
  sql=${sql//:$k/\'$v\'}
done

case "$fmt" in
  json) shctx_sql -json "$sql" ;;
  md)
    shctx_sql -header -markdown "$sql" 2>/dev/null \
      || shctx_sql -header -column "$sql"
    ;;
esac
```

- [ ] **Step 3: Write `scripts/cmd_inject.sh`** (engineer/coder/auditor variants)

```bash
#!/usr/bin/env bash
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

role="${1:-}"
[[ -n "$role" ]] || { echo "ERROR: usage: shctx inject <engineer|coder|auditor>" >&2; exit 1; }

emit_block() { echo "[DB-CONTEXT]"; echo "$1"; echo "[/DB-CONTEXT]"; }

case "$role" in
  engineer)
    issues=$(bash "$HERE/cmd_query.sh" open-issues --md)
    drift=$(bash "$HERE/cmd_query.sh" drift-risk --md)
    types=$(bash "$HERE/cmd_query.sh" canonical-types --md | head -50)
    emit_block "$(printf '## Open issues\n%s\n\n## Drift risk\n%s\n\n## Canonical types (top 50)\n%s\n' "$issues" "$drift" "$types")"
    ;;
  coder)
    types=$(bash "$HERE/cmd_query.sh" canonical-types --md | head -100)
    emit_block "$(printf '## Existing canonical types — REUSE; do not duplicate\n%s\n' "$types")"
    ;;
  auditor)
    issues=$(bash "$HERE/cmd_query.sh" open-issues --md)
    prs=$(bash "$HERE/cmd_query.sh" open-prs --md)
    emit_block "$(printf '## Open issues\n%s\n\n## Open PRs\n%s\n' "$issues" "$prs")"
    ;;
  *) echo "ERROR: unknown role: $role" >&2; exit 1 ;;
esac
```

- [ ] **Step 4: Write `scripts/cmd_export.sh`**

```bash
#!/usr/bin/env bash
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

kind="${1:-}"; shift || true
out=""
for a in "$@"; do
  case "$a" in --out=*) out="${a#--out=}" ;; esac
done

case "$kind" in
  canonical-types) data=$(bash "$HERE/cmd_query.sh" canonical-types --md) ;;
  open-issues)     data=$(bash "$HERE/cmd_query.sh" open-issues --md) ;;
  *) echo "ERROR: unknown export kind: $kind" >&2; exit 1 ;;
esac

if [[ -n "$out" ]]; then
  printf '%s\n' "$data" > "$out"
  echo "wrote $out"
else
  printf '%s\n' "$data"
fi
```

- [ ] **Step 5: Write `scripts/cmd_lint.sh`**

```bash
#!/usr/bin/env bash
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

root="$(shctx_artifacts_root)"
fail=0

# Files in plans/ must end in *.seed.md or *.plan.md.
while IFS= read -r -d '' f; do
  case "$(basename "$f")" in
    *.seed.md|*.plan.md) ;;
    *) echo "lint: $f does not match *.seed.md or *.plan.md"; fail=1 ;;
  esac
done < <(find "$root/plans" -type f -name '*.md' -print0 2>/dev/null)

# Files in reports/ must end in *.phase0.md, *.close.md, or *.walk.md.
while IFS= read -r -d '' f; do
  case "$(basename "$f")" in
    *.phase0.md|*.close.md|*.walk.md) ;;
    *) echo "lint: $f does not match *.phase0.md|*.close.md|*.walk.md"; fail=1 ;;
  esac
done < <(find "$root/reports" -type f -name '*.md' -print0 2>/dev/null)

# Files in docs/journal/ must match YYYY-MM-DD.md.
while IFS= read -r -d '' f; do
  case "$(basename "$f")" in
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].md) ;;
    *) echo "lint: $f does not match YYYY-MM-DD.md"; fail=1 ;;
  esac
done < <(find "$root/docs/journal" -type f -name '*.md' -print0 2>/dev/null)

if (( fail == 0 )); then
  echo "lint: ok"
else
  echo "lint: FAIL ($fail violation(s))"
  exit 1
fi
```

- [ ] **Step 6: Write tests**

```bash
# tests/test_query.sh
#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init
out=$("$SHCTX" query open-issues --json)
assert_eq "empty_json" "$out" ""

# Insert a row directly and query it.
db="$SHCTX_TEST_TMP/.artifacts/root.db"
pid=$(jq -r .id "$SHCTX_TEST_TMP/.artifacts/project.json")
sqlite3 "$db" "INSERT INTO index_issues VALUES ('x','$pid','github',1,'t','open','[]',NULL,'[]','b','u',1,1,1);"
out=$("$SHCTX" query open-issues --json)
assert_contains "json.t" "$out" '"title":"t"'
```

```bash
# tests/test_inject.sh
#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init
for r in engineer coder auditor; do
  out=$("$SHCTX" inject "$r")
  assert_contains "$r" "$out" "[DB-CONTEXT]"
  assert_contains "$r.close" "$out" "[/DB-CONTEXT]"
done
```

```bash
# tests/test_export.sh
#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init
"$SHCTX" export canonical-types --out="$SHCTX_TEST_TMP/out.md"
assert_file "$SHCTX_TEST_TMP/out.md"
```

```bash
# tests/test_lint.sh
#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init
"$SHCTX" lint  # empty tree → ok
echo "x" > .artifacts/plans/badname.md
if "$SHCTX" lint 2>/dev/null; then echo "FAIL: lint should reject badname.md" >&2; exit 1; fi
rm .artifacts/plans/badname.md
"$SHCTX" lint
```

- [ ] **Step 7: Run tests; commit**

```bash
chmod +x plugins/shepherd/skills/context/scripts/cmd_{query,inject,export,lint}.sh \
         plugins/shepherd/skills/context/tests/test_{query,inject,export,lint}.sh
for t in test_query.sh test_inject.sh test_export.sh test_lint.sh; do
  bash "plugins/shepherd/skills/context/tests/$t"
done
git add plugins/shepherd/skills/context/queries \
        plugins/shepherd/skills/context/scripts/cmd_{query,inject,export,lint}.sh \
        plugins/shepherd/skills/context/tests/test_{query,inject,export,lint}.sh
git commit -m "feat(shepherd-context): query/inject/export/lint subcommands"
```

---

## Task 11: `mem` subcommand

**Files:**
- Create: `plugins/shepherd/skills/context/scripts/cmd_mem.sh`
- Create: `plugins/shepherd/skills/context/tests/test_mem.sh`

- [ ] **Step 1: Write the failing test**

```bash
# tests/test_mem.sh
#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init

id=$("$SHCTX" mem add --kind=note --title="t" --body="b")
[[ "$id" =~ ^[0-9a-f-]+$ ]] || { echo "FAIL: id format: $id"; exit 1; }
out=$("$SHCTX" mem list)
assert_contains "list" "$out" "t"
"$SHCTX" mem pin "$id"
n=$(sqlite3 "$SHCTX_TEST_TMP/.artifacts/root.db" "SELECT pinned FROM mem_entries WHERE id='$id';")
assert_eq "pinned" "$n" "1"
"$SHCTX" mem unpin "$id"
n=$(sqlite3 "$SHCTX_TEST_TMP/.artifacts/root.db" "SELECT pinned FROM mem_entries WHERE id='$id';")
assert_eq "unpinned" "$n" "0"
out=$("$SHCTX" mem search --q=t)
assert_contains "search" "$out" "t"
```

- [ ] **Step 2: Write `scripts/cmd_mem.sh`**

```bash
#!/usr/bin/env bash
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

sub="${1:-}"; shift || true
project_id=$(shctx_project_id)
now=$(shctx_now)

parse_kv() {
  for a in "$@"; do
    case "$a" in
      --kind=*)  KIND="${a#--kind=}" ;;
      --title=*) TITLE="${a#--title=}" ;;
      --body=*)  BODY="${a#--body=}" ;;
      --tags=*)  TAGS="${a#--tags=}" ;;
      --q=*)     Q="${a#--q=}" ;;
    esac
  done
}

case "$sub" in
  add)
    KIND="note"; TITLE=""; BODY=""; TAGS="[]"; parse_kv "$@"
    [[ -n "$TITLE" ]] || { echo "ERROR: --title required" >&2; exit 1; }
    id=$(shctx_uuid7)
    body_esc=${BODY//\'/\'\'}
    title_esc=${TITLE//\'/\'\'}
    shctx_sql "INSERT INTO mem_entries (id,project_id,kind,title,body,tags,pinned,created_at,updated_at)
               VALUES ('$id','$project_id','$KIND','$title_esc','$body_esc','$TAGS',0,$now,$now);"
    echo "$id"
    ;;
  list)
    shctx_sql -header -column \
      "SELECT id, kind, title, pinned, created_at FROM mem_entries WHERE project_id='$project_id' ORDER BY pinned DESC, created_at DESC;"
    ;;
  search)
    Q=""; parse_kv "$@"
    q_esc="%${Q//\'/\'\'}%"
    shctx_sql -header -column \
      "SELECT id, kind, title FROM mem_entries WHERE project_id='$project_id' AND (title LIKE '$q_esc' OR body LIKE '$q_esc');"
    ;;
  pin|unpin)
    id="${1:-}"; [[ -n "$id" ]] || { echo "ERROR: usage: shctx mem $sub <id>" >&2; exit 1; }
    val=$([[ "$sub" == "pin" ]] && echo 1 || echo 0)
    shctx_sql "UPDATE mem_entries SET pinned=$val, updated_at=$now WHERE id='$id' AND project_id='$project_id';"
    ;;
  *) echo "ERROR: usage: shctx mem <add|list|search|pin|unpin>" >&2; exit 1 ;;
esac
```

- [ ] **Step 3: Run test; commit**

```bash
chmod +x plugins/shepherd/skills/context/scripts/cmd_mem.sh \
         plugins/shepherd/skills/context/tests/test_mem.sh
bash plugins/shepherd/skills/context/tests/test_mem.sh
git add plugins/shepherd/skills/context/scripts/cmd_mem.sh \
        plugins/shepherd/skills/context/tests/test_mem.sh
git commit -m "feat(shepherd-context): mem subcommand (replaces remember plugin)"
```

---

## Task 12: `profile` subcommand

**Files:**
- Create: `plugins/shepherd/skills/context/scripts/cmd_profile.sh`
- Create: `plugins/shepherd/skills/context/tests/test_profile.sh`

- [ ] **Step 1: Write the failing test**

```bash
# tests/test_profile.sh
#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init

cat > .artifacts/profiles/skip-critic-xs.toml <<'EOF'
name = "skip-critic-xs"
kind = "modifier"
[config]
skip_critic_for = ["XS"]
EOF

"$SHCTX" profile sync
n=$(sqlite3 "$SHCTX_TEST_TMP/.artifacts/root.db" \
  "SELECT COUNT(*) FROM profiles_defs WHERE name='skip-critic-xs';")
assert_eq "synced" "$n" "1"

"$SHCTX" profile disable skip-critic-xs
a=$(sqlite3 "$SHCTX_TEST_TMP/.artifacts/root.db" \
  "SELECT active FROM profiles_defs WHERE name='skip-critic-xs';")
assert_eq "disabled" "$a" "0"

"$SHCTX" profile enable skip-critic-xs
a=$(sqlite3 "$SHCTX_TEST_TMP/.artifacts/root.db" \
  "SELECT active FROM profiles_defs WHERE name='skip-critic-xs';")
assert_eq "enabled" "$a" "1"
```

- [ ] **Step 2: Write `scripts/cmd_profile.sh`**

```bash
#!/usr/bin/env bash
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

sub="${1:-list}"; shift || true
project_id=$(shctx_project_id)
now=$(shctx_now)
pdir="$(shctx_artifacts_root)/profiles"

case "$sub" in
  list)
    shctx_sql -header -column \
      "SELECT name, kind, active, source_path FROM profiles_defs WHERE project_id='$project_id';"
    ;;
  show)
    name="${1:-}"; [[ -n "$name" ]] || { echo "usage: profile show <name>" >&2; exit 1; }
    shctx_sql -header -column \
      "SELECT name, kind, active, json(config) AS config, source_path FROM profiles_defs WHERE project_id='$project_id' AND name='$name';"
    ;;
  enable|disable)
    name="${1:-}"; [[ -n "$name" ]] || { echo "usage: profile $sub <name>" >&2; exit 1; }
    val=$([[ "$sub" == "enable" ]] && echo 1 || echo 0)
    shctx_sql "UPDATE profiles_defs SET active=$val, updated_at=$now WHERE project_id='$project_id' AND name='$name';"
    ;;
  sync)
    [[ -d "$pdir" ]] || { echo "no profiles dir; nothing to sync"; exit 0; }
    for f in "$pdir"/*.toml; do
      [[ -f "$f" ]] || continue
      # Minimal TOML parser: name, kind, [config] block as JSON.
      name=$(awk -F' *= *' '/^name *=/{gsub(/"/,"",$2); print $2; exit}' "$f")
      kind=$(awk -F' *= *' '/^kind *=/{gsub(/"/,"",$2); print $2; exit}' "$f")
      config=$(awk '
        /^\[config\]/{flag=1; next}
        /^\[/{flag=0}
        flag && /=/{
          k=$1; sub(/ *=.*/,"",k);
          v=$0; sub(/^[^=]*= */,"",v); gsub(/"/,"\\\"",v);
          printf "\"%s\": %s, ", k, v
        }
        END{}' "$f" | sed 's/, $//')
      cfg_json="{${config:-}}"
      jq -e . >/dev/null 2>&1 <<<"$cfg_json" || cfg_json="{}"
      cfg_esc=${cfg_json//\'/\'\'}
      uid=$(shctx_uuid7)
      shctx_sql "INSERT INTO profiles_defs (id,project_id,name,kind,config,source_path,active,created_at,updated_at)
                 VALUES ('$uid','$project_id','$name','$kind','$cfg_esc','$f',1,$now,$now)
                 ON CONFLICT(project_id,name) DO UPDATE SET
                   kind=excluded.kind, config=excluded.config, source_path=excluded.source_path,
                   updated_at=excluded.updated_at;"
    done
    echo "shctx profile sync: ok"
    ;;
  *) echo "ERROR: usage: shctx profile <list|show|enable|disable|sync>" >&2; exit 1 ;;
esac
```

- [ ] **Step 3: Run test; commit**

```bash
chmod +x plugins/shepherd/skills/context/scripts/cmd_profile.sh \
         plugins/shepherd/skills/context/tests/test_profile.sh
bash plugins/shepherd/skills/context/tests/test_profile.sh
git add plugins/shepherd/skills/context/scripts/cmd_profile.sh \
        plugins/shepherd/skills/context/tests/test_profile.sh
git commit -m "feat(shepherd-context): profile subcommand"
```

---

## Task 13: `lock` subcommand

**Files:**
- Create: `plugins/shepherd/skills/context/scripts/cmd_lock.sh`
- Create: `plugins/shepherd/skills/context/tests/test_lock.sh`

- [ ] **Step 1: Write the failing test**

```bash
# tests/test_lock.sh
#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init

"$SHCTX" lock acquire --mode=context --session=test1
out=$("$SHCTX" lock show)
assert_contains "show.held" "$out" "test1"
"$SHCTX" lock release
out=$("$SHCTX" lock show)
assert_contains "show.free" "$out" "free"

# Stale lock reaping.
echo '{"holder_session_id":"dead","mode":"context","acquired_at":1,"pid":99999999,"children":[]}' > .artifacts/shepherd.lock
"$SHCTX" lock reap
[[ ! -f .artifacts/shepherd.lock ]] || { echo "FAIL: stale lock not reaped" >&2; exit 1; }
```

- [ ] **Step 2: Write `scripts/cmd_lock.sh`**

```bash
#!/usr/bin/env bash
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

sub="${1:-show}"; shift || true
lock="$(shctx_lock_path)"
project_id=$(shctx_project_id)
now=$(shctx_now)

parse_kv() {
  MODE="context"; SESS=""
  for a in "$@"; do
    case "$a" in
      --mode=*)    MODE="${a#--mode=}" ;;
      --session=*) SESS="${a#--session=}" ;;
    esac
  done
}

case "$sub" in
  show)
    if [[ -f "$lock" ]]; then
      echo "lock: held"; jq . "$lock"
    else
      echo "lock: free"
    fi
    ;;
  acquire)
    parse_kv "$@"
    [[ -n "$SESS" ]] || SESS=$(shctx_uuid7)
    if [[ -f "$lock" ]]; then
      echo "ERROR: lock already held" >&2; exit 1
    fi
    jq -nc --arg s "$SESS" --arg m "$MODE" --argjson p "$$" --argjson at "$now" \
      '{holder_session_id:$s, mode:$m, acquired_at:$at, pid:$p, children:[]}' > "$lock"
    shctx_sql "INSERT INTO locks_history (project_id, session_id, mode, acquired_at)
               VALUES ('$project_id', '$SESS', '$MODE', $now);"
    echo "lock: acquired ($SESS, $MODE)"
    ;;
  release)
    [[ -f "$lock" ]] || { echo "lock: free"; exit 0; }
    sess=$(jq -r .holder_session_id "$lock")
    rm -f "$lock"
    shctx_sql "UPDATE locks_history SET released_at=$now, released_by='normal' WHERE session_id='$sess' AND released_at IS NULL;"
    echo "lock: released"
    ;;
  reap)
    [[ -f "$lock" ]] || { echo "lock: free"; exit 0; }
    pid=$(jq -r .pid "$lock"); at=$(jq -r .acquired_at "$lock"); sess=$(jq -r .holder_session_id "$lock")
    age_min=$(( (now - at) / 60 ))
    if ! kill -0 "$pid" 2>/dev/null || (( age_min > 60 )); then
      rm -f "$lock"
      shctx_sql "UPDATE locks_history SET released_at=$now, released_by='reap' WHERE session_id='$sess' AND released_at IS NULL;"
      echo "lock: reaped (pid=$pid, age=${age_min}m)"
    else
      echo "lock: held by live pid $pid (age ${age_min}m); not reaping"
      exit 1
    fi
    ;;
  *) echo "ERROR: usage: shctx lock <show|acquire|release|reap>" >&2; exit 1 ;;
esac
```

- [ ] **Step 3: Run test; commit**

```bash
chmod +x plugins/shepherd/skills/context/scripts/cmd_lock.sh \
         plugins/shepherd/skills/context/tests/test_lock.sh
bash plugins/shepherd/skills/context/tests/test_lock.sh
git add plugins/shepherd/skills/context/scripts/cmd_lock.sh \
        plugins/shepherd/skills/context/tests/test_lock.sh
git commit -m "feat(shepherd-context): lock subcommand"
```

---

## Task 14: SKILL.md body + references + examples

**Files:**
- Modify: `plugins/shepherd/skills/context/SKILL.md` (replace the stub from Task 1 with full body)
- Create/Replace: `plugins/shepherd/skills/context/references/{schema,profiles,naming-conventions}.md`
- Create: `plugins/shepherd/skills/context/examples/{inject-coder,profile-modifier.toml,profile-extension.toml,journal-entry}.md` (the two `.toml` files use that extension; others are `.md`)

- [ ] **Step 1: Write `SKILL.md` body** — replace the placeholder with the full quick-reference. Keep the existing frontmatter from Task 1 verbatim.

```markdown
# /shepherd:context — Per-project Context Registry

You are reading the entry skill for `/shepherd:context`. The CLI lives at `${CLAUDE_PLUGIN_ROOT}/scripts/shctx`. The DB lives at `.artifacts/root.db` in the consumer project.

## Quick reference

- `shctx init` — scaffold `.artifacts/`, create `root.db`, register host project
- `shctx status` — row counts, refresh staleness, lock state, lint summary
- `shctx refresh [--scope=symbols|github|artifacts|all]` — idempotent rebuild
- `shctx query <name> [--json|--md] [--key=val ...]` — run a named query from `queries/`
- `shctx inject <engineer|coder|auditor>` — emit a `[DB-CONTEXT]` block
- `shctx profile <list|show|enable|disable|sync>`
- `shctx mem <add|search|list|pin|unpin>`
- `shctx lock <show|acquire|release|reap>`
- `shctx lint` — naming-convention check
- `shctx migrate` — apply pending schema migrations
- `shctx export <kind> [--out=path]`

## When to invoke

The conductor and the engineer both call into this skill via Bash. Direct invocations:

- `shctx init` once per consumer-project bootstrap.
- `shctx refresh --scope=all` at sprint open (per `[context].auto_refresh` in `shepherd.toml`).
- `shctx query dedup-check --name=<symbol>` is the conductor's DEDUP-GATE Layer 2 SQL fast-path (per `doctrines/zero-duplicate-tolerance.md` + `doctrines/context-registry.md`).
- `shctx inject coder` emits a `[DB-CONTEXT]` block the engineer can paste into a coder brief's `[CONTEXT-INVENTORY]` section.

## Cache vs canonical

See `doctrines/context-registry.md`. Tables in `index_*` and `logs_events` are derived; everything else is canonical.

## Failure modes

- `sqlite3` missing → install it (`brew install sqlite` / `apt install sqlite3`).
- `gh` missing → `refresh --scope=github` skips silently (warn).
- `cargo` missing → `refresh --scope=symbols` skips Rust extraction (warn).
- DB missing → run `shctx init`.
- Schema out of date → run `shctx migrate`.

## See also

- `references/schema.md` — full table-by-table reference.
- `references/profiles.md` — profile model and TOML format.
- `references/naming-conventions.md` — file naming rules (also copied as `.artifacts/CONVENTIONS.md` on init).
- `examples/inject-coder.md` — sample `[DB-CONTEXT]` block.
- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/doctrines/context-registry.md` — doctrine.
```

- [ ] **Step 2: Write `references/schema.md`** — table-by-table description of every column in `schema/0001_init.sql`, the views, the JSON column conventions, and the JSON1 query patterns used in the bundled `queries/`. Use the spec §6 wording verbatim (`.artifacts/docs/specs/2026-05-04-shepherd-context-design.md` §6).

- [ ] **Step 3: Write `references/profiles.md`** — profile model: kinds (`modifier|extension|override`), TOML format (`name`, `kind`, `[config]` block), sync semantics (TOML wins on conflict), example use-cases (skip critic for XS, custom DEDUP-GATE recommendations).

- [ ] **Step 4: Write `references/naming-conventions.md`** — the table from spec §4 verbatim, plus the rule "date-only for human-editable, timestamped for machine-generated".

- [ ] **Step 5: Write `examples/inject-coder.md`** — a realistic `[DB-CONTEXT]` block as it would appear in a coder brief, with 5–10 example canonical-types rows.

- [ ] **Step 6: Write `examples/profile-modifier.toml`** and `examples/profile-extension.toml`:

```toml
# profile-modifier.toml — example: skip critic for XS sprints
name = "skip-critic-xs"
kind = "modifier"
[config]
skip_critic_for = ["XS"]
reason = "XS sprints are fully scoped by the seed; critic adds no value"
```

```toml
# profile-extension.toml — example: append a security scan after every coder wave
name = "post-wave-security"
kind = "extension"
[config]
hook = "post-wave"
command = "cargo audit"
fail_on = "high"
```

- [ ] **Step 7: Write `examples/journal-entry.md`** — a sample `.artifacts/docs/journal/YYYY-MM-DD.md` showing the section format (one file per day, one `## HH:MM — <topic>` heading per entry).

- [ ] **Step 8: Commit**

```bash
git add plugins/shepherd/skills/context/SKILL.md \
        plugins/shepherd/skills/context/references \
        plugins/shepherd/skills/context/examples
git commit -m "docs(shepherd-context): SKILL.md body, references, examples"
```

---

## Task 15: Slash-command shim + new doctrine

**Files:**
- Create: `plugins/shepherd/commands/context.md`
- Create: `plugins/shepherd/skills/shepherd/doctrines/context-registry.md`

- [ ] **Step 1: Write `commands/context.md`** (mirror the convention used by `commands/start.md`)

```markdown
---
name: context
description: Manage the per-project shepherd context registry — issues, PRs, releases, code symbols, memories, profiles, locks. Backs DEDUP-GATE Layer 2 SQL fast-path.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Skill
---

# /shepherd:context — Context Registry CLI

Thin command shim. The full skill body lives at `${CLAUDE_PLUGIN_ROOT}/skills/context/SKILL.md`.

## Step 0 — Auto-orient

1. Load the `shepherd-context` skill via the Skill tool.
2. Read `.claude/shepherd.toml` `[context]` if present; otherwise use defaults from `${CLAUDE_PLUGIN_ROOT}/docs/configuration.md`.
3. Resolve the CLI path: `${CLAUDE_PLUGIN_ROOT}/skills/context/scripts/shctx`.

## Step 1 — Run

Pass arguments through to `shctx`. Common invocations:

- `shctx init` — first-time scaffold of `.artifacts/`
- `shctx refresh --scope=all` — rebuild caches at sprint open
- `shctx inject coder` — emit a `[DB-CONTEXT]` block for a coder brief
- `shctx query dedup-check --name=<symbol>` — Layer 2 SQL fast-path

For full subcommand documentation, read the skill body.
```

- [ ] **Step 2: Write `doctrines/context-registry.md`**

```markdown
# Context registry — single queryable source of context

The shepherd context registry (`.artifacts/root.db`) is the per-project SQLite store that backs `/shepherd:context`. It is the **single queryable source of context** for the flock — code symbols, GitHub issues/PRs/releases/milestones, project memories, profiles, lock history, sprint metadata (in milestone d), and an event log.

## Cache vs canonical zones

| Zone | Tables | Mode |
|---|---|---|
| **Cache** (derived) | `index_*`, `logs_events` (last 10K) | Rebuildable from source/MCP at any time. Safe to delete. |
| **Canonical** | `projects`, `sessions`, `profiles_defs`, `mem_entries`, `artifacts`, `locks_history`, `schema_versions`, `sprints_*` (milestone d) | Not recoverable elsewhere. Persistence required. |

The DB is **gitignored by default**. Consumers may opt to commit it; for most projects, treat it as a build artifact.

## When to read the DB

- **Engineer Phase 0 mesh row 1** (open-issue ledger): `shctx query open-issues --md` is the fast-path.
- **Engineer Phase 0 mesh row 12** (workspace knowledge silo): `shctx query canonical-types --md` replaces the markdown read.
- **Conductor DEDUP-GATE Layer 2** (per `zero-duplicate-tolerance.md`): `shctx query dedup-check --name=<symbol>` is the SQL pre-check before the slower per-lane grep. Grep remains source of truth.
- **Coder briefs** (milestone c, optional): engineer populates `[DB-CONTEXT]` via `shctx inject coder`. Becomes mandatory in milestone d.
- **Auditor close-time checks**: `shctx query open-issues`, `drift-risk`, plus (in milestone d) `sprints_*` queries.

## When to refresh

- At sprint open, per `[context].auto_refresh` (default `["on-sprint-open"]`).
- After any commit that adds new public types (refresh `--scope=symbols`).
- At engineer dispatch time if `index_issues.refreshed_at` older than `[context.refresh].ttl_minutes`.

## Fall-back contract (milestone c)

If the DB is absent, the flock falls back to markdown reads. Behavior is unchanged from v4.x. The DB is **optional in milestone c**, **mandatory in milestone d**.

## Anti-patterns

- **"The DB row says X exists, so I'll skip the grep."** Wrong — DB is a cache; grep remains the contract for DEDUP-GATE Layer 2. SQL is the fast-path, not the gate.
- **"I'll edit `canonical-types.md` by hand."** OK in milestone c. In milestone d, hand edits are flagged as drift; the file becomes generated.
- **"I'll commit the DB to the repo."** Allowed; not recommended unless your team has a specific reason. Default posture is gitignored.
- **"I don't need to call `shctx migrate` — schema is fine."** Wrong on every plugin upgrade. Run `shctx migrate` after pulling new shepherd versions.

## See also

- `pipeline.md` §II — DEDUP-GATE node.
- `doctrines/zero-duplicate-tolerance.md` — Layer 1/2/3 model.
- `${CLAUDE_PLUGIN_ROOT}/skills/context/SKILL.md` — CLI quick reference.
- `.artifacts/docs/specs/2026-05-04-shepherd-context-design.md` — full design spec.
```

- [ ] **Step 3: Commit**

```bash
git add plugins/shepherd/commands/context.md \
        plugins/shepherd/skills/shepherd/doctrines/context-registry.md
git commit -m "feat(shepherd): /shepherd:context command shim + context-registry doctrine"
```

---

## Task 16: Flock-side integration (engineer, coder, conductor)

**Files:**
- Modify: `plugins/shepherd/agents/engineer.md`
- Modify: `plugins/shepherd/skills/shepherd/SKILL.md`
- Modify: `plugins/shepherd/skills/shepherd/flock.md`
- Modify: `plugins/shepherd/skills/shepherd/pipeline.md`
- Modify: `plugins/shepherd/skills/shepherd/doctrines/zero-duplicate-tolerance.md`
- Modify: `plugins/shepherd/docs/configuration.md`

- [ ] **Step 1: Update `engineer.md`** — in the "Phase 0 — Current-state mesh" section, add a paragraph after the "Mesh inputs" header:

```markdown
**Fast-path via context registry.** If `.artifacts/root.db` exists (run `shctx status` to check), prefer registry queries over MCP/CLI hops:

- Mesh row 1 (open-issue ledger): `shctx query open-issues --md`
- Mesh row 12 (workspace knowledge silo): `shctx query canonical-types --md`

Refresh first if `refreshed_at` is older than `[context.refresh].ttl_minutes`: `shctx refresh --scope=github` then re-query. The DB is a cache — fall back to direct MCP/CLI if absent or stale beyond TTL. See `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/doctrines/context-registry.md`.
```

- [ ] **Step 2: Update `flock.md` → `@coder` section** — append a new bullet under the brief contract:

```markdown
- **`[DB-CONTEXT]` (optional in v5.0.0-c, required in v5.0.0-d).** When the engineer populates this block via `shctx inject coder`, the coder reads it as authoritative for `[CONTEXT-INVENTORY]` overlap. Block format:
  ```
  [DB-CONTEXT]
  ## Existing canonical types — REUSE; do not duplicate
  | package | kind | name | signature |
  | … |
  [/DB-CONTEXT]
  ```
  Coder MUST cite at least one `[DB-CONTEXT]` row in `[CONTEXT-INVENTORY]` if the lane introduces a type that overlaps with an existing canonical concept.
```

- [ ] **Step 3: Update `pipeline.md` DEDUP-GATE node section** — add a paragraph in the DEDUP-GATE node description:

```markdown
**SQL fast-path (v5.0.0+).** Before running per-lane greps, the conductor runs `shctx query dedup-check --name=<lane.new_symbol>` for each lane. If the registry returns ≥1 row, BLOCK with the standard recommendation block (citing the DB row's `file_path:line`). The grep remains the contract — registry rows are derived and may be stale; a registry miss does NOT skip the grep, but a registry hit pre-blocks dispatch and saves the grep step.
```

- [ ] **Step 4: Update `zero-duplicate-tolerance.md` Layer 2 section** — append:

```markdown
**Layer 2 SQL fast-path (v5.0.0+).** When `.artifacts/root.db` is present, run `shctx query dedup-check --name=<symbol>` first. A hit pre-blocks dispatch (citing `file_path:line` from the DB). A miss falls through to the slower grep. The grep remains the contract; SQL is a cheap pre-filter. See `doctrines/context-registry.md`.
```

- [ ] **Step 5: Update `skills/shepherd/SKILL.md`** — version bump in frontmatter (`version: 5.0.0`) plus a new entry in §IX:

```markdown
- **`${CLAUDE_PLUGIN_ROOT}/skills/context/SKILL.md`** — context registry CLI (new in v5.0.0). Backs DEDUP-GATE Layer 2 SQL fast-path. See doctrines/context-registry.md.
```

Also bump body references from `4.2.0` to `5.0.0`.

- [ ] **Step 6: Update `docs/configuration.md`** — add a new top-level section documenting `[context]`, `[context.refresh]`, `[context.lock]`, `[context.naming]` per spec §12. Include the schema/views appendix.

- [ ] **Step 7: Commit**

```bash
git add plugins/shepherd/agents/engineer.md \
        plugins/shepherd/skills/shepherd/{SKILL.md,flock.md,pipeline.md} \
        plugins/shepherd/skills/shepherd/doctrines/zero-duplicate-tolerance.md \
        plugins/shepherd/docs/configuration.md
git commit -m "feat(shepherd): flock integration for context registry (engineer + coder + DEDUP-GATE)"
```

---

## Task 17: Version bump to v5.0.0 across all manifests

**Files:**
- Modify: `plugins/shepherd/.claude-plugin/plugin.json`
- Modify: `plugins/shepherd/README.md`
- Modify: `plugins/shepherd/CHANGELOG.md`
- Modify: `.claude-plugin/marketplace.json`
- Modify: `plugins/fl03-skills/skills/shepherd/SKILL.md` (if it carries a version)
- Modify: `plugins/fl03-skills/.claude-plugin/plugin.json` (only if version tracks shepherd)

- [ ] **Step 1: Bump `plugin.json` version 4.2.0 → 5.0.0 and append the new feature line to `description`**

```json
{
  "name": "shepherd",
  "version": "5.0.0",
  "description": "Sprint-by-sprint version-cycle conductor. Five-agent flock (engineer, critic, coder, auditor, worker) on a three-section sprint pipeline (INTRODUCTION → BODY → CLOSE) plus the v4.2.0 Stage Graph and the v5.0.0 per-project SQLite context registry (.artifacts/root.db) backing /shepherd:context — code symbols, GitHub state, memories, profiles, locks, and event log all queryable. Includes a conductor-side DEDUP-GATE pre-flight (zero-tolerance for duplicate code, now with SQL fast-path), mechanical skill auto-attachment per file scope, and an Opus-pinned planter that authors drift-resistant seeds. Project-agnostic — branch topology, gates, paths, and ledger discipline configured per-project via .claude/shepherd.toml.",
  ...
}
```

(Preserve every other field; only `version` and `description` change.)

- [ ] **Step 2: Update `README.md`** — every literal `4.2.0` becomes `5.0.0`. Add a new top-level section after the existing intro:

```markdown
## v5.0.0 — Context Registry

`/shepherd:context` introduces a per-project SQLite registry at `.artifacts/root.db`. It indexes:

- code symbols (replaces hand-maintained `canonical-types.md`)
- GitHub issues, PRs, releases, milestones (cached with TTL)
- artifact files (markdown reports indexed by hash + kind)
- project memories (replaces external `remember` plugin)
- profiles (modifiers/extensions to flock behavior)
- lock history (autorun + parallel coordination)
- event log

Quick start in any consumer project:

```bash
shctx init                   # scaffold .artifacts/, create root.db
shctx refresh --scope=all    # populate caches
shctx status                 # verify
```

See `plugins/shepherd/skills/context/SKILL.md` for the full CLI.
```

- [ ] **Step 3: Append CHANGELOG entry**

```markdown
## v5.0.0 — 2026-05-XX

**MAJOR — adds context registry contract.**

- **NEW:** `/shepherd:context` command + bundled `shctx` CLI.
- **NEW:** Per-project SQLite registry at `.artifacts/root.db` (schema 0001).
- **NEW:** Doctrine `context-registry.md` (cache vs canonical zones, fall-back contract).
- **NEW:** DEDUP-GATE Layer 2 SQL fast-path (`shctx query dedup-check`); grep remains contract.
- **NEW:** `[DB-CONTEXT]` block in coder briefs (optional in c; mandatory in d).
- **NEW:** `mem` subcommand replaces external `remember` plugin.
- **NEW:** Lock-coordinated autorun + parallel sessions (`.artifacts/shepherd.lock`).
- **NEW:** `shepherd.toml` `[context]`, `[context.refresh]`, `[context.lock]`, `[context.naming]` sections.
- **NEW:** Naming-convention enforcement (`shctx lint`).
- Self-host: this repo now scaffolds `.artifacts/` and registers its own design specs.

Migration from v4.2.0: run `shctx init` once; existing markdown artifacts continue to work. DB is optional in milestone (c); becomes contract-mandatory in milestone (d) of the v5.0.0 line.
```

- [ ] **Step 4: Update `marketplace.json`** — find the shepherd entry, bump `version` to `5.0.0`, sync `description` with `plugin.json`.

- [ ] **Step 5: Inspect `fl03-skills` for shepherd version tracking**

```bash
grep -rE 'version.*4\.2\.0|version.*5\.0\.0' plugins/fl03-skills/ || true
```

If `plugins/fl03-skills/skills/shepherd/SKILL.md` has a `version:` field, bump it to `5.0.0`. If `plugins/fl03-skills/.claude-plugin/plugin.json` `version` tracks shepherd, bump it. Otherwise, leave unchanged.

- [ ] **Step 6: Commit**

```bash
git add plugins/shepherd/.claude-plugin/plugin.json plugins/shepherd/README.md \
        plugins/shepherd/CHANGELOG.md .claude-plugin/marketplace.json \
        plugins/fl03-skills/skills/shepherd/SKILL.md plugins/fl03-skills/.claude-plugin/plugin.json
git commit -m "chore: bump shepherd to v5.0.0 across all manifests"
```

---

## Task 18: Self-host + housekeeping

**Files:**
- Modify: `.gitignore`
- Modify: `CLAUDE.md`
- Create: `.artifacts/root.db` (via `shctx init`)
- Create: `.artifacts/CONVENTIONS.md`, `.artifacts/project.json`, etc. (via `shctx init`)

- [ ] **Step 1: Update root `.gitignore`** — add explicit ignores for the new shepherd state files. Insert after the `*.db` group:

```gitignore
# shepherd context registry
.artifacts/root.db
.artifacts/root.db-*
.artifacts/shepherd.lock
.artifacts/project.json
.artifacts/tmp/
.artifacts/logs/
```

- [ ] **Step 2: Self-host — run `shctx init` in this repo**

```bash
plugins/shepherd/skills/context/scripts/shctx init
plugins/shepherd/skills/context/scripts/shctx refresh --scope=artifacts
plugins/shepherd/skills/context/scripts/shctx status
```

Expected: scaffold completes; `artifacts` table contains rows for `2026-05-04-shepherd-context-design.md` (spec) and `2026-05-04-shepherd-context.plan.md` (this file).

- [ ] **Step 3: Update `CLAUDE.md`** — append the Appendix B additions from spec §B:

```markdown
## Repo invariants — v5.0.0 additions

- `.artifacts/root.db` is the per-project SQLite registry. Schema lives in `plugins/shepherd/skills/context/schema/`.
- `.artifacts/shepherd.lock` coordinates concurrent shepherd sessions. Always JSON; never edit by hand.
- `.artifacts/docs/specs/*.spec.md` and `*.design.md` are design documents; track in git. Naming: `YYYY-MM-DD-<topic>-{design|spec}.md`.
- `.artifacts/docs/journal/YYYY-MM-DD.md` are operator-editable daily notes; one file per day, append-mode.
- `.artifacts/logs/events-YYYY-MM-DD.jsonl` are append-only event streams; gitignored.
- `.artifacts/tmp/` and `.artifacts/logs/` are gitignored. `.artifacts/profiles/`, `.artifacts/docs/`, `.artifacts/plans/`, `.artifacts/reports/`, `.artifacts/ctx/` are tracked.
```

- [ ] **Step 4: Run the full test suite**

```bash
bash plugins/shepherd/skills/context/tests/run.sh
# Expected: every test_*.sh PASSES
```

- [ ] **Step 5: Smoke test the full surface**

```bash
plugins/shepherd/skills/context/scripts/shctx init
plugins/shepherd/skills/context/scripts/shctx migrate
plugins/shepherd/skills/context/scripts/shctx status
plugins/shepherd/skills/context/scripts/shctx lint
plugins/shepherd/skills/context/scripts/shctx refresh --scope=artifacts
plugins/shepherd/skills/context/scripts/shctx query open-issues --json
plugins/shepherd/skills/context/scripts/shctx inject coder
plugins/shepherd/skills/context/scripts/shctx mem add --kind=doctrine --title="dogfood" --body="self-hosted"
plugins/shepherd/skills/context/scripts/shctx mem list
plugins/shepherd/skills/context/scripts/shctx lock acquire --mode=context --session=smoke
plugins/shepherd/skills/context/scripts/shctx lock show
plugins/shepherd/skills/context/scripts/shctx lock release
```

Expected: every command exits 0; `status` shows non-zero rows in `artifacts`, `mem_entries`, `locks_history`.

- [ ] **Step 6: Commit**

```bash
git add .gitignore CLAUDE.md .artifacts/CONVENTIONS.md .artifacts/docs/
git commit -m "feat: self-host shepherd v5.0.0 context registry; .gitignore + CLAUDE.md updates"
```

(`.artifacts/root.db`, `.artifacts/project.json`, `.artifacts/shepherd.lock`, `.artifacts/tmp/`, `.artifacts/logs/` are gitignored and won't be staged.)

---

## Self-review

**1. Spec coverage:**

| Spec section | Implementation task |
|---|---|
| §3 Architecture overview | Task 1, 14 |
| §4 Filesystem layout | Task 4 (init/scaffold) |
| §5 Multi-project backbone | Task 2 (schema) + Task 4 (init insert) |
| §6.1 Migration tracking | Task 2, 5 |
| §6.2 Sessions | Task 2 (table) — populated by `mem`/`lock` writers |
| §6.3 Profiles | Task 2 (table) + Task 12 (subcommand) |
| §6.4 Memories | Task 2 + Task 11 |
| §6.5 Index tables | Task 2 + Task 7 (symbols) + Task 8 (github) |
| §6.6 Logs | Task 2 (table) — written by future hooks |
| §6.7 Artifacts | Task 2 + Task 9 |
| §6.8 Locks | Task 2 + Task 13 |
| §6.9 Sprints (deferred) | Out of scope (milestone d) |
| §7 Views | Task 2 |
| §8 Command surface | Tasks 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13 |
| §9 Refresh model | Tasks 7, 8, 9 |
| §10 Lock model | Task 13 |
| §11.1 Phase-1 flock integration | Task 16 |
| §11.2 Phase-2 (deferred) | Out of scope (milestone d) |
| §12 shepherd.toml additions | Documented in Task 16 step 6 (configuration.md) |
| §13 Version bump | Task 17 |
| §14 Phasing | Plan covers milestone (c) only — milestone (d) gets a separate plan |
| §15 Migration / backward compat | Task 5 (migrate) + fall-back contract in doctrine (Task 15) |
| §16 Risks & mitigations | Addressed by tests (Tasks 2, 5–13), pre-flight checks in `_lib.sh` (Task 1), gitignore (Task 18) |
| §17 Open questions | Documented as deferred in spec; no plan-time action |
| §18 Acceptance criteria | All ten items covered by Tasks 1–18 + Task 18 step 5 smoke test |
| Appendix A file inventory | All paths land in their designated tasks |
| Appendix B CLAUDE.md additions | Task 18 step 3 |

**2. Placeholder scan:** No `TBD`, `TODO`, or `implement later` in any code step. Stub for `naming-conventions.md` is created in Task 4 (one-line marker file) and replaced in Task 14 — flagged inline. Test scripts, SQL files, and shell scripts are complete.

**3. Type/name consistency:**
- `shctx` script name: consistent across all tasks.
- `_lib.sh` function names (`shctx_repo_root`, `shctx_db_path`, `shctx_artifacts_root`, `shctx_skill_root`, `shctx_uuid7`, `shctx_project_id`, `shctx_sql`, `shctx_now`, `shctx_lock_path`, `shctx_project_id_path`): consistent.
- Table names: identical between schema (Task 2) and queries (Task 10) and tests.
- Subcommand names: identical between `shctx` dispatcher (Task 3) and individual `cmd_*.sh` files.
- File-path patterns (`.artifacts/root.db`, `.artifacts/shepherd.lock`, `.artifacts/project.json`): identical across all tasks.
- View names (`v_open_issues`, `v_canonical_types`, etc.): identical between schema, queries, and tests.

---

---

# Addendum tasks (operator follow-up — see `2026-05-04-shepherd-context-addendum.md`)

## Task 19: Schema migration 0002 — `styles` table

**Files:**
- Create: `plugins/shepherd/skills/context/schema/migrations/0002_styles.sql`
- Modify: `plugins/shepherd/skills/context/tests/test_migrate.sh` (add 0002-applied assertion)

- [ ] **Step 1: Write `schema/migrations/0002_styles.sql`**

```sql
BEGIN;
CREATE TABLE styles (
  id          TEXT PRIMARY KEY,
  project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
  language    TEXT NOT NULL,
  source_path TEXT NOT NULL,
  active      INTEGER NOT NULL DEFAULT 1,
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL,
  UNIQUE(project_id, language)
);
COMMIT;
```

- [ ] **Step 2: Run migrate, assert table exists**

```bash
plugins/shepherd/skills/context/scripts/shctx migrate
# Assert
sqlite3 .artifacts/root.db ".schema styles" | grep -q "CREATE TABLE.*styles"
```

- [ ] **Step 3: Commit**

```bash
git add plugins/shepherd/skills/context/schema/migrations/0002_styles.sql
git commit -m "feat(shepherd-context): schema 0002 — styles table"
```

---

## Task 20: Bundled per-language style defaults

**Files (CREATE):**
- `plugins/shepherd/skills/context/styles/rust.md`
- `plugins/shepherd/skills/context/styles/python.md`
- `plugins/shepherd/skills/context/styles/typescript.md`
- `plugins/shepherd/skills/context/styles/go.md`
- `plugins/shepherd/skills/context/styles/shell.md`
- `plugins/shepherd/skills/context/styles/sql.md`

- [ ] **Step 1: Write `styles/rust.md`** — heaviest of the six; covers operator's per-language conventions (FL03's Rust ledger). Body MUST cover: error-handling shape (`thiserror` for libs, `anyhow` for bins), no `.unwrap()`/`.expect()` in lib code, prefer `?` over match, no `clone()` without justification, no `#[allow(...)]` without ticket, module layout (`lib.rs` re-exports only; one type per file when > 50 LOC), `Result<T, MyError>` not `Result<T, Box<dyn Error>>`, `tracing` not `log`, `tokio` features are explicit, `async fn` in traits via async-trait until stable, no `HashMap` without specified hasher, `BTreeMap` when ordering matters, `cargo fmt` config (max_width 100), `cargo clippy --all-targets --all-features -- -D warnings` passes, doc comments on every `pub` item. End with a "common mistakes the model makes" section listing patterns the operator has flagged in past sessions.

```markdown
# Rust — project code style

This file is project-local at `.artifacts/styles/rust.md`. The conductor injects its content into every coder brief whose `[FILE-SCOPE]` includes Rust files. Edit freely; lives next to the project, not the user.

## Error handling
- Library crates use `thiserror` for explicit error enums; binaries use `anyhow` for ergonomic propagation.
- Public APIs return `Result<T, MyError>`; never `Result<T, Box<dyn Error>>`.
- `.unwrap()` and `.expect()` are forbidden in `src/lib.rs` and any module exposed to consumers. They are tolerated in tests and `examples/`.
- Prefer `?` over `match e { Ok(v) => v, Err(e) => return Err(e) }`. Convert with `From`/`#[from]`.

## Ownership & cloning
- `.clone()` requires a comment explaining why a borrow won't work. Reviewer rejects unjustified clones.
- Prefer `&str` over `String` in function signatures unless ownership is needed.
- Use `Cow<'a, str>` when borrow-or-own is genuinely conditional.

## Module layout
- `lib.rs` is re-exports only — no logic. Public surface is a hand-curated `pub use` block.
- Files > 200 LOC are split. One primary type per file when the type exceeds ~50 LOC of methods.
- `mod tests` lives at the bottom of the file under test (small) or in `tests/` (integration).

## Async
- `tokio` features are explicit in `Cargo.toml` — never `features = ["full"]` in libraries; binaries may use `full` only with justification.
- `async fn` in traits uses `#[async_trait]` until the language stabilizes the feature; revisit per Rust release notes.
- `.await` boundaries respect cancellation safety; document non-cancel-safe futures in doc comments.

## Collections
- `HashMap` requires a specified hasher (`ahash::HashMap` or `std::collections::HashMap<K, V, BuildHasherDefault<Hasher>>`) when used in hot paths or for security-sensitive keys.
- `BTreeMap` when key ordering is observable to consumers.
- `Vec::with_capacity` when the size is known.

## Tooling
- `cargo fmt` config: `max_width = 100`, `use_small_heuristics = "Default"`.
- `cargo clippy --all-targets --all-features -- -D warnings` MUST pass before commit.
- `#[allow(...)]` requires a comment with a tracking issue number.

## Documentation
- Every `pub` item has a `///` doc comment with at minimum a one-line summary.
- `pub` types include a `# Examples` block when non-trivial.
- `# Errors`, `# Panics`, `# Safety` sections follow rustdoc conventions where applicable.

## Common patterns to AVOID (operator-flagged)
- Wrapping types just to add one method — extension traits or inherent `impl` first; new types only when invariant is meaningful.
- Returning `&Vec<T>` from getters — return `&[T]`.
- `Arc<Mutex<T>>` in single-threaded contexts.
- `let _ = ...` to silence warnings — use `drop(...)` or fix the underlying.
- Recreating `Regex` in a hot loop — use `once_cell::sync::Lazy` or `OnceLock`.
- `unsafe` without a `// SAFETY:` comment explaining the invariant being upheld.
```

- [ ] **Step 2: Write `styles/python.md`**, `styles/typescript.md`, `styles/go.md`, `styles/shell.md`, `styles/sql.md`. Each follows the same structure (Error handling, Ownership/State, Layout, Tooling, Documentation, Common patterns to AVOID). Use the existing `fl03-skills/skills/code-style/` ledger as a starting point — copy operator preferences verbatim, expand with project-applicable rules.

For brevity, each file's required sections (full body authored at implementation time):
- **python.md**: `ruff` + `mypy --strict`, no bare `except`, `dataclass`/`TypedDict` over dicts, `pathlib.Path` over string paths, f-strings, type hints on all public functions, `pytest` patterns, no mutable defaults.
- **typescript.md**: `strict: true` in tsconfig, no `any` without `// reason: ...` comment, `unknown` for boundaries, ES modules only, `Promise.all` over sequential `await` in collections, `Result<T, E>`-style error wrappers (no exceptions in domain code), zod for runtime validation at boundaries.
- **go.md**: Errors are values, no panic in libs, `errors.Is`/`As` for matching, struct embedding sparingly, table-driven tests, `golangci-lint` clean, no `init()` for non-trivial work.
- **shell.md**: `set -eu -o pipefail` at top, `${var:-default}` for safe expansion, `[[ ]]` over `[ ]`, quote everything, `mktemp -d` for temp dirs, traps for cleanup.
- **sql.md**: explicit column lists in `INSERT`/`SELECT`, named indexes, `ON CONFLICT` clauses spell out the resolution, transactions wrap multi-row mutations, no `SELECT *` outside ad-hoc queries.

- [ ] **Step 3: Commit**

```bash
git add plugins/shepherd/skills/context/styles
git commit -m "feat(shepherd-context): bundled per-language style defaults (rust/python/ts/go/shell/sql)"
```

---

## Task 21: `style` subcommand

**Files:**
- Create: `plugins/shepherd/skills/context/scripts/cmd_style.sh`
- Create: `plugins/shepherd/skills/context/tests/test_style.sh`
- Modify: `plugins/shepherd/skills/context/scripts/shctx` (add `style` to subcommand list)

- [ ] **Step 1: Write the failing test**

```bash
# tests/test_style.sh
#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
shctx_test_repo
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"
"$SHCTX" init
"$SHCTX" migrate

"$SHCTX" style init rust
assert_file "$SHCTX_TEST_TMP/.artifacts/styles/rust.md"

# Idempotent — second init does not overwrite custom edits.
echo "# CUSTOMIZED" >> "$SHCTX_TEST_TMP/.artifacts/styles/rust.md"
"$SHCTX" style init rust
grep -q CUSTOMIZED "$SHCTX_TEST_TMP/.artifacts/styles/rust.md" || { echo "FAIL: init clobbered custom edits"; exit 1; }

# init --all bootstraps every bundled language.
"$SHCTX" style init --all
for l in rust python typescript go shell sql; do
  assert_file "$SHCTX_TEST_TMP/.artifacts/styles/$l.md"
done

# `list` enumerates files.
out=$("$SHCTX" style list)
assert_contains "list" "$out" "rust.md"

# DB row created for each language.
n=$(sqlite3 "$SHCTX_TEST_TMP/.artifacts/root.db" "SELECT COUNT(*) FROM styles;")
[[ "$n" -ge 6 ]] || { echo "FAIL: expected ≥6 styles rows, got $n"; exit 1; }
```

- [ ] **Step 2: Write `scripts/cmd_style.sh`**

```bash
#!/usr/bin/env bash
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

sub="${1:-list}"; shift || true
project_id=$(shctx_project_id)
now=$(shctx_now)
src_dir="$(shctx_skill_root)/styles"
dst_dir="$(shctx_artifacts_root)/styles"
mkdir -p "$dst_dir"

upsert_row() {
  local lang="$1" path="$2" uid; uid=$(shctx_uuid7)
  shctx_sql "INSERT INTO styles (id,project_id,language,source_path,active,created_at,updated_at)
             VALUES ('$uid','$project_id','$lang','$path',1,$now,$now)
             ON CONFLICT(project_id,language) DO UPDATE SET source_path=excluded.source_path, updated_at=excluded.updated_at;"
}

init_one() {
  local lang="$1"
  local src="$src_dir/$lang.md"
  local dst="$dst_dir/$lang.md"
  [[ -f "$src" ]] || { echo "ERROR: no bundled style for $lang" >&2; return 1; }
  if [[ -f "$dst" ]]; then
    echo "shctx style: $dst already exists (preserving)"
  else
    cp "$src" "$dst"
    echo "shctx style: wrote $dst"
  fi
  upsert_row "$lang" "$dst"
}

case "$sub" in
  init)
    arg="${1:-}"; [[ -n "$arg" ]] || { echo "ERROR: usage: shctx style init <lang|--all>" >&2; exit 1; }
    if [[ "$arg" == "--all" ]]; then
      for f in "$src_dir"/*.md; do init_one "$(basename "$f" .md)"; done
    else
      init_one "$arg"
    fi
    ;;
  show)
    arg="${1:-}"; [[ -n "$arg" ]] || { echo "ERROR: usage: shctx style show <lang>" >&2; exit 1; }
    cat "$dst_dir/$arg.md"
    ;;
  list)
    if [[ -d "$dst_dir" ]]; then ls "$dst_dir"; else echo "(no styles initialized)"; fi
    ;;
  edit)
    arg="${1:-}"; [[ -n "$arg" ]] || { echo "ERROR: usage: shctx style edit <lang>" >&2; exit 1; }
    [[ -f "$dst_dir/$arg.md" ]] || init_one "$arg"
    "${EDITOR:-vi}" "$dst_dir/$arg.md"
    ;;
  *) echo "ERROR: usage: shctx style <init|show|list|edit>" >&2; exit 1 ;;
esac
```

- [ ] **Step 3: Add `style` to dispatcher**

In `scripts/shctx`, extend the `case "$cmd"` block: add `style` to the list of recognized subcommands. Update the `usage()` heredoc to document `style <init|show|list|edit>`.

- [ ] **Step 4: Run test; commit**

```bash
chmod +x plugins/shepherd/skills/context/scripts/cmd_style.sh \
         plugins/shepherd/skills/context/tests/test_style.sh
bash plugins/shepherd/skills/context/tests/test_style.sh
git add plugins/shepherd/skills/context/scripts/{cmd_style.sh,shctx} \
        plugins/shepherd/skills/context/tests/test_style.sh
git commit -m "feat(shepherd-context): style subcommand (per-language project styles)"
```

---

## Task 22: Conductor brief — auto-attach `[CODE-STYLE]` block

**Files:**
- Modify: `plugins/shepherd/skills/shepherd/flock.md` (§ @coder dispatch procedure)
- Modify: `plugins/shepherd/skills/shepherd/SKILL.md` (§I dispatch procedure)
- Modify: `plugins/shepherd/skills/shepherd/doctrines/zero-duplicate-tolerance.md` ("Skill auto-attachment" section)

- [ ] **Step 1: In `flock.md` § @coder, append a new bullet to the dispatch procedure**

```markdown
- **Auto-attach `[CODE-STYLE]` block (v5.0.0+).** For every language detected in `[FILE-SCOPE]`, the conductor reads `.artifacts/styles/<lang>.md` and prepends its content as a `[CODE-STYLE]` block in the brief. If the file is missing for a detected language, the conductor runs `shctx style init <lang>` first. The bundled `code-style` skill (`fl03-skills/skills/code-style/`) remains the universal ledger; `[CODE-STYLE]` is the project-specific override layer. Coders read both; project rules win on conflict.
```

- [ ] **Step 2: In `SKILL.md` §I.5 dispatch procedure block, add a step**

```markdown
6. **Auto-attach `[CODE-STYLE]`** for every language in `[FILE-SCOPE]`. See `flock.md` § @coder.
```

(Renumber subsequent steps if any.)

- [ ] **Step 3: In `zero-duplicate-tolerance.md` "Skill auto-attachment" section, append**

```markdown
### Code-style auto-attachment (v5.0.0+)

The mechanical `[SKILLS]` computation is augmented by a `[CODE-STYLE]` block. For every language detected in `[FILE-SCOPE]`:

1. Conductor reads `.artifacts/styles/<lang>.md` (project-local override).
2. Block is prepended to the coder brief verbatim under `[CODE-STYLE]`.
3. If the file is missing, conductor runs `shctx style init <lang>` to bootstrap from the plugin default.
4. The bundled `code-style` skill remains in `[SKILLS]`. Project rules (the block) override skill rules on conflict.

This delivers operator-specific code conventions to every coder dispatch without bloating the universal `code-style` skill.
```

- [ ] **Step 4: Commit**

```bash
git add plugins/shepherd/skills/shepherd/{flock.md,SKILL.md,doctrines/zero-duplicate-tolerance.md}
git commit -m "feat(shepherd): auto-attach [CODE-STYLE] block from .artifacts/styles/<lang>.md"
```

---

## Task 23: Worker patterns doctrine

**Files:**
- Create: `plugins/shepherd/skills/shepherd/doctrines/worker-patterns.md`
- Modify: `plugins/shepherd/skills/shepherd/flock.md` (§ @worker)

- [ ] **Step 1: Write `doctrines/worker-patterns.md`**

```markdown
# Worker dispatch patterns — when conductor offloads non-code work

`@worker` is the flock's bounded-task executor. The conductor uses it to keep its own context lean and focused on plan walking + dispatch decisions. This doctrine codifies WHEN to dispatch and WHAT briefs work well.

## Heuristic — when to dispatch worker (not inline)

Dispatch worker when ANY of the following hold:

- Task is IO-bound for > 5 minutes (deploy log tail, build watch, pulse-poll an external system).
- Task involves > 10 MCP calls in sequence (issue triage, schema enumeration, batch label changes).
- Task produces a structured deliverable that doesn't need to land in main-chat context (research summary, classification table, file-organization report).
- Task can run in parallel with main-chat work without contention.
- Inlining would consume > ~1000 tokens for an operation that produces a small final answer.

Inline when: the result is a one-line answer the conductor needs immediately for the next dispatch decision.

## Brief shape for non-code work

```
@worker brief
DELIVERABLE: <one sentence — the artifact that lands>
SCOPE: <tight bound — files, MCP scope, time window>
INPUTS: <required reads — paths, MCP queries, prior artifacts>
OUTPUT FORMAT: <markdown table | JSONL | summary paragraph | ...>
BUDGET: <time / tokens / iterations>
HALT CONDITIONS: <what the worker should refuse>
```

## Pattern catalog

### Issue-ledger triage

When the engineer's Phase 0 mesh surfaces > 30 open issues, dispatch worker:

```
DELIVERABLE: classify all open issues into {drift-risk, current-milestone, non-issue, tracking-future} per the ledger schema; report as markdown table.
SCOPE: GitHub `state:open`; full ledger.
INPUTS: open-issue list (already in DB via `shctx query open-issues --json`); `[ledger.classify_into]` from shepherd.toml.
OUTPUT FORMAT: markdown table — `| # | title | bucket | reason |`.
BUDGET: 15 min, 5K tokens.
HALT CONDITIONS: contradictory labels — flag and continue.
```

### Deploy monitor

After a deploy, watch logs:

```
DELIVERABLE: tail deploy logs for 15 min; report Sentry-error count + sample lines.
SCOPE: `fly logs` (or equivalent) for current app.
OUTPUT FORMAT: 1-paragraph summary + table of errors.
BUDGET: 15 min wall.
HALT CONDITIONS: deploy rolled back — exit immediately and surface.
```

### Branch cleanup

After a sprint close:

```
DELIVERABLE: list local + origin branches matching {sprint_branch_pattern} that are merged into {patch_branch}; recommend deletions; do NOT execute (operator confirms).
INPUTS: `git branch --merged`, `git branch -r --merged`.
OUTPUT FORMAT: markdown table — `| branch | last commit date | recommend |`.
BUDGET: 5 min.
```

### Research summary (web/MCP scrape)

When a design decision needs external context:

```
DELIVERABLE: 5-bullet summary of <topic> with citations; flag any operator-prior-art references.
INPUTS: <specific URLs | search queries>.
OUTPUT FORMAT: markdown bullets, each with [source] suffix.
BUDGET: 10 min, 8K tokens.
HALT CONDITIONS: no authoritative sources found — surface "insufficient" and exit.
```

### File organization (non-code)

When `.artifacts/` accumulates clutter:

```
DELIVERABLE: classify .artifacts/docs/journal/*.md into {keep, archive, prune}; recommend rotation; do NOT delete.
INPUTS: `ls -la .artifacts/docs/journal/`, `shctx query mem-search --q=<term>` for cross-references.
OUTPUT FORMAT: 3-column table.
BUDGET: 5 min.
```

## Anti-patterns

- **"Worker should write code."** No — `@coder` writes code. Worker owns bounded non-code deliverables.
- **"Worker can run inline; same context."** Wrong — the point of dispatch is context isolation. If the work is so small that dispatch overhead exceeds the value, inline it; otherwise dispatch.
- **"Worker decides when to halt."** No — `HALT CONDITIONS` are explicit in the brief. The conductor designs the halt; the worker honors it.
- **"Worker reads the full project."** Wrong — `INPUTS` are explicit. Workers do not browse.
- **"Worker can call other agents."** Wrong — workers are leaf dispatches. They never compose flock work.

## See also

- `flock.md` § @worker — full agent contract.
- `references/agent-briefs.md` § @worker — copy-paste templates.
- `agents/worker.md` — system prompt body.
```

- [ ] **Step 2: In `flock.md` § @worker, append a new sentence**

```markdown
**Dispatch patterns and brief catalog**: see `doctrines/worker-patterns.md` for when to dispatch worker (vs inline), brief templates for issue triage / deploy monitoring / branch cleanup / research / file organization, and anti-patterns the conductor must avoid.
```

- [ ] **Step 3: Commit**

```bash
git add plugins/shepherd/skills/shepherd/doctrines/worker-patterns.md \
        plugins/shepherd/skills/shepherd/flock.md
git commit -m "feat(shepherd): worker-patterns doctrine — main-chat dispatch heuristics"
```

---

## Task 24: Engineer brief — enforce seed → brainstorming → writing-plans

**Files:**
- Modify: `plugins/shepherd/agents/engineer.md`
- Modify: `plugins/shepherd/skills/shepherd/doctrines/seed-anchored-by-issues.md` (or create a new `engineer-flow.md`)
- Modify: `plugins/shepherd/agents/auditor.md` (completeness-concern check addition)

- [ ] **Step 1: Update `agents/engineer.md`** — replace the existing "Mandatory skills" section with a hard runtime check:

```markdown
## Mandatory skill load order — ENFORCED

You MUST invoke these in order before writing a single line of plan content. Skipping or reordering is a process violation; the auditor's `completeness` concern catches it and grade-caps the plan at C+.

1. **Read the seed** at `{paths.plans}/{sprint_branch}.seed.md` end-to-end. The seed is ground truth, not a prompt — do not expand or reinterpret it.
2. **Invoke `superpowers:brainstorming`** via the Skill tool. Use it to internalize the seed's user intent, requirements, and design tradeoffs. Do NOT skip — even when the seed feels "obvious", brainstorming forces the questions that catch silent expansion.
3. **Invoke `superpowers:writing-plans`** via the Skill tool. Use it as the structural framework for the plan document.
4. **Load per-language skill** per `shepherd.toml [project].language`.
5. **Load domain skills** per `[skills.by_domain]` matching the sprint's file scope.
6. **Load `workflow`** for branch hygiene, milestones, releases.

After load: write the plan with binding `## Stage Graph` per `pipeline.md` §XII, full `[CONTEXT-INVENTORY]` and `[DO-NOT-DUPLICATE]` per coder lane.
```

- [ ] **Step 2: Update `agents/auditor.md`** — in the `completeness` concern section, append:

```markdown
- **Engineer skill-load discipline (v5.0.0+).** Verify the plan opens with seed citation; verify the brainstorming + writing-plans skills were invoked (engineer leaves a one-line trace at top of plan: "Loaded: brainstorming, writing-plans, <lang>, <domain skills>"). Missing trace OR missing seed citation → process violation, grade-cap C+.
- **`[CODE-STYLE]` block presence (v5.0.0+).** For every coder lane brief whose `[FILE-SCOPE]` includes source files, verify the conductor injected a `[CODE-STYLE]` block from `.artifacts/styles/<lang>.md`. Missing block → conductor process violation; grade-cap C+ for first occurrence, F for repeat.
- **`[DB-CONTEXT]` block presence.** Optional in milestone (c); audit warns. Required in milestone (d); audit flags as critical.
```

- [ ] **Step 3: Commit**

```bash
git add plugins/shepherd/agents/{engineer.md,auditor.md}
git commit -m "feat(shepherd): enforce engineer seed→brainstorming→writing-plans + auditor checks"
```

---

## Task 25: Update CHANGELOG + README + smoke test

**Files:**
- Modify: `plugins/shepherd/CHANGELOG.md`
- Modify: `plugins/shepherd/README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Append to `CHANGELOG.md` v5.0.0 entry**

```markdown
- **NEW:** `shctx style <init|show|edit|list>` — per-language project style files at `.artifacts/styles/<lang>.md` (rust/python/typescript/go/shell/sql).
- **NEW:** Schema migration `0002_styles.sql` — `styles` table.
- **NEW:** Conductor mechanically injects `[CODE-STYLE]` block from `.artifacts/styles/<lang>.md` into every coder brief whose `[FILE-SCOPE]` matches a language.
- **NEW:** Doctrine `worker-patterns.md` — main-chat dispatch heuristics for non-code work (issue triage, deploy monitoring, branch cleanup, research, file org).
- **HARDENED:** Engineer brief now enforces seed → `superpowers:brainstorming` → `superpowers:writing-plans` load order; auditor `completeness` verifies trace.
- **HARDENED:** Auditor `completeness` checks `[CODE-STYLE]` presence on every code-touching coder lane.
```

- [ ] **Step 2: Update `README.md`** — extend the "v5.0.0 — Context Registry" section with a "Per-language style files" subsection citing `.artifacts/styles/<lang>.md` and `shctx style init --all`.

- [ ] **Step 3: Update `CLAUDE.md`** — append:

```markdown
- `.artifacts/styles/<lang>.md` are project-local code style overrides; tracked in git. Languages: rust, python, typescript, go, shell, sql. Bundled defaults at `plugins/shepherd/skills/context/styles/`. The conductor auto-injects these into every coder brief whose `[FILE-SCOPE]` matches.
- The flock remains closed at five (engineer, critic, coder, auditor, worker). Non-code work goes to `@worker` per `doctrines/worker-patterns.md`.
```

- [ ] **Step 4: Extend Task 18 step 5 smoke test with the new commands**

```bash
plugins/shepherd/skills/context/scripts/shctx style init rust
plugins/shepherd/skills/context/scripts/shctx style list
plugins/shepherd/skills/context/scripts/shctx style init --all
ls .artifacts/styles/  # expect 6 .md files
```

- [ ] **Step 5: Commit**

```bash
git add plugins/shepherd/CHANGELOG.md plugins/shepherd/README.md CLAUDE.md
git commit -m "docs(shepherd): v5.0.0 changelog + readme + claude.md updates for style/worker addenda"
```

---

## Self-review (addendum)

**Spec coverage (addendum §A1–A4):**

| Addendum section | Implementation task |
|---|---|
| A1 Engineer mandatory skill load order | Task 24 |
| A2 `shctx style` subcommand + bundled defaults | Tasks 19, 20, 21 |
| A2 Conductor `[CODE-STYLE]` auto-injection | Task 22 |
| A3 Worker patterns doctrine | Task 23 |
| A4 Auditor completeness checks | Task 24 |
| Acceptance items 11–16 | Tasks 19–22 + Task 24 |

**Type/name consistency check:**
- `.artifacts/styles/<lang>.md` path: identical across Tasks 20–22, 25.
- `shctx style` subcommand: identical between dispatcher (Task 21 Step 3), test (Task 21 Step 1), doctrine (Task 22).
- `[CODE-STYLE]` block name: identical across flock.md, SKILL.md, zero-duplicate-tolerance.md, auditor.md (Tasks 22, 24).
- Schema migration `0002_styles.sql`: numbering consistent; sprints schema renumbered to `0003` per addendum §A2 (deferred).
- Languages covered (rust/python/typescript/go/shell/sql): identical between Task 20 file list, Task 21 `init --all` test, Task 25 CLAUDE.md.

---

## Execution Handoff

**Plan complete and saved to `.artifacts/docs/plans/2026-05-04-shepherd-context.plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration. Each task is self-contained with full file paths and complete code; subagents won't need conversation history.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch with checkpoints for review.

**Which approach?**
