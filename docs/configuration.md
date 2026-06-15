# Configuration

Shepherd is project-agnostic. The framework speaks principles (Phase 0 mesh, SUBTRACT-DON'T-ADD, wrapper-must-earn, Pattern B overlap); per-language details (build commands, idioms, code-review preferences) come from per-language skills loaded via `[skills.by_domain]`.

> **Examples in this doc lean Rust** because that's the most-tested binding so far. Equivalent values for Python, TypeScript, Go, and others appear in the [Language matrix](#language-matrix) section at the end. The framework itself has no Rust dependency.

To bind shepherd to your repo, drop a `shepherd.toml` at one of these locations:

```
.claude/shepherd.local.toml   ← project-pinned, gitignored (operator per-key overrides)
.claude/shepherd.toml         ← project-pinned, checked into the repo (the base)
$XDG_CONFIG_HOME/shepherd.toml ← user-global default
```

**Resolution is per-key (v6.1.5+).** For any given key, `.claude/shepherd.local.toml`
overrides `.claude/shepherd.toml`, which overrides `$XDG_CONFIG_HOME/shepherd.toml`. A
`.local.toml` that sets only one key inherits the rest from the project file — it is a
partial override, not a whole-file replacement. Every hook guard and `shctx` command
resolves config through a single helper (`cfg_get`, defined in both `_lib.sh` files), so
the precedence is identical across the runtime and the hooks.

If no config is found, the entry commands **scaffold one and proceed** (v6.1.5 #15) rather than refusing or running blind. Run it yourself any time with:

```bash
shctx config init        # writes .claude/shepherd.toml from the bundled minimal template
```

`config init` is idempotent (it never clobbers an existing binding) and derives the load-bearing values automatically: `[project].name` from the git remote (falling back to the repo-root basename), `[gates]` from the repo's build manifest (`Cargo.toml`→cargo, `go.mod`→go, `pyproject.toml`/`setup.py`→pytest+ruff, `package.json`→npm), and `[paths]` realigned to whichever shctx namespace (`.shepherd/` or `.artifacts/`) the project already uses. The entry points wire it as follows:

- **`/shepherd:start`, `/shepherd:spawn` (root):** scaffold → one-line `[CONFIG]` notice → PROCEED. Execution sessions are action-biased (`doctrines/operator-signaling.md`); they do not stop for confirmation.
- **`/shepherd:plant`:** scaffold → **one batched `AskUserQuestion`** to confirm/refine the `[branching]` scheme and `[gates]` (the scaffold gets the toolchain right but can only guess version/branch topology) → continue. The planter plans *with* the operator, so it surfaces the choice but never blocks on a hand-edited file.

You should still review `[branching]` and any non-standard `[gates]` before the first sprint — a seed authored against guessed branching is drift on arrival.

## Schema

### `[project]` — identity

```toml
[project]
name        = "rust-service"    # repo / project name (required)
language    = "rust"            # primary language: rust | python | typescript | go | mixed
description = "Multi-crate Rust service — HTTP node + background worker"
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
    { name = "node-serve",   cmd = "cargo check -p service-node --features serve,native" },
    { name = "worker-serve", cmd = "cargo check -p service-worker --features serve" },
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
plans   = ".shepherd/docs/plans"     # seeds + plans (v6.1.2 standard — now under docs/)
reports = ".shepherd/docs/reports"   # close reports + audit reports (under docs/)
docs    = ".shepherd/docs"           # handoffs, specs, diagrams, journal, release notes
ctx     = ".shepherd/ctx"            # workspace knowledge silo (canonical-types, dedup-ledger, etc.)
```

Paths are relative to the repo root. Directories are auto-created on first write.

**Standard layout (v6.1.2).** The per-project workdir now follows a consistent internal tree — `docs/{plans,reports,diagrams,handoffs,specs,journal}/`, `logs/`, `archive/`, `cache/`, `scripts/`, `templates/`, `tmp/`, `types/`, plus `toolkit.json` (tracked) and `shepherd.db` (gitignored). `shctx init` scaffolds it for new projects. **Back-compat is total:** projects on the legacy shape (top-level `plans/`+`reports/`, `root.db`, `.artifacts/`) keep working untouched — the runtime auto-detects both. To migrate an existing project to the standard tree, run the opt-in `shctx migrate --layout v2` (idempotent; `git mv`s `plans/`→`docs/plans/`, `reports/`→`docs/reports/`, renames `root.db`→`shepherd.db`). See `skills/context/references/naming-conventions.md`.

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
db_path         = ".shepherd/shepherd.db"    # SQLite registry (v6.1.2; legacy root.db auto-detected; .artifacts/ for legacy namespace)
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
log      = "*.log.md"          # human-readable daily logs (v6.1.2; in logs/)
log_jsonl = "*.log.jsonl"      # machine event streams (v6.1.2; in logs/ or tmp/)
toolkit  = "toolkit.json"      # tool registry (v6.1.2; tracked, namespace root)
```

The `<slug>.<group>.<ext>` convention is uniform: a filename is a kebab/slug stem, a `<group>` tag (`seed`, `plan`, `phase0`, `close`, `walk`, `handoff`, `spec`, `design`, `log`, …), and an extension. Seeds/plans already use it (`v512-dev3.seed.md`); logs extend it (`2026-06-11.log.md`, `2026-06-11T14-32-45.log.jsonl`).

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

### Toolkit registry (v6.1.2)

The **toolkit** is a mutable registry of commonly-used tools — MCP servers, skills, plugins, CLIs, ssh targets — so a session never forgets a capability exists (e.g. `ssh pzzld@laptop`, the `context7` MCP). It is the tool-memory sibling of the adaptation loop's lesson-memory. Two tiers, merged at read time (local overrides global on name collision):

| Tier | File | Holds |
|---|---|---|
| `local` | `<namespace>/toolkit.json` (tracked) | project-specific tools |
| `global` | `$XDG_CONFIG_HOME/shepherd/toolkit.json` | cross-project tools (reused in every repo) |

Each entry carries the required `{ name, scope (local\|global), type (mcp\|skill\|plugin\|cli), capabilities[], description }` plus optional `invocation`, `when`, `tags`, `pinned`. It is **file + CLI managed** — no toml block required:

```bash
shctx toolkit add --name=context7 --type=mcp --scope=global \
  --description="library docs; prefer over web search" --capabilities=docs --pin
shctx toolkit list --scope=all          # merged roster (local ⊕ global)
shctx toolkit md   --scope=all          # markdown for brief / session injection
```

Three surfaces keep it in front of the model: (1) a **SessionStart hook** (`toolkit_surface.sh`) injects a compact roster every session — suppress it with `[hooks].quiet_warnings = true`; (2) the `shctx toolkit` CLI; (3) a `[TOOLKIT]` block injected into engineer/coder/planter briefs. **Never store secrets or credentials in the toolkit.** See `skills/shepherd/doctrines/toolkit.md`.

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
supabase   = ["supabase:supabase"]
payments   = ["payments"]
claude_api = ["claude-api"]

# Detection rules — which file-scope patterns map to which domains.
# Fallback: every Rust file → rust; every cmp/* path → wasm; etc.
[skills.detection]
rust       = ["**/*.rs"]
wasm       = ["cmp/**", "**/*.wit"]
supabase   = ["**/supabase/**", "**/migrations/**.sql"]
payments   = ["**/payments/**", "**/billing/**"]
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

# (v6.1.4) Backstop for the dev.{last} release-trigger miss: refuse to create or
# publish a sprint branch whose number N >= sprints_per_patch (there is no
# dev.{sprints_per_patch} — closing dev.{last} is a RELEASE, not a new sprint).
# block (default) | warn | off.
devlast_guard = "block"
```

### `[tmux]` — teammate pane observability + cleanup (v6.1.4)

```toml
[tmux]
# When teammateMode = "tmux" | "auto", Claude Code opens one pane per teammate.
# pane_cleanup reaps panes of CLOSED (crashed/retired) teammates at SessionEnd —
# the dead-pane gap (#66.6). on (default) | off.
pane_cleanup = "on"
```

Observe live teammate panes: `shctx panes status` (per-lane liveness dashboard),
`shctx panes capture` (snapshot each pane → `<ns>/logs/panes/<lane>.log`), and
`shctx panes tail <lane>`. For a live view, run it under native `/loop`:
`/loop 30s shctx panes status`. The pane id is captured automatically from each
teammate's heartbeat (`$TMUX_PANE`) — no `--pane` wiring needed.

### `[memory]` — memory + doctrine paths

```toml
[memory]
# Where the user's auto-memory lives. Shepherd references this (read-only
# unless in planter mode) for project-specific feedback and project entries.
project_memory = "~/.claude/projects/<your-project>/memory"

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

### `[spawn]` — teammate-spawn coordination (`/shepherd:spawn`)

```toml
[spawn]
# v6.0.5 — the coordinate-mode active-drive backstop (hooks/scripts/
# coordinate_drive_guard.sh, a Stop hook). Controls what happens when the root
# shepherd tries to END ITS TURN while a spawn session still has actionable,
# root-clearable coordinate state (an idle teammate, or unread lead mail) — i.e.
# the "spawn pauses at the dispatch boundary" failure (doctrines/
# coordinate-active-drive.md). Outside a live spawn session the guard fast-paths
# and never fires, so solo /shepherd:start and all non-spawn work are untouched.
#   block (default) — re-engage the root (Stop "decision: block") so it drains
#                     the work before yielding. Bounded by a 2-nudge runaway cap
#                     (then fails open) so a deliberate stop is never trapped.
#   warn            — never block; emit a one-line stderr nudge only.
#   off             — disable the guard entirely (fast-path exit).
coordinate_drive_guard = "block"

# Wave-ack / cross-dependency timeouts consumed by the escalation contract
# (doctrines/spawn-escalation.md). Optional; defaults shown.
wave_ack_timeout_sec  = 60     # conductor waits this long for a wave-ack before continuing
cross_dep_timeout_sec = 300    # CROSS-DEP-WAIT escalates to operator after this

# --- Toggles (v6.1.5 #10) — read via `shctx config get <key>`; defaults below
#     preserve the pre-v6.1.5 behavior exactly. -----------------------------

# Upper bound on `--parallel <N>` fan-out (Preflight Check 5). Default 4 — the
# pre-v6.1.5 hard cap, above which the lead's TeammateIdle handler saturates.
# Lower it on rate-limited plans (e.g. 2). N is still floored at 2 (N=1 is just
# a base spawn). Resolved at Check 5 via `shctx config get max_parallel 4`.
max_parallel      = 4          # int, 2..N — upper bound on --parallel fan-out

# Recommended cadence for the observability dashboard loop (#13):
#   /shepherd:loop <dashboard_cadence> shctx dash
# Default 3m (suits active waves; widen to 5m+ for slow sprints). Purely a
# recommendation surfaced in the [SPAWN] confirmation — the dashboard is
# read-only, so the cadence never affects sprint state.
dashboard_cadence = "3m"       # duration — default interval for the dash loop
```

> **Prompt-cache TTL (caching optimization, v6.0.5).** A multi-wave sprint easily
> exceeds the **5-minute** default cache TTL between waves (gates, audits, operator
> pauses), so cached brief/system prefixes silently expire and get re-created at full
> input rate. For `--scope >= patch` (and any long autorun) set
> **`ENABLE_PROMPT_CACHING_1H=1`** in your environment to opt into the **1-hour** TTL
> (unified flag, April 2026; works on API key / Bedrock / Vertex / Foundry — Claude
> *subscriptions* already request 1h automatically, so this matters most for API-key
> use). This is the single highest-leverage token win for long runs. Refs:
> `https://code.claude.com/docs/en/prompt-caching`, `doctrines/cache-telemetry.md`.

### `[autorun]` — unattended sequential walks (`/shepherd:spawn --scope patch` / `--auto`)

Governs the sequential autopilot that walks `dev.0..dev.LAST` unattended. All keys
are read via `shctx config get <key>`; the defaults reproduce the pre-v6.1.5
behavior exactly, so an existing project sees no change until it opts in.

```toml
[autorun]
# Grade floor for an unattended walk. A sprint that closes BELOW this grade
# triggers `on_grade_floor`. Grades are the close-report letter grades
# (A+ … F) from references/grading-rubric.md. Default B.
min_grade      = "B"           # letter grade — floor for continuing the walk

# What the walk does when a sprint grades below `min_grade` (v6.1.5 #10):
#   abort (default) — emit the AUTO ABORT REPORT and stop the walk. This is the
#                     pre-v6.1.5 GRADE-FLOOR behavior (commands/spawn.md autorun
#                     loop; agents/planter.md §autorun).
#   pause           — pause and surface one operator decision (re-spawn the
#                     failed sprint / continue anyway / stop), then honor it.
#   continue        — log a GRADE-FLOOR warning to the walk status and proceed
#                     to the next sprint (fully unattended; use with care).
on_grade_floor = "abort"       # abort (default) | pause | continue

# Pause posture BETWEEN sprints in a sequential walk (v6.1.5 #10):
#   brief (default) — emit the inter-sprint status + a short (~5s) window, then
#                     proceed. This is the pre-v6.1.5 behavior.
#   signoff         — hard pause; require an explicit operator sign-off before
#                     opening the next sprint (turns the walk semi-attended).
#   none            — fully continuous; no inter-sprint pause window at all.
inter_sprint_pause = "brief"   # brief (default) | signoff | none
```

`min_grade` has always been consulted by the `--auto` / `--scope patch` loop and the
planter's autorun step; v6.1.5 documents the section it lives in and adds the two
behavior toggles around it. The grade-floor abort remains the default, so nothing
changes unless you set `on_grade_floor` / `inter_sprint_pause`.

### `[compaction]` — compaction resilience (v6.0.9)

```toml
[compaction]
# Snapshot drive-state to disk immediately before any compaction event
# (manual /compact or auto-compact). The PreCompact hook writes a JSON
# snapshot of state.json ready/in_flight sets, trace tail, undrained mailbox,
# shepherd.lock, and the current focus digest into
# <namespace>/snapshots/precompact-<session>-<epoch>.json.
# Never blocks compaction — the hook always exits 0.
precompact_snapshot = "on"   # on (default) | off

# How many precompact snapshots to retain per namespace. Older snapshots
# are pruned on each PreCompact firing. Set 0 for unlimited (not recommended).
snapshot_retention  = 5      # int — keep N most-recent snapshots
```

Snapshots land in `<namespace>/snapshots/` (created automatically). They survive compaction because compaction truncates only the conversation, not the filesystem.

#### Auto-compaction threshold — `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`

The **only** official knob for tuning when automatic compaction fires is the environment variable `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` (integer 1–100). Set it in your `settings.json` under `env`:

```json
{
  "env": {
    "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "70"
  }
}
```

**Important constraints and honest caveats:**

- **Global only.** This variable affects every Claude Code session on the machine — shepherd sessions, plain coding sessions, everything. There is no per-model, per-project, or per-session form.
- **No disable toggle.** There is no documented way to turn auto-compaction off entirely.
- **Agents cannot self-trigger or steer compaction.** There is no tool, slash command, SDK call, or hook return value that lets the model initiate `/compact`. The model also cannot read its own live context percentage — `/context` is display-only. Shepherd therefore cannot time compaction deliberately (e.g., at a wave boundary); it can only make each compaction event *safe* (snapshot) and statistically *earlier/cheaper* (lower threshold).
- **No recommended default is shipped.** Lowering the threshold (e.g., to 70%) makes compactions fire earlier and more often, which tends to cluster them at lower-context moments near wave boundaries — useful for long Sonnet-root spawns. But it also increases compaction frequency, which trades against the snapshot+rehydrate overhead. Operators running long `--scope patch` or `--scope minor` sprints with Sonnet as root may find ~70 a reasonable starting point. Operators who rarely hit the context limit should leave it unset (platform default, typically 95%).

### `[focus]` — focus loop rehydration (v6.0.9)

```toml
[focus]
# Re-inject the latest precompact snapshot as additionalContext after a
# compaction event, so the orchestrator resumes its drive deterministically.
# Primary path: SessionStart with source == "compact".
# Guaranteed fallback: UserPromptSubmit that drains the rehydration-pending
# flag once (drain-once, runaway-bounded).
# Gating this off disables both paths; the snapshot file is still written
# (controlled separately by [compaction].precompact_snapshot).
rehydrate        = "on"   # on (default) | off

# Default max_iterations for FOCUS-LOOP pattern instances (Pattern 6,
# FOCUS-LOOP composite). Each /shepherd:focus or shctx loop init call that
# does not supply an explicit --max inherits this value. Raise for very long
# sprints; lower for bounded sub-loops.
loop_max_default = 8      # int — default max_iterations for FOCUS-LOOP

# Whether the root (under /shepherd:spawn) and long-running conductors enter
# the FOCUS-LOOP by default on team initialization / lane start. "on" means
# active coordination is the primary operating mode (wake → act → probe),
# not a fallback; coordinate_drive_guard.sh is the backstop that catches
# lapses, not the mechanism. Set "off" to suppress and rely on the backstop
# alone — not recommended.
loop_default     = "on"   # on (default) | off — root (under /shepherd:spawn) and long-running conductors adopt the FOCUS-LOOP by default to stay active/focused (Pattern 6; doctrines/coordinate-active-drive.md)
```

The focus record itself (objective, active Stage-Graph node, ready-set, outstanding obligations, invariants) lives in `root.db` (`focus` table) and survives compaction natively. The rehydration consumer reads the latest snapshot + focus digest and emits them as `additionalContext` so the model's drive cursor is restored without manual re-orientation.

### `[close]` — close-phase behavior

Controls authorized supervised self-heal during a post-close soak (v6.1.5 #148,
`doctrines/autonomous-sentinel.md`).

```toml
[close]
# Authorized supervised self-heal during a post-close soak (v6.1.5 #148).
# Default OFF = detection-only: a SOAK-LOOP surfaces an OUTCOME-REGRESSION and the
# operator decides. Setting "on" ALONE does nothing — the seed must ALSO declare
# `close: autonomous-sentinel` AND carry a complete `sentinel_rails` block
# (gates-before-deploy, max_severity, max_concurrent, hf_cap, no_destructive_db_ops,
# auto_rollback, live_flip, operator_override_each_tick, audit_trail). Three
# independent opt-in gates; the safe default is detection-only.
# See doctrines/autonomous-sentinel.md and references/loop-templates.md §AUTONOMOUS-SENTINEL.
autonomous_sentinel = "off"   # off (default — detection-only) | on
```

### `[discovery]` — capability auto-discovery (SessionStart)

Controls the capability auto-discovery probe (v6.1.5 #146,
`doctrines/capability-discovery.md`).

| Key | Type | Default | Meaning |
|---|---|---|---|
| `auto_capabilities` | `on` \| `off` | `on` | When `on`, the `capability_discovery.sh` SessionStart hook enumerates installed plugins/skills and writes an EPHEMERAL capability roster to `<workdir>/cache/discovered-capabilities.json` (gitignored, distinct from the curated `toolkit.json`). Surfaced — labeled auto-discovered — in the SessionStart roster and engineer/coder/planter `[TOOLKIT]` blocks. Set `off` to disable the probe entirely. Zero hot-path cost (one-time-per-session, fail-open); never hard-depends on a third-party plugin. |

```toml
[discovery]
auto_capabilities = "on"   # auto-detect available plugins/skills; "off" disables
```

### `[ponytail]` — senior-engineering standard + `/shepherd:ponytail`

Controls the senior-engineering operating standard (v6.1.6,
`doctrines/senior-engineering.md`) that elevates `@auditor` and `@coder`, and the
on-demand `/shepherd:ponytail` review→refine→verify command (`commands/ponytail.md`).

| Key | Type | Default | Meaning |
|---|---|---|---|
| `senior_standard` | `on` \| `off` | `on` | When `on`, the conductor injects a stable `[SENIOR-STANDARD]` pointer block (a reference, NOT a re-paste — `doctrines/brief-cache-discipline.md`) into every `@auditor`/`@coder` brief, so the eight senior primitives are always-on. `off` restores pre-v6.1.6 briefs (the agents still honor the doctrine they cite, but it is not re-surfaced per brief). |
| `default_mode` | `review` \| `refine` | `review` | Default mode for `/shepherd:ponytail` with no `--mode`/`--apply` flag. `review` = read-only senior report; `refine` = review → apply → re-verify. |
| `max_verify_iterations` | integer ≥ 1 | `3` | Cap on the review↔refine↔re-verify loop (Pattern 3 / `references/loop-templates.md §AUDITOR-REFINE`). Reaching it with findings open halts as `PONYTAIL-LOOP-CAP`. |
| `apply_requires_approval` | `true` \| `false` | `true` | When `true`, the refine (coder-apply) phase pauses for operator approval before any write. `--no-approval` overrides per-invocation. |
| `conformance_sources` | array | `["doctrines","styles","ledger","adaptation","neighbors","defaults"]` | The `senior-engineering.md §V` precedence ladder, highest-first. Operator-reorderable to express project taste (e.g. demote `neighbors` if the codebase is mid-migration). |

```toml
[ponytail]
senior_standard       = "on"        # inject [SENIOR-STANDARD] into auditor/coder briefs
default_mode          = "review"    # review (read-only) | refine (review→apply→verify)
max_verify_iterations = 3           # cap on the review↔refine↔re-verify loop
apply_requires_approval = true      # pause for approval before the coder-apply phase
conformance_sources   = ["doctrines", "styles", "ledger", "adaptation", "neighbors", "defaults"]
```

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
plans   = ".shepherd/docs/plans"
reports = ".shepherd/docs/reports"
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
- [`examples/rust-service/shepherd.toml`](../examples/rust-service/shepherd.toml) — concrete working Rust config
