# Configuration

Shepherd is project-agnostic. The framework speaks principles (Phase 0 mesh, SUBTRACT-DON'T-ADD, wrapper-must-earn, Pattern B overlap); per-language details (build commands, idioms, code-review preferences) come from per-language skills loaded via `[skills.by_domain]`.

> **Examples in this doc lean Rust** because that's the most-tested binding so far. Equivalent values for Python, TypeScript, Go, and others appear in the [Language matrix](#language-matrix) section at the end. The framework itself has no Rust dependency.

To bind shepherd to your repo, drop a `shepherd.toml` at one of these locations (first found wins):

```
.claude/shepherd.toml         ← project-pinned, checked into the repo
.claude/shepherd.local.toml   ← project-pinned, gitignored (operator overrides)
$XDG_CONFIG_HOME/shepherd.toml ← user-global default
```

If no config is found, shepherd uses the framework defaults documented below — but the conductor will surface a warning at every `/shepherd:*` invocation until one is created.

## Schema

### `[project]` — identity

```toml
[project]
name        = "axiom"           # repo / project name (required)
language    = "rust"            # primary language: rust | python | typescript | go | mixed
description = "BTC prediction + Polymarket trading"
```

`language` is hand-tagged because file-extension sniffing is unreliable for mixed repos. Sets the default `[skills.by_domain]` mapping — Rust projects get `rust` + `code-style` for any `.rs` file, Python gets `code-style` (and `python` if you author one), etc.

### `[branching]` — branch topology

```toml
[branching]
patch_branch_pattern  = "v{X}.{Y}.{Z}"          # patch-arc branch (dots — git-valid)
sprint_branch_pattern = "v{X}.{Y}.{Z}-dev.{N}"   # sprint branch (dots — git-valid)
# Filesystem-slug forms (v5.1.1+) — dots collapsed for filename safety
# Used in seed/plan filenames so we don't get double-dotted paths
patch_slug_pattern    = "v{X}{Y}{Z}"             # e.g., v512 (was v5.1.2)
sprint_slug_pattern   = "v{X}{Y}{Z}-dev{N}"      # e.g., v512-dev3 (was v5.1.2-dev.3)
sprints_per_patch     = 10                       # 0..N-1 sprints per patch (default 10)
main_branch           = "main"                   # release target
release_tag_pattern   = "v{X}.{Y}.{Z}"          # tag emitted at dev.{last} squash
allow_direct_main_commit = false                 # NEVER true except solo bootstrap
```

The framework reads `{X}/{Y}/{Z}/{N}` as integer placeholders. Other patterns work — e.g., `release/{X}.{Y}` + `release/{X}.{Y}/sprint-{N}` — but the placeholder set is fixed.

**Branch vs. slug distinction (v5.1.1+):** branches keep dots because git accepts dotted refs natively (`v5.1.2-dev.3` is a valid branch name). But `.seed.md` / `.plan.md` filenames in `{paths.plans}/` derive from `*_slug_pattern` to avoid the documented `v0.3.2-dev.5.seed.md`-style filename drift (per `doctrines/seed-naming.md`). If `*_slug_pattern` is absent, the framework falls back to `*_branch_pattern` for backward compat but emits a deprecation warning.

### `[gates]` — between-wave validation

```toml
[gates]
# Commands that run between coder waves and at sprint close.
# An empty string skips the gate. The conductor runs each one in order;
# any non-zero exit halts the wave and triggers hot-fix coder dispatch.
check  = "cargo check --workspace --features full"
lint   = "cargo clippy --workspace --features full -- -D warnings"
format = "cargo fmt --all"

# Optional supplementary gates (run after the primary three pass).
# Useful for project-specific build profiles (Fly Docker build, multi-target, etc.).
extra = [
    { name = "node-serve",   cmd = "cargo check -p axiom-node --features serve,native" },
    { name = "worker-serve", cmd = "cargo check -p axiom-worker --features serve" },
]

# Auto-clean target/ when it grows past this many GB (0 = disabled).
target_clean_threshold_gb = 20

# Source-code globs the SUBTRACT-DON'T-ADD doctrine measures. The auditor
# `completeness` concern runs `git diff --shortstat <patch_branch>..HEAD --
# <subtract_paths>` for the LOC-delta check (per doctrines/subtract-dont-add.md).
# Documentation, audit artifacts, plans, reports, and config files are
# excluded by design — SUBTRACT applies to production source only.
# Default below is Rust-leaning; override per-project for other languages.
subtract_paths = [
    "crates/**/*.rs",
    "bin/**/*.rs",
    "src/**/*.rs",
    "**/*.toml",        # build manifests count
    "**/*.sql",         # migrations count
]
```

### `[paths]` — artifact locations

```toml
[paths]
plans   = ".shepherd/plans"     # seeds + plans live here
reports = ".shepherd/reports"   # close reports + audit reports
docs    = ".shepherd/docs"      # handoffs + release notes
ctx     = ".shepherd/ctx"       # workspace knowledge silo (canonical-types, dedup-ledger, etc.)
```

Paths are relative to the repo root. Directories are auto-created on first write.

**Namespace default (v5.0.0):** the per-project namespace directory is **`.shepherd/`** by default. Projects that prefer the legacy `.artifacts/` layout opt in by running `shctx init --artifacts`; substitute `.artifacts/` for `.shepherd/` in the snippet above. The `shctx` CLI auto-detects which directory is in use at every invocation (preferring `.shepherd/` when both exist). **The `[paths]` entries here must match the active namespace** — if they diverge, `shctx doctor` will surface a conflict warning. As of v5.0.9, `shctx init` also refuses to scaffold a new namespace when the other is already initialized, preventing this split-brain at the source.

#### `$SHEPHERD_WORKDIR` — work-directory override (v6.0.2)

`$SHEPHERD_WORKDIR` is the first-class, public way to point shepherd at a project-local work directory. Both the `shctx` runtime and the hooks honor it with this precedence:

1. **`$SHEPHERD_WORKDIR`** — if set and non-empty. An absolute path is used as-is; a relative path resolves against the repo root.
2. `$SHCTX_ROOT_OVERRIDE` — legacy override (kept for backward compat; set by `shctx init --artifacts`).
3. Existing **`.shepherd/`** (the default).
4. Existing **`.artifacts/`** (accepted auto-pickup fallback for legacy projects).
5. Otherwise default to **`.shepherd/`**.

When both `.shepherd/` and `.artifacts/` exist (and no override is set), shepherd picks `.shepherd/` and emits a split-brain warning (suppressed by `SHCTX_QUIET=1`).

### `[context]` — context registry (new in v5.0.0)

```toml
[context]
enabled         = true                       # opt-out is valid in v5.0.0-c (DB-optional); rejected in v5.0.0-d (DB mandatory)
db_path         = ".shepherd/root.db"        # SQLite cache backing the registry (.artifacts/ for legacy opt-in)
lock_path       = ".shepherd/shepherd.lock"  # file-based single-writer lock
project_id_path = ".shepherd/project.json"   # stable project_id (multi-project backbone)
auto_refresh    = ["on-sprint-open"]         # triggers that fire `shctx refresh --scope=all`

[context.refresh]
symbols_languages = ["rust"]                                # languages the symbol extractor walks
github_scope      = ["issues", "prs", "releases", "milestones"]  # GH index scope
ttl_minutes       = 30                                      # rows older than this are stale; engineer refreshes before query

[context.lock]
stale_minutes = 60     # locks older than this are reaped on next acquire attempt
reap_on_init  = true   # `shctx init` clears stale locks automatically

[context.naming]
seed     = "*.seed.md"     # discoverable artifact glob → indexed into `index_artifacts`
plan     = "*.plan.md"
phase0   = "*.phase0.md"
close    = "*.close.md"
walk     = "*.walk.md"
handoff  = "*.handoff.md"
spec     = "*.spec.md"
design   = "*.design.md"
journal  = "????-??-??.md"
```

The context registry is a per-project SQLite cache that backs:

- **Phase 0 mesh fast-path** — `shctx query open-issues --md`, `shctx query canonical-types --md` instead of MCP/CLI round-trips (per `agents/engineer.md` Phase 0 mesh inputs).
- **DEDUP-GATE Layer 2 SQL pre-filter** — `shctx query dedup-check --name=<symbol>` runs before per-lane greps (per `doctrines/zero-duplicate-tolerance.md` Layer 2 SQL fast-path).
- **`[DB-CONTEXT]` brief block** — populated via `shctx inject coder` (per `flock.md` → @coder).
- **Memory + profiles + locks + artifacts** — replaces the external `remember` plugin; tracks active locks; indexes discoverable artifacts via `[context.naming]` globs.

`enabled = false` is a valid configuration in v5.0.0-c (the DB is optional and the framework falls back to direct MCP/CLI). In v5.0.0-d the DB becomes mandatory — `shctx migrate` and `shctx status` reject `enabled = false`.

`auto_refresh` triggers (additive list):
- `on-sprint-open` — fire `shctx refresh --scope=all` at the top of every `/shepherd:start` and `/shepherd:spawn` walk (including `--auto` and `--parallel <N>` modes).
- `on-engineer-dispatch` — fire `shctx refresh --scope=github` if `index_issues.refreshed_at` older than `[context.refresh].ttl_minutes`.
- `on-close-finalize` — fire `shctx refresh --scope=artifacts` after handoff is written.
- `on-wave-gate` *(v5.0.3)* — fire `shctx refresh --scope=github,artifacts` after every `WAVE-GATE` lands. Combats stale carry-forward / dedup-ledger drift mid-sprint (per v5.0.1 field feedback §2.8). Recommended for L/XL sprints with 4+ waves; LOW for S/M sprints (refresh churn outweighs benefit).

#### Schema + views appendix (v5.0.0 — `schema/0001_init.sql`)

Bundled tables (full DDL lives in the `context` skill at `${CLAUDE_PLUGIN_ROOT}/skills/context/schema/0001_init.sql`):

| Table | Purpose |
|---|---|
| `schema_migrations` | migration tracking |
| `sessions` | session metadata |
| `profiles` | per-project profiles |
| `mem_entries` | memory entries (replaces external `remember` plugin) |
| `index_issues` | GH issue cache (Phase 0 mesh fast-path) |
| `index_prs` | GH PR cache |
| `index_releases` | GH release cache |
| `index_milestones` | GH milestone cache |
| `index_symbols` | extracted source symbols (DEDUP-GATE Layer 2 fast-path; `canonical-types` view) |
| `index_concepts` | canonical-concept ↔ symbol mapping |
| `logs` | structured event log |
| `index_artifacts` | filesystem-pointer table (driven by `[context.naming]` globs) |
| `locks_history` | audit trail for the file-based lock |
| `sprint_metadata` | sprint-state cache (deferred to milestone d) |

Bundled views (`schema/views/*.sql`):

| View | Purpose |
|---|---|
| `v_open_issues` | open-issue ledger sweep (Phase 0 mesh row 1) |
| `v_canonical_types` | canonical-types index (Phase 0 mesh row 12; replaces `{paths.ctx}/canonical-types.md` regeneration) |
| `v_drift_risk` | open CRITICAL/HIGH outside the current milestone |
| `v_mem_recent_7d` | last-7-day memories + pinned |
| `v_active_locks` | currently held locks |

Plus `queries/dedup-check.sql` — a parameterized SQL template bound at call time by `shctx query dedup-check --name=<symbol>`.

### `[skills]` — local-skill integration

```toml
[skills]
# Mandatory in every coder brief regardless of file scope.
# code-style is the canonical entry — your personal language preferences.
mandatory = ["code-style"]

# Domain-driven additions. The engineer reads file scope and adds matching
# entries to [SKILLS] in each coder brief.
[skills.by_domain]
rust       = ["rust"]
wasm       = ["webassembly"]
finance    = ["finance"]
supabase   = ["supabase:supabase"]
polymarket = ["polymarket"]
claude_api = ["claude-api"]

# Detection rules — which file-scope patterns map to which domains.
# Fallback: every Rust file → rust; every cmp/* path → wasm; etc.
[skills.detection]
rust       = ["**/*.rs"]
wasm       = ["cmp/**", "**/*.wit"]
supabase   = ["**/supabase/**", "**/migrations/**.sql"]
polymarket = ["**/polymarket/**", "**/clob/**", "**/pm/**"]
```

The mandatory list is enforced — every coder brief MUST carry these in `[SKILLS]` or the conductor's Brief-Validity Checklist rejects it. Domain entries are additive (the engineer plus the conductor decide which apply per lane).

### `[mcp]` — MCP server availability

```toml
[mcp]
# Which MCP servers shepherd can rely on. Affects engineer + worker tooling.
github   = true   # plugin_github_github__*  (issues, PRs, labels, milestones)
sentry   = true   # plugin_sentry_sentry__*  (Phase 0 mesh, error triage)
supabase = true   # plugin_supabase_supabase__* (schema mesh, query execution)
grafana  = false  # placeholder — wire when MCP available
```

If a server is `false`, the engineer's brief omits its tools and the corresponding mesh row is downgraded from "MUST query" to "if available, query".

### `[cli]` — CLI tool availability

```toml
[cli]
# CLI tools shepherd can shell out to via the Bash tool.
fly      = true    # flyctl — deploy + machine inspection
gh       = true    # gh — GH CLI (read-only enumeration; writes go through GH MCP per use_github_mcp_not_gh_cli doctrine)
docker   = true    # build verification before Fly deploy
just     = false   # justfile runner (if your project uses it)
make     = false
```

### `[ledger]` — issue-ledger awareness

```toml
[ledger]
# Combats the tunnel-vision failure mode where the conductor only sees
# current-milestone deliverables and ignores the broader open-issue ledger.
# Phase 0 mesh enumerates ALL open issues (not just current milestone) and
# surfaces non-current-milestone CRITICAL/HIGH items as drift risks.

# How many open issues, beyond the current milestone, the engineer must
# enumerate and classify in Phase 0. 0 = disabled (don't do this).
phase_0_full_ledger = true
classify_into = ["blocking-this-sprint", "labeled-non-issue", "tracking-future", "drift-risk"]

# Labels treated as "explicitly tracked but not actioned" — these are
# expected to persist across sprints and are not drift risks.
non_issue_labels = ["wontfix", "tracking-future", "design-question", "rfc"]

# Carry-forward ledger location.
carry_forward_file = "{paths.plans}/v{X}.{Y}.{Z}-carry-forwards.md"

# Threshold beyond which an issue gets the `chronic` label (≥ N patch
# crossings without being landed). Auditor (completeness) applies.
chronic_threshold_patches = 2
```

This block is what the operator was getting at with "tunnel vision" — shepherd's framework now structurally requires the engineer to enumerate the full open-issue space at every sprint open and classify each, so non-current-milestone CRITICAL items can't fester invisibly.

### `[release]` — release pipeline

```toml
[release]
# When dev.{N=last} closes, who drives the squash → tag → release pipeline?
# - "conductor"        : shepherd runs the full pipeline (squash, tag, gh release create, deploy)
# - "github-workflow"  : shepherd writes release notes + opens PR; a GH Actions workflow handles squash/tag/release
# - "operator"         : shepherd writes release notes; operator does the rest manually
driver = "github-workflow"

# Path to the release-notes file shepherd authors at dev.{last} close.
release_notes_path = "{paths.docs}/v{X}.{Y}.{Z}-release-notes.md"

# When driver = "github-workflow", the workflow filename to verify exists.
workflow_file = ".github/workflows/release.yml"
```

### `[memory]` — memory + doctrine paths

```toml
[memory]
# Where the user's auto-memory lives. Shepherd references this (read-only
# unless in planter mode) for project-specific feedback and project entries.
project_memory = "~/.claude/projects/-Users-jo3-src-fl03-axiom/memory"

# Path to additional project doctrines (memory entries that DRIFT beyond
# what the framework ships in skills/shepherd/doctrines/).
# These get loaded by every flock dispatch. Optional.
project_doctrines = ".claude/doctrines"
```

### `[hooks]` — local skill / hook integration

```toml
[hooks]
# Skills that should be loaded by EVERY flock agent dispatch (in addition
# to the agent's own [SKILLS] line). Use this to bake in project-wide
# context that every agent needs — e.g., a `project-glossary` skill.
on_every_dispatch = ["code-style"]

# Skills loaded only by the conductor (main chat), not by flock agents.
on_conductor_only = []

# Skills loaded only by the engineer.
on_engineer_only = ["workflow"]

# Skills loaded only by the planter.
on_planter_only = []

# v5.1.8+: suppress informational additionalContext emissions from hooks
# (bash_guard cargo-parallel warn, cd-into-worktree warn, session_open
# hygiene warnings). When true, the warnings are still logged to
# `<namespace>/logs/hooks/YYYY-MM-DD.jsonl` for grep, but no
# additionalContext JSON is emitted — Claude doesn't see them and the
# operator UI doesn't render them as a "PreToolUse error". Recommended
# only after the operator is familiar with shepherd's discipline rules.
# Default: false (warnings visible). Closes #19 as opt-out.
quiet_warnings = false
```

This is the integration point with locally developed skills — `code-style` is the canonical example, but you can wire any skill you want into the dispatch.

## Path interpolation

Any `{X}/{Y}/{Z}/{N}` placeholder in `branching`, `release`, or `ledger` is interpolated at runtime. Any `{paths.*}` reference is resolved against `[paths]`. So:

```toml
release_notes_path = "{paths.docs}/v{X}.{Y}.{Z}-release-notes.md"
```

resolves to (for v0.2.9):

```
.shepherd/docs/v0.2.9-release-notes.md
```

(or `.artifacts/docs/v0.2.9-release-notes.md` for projects on the legacy namespace).

## Defaults

If `shepherd.toml` is missing, shepherd uses these defaults (which work for a generic Rust project):

```toml
[project]
name = "{detected from Cargo.toml package.name or git remote}"
language = "rust"

[branching]
patch_branch_pattern  = "v{X}.{Y}.{Z}"
sprint_branch_pattern = "v{X}.{Y}.{Z}-dev.{N}"
sprints_per_patch     = 10
main_branch           = "main"

[gates]
check  = "cargo check --workspace"
lint   = "cargo clippy --workspace -- -D warnings"
format = "cargo fmt --all"

[paths]
plans   = ".shepherd/plans"
reports = ".shepherd/reports"
docs    = ".shepherd/docs"
ctx     = ".shepherd/ctx"

[skills]
mandatory = ["code-style"]

[skills.by_domain]
rust = ["rust"]

[mcp]
github = true
sentry = false
supabase = false

[cli]
gh = true
fly = false

[ledger]
phase_0_full_ledger = true
chronic_threshold_patches = 2

[release]
driver = "operator"
```

## Validation

`/shepherd:start` validates `shepherd.toml` at Step 0. Errors that block the sprint:

- `branching.patch_branch_pattern` and `branching.sprint_branch_pattern` don't share a common prefix → can't determine patch from sprint
- `gates.check` references a binary that isn't on `$PATH`
- `paths.*` directory exists but isn't writeable
- `[skills.by_domain]` references a skill slug not present in this Claude Code installation
- `[release].driver = "github-workflow"` but `workflow_file` doesn't resolve

Warnings (don't block):

- `[mcp]` server is `true` but the corresponding `mcp__plugin_*` tools aren't loaded in the current session
- `[ledger].phase_0_full_ledger = true` but the project has < 5 open issues (likely no drift risk surface)

## Language matrix

The framework expects gate commands and detection greps to come from the corresponding per-language skill. Reference table:

| Language | `[gates].check` | `[gates].lint` | `[gates].format` | `[skills.by_domain]` entry | Build manifest |
|---|---|---|---|---|---|
| Rust | `cargo check --workspace` | `cargo clippy --workspace -- -D warnings` | `cargo fmt --all` | `rust = ["rust"]` | `Cargo.toml` |
| Python | `uv run python -m mypy .` (or `pyright`) | `uv run ruff check .` | `uv run ruff format .` | `python = ["python"]` | `pyproject.toml` |
| TypeScript | `pnpm tsc --noEmit` | `pnpm eslint .` | `pnpm prettier --check .` | `typescript = ["typescript"]` | `package.json` |
| Go | `go build ./...` | `go vet ./... && staticcheck ./...` | `gofmt -l -w .` | `go = ["go"]` | `go.mod` |
| Mixed | (compose multiple) | (compose multiple) | (compose multiple) | per-language entries | per-language manifests |

For a language not listed: pick a `[gates]` triple that mirrors the (typecheck, lint, format) shape, and author a per-language skill that documents the idioms.

If the corresponding language skill doesn't exist in your Claude Code installation yet, create one — the [skill-creator](https://github.com/anthropic-experimental/skill-creator) is the canonical entry point. Shepherd is designed to compose with skills, not replace them.

## See also

- [`docs/integration.md`](integration.md) — how shepherd integrates with `code-style`, `rust`, etc.
- [`docs/customization.md`](customization.md) — bring-your-own branch model, custom doctrines
- [`examples/axiom/shepherd.toml`](../examples/axiom/shepherd.toml) — concrete working Rust config
