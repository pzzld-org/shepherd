# shepherd — changelog

The `shepherd` plugin's per-version history. Format loosely based on [Keep a Changelog](https://keepachangelog.com/); follows [Semantic Versioning](https://semver.org/).

Repo-level changelog covering both `shepherd` and `fl03-skills` lives at the [repo root](../../CHANGELOG.md).

---

## v5.0.4 — 2026-05-05

**v5.0.3 field-feedback batch + ctx production-grade pass + token-budget
pipelines.** Compiled live from the v5.0.3 conductor's working notes during
the axiom v0.3.0-dev.5 sprint
(`~/src/fl03/axiom/.artifacts/docs/shepherd-v503.feedback.md`). Every
addition cites the originating §. Plus operator-driven asks: ctx command
production-grade, multi-step automation pipelines, flag consistency, and
project-agnostic cleanup.

### Added — doctrines

- **`doctrines/worktree-base-drift.md`** *(§1)* — explicit ban on
  `Agent({ isolation: "worktree" })` for sprint coder dispatch. Conductor
  pre-creates worktrees from sprint HEAD via `shctx worktree create-batch`,
  then pastes `[WORKTREE-PATH]` and `[BASE-COMMIT-EXPECTED]` into briefs.
  Eliminates the v5.0.3 axiom dev.5 BASE-DRIFT pattern.
- **`doctrines/worktree-confinement.md`** *(§3)* — ALL coder writes
  (including `.shepherd/ctx/*.md`) MUST land under `[WORKTREE].Path`.
  Writes to sprint root are silently dropped from the cherry-pick;
  documented with the field origin and a worked example.
- **`doctrines/coder-brief-format-shared-artifacts.md`** *(§4)* — when
  multiple coder lanes write to the same shared file, the brief specifies
  Pattern A (line-range partition), Pattern B (footer-append), or
  Pattern C (single-author-per-file). Prevents cherry-pick conflicts.

### Added — references

- **`references/grading-rubric.md`** *(§9)* — explicit weight + numeric
  formula for synthesizing per-concern audit grades into a sprint-level
  grade. Default weights: completeness 0.35, code-quality 0.20,
  dependency-topology 0.20, data-flow 0.15, datastore-state 0.10.
  Overridable via `[gates.audit_weights]` in shepherd.toml.

### Added — context registry

- **`shctx worktree create-batch <lane-id…> [--from=<branch>]`** *(§1)* —
  pre-creates one worktree per lane-id at `.claude/worktrees/agent-<id>`
  rooted at the HEAD of `--from` (default: current branch). Emits
  `[BASE-COMMIT-EXPECTED] <SHA>` for the brief. Idempotent.
- **`shctx doctor [--md|--json]`** — first-class diagnostic / pre-flight:
  required binaries, namespace dir + project.json, schema version +
  pending migrations, lock state (held/stale/free), refresh staleness per
  zone, shepherd.toml locatability. Exit 0 / 1 / 2 (ok / fail / warn).
- **Multi-step pipelines (operator ask):**
  - **`shctx sync [--scope=…|--all]`** — refresh → lint → status.
  - **`shctx ready`** — init → migrate → refresh `--all` → lint → doctor.
  - **`shctx sprint open <branch>`** — lock acquire → refresh `--all` →
    lint → status.
  - **`shctx sprint wave <id> [--all]`** — refresh github+artifacts → lint
    (replaces `auto_refresh = ["on-wave-gate"]`).
  - **`shctx sprint close <branch>`** — close-lane (each known) → handoff
    create → worktree gc → lock release.
  - **`shctx audit`** — read-only validation: lint → doctor → status.
- **`shctx_gh_retry()` helper in `_lib.sh`** *(§8)* — 3× retry with
  exponential backoff for transient `gh` failures (504/502/503/timeout).
  Wired into `refresh-github.sh` + `cmd_close-lane.sh`.
- **`shctx export --all`** — bundles every export kind (canonical-types,
  open-issues, open-prs, recent-releases, drift-risk, mem) to a directory.
- **`shctx mem show <id>` + `shctx mem rm <id>`** — completes the mem CRUD
  surface (was add/list/search/pin/unpin).
- **`shctx lock release --force`** — explicit alias for force-clearing a
  stuck lock (parallel to `lock reap`).
- **Role-tailored `shctx inject`** *(token budget)* — engineer gets the
  full context surface (limit 80); coder gets a `[FILE-SCOPE]`-filtered
  subset (limit 30); auditor gets cross-cutting state only (limit 25).
  `--limit=N` overrides; `--full` removes the cap. Meaningful per-brief
  token reduction without quality compromise.

### Added — flag consistency

- **`--all` is the canonical universal flag** across `refresh`, `search`,
  `style init`, `worktree gc`, `lock release`, `export`. Aliases
  `--scope=all` where applicable; preserves backward compat. The
  inconsistency caller-side (`--all` here, `--scope=all` there) is
  resolved.

### Added — Stage Graph node taxonomy

- (No new node types; `WORKTREE-CREATE-BATCH` is now the conductor-inline
  predecessor of every `WAVE-IMPL` per `worktree-base-drift.md`.)

### Hardened — auditor discipline *(§2)*

- **`agents/auditor.md`** — new hard constraint: auditors verify
  `git rev-parse HEAD` matches the sprint root before invoking any gate
  command. `WORKTREE-DRIFT` halt code added. Every gate finding cites the
  gate's `Finished` or `error:` line verbatim as evidence.
- **`doctrines/auditor-readonly.md`** — adds the WORKTREE-DRIFT halt
  with field-origin attribution.

### Hardened — coder discipline *(§3)*

- **`agents/coder.md`** — new hard prohibition: NEVER write outside the
  worktree, including `.shepherd/ctx/*.md` artifacts. Cite
  `doctrines/worktree-confinement.md`.

### Hardened — SUBTRACT doctrine *(§5)*

- **`doctrines/subtract-dont-add.md`** — LOC-delta measurement scoped to
  `[gates.subtract_paths]` from `shepherd.toml`. Documentation, audit
  artifacts, plans, reports, journals are OUTSIDE scope by construction.
  Default glob is Rust-leaning (`crates/**/*.rs bin/**/*.rs **/*.toml
  **/*.sql`); override per-project for other languages.

### Hardened — pipeline.md

- New § XV-bis: worktree `target/` policy (worktrees DO share parent
  cache; coder no-cargo prohibition stays in force).
- New § XV-ter: `SendMessage` (existing agent) vs `Agent({...})` (new
  spawn) distinction for operator-directed amendments *(§7)*.
- New § XV-quater: shared-context append discipline (cross-ref).

### Compressed — token optimization (operator ask)

- **`SKILL.md` § VII anti-patterns** — collapsed from 18 verbose
  paragraphs to 21 single-line cues with doctrine cross-references.
  Authoritative content lives in the doctrines; the cue list is just
  the conductor's mental index.
- **Role-tailored inject** (above) — delivers the token savings where
  briefs are largest.

### Project-agnostic cleanup

- **`cmd_init.sh`**, **`styles/rust.md`**, **`doctrines/use-mcp-not-cli.md`**
  — replaced residual axiom-specific examples with project-agnostic
  placeholders. Bundled defaults are now neutral; project-specific
  details belong in the consumer's `.shepherd/styles/<lang>.md` and
  `.claude/doctrines/`.
- **`doctrines/conductor-cwd.md` + `gates-restoration.md`** — added
  "Project-agnostic principle:" preamble to each, separating the
  framework-intrinsic rule from its field-origin attribution.
- **Auto-detection** of `.shepherd/` vs `.artifacts/` audited across
  every script: only `_lib.sh` and `cmd_init.sh` reference either path
  literally; all other scripts route through `shctx_artifacts_root()`.
- **`[gates.subtract_paths]`** added to `docs/configuration.md` — gives
  projects an explicit knob for the SUBTRACT scope without baking
  language-specific globs into the framework.

### Tests

- 5 new tests: `test_doctor.sh`, `test_sync.sh`, `test_sprint_pipelines.sh`,
  `test_worktree_create_batch.sh`, `test_flag_aliases.sh`. Suite is now
  27/27 passing on macOS bash 3.2.

### Migration notes

- No new schema migrations — all v5.0.4 features run on the v5.0.3 schema
  (0001–0004). `shctx migrate` is a no-op for v5.0.3 → v5.0.4 upgrades.
- Coder briefs SHOULD now include `[WORKTREE-PATH]` (in addition to
  `[BASE-COMMIT-EXPECTED]` from v5.0.3). Pre-v5.0.4 conductors recording
  the SHA but no path keep working.
- `shctx inject coder --scope=<glob>` is new; old call form
  `shctx inject coder` still works (returns the unfiltered top-30 set).

### Pushed to v5.1+ (intentionally NOT in this patch)

- syn-based Rust symbol parser (drops shell regex)
- Vector embeddings on top of FTS5 for semantic search
- `index_imports` + `index_callers` cross-reference tables
- Hook-based engineer source-code-write filter (currently a doctrine)
- `shctx ctx-merge <file> <wt-1> <wt-2>` automated section-partitioned
  merger for shared `.shepherd/ctx/*.md` files
- Per-worktree `target/` isolation via `CARGO_TARGET_DIR` (currently
  documented in pipeline.md § XV-bis as opt-in via `[env]` block)

---

## v5.0.3 — 2026-05-05

**Field-feedback-driven discipline + tooling.** Compiled live from the v5.0.1
conductor's working notes during the axiom v0.3.0-dev.4 XL rescue sprint
(`~/src/fl03/axiom/.artifacts/docs/shepherd_feedback_v501.md`). Every
addition cites the originating §.

### Added — doctrines

- **`doctrines/conductor-cwd.md`** *(§2.1)* — the conductor never `cd`'s mid-Bash. Use `git -C <path>` and absolute paths instead. Bash's persistent cwd was causing conductor commits to land on worktree branches.
- **`doctrines/gates-restoration.md`** *(§2.4)* — when gates are red, run a conductor-inline `GATES-DISCOVERY` first to capture the FULL latent error inventory, then brief Lane 0 on all errors — not just the engineer-found subset. Cuts the 5–7-iteration hot-fix cascade pattern.

### Added — brief contract

- **`[BASE-COMMIT-EXPECTED]` block** in coder briefs *(§2.3)* — the conductor records `git rev-parse HEAD` of `{sprint_branch}` immediately before dispatch and pastes the SHA into the brief. The coder's new **Step 0.5** verifies and halts with `BASE-DRIFT` on mismatch (catches worktrees branched from `main` instead of the active sprint branch — the v5.0.1 cherry-pick storm).
- New halt code: **`BASE-DRIFT`** (alongside `BRIEF INVALID`, `CONTEXT-INVENTORY STALE`, `DUPLICATION RISK`, `BRIEF-AMENDMENT REQUEST`, `SCOPE OVERFLOW`).

### Added — context registry

- **`shctx search <text>`** *(§3)* — FTS5 fast-path over symbol index + artifact content. `--scope=symbols|artifacts|all`, `--md|--json`, `--limit=N`. Solves the "which crate has the BookSnapshot type?" / "did any close report mention X?" queries that grep returns thousands of false positives for.
- **`shctx close-lane <lane-id> --sprint=<branch> [--issues=#a,#b] [--status=...]`** *(§2.7)* — record a mid-sprint lane closure; auto-resolves carry-forward ledger entries by querying `gh issue view --json state`; emits a markdown patch the conductor commits to the ledger.
- **`shctx worktree list|gc|merge`** *(§4 P3)* — worktree hygiene helpers. `gc --older-than=<hours>` prunes stale `.claude/worktrees/agent-*`. `merge <agent-id> --strategy=theirs|prompt --no-cleanup` cherry-picks a coder's worktree HEAD onto the sprint branch with optional cleanup. Uses `git -C <path>` per `doctrines/conductor-cwd.md` — conductor never leaves sprint root.
- **`v_canonical_types` view tightened** *(§2.2)* — now filters to `kind ∈ {struct, enum, trait, class, interface, type-alias}` AND `visibility = pub`. The previous broad-query semantic moved to the new `v_canonical_symbols` view.
- **`auto_refresh = ["on-wave-gate"]` trigger** *(§2.8)* — fire `shctx refresh --scope=github,artifacts` after every `WAVE-GATE`. Combats stale carry-forward / dedup-ledger drift mid-sprint. Recommended for L/XL sprints.

### Added — schema migrations

- **`0003_canonical_types_filter.sql`** — recreates `v_canonical_types` with kind+visibility filters, adds `v_canonical_symbols` for broad queries, adds `lane_closures` table for the `close-lane` audit trail.
- **`0004_fts_search.sql`** — adds `index_fts_symbols` + `index_fts_artifacts` FTS5 virtual tables with sync triggers, plus a `content` column on `artifacts` so artifact body is searchable. Backfills both FTS tables for projects upgrading from older schemas.

### Added — Stage Graph node taxonomy

- **`GATES-DISCOVERY`** — conductor-inline; predecessor of any `WAVE-IMPL` whose mission is "restore the gates" (typically Wave 0 / Lane 0). Per `doctrines/gates-restoration.md`.
- **`LANE-CLOSE`** — conductor-inline (`shctx close-lane <lane-id>`); fires after each `WAVE-GATE` per lane. Carry-forward auto-resolution.

### Hardened — engineer prohibition

- **`agents/engineer.md` "DO NOT write source code" doctrine substantially stiffened** *(§2.5)*. Field origin: v5.0.1 commit `ffd9dbd7` where the engineer wrote `.rs` to "fix two clippy items". The new wording lists the specific path extensions banned, names the auditor `completeness` grep that catches the violation, and gives the alternative pattern (`BRIEF-AMENDMENT REQUEST` for a hot-fix coder lane). Plus a new "When you spot a bug while meshing" section that walks the discipline.

### Hardened — symbol extractor

- **`refresh-symbols.sh`** *(§2.2)* — now indexes `pub use` re-exports (single, group, and `as Alias` rename forms). `re-export` is a new `kind` value. Multi-line `pub trait Foo: Bar where ...` declarations are picked up via the line carrying the trait name.
- Conductor anti-patterns (15–18) added to `SKILL.md` §VII covering all the discipline shifts above (cwd, broad-sweep, base-drift, stale-ledger).

### Tests

- 4 new tests: `test_search.sh`, `test_close_lane.sh`, `test_canonical_types_filter.sh`, `test_pub_use_re_exports.sh`. Suite is now 22/22 passing on macOS bash 3.2.

### Migration notes

- Run `shctx migrate` once per project on upgrade. 0003 + 0004 apply idempotently. Existing projects' `artifacts.content` starts NULL and populates on next `shctx refresh --scope=artifacts`.
- `[context].auto_refresh` is additive. Add `"on-wave-gate"` to opt in; existing projects without the entry behave unchanged.
- `[BASE-COMMIT-EXPECTED]` becomes mandatory in v5.0.3 briefs. Conductors running pre-v5.0.3 plans should add it manually (the SHA from `git rev-parse HEAD` at dispatch time).

### Pushed to v5.1+ (intentionally NOT in this patch)

- syn-based Rust symbol parser (drops shell regex)
- Vector embeddings on top of FTS5 for semantic search
- `index_imports` + `index_callers` cross-reference tables
- Hook-based engineer source-code-write filter (currently a doctrine; would need user-project hook installation)

---

## v5.0.0 — 2026-05-XX

**MAJOR — adds context registry contract.**

- **DEFAULT CHANGE:** per-project namespace is now `.shepherd/` (auto-detects existing `.artifacts/`; `init --artifacts` opts back in).
- **NEW:** `/shepherd:ctx` command + bundled `shctx` CLI.
- **NEW:** Per-project SQLite registry at `.shepherd/root.db` (or `.artifacts/root.db` for legacy opt-in; schema 0001).
- **NEW:** Doctrine `context-registry.md` (cache vs canonical zones, fall-back contract).
- **NEW:** DEDUP-GATE Layer 2 SQL fast-path (`shctx query dedup-check`); grep remains contract.
- **NEW:** `[DB-CONTEXT]` block in coder briefs (optional in c; mandatory in d).
- **NEW:** `mem` subcommand replaces external `remember` plugin.
- **NEW:** Lock-coordinated autorun + parallel sessions (`.artifacts/shepherd.lock`).
- **NEW:** `shepherd.toml` `[context]`, `[context.refresh]`, `[context.lock]`, `[context.naming]` sections.
- **NEW:** Naming-convention enforcement (`shctx lint`).
- **NEW:** `shctx style <init|show|edit|list>` — per-language project style files at `.artifacts/styles/<lang>.md` (rust/python/typescript/go/shell/sql).
- **NEW:** Schema migration `0002_styles.sql` — `styles` table.
- **NEW:** Conductor mechanically injects `[CODE-STYLE]` block from `.artifacts/styles/<lang>.md` into every coder brief whose `[FILE-SCOPE]` matches a language.
- **NEW:** Doctrine `worker-patterns.md` — main-chat dispatch heuristics for non-code work (issue triage, deploy monitoring, branch cleanup, research, file org).
- **HARDENED:** Engineer brief now enforces seed → `superpowers:brainstorming` → `superpowers:writing-plans` load order; auditor `completeness` verifies trace.
- **HARDENED:** Auditor `completeness` checks `[CODE-STYLE]` presence on every code-touching coder lane.
- Self-host: this repo now scaffolds `.artifacts/` and registers its own design specs.

Migration from v4.2.0: run `shctx init` once; existing markdown artifacts continue to work. DB is optional in milestone (c); becomes contract-mandatory in milestone (d) of the v5.0.0 line.

---

## [4.2.0] — 2026-05-04

The Stage Graph release. Orchestration moves from the conductor's working memory into a declarative DAG the engineer's plan emits. Plus a hard zero-tolerance dedup contract enforced as a conductor-side pre-dispatch gate.

### Added

- **`skills/shepherd/pipeline.md`** — the Stage Graph contract. Defines node taxonomy, edge labels, walk algorithm, and the canonical sprint DAG. Pattern B is now a graph constraint (`parallel_with`); WORKER-IO is auto-batched with WAVE-1-IMPL by graph construction.
- **`skills/shepherd/doctrines/stage-graph.md`** — the principle: every plan emits a Stage Graph; every dispatch is a graph edge; off-graph dispatch is a process violation auditors catch.
- **`skills/shepherd/doctrines/zero-duplicate-tolerance.md`** — three-layer anti-duplication contract. Layer 1: engineer pre-populates `[CONTEXT-INVENTORY]` and `[DO-NOT-DUPLICATE]`. Layer 2 (the primary defense): conductor runs every dedup grep BEFORE the Agent batch fires; hits ≠ expected → dispatch BLOCKED, brief amended to "wire to existing", re-fire. Layer 3: coder-side fallback halt. Includes mechanical `[SKILLS]` auto-attachment per file scope, the `{paths.ctx}/canonical-types.md` workspace catalog contract, and cross-coder coherence rules.
- **`DEDUP-GATE` graph node** — runtime body of the Brief-Validity Checklist; predecessor of every WAVE-IMPL.
- **`CANONICAL-TYPES-REFRESH` worker node** — fires at every dev.0; refreshes `{paths.ctx}/canonical-types.md` so subsequent sprints' Phase 0 starts from a current workspace catalog.
- Stage decomposition hint section (§7-bis) in `references/seed-template.md` — the planter sketches a non-binding partial DAG; the engineer specializes it into the binding `## Stage Graph` plan section.
- Required `## Stage Graph` plan section per `agents/engineer.md` §"plan-quality bar".

### Changed

- **`skills/shepherd/SKILL.md` §III** — references the Stage Graph as the dispatch source-of-truth. Conductor checklists per §1/§2/§3 reformulated as graph-walk operations. Anti-patterns table extended (off-graph dispatch, stale canonical-types catalog, dedup-skip elevated to ZERO-TOLERANCE).
- **`skills/shepherd/flock.md` @coder Required-Skills Matrix** — conductor now MECHANICALLY computes `[SKILLS]` per file scope from `[skills.mandatory]` + `[skills.detection]` + `[skills.by_domain]`. Engineer's suggestions are a SUBSET, never authoritative. Skill-attachment audit at sprint close emits `SKILL-DRIFT` findings.
- **`skills/shepherd/flock.md` Brief-Validity Checklist** — IS the runtime body of the DEDUP-GATE node. Failure on any line BLOCKS dispatch.
- **`skills/shepherd/references/agent-briefs.md` Brief-Validity Checklist** — restructured into brief-shape / skills auto-attachment / anti-duplication pre-flight sections, each enforced before the Agent batch fires.
- **`agents/coder.md` Startup Protocol** — Step 2 now requires reading `{paths.ctx}/canonical-types.md` first; Step 3 (dedup grep) framed as a fallback tripwire (the conductor's pre-flight is the contract, not the coder's halt).
- **`agents/engineer.md`** — plan-quality bar requires `## Stage Graph` section; hard prohibitions extended to forbid omitting the graph.
- **`skills/shepherd/autorun.md`** — loop is "walk graph, then re-walk new graph for next sprint" instead of "remember the per-stage discipline". Cognitive load drops.
- Plugin manifest description updated to surface Stage Graph + DEDUP-GATE.

### Compatibility

Pre-4.2.0 plans without `## Stage Graph` continue to work — the conductor falls back to the §III §1/§2/§3 sequencing in `SKILL.md`. New plans (post-install) MUST emit the graph.

### Why this version

The pre-4.2.0 conductor re-derived dispatch sequencing at every decision point by reading SKILL.md §III + flock.md + the plan in working memory. Cognitive cost was high; failure modes (silent drift, skipped Pattern B, ad-hoc dispatch, **duplicate code re-introduced across sprints**) compounded. v4.2.0 moves orchestration from working memory to declarative artifact: the engineer emits the graph; the conductor walks it; deviation is structurally visible. Plus the DEDUP-GATE makes duplicate-code-shipping mechanically impossible — the conductor blocks the Agent batch before the coder ever sees it.

---

## [4.1.0]

GitHub-leverage release. Planter publishes patch arcs into GH milestone descriptions; sprint seeds remain local. Lane discipline anchored by GH issues. Full-ledger Phase 0 sweep (combats tunnel vision). Carry-forward chronic flagging at ≥ 2 patch crossings.

## [4.0.0]

Initial extracted-and-generalized cut from the v3.2.0 axiom-pinned skill. Closed-flock contract (5 agents: engineer, critic, coder, auditor, worker). Three-section sprint pipeline. Project-agnostic via `.claude/shepherd.toml`. Four commands (`plant`, `start`, `autorun`, `parallel`).

---

## Tagging

After this release lands on `main`:

```bash
git tag -a v4.2.0-shepherd -m "shepherd v4.2.0 — Stage Graph + DEDUP-GATE"
git push origin v4.2.0-shepherd
gh release create v4.2.0-shepherd --notes-from-tag --title "shepherd v4.2.0"
```
