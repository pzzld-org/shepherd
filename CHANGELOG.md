# shepherd — changelog

Per-version history for the `shepherd` plugin (this repo). Format loosely based on [Keep a Changelog](https://keepachangelog.com/); follows [Semantic Versioning](https://semver.org/).

---

## v6.1.5 — 2026-06-15

Kickoff-hardening + config-auto-scaffold + observability release (#147), extended
with **two new capabilities** — #148 supervised self-heal and #146 capability
auto-discovery — plus a reliability follow-up that repairs the
**operator-signaling inversion** (the planter under-asked while the shepherds
over-asked), the **"`Workflow` tool is always present" overclaim** that made
web/remote sessions give up instead of degrading, and two **latent namespace/DB
defects** the new kickoff wiring exposed.

### Authorized supervised self-heal — AUTONOMOUS-SENTINEL (#148)
- New loop template (`references/loop-templates.md §AUTONOMOUS-SENTINEL`) +
  binding doctrine (`doctrines/autonomous-sentinel.md`) for **authorized
  supervised autonomy** — the supervised-remediation superset of SOAK-LOOP.
  Stages: PROBE (seeded acceptance predicates, live) → CLASSIFY
  (HOLD/REGRESSED/NEW) → ACT (dispatch a ≤S `@coder` hotfix through the existing
  hotfix-dispatch ladder → gates-before-deploy → re-probe) → TERMINATE (K clean
  ticks / N-HF cap / hard-stop). Hard rails: gates-before-deploy, ≤S / ≤3
  concurrent / ≤N total HF caps, no destructive DB ops, auto-rollback on red,
  paper-only (never flip to live without authorization), operator-override-each-
  tick, full audit trail.
- New config key `[close].autonomous_sentinel` (default `"off"` — detection-only).
  It must be `"on"` AND the seed must declare `close: autonomous-sentinel` AND a
  complete `sentinel_rails` block must be present before a single remediation
  fires (three independent opt-in gates). New halt codes `SENTINEL-RAILS-MISSING`
  / `-SCOPE-EXCEEDED` / `-HF-CAP` / `-ROLLBACK` / `-HARD-STOP` / `-LOOP-CAP`.
- Reconciled the depth-3 "remediating inside a watch loop" anti-pattern in
  `references/loop-templates.md §SOAK-LOOP` and `doctrines/outcome-enforcement.md
  §Seam 4`: detection-only stays the DEFAULT and the anti-pattern for the
  UNAUTHORIZED case; the explicitly-authorized AUTONOMOUS-SENTINEL case is carved
  out.

### Capability auto-discovery (#146)
- Shepherd now auto-detects the Claude Code plugins/skills available in the
  environment and adapts without operator wiring. A cheap, one-time-per-session
  SessionStart probe (`hooks/scripts/capability_discovery.sh`) enumerates
  installed plugins + skills and writes an **EPHEMERAL** capability roster
  (`<ns>/cache/discovered-capabilities.json`, gitignored) kept strictly distinct
  from the operator-curated `toolkit.json` — discovery never overwrites intent.
  The roster is merged at read time into the `[TOOLKIT]` surfaces (SessionStart
  roster + engineer/coder/planter brief injection via the new `shctx toolkit
  discovered`), labeled auto-discovered and bounded at 12.
- New doctrine `doctrines/capability-discovery.md` codifies the guarded-integration
  pattern ("if `/remember` is available → use at handoff/CLOSE-FINALIZE + resume,
  else shepherd-native"; same for `superpowers`, `pr-review-toolkit`), so behavior
  degrades cleanly when a plugin is absent — shepherd never hard-depends on a
  third-party plugin.
- The probe also records whether the native **`Workflow` tool** is present;
  web/remote sessions that omit it degrade to in-context `Agent(...)` fan-out
  instead of giving up (cross-referenced in `references/glossary.md`).
- New config key `[discovery].auto_capabilities` (`on` default | `off`), resolved
  via `cfg_get` (local → project → XDG-global precedence). Zero hot-path cost,
  fail-open.

### Seed-optional kickoff (#8)
- `/shepherd:start` (Step 0) and `/shepherd:spawn` (Hard-stop #2 / Check 6) no
  longer hard-refuse on a missing seed for a single `--scope sprint` run: derive
  the objective from the repo/issue ledger, or ask ONE batched kickoff question,
  then run — per `doctrines/operator-signaling.md §"Seed is recommended, not
  required"`. `--parallel` and multi-sprint `--scope patch|minor|version` walks
  still HARD-refuse (seeds are load-bearing there for collision detection + walk
  enumeration).

### Config auto-scaffold (#15)
- New **`shctx config init`** scaffolds `.claude/shepherd.toml` from the bundled
  minimal template when absent (idempotent): derives `[project].name` (git
  remote → cwd basename) and `[gates]` (Cargo.toml→cargo, go.mod→go,
  pyproject/setup.py→pytest+ruff, package.json→npm), and realigns `[paths]` to
  the active shctx namespace. Adds `shctx config get/show/path`.
- Wired at kickoff: start/spawn root scaffold → `[CONFIG]` notice → PROCEED
  (action-biased); plant scaffold → ONE batched `AskUserQuestion` to refine
  `[branching]`+`[gates]` (replaces the #120 hard STOP).

### Observability dashboard (#13)
- New **`shctx dash`** — a one-glance, read-only sprint snapshot composed from
  primitives the root already maintains (focus, graph state, live teammates,
  unread mailbox, open escalations, active loops, GitHub cache freshness). No
  new table/subsystem; bash-3.2-safe; degrades cleanly on missing DB/tmux.
  Monitoring recipe: `/shepherd:loop <interval> shctx dash`.

### Four config toggles (#10)
- `shctx config get <key> [default]` is the uniform resolver (local→project→XDG)
  the toggles read through. Defaults reproduce pre-v6.1.5 behavior exactly:
  `[autorun].on_grade_floor` (abort), `[autorun].inter_sprint_pause` (brief),
  `[spawn].max_parallel` (4), `[spawn].dashboard_cadence` (3m). The
  previously-undocumented `[autorun]` section is now in `docs/configuration.md`.

### Neutralized the bundled example (#9) + subagent-preference (#11)
- `examples/axiom/` → `examples/rust-service/`; scrubbed all domain-specific
  references (finance/polymarket/geo-block) from the example and ~23 doctrine
  teaching snippets. `geo-block-law.md` rewritten as a generic
  regulated-upstream-API teaching example. Historical `.artifacts/` docs are
  intentionally left intact.
- `doctrines/agent-excellence.md` Rule 6 (token-conservation / subagent
  preference) is now wired into every agent profile.

### Reliability follow-up — operator-signaling inversion
`doctrines/operator-signaling.md` (v6.1.4) was correct, but its posture was
never reproduced into the agent profiles that actually become system prompts at
runtime. `AskUserQuestion` is granted correctly in every profile — the inversion
was a **prose-propagation gap**, not a tools-grant bug:
- `agents/planter.md`: added a standing **"the planter asks freely"** posture at
  the top of plant mode (previously the ONLY trigger was the rare no-config
  bootstrap branch, so the common case invented answers instead of asking).
- `agents/conductor.md`: SOLO = `AskUserQuestion` is a narrow escape valve only;
  TEAMMATE mode MUST NOT call it (the `MODE-MISUSE` halt code now names the
  tool).
- `agents/shepherd.md`: root action-bias note — the defined gates are the only
  operator stop points; no invented mid-run confirmation asks.

### Reliability follow-up — the `Workflow` tool is NOT "always present"
- `references/glossary.md` listed the native `Workflow` tool alongside
  `Agent`/`Bash`/`Edit` as always-present and blamed any absence solely on "a
  build below the Dynamic Workflows floor." Claude-Code-on-the-web /
  remote-execution sessions omit it **even on a supporting build**, so a
  spawn/loop that reached for it gave up instead of degrading. Corrected to
  **environment-dependent** presence, with the visible-tool-list test as the
  only authority and degrade-to-`Agent(...)` as the documented path (ties into
  #146).

### Reliability follow-up — two latent defects the kickoff wiring exposed
Both were invisible to the green suites (the harnesses set neither
`CLAUDE_PLUGIN_ROOT` nor a `shepherd.db` registry); #15's config-scaffold pulled
them onto the kickoff hot path:
- **`shctx_skill_root()` returned bare `$CLAUDE_PLUGIN_ROOT`**, but `schema/` +
  `references/` live at `$CLAUDE_PLUGIN_ROOT/skills/context/`. `scaffold.sh`'s
  `cp references/naming-conventions.md` aborted under `set -e`, so `shctx
  init`/`config init` never created the DB and every downstream `shctx` command
  failed. Now prefers the dispatcher-exported `SHCTX_SKILL_ROOT`, else
  `$CLAUDE_PLUGIN_ROOT/skills/context`. Verified end-to-end (init exits 0,
  creates `shepherd.db`, copies `CONVENTIONS.md`).
- **9 hooks hardcoded `$ns/root.db`** while v6.1.2+ `shctx init` creates
  `shepherd.db`, so `[[ -f "$DB" ]]` was always false → silent no-op, disabling
  the spawn-coordination guards (`coordinate_drive_guard`,
  `worktree_teardown_guard`, `teammate_idle`, …) on every modern project. New
  `hook_db_path()` in `hooks/scripts/_lib.sh` mirrors the skills-side
  `shctx_db_path()` (prefer `shepherd.db`, fall back to an existing `root.db`,
  default `shepherd.db`); all 9 assignments route through it.

Tests: hooks 38/38 (+1 for the #146 capability-discovery probe), context 42/42.

## v6.1.4 — 2026-06-12

A reliability + native-alignment release. Fixes the **`dev.{last}` → `dev.{last+1}` release-trigger miss** that cut a stray dev branch instead of releasing, corrects a wrong **native `/loop` expiry constant** that had propagated as a load-bearing invariant, makes Claude Code's **`Workflow` tool** unmistakable (it was being mistaken for a `ToolSearch` target and given up on), restores **tmux pane observability** plus the dead-pane cleanup that had been documented but never built, and gives planning + main-chat sprint sessions a **native operator-signaling** path — without letting execution sessions become approval-seekers.

### Release trigger — never cut `dev.{sprints_per_patch}` again
- **The bug.** At the close of `dev.{last}` (e.g. `v0.3.5-dev.9`, `sprints_per_patch = 10`) the conductor cut `dev.10` instead of firing the release cascade. Root cause: `agents/conductor.md` Step 5 and `agents/shepherd.md` RF-4 stated the mod-N condition in *prose* but showed an *unconditional* `git checkout -b {next}` beneath it — and an exhausted-context conductor runs the visible command and drops the prose.
- **Mechanized the decision.** Both briefs now run `shctx release --dry-run` (the authoritative oracle) *before* the rebase, and gate the next-branch cut on an explicit `[ "$N" -lt "$((K-1))" ]` conditional with the release path stated first.
- **Deterministic backstop.** New `hooks/scripts/release_trigger_guard.sh` (`PreToolUse(Bash)`) blocks creating/publishing a `…-dev.N` branch where `N ≥ sprints_per_patch`, while allowing mid-patch cuts, `dev.0` rollovers, and remediation deletes. Config: `[release].devlast_guard = block (default) | warn | off`. A raw pre-filter skips JSON parsing on every Bash call that doesn't mention `dev.N` (≈zero added cost). 13-case behavioral test matrix.
- **Wired `sprints_per_patch` into `cmd_release.sh`** (was hardcoded `=10`, silently wrong for projects on 5/7).

### Native `/loop` expiry — "3 days" was wrong; it's 7
- Corrected ~19 references across `references/loop-templates.md` and `references/workflow-templates.md` asserting a "3-day" outer bound. Per `code.claude.com/docs/en/scheduled-tasks`, fixed-interval and self-paced loops expire after **7 days**. The canonical note now distinguishes interval mode (runs until stopped or 7 days), self-paced mode (1 min–1 hr dynamic delay, ends early when done), and `Esc`-to-stop.

### Loops — discoverable from a cold session
- `SKILL.md §0-ter` surfaces loops in the always-on layer: the Q4 trigger, the role→template map, an "author your own" recipe, and the bounded + measurable invariants.
- `[LOOP-CONTEXT]` added to `agents/worker.md` and `agents/discovery.md` so a looped agent reads its `new_findings` contract in its own brief; the conductor gains a mid-sprint loop-recognition note.

### The `Workflow` tool vs "workflow patterns" vs GitHub Actions
- New `references/glossary.md` disambiguates the three senses of "workflow" and states the rule that broke a sprint: the native **`Workflow` tool is always present and is NEVER a `ToolSearch` target** — if it isn't visible you're below the version floor, so fall back to in-context `Agent(...)`. First-mention corrections added at `workflow-compile-down.md`, `hotfix-dispatch.md`, and `conductor.md`.

### tmux observability + dead-pane cleanup (#66.6)
- New `shctx panes` (`status` / `capture` / `tail` / `prune`) — the first consumer of the long-orphaned `teammates.tmux_pane_id` column. `capture` snapshots each live teammate pane to `<ns>/logs/panes/`; `status` is a per-lane liveness dashboard (run under `/loop` for a live view).
- New `hooks/scripts/tmux_pane_cleanup.sh` on `SessionEnd` reaps panes of closed teammates (the documented-but-unbuilt #66.6 gap). Config: `[tmux].pane_cleanup = on (default) | off`.
- `shctx teammate heartbeat` now self-heals `tmux_pane_id` from `$TMUX_PANE` (zero brief changes), so the column populates without operator wiring.

### Native operator signaling — the planner asks, execution runs
- `AskUserQuestion` enabled for the planter, root shepherd, and SOLO conductor (teammate-conductors still escalate to root via `SendMessage`).
- New `doctrines/operator-signaling.md`: the **planter asks freely** (planning is interactive), while **execution sessions are action-biased** — `AskUserQuestion` is a narrow escape valve (no-seed kickoff, irreversible outward actions, hard blocking forks) with an explicit ban on confirmation/approval-seeking and on inventing new stop points. Codifies that the **seed is recommended, not required**.

## v6.1.3 — 2026-06-12

The toolkit-hardening, bash-3.2-portability, and **outcome-enforcement** release. Fixes the v6.1.2 toolkit "Permission denied" that fired at session start, repairs three macOS bash-3.2 breakages (including a silently-broken hotfix guard and unbounded precompact-snapshot pileup), removes the retired `autorun`/`parallel` machinery for good, and adds a behavioral layer that makes the *seeded outcome* — not just green gates — the thing that closes a sprint.

### Toolkit — the v6.1.2 feature, hardened

- **The reported bug.** `hooks/scripts/toolkit_surface.sh` and `skills/context/scripts/cmd_toolkit.sh` shipped in v6.1.2 with git mode `100644` (non-executable). The SessionStart hook is invoked by path, so it failed with `Permission denied` on every new session. Both are now `100755`. A new regression guard — `hooks/tests/test_exec_bits.sh` — asserts every path-invoked hook/CLI script carries the executable bit (the smoke harness runs scripts via `bash <file>`, which is mode-agnostic, so this class slipped past every other test).
- **CLI ↔ docs reconciliation.** The documented `add` syntax was unusable (`add <name> --desc=… --global` while the CLI required `--name=`, `--description=`, `--scope=global`). The CLI now accepts the ergonomic aliases `--global` / `--local` (for `--scope=…`) and `--desc` (for `--description`); `commands/toolkit.md` and `doctrines/toolkit.md` are corrected to match.
- **Doctrine accuracy.** Dropped `api` from the canonical type enum (it is non-canonical → WARN); marked `scope` + `capabilities` *required* (the `validate` command enforces them); reworded the over-promising "pinned never drop" and "add is idempotent" claims to match the code (add refuses duplicates; pinned-first within the cap).
- **Bounded injection + defensiveness.** `shctx toolkit md` (the brief-injection surface) now caps at 12 entries, pinned-first, matching the SessionStart hook; interactive `list` stays uncapped. Empty-`capabilities` rendering is guarded. New `hooks/tests/test_toolkit_surface.sh` covers merge / local-wins / pinned-first / 12-cap / graceful-empty; `test_toolkit.sh` gains alias coverage.

### bash 3.2 portability (macOS default `/bin/bash`)

Three hooks/CLI scripts used bash-4-only constructs that silently broke on the operator's platform:

- **`hotfix_vehicle_guard.sh` (#135).** Used `${SUBAGENT_TYPE,,}` (bash-4 lowercase) → "bad substitution" on 3.2, so an `H=1` hotfix spawned as a `shepherd:conductor` teammate slipped past the guard. Replaced with portable `tr`. The guard's primary case now actually enforces — `test_hotfix_vehicle_guard.sh` goes 9/10 → 10/10.
- **`precompact_snapshot.sh`.** The retention trim used `mapfile` (bash 4+); on 3.2 it died under `set -u`, so snapshots were *written but never trimmed* — the "so many precompact files" pileup. Replaced with a portable read loop; retention (default 5) now holds.
- **`cmd_issues.sh`.** `declare -A` (associative arrays) is a fatal "invalid option" on 3.2, breaking `shctx issues` outright. Reworked to safe `printf -v` / `${!var}` indirection (no `eval`).

These two fixes turn the hooks smoke suite from 33/35 → **37/37** (the two newly-green tests plus the two new toolkit tests).

### Precompact snapshots — relocated + meaningful

- **Relocated** from `<workdir>/snapshots/` to **`<workdir>/memory/snapshots/`**, co-located with other ephemeral rehydration state. Writer (`precompact_snapshot.sh`) and reader (`focus_rehydrate.sh`) move together; a fail-open one-time migration sweeps any snapshots from the legacy location, and the reader falls back to it so an in-flight snapshot taken before the upgrade still rehydrates.
- **Kept (they are meaningful):** snapshots carry the focus digest, graph cursor, trace tail, mailbox, and lock state — the load-bearing compaction-resilience payload. The "noise" perception was the broken retention (above), now fixed.

### Outcome enforcement — make the seeded outcome close the sprint

Shepherd ships code and green gates reliably but drifts off the *outcome* a seed promised. New `doctrines/outcome-enforcement.md` binds outcome verification to four existing seams, **behavioral wiring only — no new schema or state table**:

- **Seam 1 — SEED:** each `seed §6` deliverable's acceptance is a *runnable* predicate (grep+count / structural assertion / LOC floor / log·metric·DB query / health probe), not prose (`references/seed-template.md §6-bis`).
- **Seam 2 — PLAN-GATE:** the `@critic` confirms every deliverable carries a runnable predicate; a plan that drops one or leaves prose-only fails with `PLAN-MISSING-OUTCOME-VERIFICATION` (`agents/critic.md`).
- **Seam 3 — CLOSE (the enforcement point):** the close auditor *re-runs* every seeded predicate against live HEAD/state **before** grading; a promised-true predicate that now returns false is an `OUTCOME-REGRESSION` (HIGH) that caps the completeness grade (`agents/auditor.md`, `agents/conductor.md §3`, `references/grading-rubric.md`). Reuses the same read-only re-run INTRO already runs on the *prior* sprint.
- **Seam 4 — SOAK (optional, post-close):** a new **SOAK-LOOP** template (`references/loop-templates.md`, a WATCH-LOOP specialization) re-verifies the predicates on a wall-clock interval (T+1d, T+7d) via native `/loop` + `Monitor`, surfacing `OUTCOME-REGRESSION` on post-delivery drift. Detection-only; never auto-remediates. Invoke: `/shepherd:loop "soak outcomes for <sprint>" --agent worker --interval 1d --max 6`.

### Retired-command cleanup

Deleted the thin retired-redirect stubs (`/shepherd:autorun` + `/shepherd:parallel`, retired since v5.1.4): `commands/{autorun,parallel}.md` and `skills/shepherd/{autorun,parallel,planter}.md`. References in `CLAUDE.md` and `SKILL.md` are scrubbed; the live `--auto` / `--parallel <N>` flags, the `[autorun].min_grade` config key, and the `shepherd-parallel-<slug>` teammate-naming prefix are unaffected.

### Doctrine + brief fixes (batched issues)

- **#61** — `agents/engineer.md` gains a work-shape→vehicle tier-matching table so a conductor/teammate is not allocated for single-file or markdown work.
- **#100** — `agents/conductor.md` boot adds a hard W0-GATE precondition: no body batch fires until INTRO ground-truth certification has passed (block-and-recheck, never proceed-and-hope).
- **#120** — the planter (`agents/planter.md`, `commands/plant.md`) now has a fresh-project bootstrap: when `.claude/shepherd.toml` is absent it surfaces `examples/minimal/shepherd.toml` and stops for operator confirmation.
- **#123** — reconciled the `-dev.N` seed-filename conflict: intermediate per-sprint seeds may carry `-devN`; the version-scale-roadmap restriction applies only to final shipped artifacts (`doctrines/version-scale-roadmap.md`, `references/seed-template.md`).

### Closed as verified-shipped

Verified present + wired and closed: **#107** (toolkit registry, v6.1.2), **#121** (namespace resolution parity, v6.0.8), **#134** (Focus Loop, v6.0.9), **#87** (compile telemetry, v6.0.9), **#103** (engineer model pin + `ENGINEER-MODEL-FAIL`, v6.0.3+), **#99** (teammate git guard, v6.0.9), **#119** (planter discovery wave, v6.0.7+), and **#135** (hotfix vehicle guard — fixed and now enforcing, this release).

### Test suite — repaired the `shctx` harness (23/40 → 40/40)

The `skills/context/tests` suite had 17 pre-existing failures (present on `main`) — not a sqlite issue (the migrations apply cleanly), but **v6.1.2 renames that never reached the test harness**:

- `root.db` → `shepherd.db`: `shctx init` now creates `shepherd.db`, but the harness (`_setup.sh`) and 22 tests still hardcoded `root.db` in their direct `sqlite3` queries → "no such table" against a fresh empty file. Renamed throughout (leaving `test_workdir.sh`'s intentional legacy-detection assertions).
- `plans/`+`reports/` → `docs/plans/`+`docs/reports/`: `test_init` / `test_lint` referenced the pre-v6.1.2 top-level dirs the scaffold no longer creates.
- `cmd_doctor.sh` hard-coded the label `root.db` regardless of the actual file — now reports the real `shctx_db_path` basename (a real cosmetic bug).
- `test_compile_telemetry` asserted spaced JSON (`"…": 1`) against compact output (`"…":1`).

Both suites now pass clean: **hooks 37/37, context 40/40**.

---

## v6.1.2 — 2026-06-11

The self-improvement-substrate release: a persistent **tool toolkit** so a session never forgets a capability, a standardized + back-compatible workdir layout, **per-flock-role loop templates**, discovery waves on Dynamic Workflows, and a flock-profile polish pass.

### Toolkit — persistent tool memory (operator request)

The flagship of this version. A mutable registry (`toolkit.json`) of commonly-used tools — MCP servers, skills, plugins, CLIs, ssh targets — so a Claude Code session never forgets a capability exists and the operator never has to re-explain it (e.g. `ssh pzzld@laptop` for a self-hosted dev surface, the `context7` MCP). It is the **tool-memory sibling** of the adaptation loop's lesson-memory (`doctrines/self-improvement.md`).

- **Two tiers, merged at read time.** Project-local `<namespace>/toolkit.json` (tracked) ⊕ user-global `$XDG_CONFIG_HOME/shepherd/toolkit.json`; the `scope` field routes each entry, and local overrides global on name collision — so cross-project tools live once, globally.
- **Entry schema.** Required `{ name, scope (local|global), type (mcp|skill|plugin|cli), capabilities[], description }` plus optional `invocation`, `when`, `tags`, `pinned`. JSON Schema at `skills/context/references/toolkit.schema.json`; the validator warns (never fails) on a non-canonical `type` so ssh/service targets are permitted.
- **CLI.** New `skills/context/scripts/cmd_toolkit.sh` (registered in `shctx`): `toolkit list|add|rm|pin|unpin|show|md|init|validate`. Lazily creates the file on first `add`; `md` emits compact markdown (graceful-empty — nothing on an empty registry, exactly like `shctx adapt priors`).
- **Three surfaces keep it in front of the model.** (1) A SessionStart hook `hooks/scripts/toolkit_surface.sh` injects a compact, ≤12-entry, pinned-first roster every session (fail-open; suppressed by `[hooks].quiet_warnings`); (2) the `shctx toolkit` CLI; (3) a `[TOOLKIT]` block injected into engineer/coder/planter briefs via `cmd_inject.sh` (variable-tail, cache-discipline-preserving).
- **Doctrine + command + examples.** `skills/shepherd/doctrines/toolkit.md` (bounded / graceful-empty / never-store-secrets), `commands/toolkit.md` (`/shepherd:toolkit`), `examples/{axiom,minimal}/toolkit.json`, and the five tool-using agents (engineer, coder, worker, discovery, planter) gained a one-line toolkit-awareness nudge. Test: `skills/context/tests/test_toolkit.sh`.

### Standardized workdir layout — one consistent tree, totally back-compatible (operator request)

The per-project workdir now follows a standardized internal tree — `docs/{plans,reports,diagrams,handoffs,specs,journal}/`, `logs/`, `archive/`, `cache/`, `scripts/`, `templates/`, `tmp/`, `types/`, plus `toolkit.json` (tracked) and `shepherd.db` (gitignored). Adopted **additively** per the `#121` "never mass-rename" invariant.

- **`root.db` → `shepherd.db`, with auto-detection.** `shctx_db_path()` prefers `shepherd.db`, falls back to legacy `root.db`, defaults to `shepherd.db` for new projects — mirroring the existing `.shepherd/`↔`.artifacts/` resolution. Zero change for legacy trees.
- **`plans/` + `reports/` now nest under `docs/`.** `[paths]` defaults updated; `scaffold.sh` scaffolds the full tree with `.gitkeep` for tracked-but-empty dirs.
- **Opt-in migration.** `shctx migrate --layout v2` `git mv`s `plans/`→`docs/plans/`, `reports/`→`docs/reports/`, renames `root.db`→`shepherd.db`, and creates the new dirs — idempotent, no-clobber.
- **`*.{group}.{ext}` naming, formalized.** `references/naming-conventions.md` documents the uniform `<slug>.<group>.<ext>` rule and adds log patterns `{date}.log.md` (human) + `{ts}.log.jsonl` (machine); `cmd_lint.sh` accepts both the legacy and new locations + log groups. `.gitignore` covers `shepherd.db*` under both namespaces and keeps `toolkit.json` tracked.

### Per-role loop templates — bounded, role-shaped Loop-Until-Done (operator request)

`/shepherd:loop` (Pattern 6) gains a per-flock-role catalog so the loop primitive is reusable per agent. New `skills/shepherd/references/loop-templates.md` defines seven templates — **CODER-CONVERGENCE** (fix-until-green), **DISCOVERY-EXHAUST** (research-until-comprehensive), **WORKER-WATCH** / **WORKER-CONVERGENCE**, **AUDITOR-REFINE**, **ENGINEER-PLAN-REFINE**, and the orchestrator's **FOCUS-LOOP** — each specializing an existing composite, each with a hard `--max` cap and a measurable terminate-on predicate. New binding doctrine `skills/shepherd/doctrines/loop-templates.md`; `commands/loop.md` points operators at the catalog. No new halt codes (reuses the v6.0.9 circuit-breaker set).

### Discovery waves compile to Dynamic Workflows (operator request)

All discovery fan-out now compiles like coder/audit fan-out instead of dispatching as inline Agent batches. `doctrines/workflow-compile-down.md` §V documents `INTRO-COMBO-WAVE` and `DISCOVERY-COMBO-WAVE` as compile targets (gate-free, parallel-safe → one `Promise.all` of discovery + auditor [+ worker] spawns); `intro-combo-wave.md` and `discovery-combo-wave.md` adopt the compile framing; `pipeline.md` gains the missing `DISCOVERY-COMBO-WAVE` taxonomy row. The compiler `cmd_graph.sh` was already role-agnostic (`spawns_for_node` expands any role mix) and verified end-to-end — the change is a clarifying comment plus a fixed latent bug where a node typed `dynamic_workflow` would not have matched the compiler's literal node-type key.

### Spawn flow — per-sprint context certification, teammate Dynamic Workflows, default FOCUS-LOOP (operator request)

Four coordinated `/shepherd:spawn` fixes so the team substrate behaves as designed:

- **Per-sprint context-certification wave.** The spawn-flow walkthrough now makes the root's INTRO-COMBO-WAVE explicit (it was mandated in `agents/shepherd.md` but omitted from `commands/spawn.md`'s flow): `@discovery` × N gather ground-truth, intro-mode `@auditor` × 2 **certify** it (regression / carry-forward / freshness) — the sprint's own certifiable current context. Always-on under spawn (every T-shirt) and **fresh per sprint** — each `--scope patch`/`--auto` sprint and each `--parallel` sibling certifies its own; a prior sprint's context is never inherited. `intro-combo-wave.md` gains the spawn framing.
- **Teammate-conductors compile their lane fan-out.** The contract required it (`dispatch-cascade.md §IV-bis`, `conductor.md`) but no operational instruction existed, so teammates dispatched in-context. Added the explicit `shctx graph compile --segment=<entry> --verify` → run → `shctx graph mark` sequence (in-context fallback only on confirmed runtime failure) to the `commands/spawn.md` teammate boot prompt and `agents/conductor.md` Step 2 + hard-prohibition #22; hand-rolled in-context step fan-out is a `PRIMITIVE-INVERSION` off-substrate violation. Reconciled the self-contradictory `SKILL.md §X`: under spawn, **both** root and each teammate compile their respective fan-out (mode-agnostic).
- **Root adopts the FOCUS-LOOP by default on team init.** Coordinate mode is reframed as *operating* the Pattern-6 FOCUS-LOOP (wake → act → probe, opened at SEED-VERIFY), entered the instant teammates spawn — the active engine, not a passive focus-record write backstopped only by `coordinate_drive_guard.sh`. The root stays engaged and drives until CLOSE-FINALIZE.
- **Long-running conductors adopt their own FOCUS-LOOP.** A teammate-conductor opens a lane-keyed focus loop at Step 0 (lane start, before any node — so a teammate that skips INTRO still gets one) and runs wake → act → probe over its lane micro-Stage-Graph, refreshing at each wave so a long lane doesn't drift.

All four default-on, config-gatable via the new `[focus].loop_default` key; doctrine framing in `coordinate-active-drive.md`.

### Flock profile polish

Description-field shrink for the two genuinely bloated meta profiles — `conductor` (198→157 chars) and `shepherd` (195→152) — moving mode/tier detail into the body; `planter`/`auditor` tightened further. Frontmatter already consistent across all nine (`name → color → model → thinking → description → tools`); no value changes.

### Foundation

- Version moved to 6.1.2 across the six sources of truth (`plugin.json`, `marketplace.json` ×2 keys, both `SKILL.md` frontmatters, `README.md`, this file).
- Removed a stray tracked `err.txt` and the dogfood repo's `.artifacts/` tree reorganized onto the standard layout (`plans/`+`reports/` → `docs/`).
- All new bash honors house style — `set -uo pipefail`, source `_lib.sh || exit 0`, exit-0-always hooks, `resolve_namespace`/`resolve_workdir` (never hardcoding `.artifacts`/`.shepherd`), and graceful-empty reads. New test auto-discovered by `skills/context/tests/run.sh`.

---

## v6.1.0 — 2026-06-09

### Spawn pane-massacre containment — blanket worktree teardown can no longer run mid-sprint (#141)

A `/shepherd:spawn` session tore down every live teammate's worktree mid-sprint. A root re-engaged by the coordinate-drive `Stop` hook ran the blanket `git worktree list | grep agent- | … remove --force` loop (followed by `git worktree prune`) **while teammates were still live in their tmux panes** — every pane's worktree vanished, every teammate session died, and the lead quit with them. Compounding it, teammates had booted at the lead session's Opus-4.8 model instead of the conductor's pinned `sonnet`, multiplying cost by the lane count. Five guards close the gap:

- **`teammate_git_guard.sh`** now denies `git worktree add|remove|prune` from teammate sessions (previously only `merge|rebase|push|cherry-pick`), while still allowing read-only `git worktree list`. The missing coverage was exactly the command that caused the incident.
- **New `worktree_teardown_guard.sh`** (`PreToolUse(Bash)`, registered in `hooks/hooks.json`) hard-denies blanket `git worktree prune` and `list | … | remove` sweeps whenever `v_teammates_live > 0`, emitting the `WORKTREE-TEARDOWN-LIVE` halt code. Scoped single-lane `git worktree remove .worktrees/<slug>-<lane>` is still allowed. Config-gated via `[spawn].worktree_teardown_guard = block | warn | off`; fail-open on any uncertainty.
- **`agents/conductor.md` Step 8 + `agents/shepherd.md` RF-5** gate the blanket teardown loop on `v_teammates_live == 0` — it is a CLOSE-only sweep, never a mid-sprint action.
- **`doctrines/coordinate-active-drive.md` + `coordinate_drive_guard.sh`** redefine idle-prune as scoped, per-lane worktree removal by explicit path, never the blanket loop — killing the trigger path where the `Stop` hook nudged the root to "prune idle teammates."
- **`commands/spawn.md`** makes an explicit `model: sonnet` pin mandatory in the `TeamCreate` instruction and adds a pre-spawn Opus cost advisory — teammates were inheriting the lead session's model rather than the `shepherd:conductor` definition's frontmatter.

Verification: 35/35 hook smoke tests pass (`bash hooks/tests/run.sh`), including the extended `test_teammate_git_guard.sh` (worktree cases) and the new `test_worktree_teardown_guard.sh` (#141 blanket-teardown gate).

---

## v6.0.9 — 2026-06-09

<!-- GROUPING CONVENTION (#130): buckets in fixed order — Focus loop / Compaction, Template loops, Hotfix dispatch, Teammate integration, Telemetry, Foundation. Each `###` heading names its concern + issue refs. -->

### Focus Loop + compaction resilience — survive compaction by snapshot + rehydrate, not by self-trigger (#134)

Honest framing first: current Claude Code exposes **no** way for an agent to trigger or steer its own compaction, and **no** machine-readable context-budget surface. The only official threshold lever is the global env var `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`. So "stay on-track through compactions" is implemented as making compaction **safe** (snapshot the drive-state + rehydrate) and **predictable** (documented threshold), keyed off a durable focus record — not as the (impossible) self-timed compaction.

- **Loop foundation (closes the v6.0.7 overclaim).** `/shepherd:loop` advertised `shctx loop init|record|close|status|list` but had no backing — no `cmd_loop.sh`, no `loop` table, no dispatcher entry. New `skills/context/scripts/cmd_loop.sh` + migration `0012_loop_state.sql` (`loops` + `loop_iterations` + `v_loops_active`) + a `loop` entry in the `shctx` allowlist implement the full verb surface, plus a `focus <upsert|show>` verb.
- **Focus record.** Migration `0013_focus.sql` (`focus` table + `v_focus_current`) — the sprint north-star: objective, active node, ready-set, obligations, invariants. It lives in `root.db`, so it survives compaction natively; written at SEED-VERIFY, refreshed at each WAVE-GATE, finalized at CLOSE-FINALIZE (wired into `agents/conductor.md` + `agents/shepherd.md`).
- **PreCompact snapshot.** New `hooks/scripts/precompact_snapshot.sh` on the new `PreCompact` event captures the in-context drive cursor (`state.json` ready/in_flight, `trace.jsonl` tail, undrained `mailbox`, `shepherd.lock`, focus digest) to `<ns>/snapshots/`, sets a rehydrate-pending flag, trims to `[compaction] snapshot_retention` (default 5), and **never blocks compaction** (exit 0).
- **Rehydration.** New `hooks/scripts/focus_rehydrate.sh` on `SessionStart` + `UserPromptSubmit` drains the pending flag once and re-injects the snapshot digest as `additionalContext`, so the orchestrator resumes its drive deterministically after a compaction.
- **Threshold doctrine.** `docs/configuration.md` documents the sole official knob (`CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`) — global, no per-model form, opt-in, **no shipped default** — with a ~70 suggestion for long Sonnet-root sprints. New `[compaction]` / `[focus]` config sections (both examples updated).
- **`/shepherd:focus`** (`commands/focus.md`) wraps `loop --kind=focus`; interval mode delegates to the native Claude Code `/loop`.

### Template loops — first Pattern-6 named composites (operator request)

Three named loop composites added to `skills/shepherd/references/workflow-templates.md` and the `skills/shepherd/doctrines/workflow-patterns.md` composite table — the **first** composites with `Pattern basis = Pattern 6` (alongside the existing Pattern-2 `INTRO-COMBO-WAVE` / `DISCOVERY-COMBO-WAVE` / `HOTFIX-BATCH`): **FOCUS-LOOP** (orchestrator self-orientation; the runtime shape of coordinate-mode drive), **CONVERGENCE-LOOP** (gate-rerun-until-green), **WATCH-LOOP** (interval monitoring via the native `/loop`). All declare a mandatory `max_iterations`, are Loop-OUTER (never nested inside a fanout iteration body, per the existing illegal-composition rule), and reuse the existing `PLAN-MISSING-LOOP-CAP` / `LOOP-REPORT-INVALID` / `LOOP-CAP` halt codes (no new codes).

### Hotfix dispatch — mechanical guard for the H=1 rule (#135)

The v6.0.8 cardinality ladder was doctrine-complete but **unenforced**. New `hooks/scripts/hotfix_vehicle_guard.sh` (`PreToolUse` Agent|Task) denies a teammate / `TeamCreate` spawn whose context is a single-cluster (`H = 1`) hotfix, emitting the now-registered **`WRONG-VEHICLE`** halt code (added to the halt-code tables in both `agents/conductor.md` and `agents/shepherd.md`). The doctrine itself is unchanged — this closes the enforcement gap, not a wording gap.

### Teammate integration authority — root-only merge, reviewed (#99 + operator)

Team-based conductors must **never** integrate their own worktree into the dev branch. New `hooks/scripts/teammate_git_guard.sh` (`PreToolUse` Bash) denies dev-branch integration commands (`git merge` / `rebase` / `push` / `cherry-pick`) from teammate sessions — keyed on the `teammates` table by `session_id` — while still allowing legitimate in-worktree `git add` / `git commit`, emitting the registered **`TEAMMATE-GIT-WRITE`** halt code. A new **`LANE-INTEGRATE`** seam (`skills/shepherd/pipeline.md` + `agents/shepherd.md`) makes integration a root-exclusive, **size-gated reviewed** decision: small diffs root-reviews inline; lanes ≥ 200 changed lines get an `@auditor` diff-review concern before merge. New binding doctrine `skills/shepherd/doctrines/teammate-integration-authority.md`.

### Compile-down telemetry — measurable pilot feedback (#87)

New migration `0014_compile_runs.sql` (`compile_runs` + `v_compile_runs_sprint`) captures, per compiled segment per run: segment size, peak concurrency vs the ceiling, the §IV faithfulness-diff result (the structured object `shctx graph compile --verify` already emits), seam-handoff outcome, and every degradation-to-direct-dispatch event with its cause. `shctx adapt` gains a `## Compile-down telemetry` close-report subsection (mirroring the existing cache-telemetry precedent over `v_cache_usage`). The dead `shctx graph trends` reference in `dispatch-cascade.md §VII` (never implemented) is repointed to the live `shctx adapt report --trends`. A **deliberate degradation test** (`skills/context/tests/test_compile_telemetry.sh`) exercises the direct-dispatch fallback — the path #87 flagged as the real risk.

### Foundation — design spec, tests, namespace discipline

- Authoritative design-of-record: `.artifacts/docs/specs/2026-06-09-v609-focus-loop-and-compaction-resilience.spec.md` (four-pass: goals/deliverables, assumptions/constraints, diagrams, derivations).
- New tests, all registered in their harnesses: `skills/context/tests/test_loop_lifecycle.sh`, `test_compile_telemetry.sh`; `hooks/tests/test_precompact_snapshot.sh`, `test_focus_rehydrate.sh`, `test_hotfix_vehicle_guard.sh`, `test_teammate_git_guard.sh`.
- All new hook scripts honor house style — `set -uo pipefail`, source `_lib.sh || exit 0`, **exit 0 always** (decision via stdout JSON), config-gated, runaway-bounded, and namespace-resolved via `resolve_namespace` / `resolve_workdir` (never hardcoding `.artifacts` / `.shepherd`, per #121).
- Version already at 6.0.9 across the six sources of truth (bumped at branch cut); this section is the hand-authored record.

---

## v6.0.8 — 2026-06-09

<!-- GROUPING CONVENTION (#130): within a patch section, organize `###` headings into concern buckets in this fixed order — Planter / Models, Hotfix dispatch, Adaptation, Namespace / Hooks, Foundation. Each `###` heading names its concern and cites its issue refs inline as `(#NNN)`. One heading per coherent change; a change spanning files stays one heading. This keeps multi-lane patches coherent without a separate index. -->

### Planter model policy + discovery wave — hard ABORT becomes soft ADVISORY, root engineer pin hardened (#119, #103)

The planter's wrong-model gate no longer aborts. Opus (`claude-opus-4-8` / `claude-opus-4-8[1m]`) remains the RECOMMENDED default; Fable 5 (`claude-fable-5`) is documented as the SUPERIOR (pricier) upgrade; Sonnet (`claude-sonnet-4-6`) and Haiku (`claude-haiku-4-5-20251001`) are ALLOWED with a degraded-seed-quality WARNING.

- **`commands/plant.md` + `agents/planter.md`:** the `## Step 0 — Model gate` hard-ABORT block (`PLANTER ABORT — wrong model`) is replaced by `## Step 0 — Model advisory` — a tier table (Fable 5 superior · Opus recommended · Sonnet/Haiku allowed-degraded) that emits a one-shot `PLANTER MODEL ADVISORY` and then proceeds. Planting never refuses on tier. The frontmatter descriptions, the "You are model opus because…" prose, the halt-code table row, and the "every minute of planter Opus time…" closing line are all reframed from necessity to recommendation. The planter `model:` frontmatter default stays `opus[1m]` (the recommended default is unchanged — only the gate softens).
- **Bounded discovery wave (#119):** the planter's Hard-prohibition #1 carves a strictly bounded exception — in plant mode, for a broad/unfamiliar scope, the planter MAY fan out a read-only `@discovery` wave (1–3 parallel lanes, `subagent_type=shepherd:discovery`, never the flock pipeline) that feeds the 12-row planter mesh. A new `§Step 2-bis` documents the bounds (read-only, scope-partitioned, Pattern A/F) and reconciles it against `intro-combo-wave.md` / `discovery-combo-wave.md`. The `Agent` tool is granted at the front of the planter `tools:` list to enable this dispatch; `hooks/tests/lint_agent_capabilities.sh` pins the grant to its documented read-only `shepherd:discovery` scope (a planter that grants `Agent` must document the discovery-only bound), so the grant cannot silently broaden to `@coder`/`@auditor` without the prose contract.
- **Root engineer model pin HARDENED (#103) — kept HARD, contrasted with the soft planter advisory.** The single root `@engineer` dispatch (`agents/shepherd.md`) now pins the explicit model id `claude-opus-4-8[1m]` at the dispatch site (with the 200k `claude-opus-4-8` documented as a fallback if `[1m]` is unavailable) rather than relying on the frontmatter alias resolving silently. A model-resolution / unavailable / API error surfaces `ENGINEER-MODEL-FAIL` and PAUSES — never treated as an empty plan, never silently retried, never advanced to the `@critic` gate. This is a **HARD halt**, explicitly distinguished from the planter's **SOFT** `PLANTER MODEL ADVISORY`: the engineer's Opus tier is the single point of failure for the sprint INTRO phase, so it must stop, not warn. The planter softening deliberately does NOT leak into the engineer pin.

### Hotfix dispatch ladder — reach for a dynamic workflow before a teammate (#135)

New binding doctrine `skills/shepherd/doctrines/hotfix-dispatch.md` defines the hotfix cardinality ladder over `H` = the count of file-disjoint independent hot-fixes:

- **`H = 1`** → ONE single subagent via a dynamic-workflow `agent()` step — **NEVER a teammate** (and only after confirming the fix is not merely awaiting another agent's result; re-count first). Fixes the v6.0.x defect where the shepherd spun up a hot-fix teammate for a single-coder dispatch.
- **`H ∈ (1, 5]`** (domain notation; excludes 1, includes 5) → ONE batched dynamic workflow dispatched **directly by the root shepherd** (conductor inline in solo) — not delegated to a teammate.
- **`H ≥ 6`** → a dedicated HOT-FIX lane: one teammate-conductor instance with its own Stage-Graph loop to drive the batch to convergence (spawn-mode only; solo surfaces a `HARD-STOP` recommendation). The `H = 6` boundary is hard.

The ladder selects the **vehicle**; the existing **≤3 concurrent coders** and **3 HOTFIX iterations** caps are orthogonal and still bind inside whichever vehicle is chosen. Wired into `agents/conductor.md` (new HOTFIX-vehicle walk-tick bullet), `agents/shepherd.md` (the HOTFIX-CLOSE default — formerly "re-spawn a small teammate" — now follows the ladder), `skills/shepherd/pipeline.md` (§II HOTFIX-DYNAMIC cardinality cross-ref + §XVI See also), and `skills/shepherd/doctrines/workflow-patterns.md` (named-composite `HOTFIX-BATCH` row for the `(1,5]` Pattern-2 fanout + See also).

### Adaptation surface — trends report, prior decay, recommend verb (#103)

Three slim, SQLite-canonical, graceful-on-empty additions to the `shctx adapt` surface (no schema migration — `updated_at` already exists):

- **`shctx adapt report --trends`** mechanizes `doctrines/adaptation-loop.md §VI` deterministically: a pure-SQL `TREND ALERT` over the last 3 sprints detecting (a) a HIGH/CRITICAL concern recurring in ≥2 of 3 sprints, (b) sprint grade trending strictly worse (A→B→C), and (c) avg wall/api cost rising sharply (newest ≥ 1.5× oldest). Emits nothing on insufficient history; `--md`/`--json`.
- **Prior decay in `shctx adapt roll`:** every recurrence touches the prior's `updated_at` (last-seen); unpinned `kind='prior'` rows not re-seen within `SHCTX_ADAPT_DECAY_SPRINTS` sprint closes (default 6) are pruned via a measured inter-sprint-gap cutoff, so the store self-cleans over long arcs. Bounded (deletes only), idempotent, pin-protected, and graceful (a young store with <2 sprints never prunes).
- **`shctx adapt recommend [--md|--json]`** turns measured `sprint_metrics` averages + recurring priors into a concrete dispatch RECOMMENDATION (suggested lane count, t-shirt size band, watch-concerns); empty store ⇒ "no history yet, use defaults". Wired into the engineer `[DB-CONTEXT]` (omit-when-empty), routed through the dispatcher usage stanza, and covered by new `test_cmd_adapt.sh` cases (trends fire / graceful-empty, decay prune-vs-pin, recommend md/json fields).

### Namespace resolution — hooks/skills parity, single `${SHEPHERD_WORKDIR}` point (#121, #122)

- **(#121) Hooks/skills namespace split-brain fixed.** `hooks/scripts/_lib.sh::resolve_namespace` auto-detected `.artifacts` before `.shepherd` and defaulted to `.artifacts`, contradicting the documented contract and the skills-side `resolve_workdir`. A default-`.shepherd/` consumer's 12 hook scripts would write event logs / dispatch tags / locks into a different directory than the shctx runtime reads. Fixed: precedence realigned to `SHEPHERD_WORKDIR` → `SHCTX_ROOT_OVERRIDE` → existing `.shepherd/` (tie-break winner) → existing `.artifacts/` → default `.shepherd/`, exactly matching the skills lib and `docs/configuration.md §SHEPHERD_WORKDIR`. The header comment was corrected, `adaptation-loop.md §23` brought in line with the resolved-path phrasing, and a new `hooks/tests/test_resolve_namespace.sh` (6 cases, registered in `hooks/tests/run.sh`) pins the contract so the divergence cannot silently return. Behavior-neutral for this repo and the axiom project (both run a single pre-existing `.artifacts/` tree).
- **(#122) Close-finalize false-positive — regression test pinned.** The destructive-instruction false positive (a PRIOR sprint's close report committed and reachable from the current LIVE branch's HEAD triggering a delete of the live branch) was already fixed by the v6.0.7 `#127` slug-scoped `close_finalize_check.sh` rewrite. Verified by live repro and now pinned by a new step-4b regression case in `hooks/tests/test_close_finalize_check.sh` (prior-sprint close report in HEAD + current live sprint branch on origin → no block).

### Foundation — version bump, changelog grouping, release mechanics (#130)

- Version bumped 6.0.7 → 6.0.8 across the six sources of truth.
- Introduced the **#130 CHANGELOG concern-bucket grouping convention** (this section's structure; recorded as an HTML comment at the top of each patch section): a fixed bucket order — Planter/Models, Hotfix, Adaptation, Namespace/Hooks, Foundation — over the repo's existing flat `### <concern> (#refs)` heading idiom, so multi-lane patches stay coherent without a separate index.
- **`shctx release` JSON bumper fix:** `bump_file()`'s `json)` case now patches BOTH the top-level `.version` AND any nested `plugins[].version` (guarded by `has("plugins")`), so `marketplace.json`'s nested plugin-block version stops silently drifting at release time. `plugin.json` has no `plugins` key, so the guard makes it a no-op there.
- `CLAUDE.md` `## Shepherd file contracts` inventory updated for the new `hotfix-dispatch.md` doctrine (plus the already-shipped v6.0.7 `workflow-patterns.md`), the planter advisory-model + discovery-wave change, the marketplace dual-key version-sync note, and the `${SHEPHERD_WORKDIR}` hook namespace-resolution contract.

---

## v6.0.7 — 2026-06-04

### Stop hook: close-finalize check converted to deterministic script (#127 fires #1–17)

The `type: "agent"` close-finalize Stop hook prompt has been replaced with a deterministic shell script (`hooks/scripts/close_finalize_check.sh`). This closes the long-running false-positive chain (#127) that survived the v6.0.6 prompt hardening.

**Fire #17 (trigger for this fix):** `/shepherd:plant` for `v0.3.5-dev.0` committed a planter mesh report (`2026-06-04-planter-mesh.md`) to `.artifacts/reports/`. The agent saw "a report committed to reports/ on a dev branch that exists on origin" and emitted CLOSE-FINALIZE INCOMPLETE, ignoring that the filename doesn't match the `*v035-dev0-close.md` slug pattern. Plant-mode artifacts in the reports directory are a new context trigger for the agent's free-form failure mode.

**Root cause (shared by all 17 fires):** an agent-type hook free-forms `ok: false` from session context rather than mechanically applying detection logic. Fire #10 showed the hook can "correctly diagnose everything... and still return ok:false." A script cannot override its own logic with narrative context.

**Script invariants vs prior agent prompt:**

| Check | Old (agent prompt) | New (script) |
|-------|--------------------|-------------|
| Sprint-branch guard | agent regex | `[[ $BRANCH =~ -dev\.[0-9]+$ ]]` |
| Subworktree guard | agent compare | `pwd -P == git show-toplevel` |
| Slug derivation | agent inference | `sed` — strict `^[0-9]+-dev[0-9]+$` sanity |
| Signal A scope | `--all` (all refs!) | `HEAD` only — excludes other branches/worktrees |
| Signal A pattern | `*${slug}*close*.md` (loose) | `{NS}/reports/*-v${slug}-close.md` (exact convention) |
| Plant-mode artifacts | not excluded (fire #17) | don't match strict pattern; implicitly excluded |
| Signal A empty → | agent may override | `exit 0` — hard coded, no override possible |
| Destructive remediation | `git push origin --delete` in reason | removed entirely |
| Failure mode | free-form ok:false | exit 0 (fail-open on every error) |

### Six canonical workflow pattern templates (`references/workflow-templates.md`)

Added a new reference defining the **six canonical workflow patterns** that form the structural vocabulary for every Stage Graph authored under `/shepherd:plant`:

| # | Pattern | Flock binding | Key use |
|---|---------|---------------|---------|
| 1 | **Classify-And-Act** | `@discovery` → branch → target agent | Unknown task routing |
| 2 | **Fanout-And-Synthesize** | parallel `@coders`/`@workers` → synthesizer | Parallel decomposable work |
| 3 | **Adversarial Verification** | producer → `@auditor` swarm (no shared context) | High-stakes artifact validation |
| 4 | **Generate-And-Filter** | parallel generators → `@critic` gate (rubric + dedupe) | Multiple viable approaches, rubric selects |
| 5 | **Tournament** | N attempts → bracket `@critic` pairs → final judge | Comparative ranking over rubric scoring |
| 6 | **Loop-Until-Done** | `@worker`/`@discovery` → check node → conditional back-edge | Convergent iteration; `max_iterations` required |

Each pattern entry covers: ASCII diagram, when-to-use trigger conditions, Stage Graph shape with YAML node/edge notation, flock agent binding table, composition notes, and anti-patterns. A composition index maps the six legal cross-pattern compositions (prefix routing, sequential pipeline, layered verification, nested iteration, competitive implementation, routed competition).

### Workflow pattern selection doctrine (`doctrines/workflow-patterns.md`)

Added a new **binding doctrine** that makes pattern selection an explicit, enforced Phase 0 decision rather than an implicit conductor judgment:

- **Decision tree (Q1–Q4):** deterministic selection from "task type unknown?" through "parallel decomposable?" through "adversarial challenge needed?" through "convergent iteration?" to direct dispatch for XS leaf nodes.
- **Composition grammar:** legal vs illegal pattern nestings, with three axes (prefix routing, sequential pipeline, nested iteration). Illegal compositions include Generate-And-Filter inside Tournament, Loop inside Fanout body, and Adversarial Verification as classifier.
- **Circuit-breaker invariants per pattern:** non-overlapping scope guarantee (Pattern 2), rubric-before-dispatch invariant (Pattern 4), bracket-declaration and match-isolation requirements (Pattern 5), mandatory `max_iterations` and structured `new_findings` field (Pattern 6).
- **Rigor additions:** checkpoint nodes for L/XL compositions (materializes state to `shctx sprint record` at composition boundaries), escalation laddering (L1–L4 escalation levels replace bare HALTs), and a composition depth limit of ≤3 levels (critic gates justification for deeper nesting, `COMPOSITION-TOO-DEEP` halt code).
- **Enforcement surface:** nine new halt codes wired to existing enforcement points (dispatch guard, PLAN-GATE, preflight doctor, conductor inline).
- **Pattern-to-flock alignment table:** canonical role bindings per pattern — wrong agent type for a role is `DISPATCH-WRONG-ROLE`.

### `/shepherd:loop` command (`commands/loop.md`) — NEW v6.0.7

Added a first-class slash command that runs **Pattern 6 (Loop-Until-Done)** directly from the operator interface:

- **Flags:** `--max <N>` (iteration ceiling, default 5; > 10 requires operator acknowledgement), `--agent <worker|discovery>`, `--interval <duration>`, `--until <field>`, `--resume <loop-id>`
- **In-session mode:** shepherd drives the `wake → act → probe → yield` coordinate cycle directly, dispatching one iteration per turn until convergence or cap
- **Interval mode:** when `--interval` is set, shepherd registers the loop state in SQLite then delegates recurring scheduling to the native Claude Code `/loop` skill (`/loop <duration> /shepherd:loop --resume <loop-id>`); each wake-up runs exactly one iteration and exits
- **Circuit breakers:** `--max` is mandatory (validated in preflight); values > 10 require live operator confirmation; cap-exceeded emits `LOOP-CAP` halt rather than silently exiting; missing `new_findings` field emits `LOOP-REPORT-INVALID`
- **SQLite state:** `shctx loop init / record / close / status / list` verbs manage loop lifecycle in `.artifacts/root.db`
- **Halt codes:** `LOOP-INVALID-AGENT`, `LOOP-INVALID-INTERVAL`, `LOOP-REPORT-INVALID`, `LOOP-CAP`, `LOOP-STATE-MISSING`
- SKILL.md `metadata.triggers` updated to include `/shepherd:loop`; command added to §X invocation table

### SKILL.md §XI updated

Added `references/workflow-templates.md` and `doctrines/workflow-patterns.md` to the §XI file map with load-trigger annotations ("Phase 0 seed analysis; plan authoring; PLAN-GATE").
Added `commands/loop.md` to the §X invocation table.

---

## v6.0.6 — 2026-06-04

### Close-finalize hook false-positive fix — CRITICAL (#122, #127)

The Stop hook's close-finalize agent prompt triggered a false-positive mid-sprint that proposed `git push origin --delete <live-sprint-branch>`, which would orphan active lane worktrees and in-flight deploy refs. Root cause: three defects compounded:

1. `find . -path '*reports*' -name '*close*' -newer .git/HEAD` was unanchored (recursed into `.worktrees/`), not sprint-slug-scoped, and compared mtime (refreshed by worktree creation) instead of authorship.
2. The second condition (`git ls-remote --heads origin` non-empty) is always true mid-sprint under the proactive-push doctrine.
3. The destructive remediation (`git push origin --delete`) required only ONE positive signal.

**Fix:** The prompt now requires **two independent signals** before flagging: (a) a close report committed in git (`git log --diff-filter=A --all`) AND (b) the sprint branch still on origin. Replaced `find`-mtime detection with git-log-based authorship check scoped to the sprint slug. Added a subworktree fast-path (step 2) since `git rev-parse --show-toplevel` ≠ `pwd` when inside a worktree. Removed the destructive `--delete` command from the prompt entirely — the hook now directs the operator to conductor §CLOSE-FINALIZE steps rather than prescribing destructive remediation directly.

### Namespace drift fix — resolve_namespace defaults to .artifacts (#121)

Hook scripts created `.shepherd/logs/` unconditionally as the default namespace while docs and seed-template consistently use `.artifacts/`. When both directories co-existed, `.shepherd` won (checked first), causing a permanent split and a perpetual shctx warning.

**Fix:** `_lib.sh` `resolve_namespace()` now checks `.artifacts` before `.shepherd` and defaults to `.artifacts`. Projects with only `.shepherd` (older installs) continue to work via the fallback. Projects using `SHEPHERD_WORKDIR` are unaffected.

### Hardcoded MCP tool names removed from planter and seed-template (#124)

`agents/planter.md` hardcoded `mcp__plugin_github_github__*`, `mcp__plugin_sentry_*`, and `mcp__plugin_supabase_*` tool IDs in its YAML `tools` frontmatter and mesh table. In harness setups where GitHub MCP runs under a different server name (e.g. `mcp__github__*`, Docker MCP gateway, or CLI-only), those names are dead and agents silently fail to fetch the issue ledger.

**Fix:** Removed all `mcp__plugin_*` names from planter's YAML `tools` frontmatter; added `ToolSearch`. Added a callout box in the mesh section instructing the planter to discover available GitHub/Sentry/Supabase tools via `ToolSearch` at session start, with `gh` CLI as the fallback for GitHub. Updated `seed-template.md` Phase 0 mesh rows 1, 5, and 6 to the same ToolSearch-first pattern. Conductor's MCP tool list is unchanged (read-only tools, standard harness assumption).

### Plant bootstrap path for missing shepherd.toml (#120)

`/shepherd:plant` Step 1 assumed `.claude/shepherd.toml` existed and had no fallback for a first-ever plant. On a fresh project the planter hand-derived config from `examples/axiom/shepherd.toml`, producing inconsistent results.

**Fix:** `commands/plant.md` Step 1 now includes a bootstrap clause: if `.claude/shepherd.toml` is missing, the planter surfaces a clear instruction to copy from `${CLAUDE_PLUGIN_ROOT}/examples/minimal/shepherd.toml` and halts rather than guessing config values inline.

### Background process prohibition — conductor hard prohibition #21 (#108)

Conductor and worker agents repeatedly used `run_in_background: true` on long-running commands (`cargo check`, `cargo test`, build daemons). Background processes lose context on compaction, cannot be monitored turn-to-turn, and orphan when the session ends.

**Fix:** Added hard prohibition #21 to `agents/conductor.md`: `run_in_background: true` is forbidden in any tool call for both SOLO and TEAMMATE modes. Long-running work goes to `@worker` with explicit monitor-and-report briefs. `@worker` is also forbidden from backgrounding. Violation code: `BACKGROUND-PROCESS-SPAWN`.

---

### Sprint numbering: planter starts new patch arcs at dev.0, not dev.1 (field issue: FL03/pzzld v0.0.8)

When `/shepherd:plant` was invoked for a brand-new patch arc (no prior dev.N branches on origin), the planter derived the first sprint number from the prior patch's last sprint (e.g., v0.0.7-dev.5 → dev.6 for v0.0.8) rather than resetting to dev.0. This violates the hard invariant in `references/branching-model.md`: *"The sprint AFTER dev.{last} is dev.0 of the NEXT PATCH — never dev.{sprints_per_patch}."*

**Root cause:** `agents/planter.md` Step 3 documented scope dispatch but gave no algorithm for deriving N, leaving the model to infer from ambient context — which is wrong at patch-arc boundaries.

**Fix:** Added an explicit N-derivation block to Step 3:
1. Run `git ls-remote --heads origin 'v{X}.{Y}.{Z}-dev.*'` for the current patch version
2. If no dev.N branches exist → N = 0 (hard rule; brand-new patch arc)
3. If dev.N branches exist → N_next = highest existing N + 1
4. Explicit callout: do NOT use the prior patch's sprint counter as a base

Also updated `commands/plant.md` argument-hint and Step 2 note to surface this rule at invocation time.

---


## v6.0.5 — 2026-06-02

### Schema migrations: fix `ALTER TABLE … RENAME` view-dangling on SQLite ≥ 3.25 (debug-session find)

A debug session on the v6.0.5 cut surfaced a **pre-existing, release-blocking** defect
unrelated to the spawn work: migrations `0009_locks_mode_sprint.sql` and
`0011_mem_entries_prior_kind.sql` (recreate-table migrations) ran `DROP TABLE` + `ALTER
TABLE … RENAME TO` **while the dependent view still existed** (`v_active_locks` /
`v_mem_recent_7d`), dropping the view only afterward. On SQLite ≥ 3.25.0 `RENAME`
validates every view/trigger in the schema, so the rename aborted with `error in view
…: no such table: …`. Because `0009` halts mid-chain, `0010`/`0011` never applied —
**every fresh `shctx init` and `shctx sprint open` was broken on modern SQLite**
(observed on 3.45.1), and the context test suite ran **24/37**.

- Fix: drop the dependent view **before** the table swap in both migrations; recreate it
  after the rename. Net schema is identical — only the statement order changes to satisfy
  SQLite's modern `RENAME` validation. Idempotent migrations already applied on older
  SQLite are unaffected (the `schema_versions` guard prevents re-run).
- After the fix: full migration chain applies (11 versions), all three dependent views
  query, and the context suite is **37/37** (was 24/37).
- **Root-cause note:** this shipped because **no CI runs the test suites** (only
  `release.yml` exists). Recommend adding a workflow that runs `hooks/tests/run.sh` +
  `skills/context/tests/run.sh` on a modern SQLite — tracked as a follow-up.

### Coordinate-mode active-drive — `/shepherd:spawn` no longer pauses at the dispatch boundary (#113 / #98 / #112)

Closes the single most expensive `/shepherd:spawn` failure: **the root pausing the
moment it dispatches teammate-conductors.** After `TeamCreate` the root's turn ended
and it waited passively — there was no contract for the window between "team spawned"
and "first teammate event," and the default LLM behavior in that gap is to stop. The
operator (who chose spawn precisely to step away) returned to a session paused at the
dispatch boundary with nothing shipped (a full day lost in the field report that
motivated this). Passive `TeammateIdle` waiting "only fires when a conductor goes idle
— typically at the END of its work" (#113), idle teammates surfaced no signal (#98),
and post-`WAVE-COMPLETE` prune was deferred (#112).

- **New doctrine `doctrines/coordinate-active-drive.md`** — the binding contract:
  - **Two kinds of stop, rigorously separated:** the enumerated, closed set of
    legitimate *operator-pauses* (pre-spawn approval, `HARD-STOP`, operator-question,
    dispute adjudication, scope-confirmation, ROOT CLOSE REPORT, explicit interrupt)
    vs *passive-wait* (ending the turn with undrained coordinate state and no operator
    question pending — the bug). One-line rule: **yield to events, never to the
    operator — unless the operator is the only one who can answer the open question.**
  - **Kickoff guarantee (§III):** teammates BEGIN their lane on creation (first action
    `/shepherd:start --teammate`, no go-signal); root **confirms liveness** before
    treating dispatch as complete. Closes the mutual-wait deadlock (teammate waits for
    a kickoff while root waits for a teammate event).
  - **The coordinate cycle (§IV):** `wake → act (drain mail/idle) → probe (liveness +
    per-lane `git diff --stat` drift, `[DRIFT-WARN]`) → yield-to-events`. The same
    turn-end mechanic as passive-wait, opposite correctness: yield is cheap and
    auto-resumes; passive-wait leaves work undrained and implicitly asks the operator.
  - **Idle-without-signal (§VI, #98)** proactive probe; **active inspection cadence
    (§V, #113)** realizable subset (event-anchored sweeps; honest about no wall-clock timer).
- **Mechanical backstop `hooks/scripts/coordinate_drive_guard.sh`** (`Stop` hook,
  per the #86/#66 "mechanize prose-only invariants" lesson): blocks a premature root
  halt while a live spawn session has an `idle` teammate or lead-bound unread mail.
  - **Fast-path:** no DB / zero live teammates → exit 0. Solo `/shepherd:start`,
    `/shepherd:plant`, and ALL non-spawn work are never touched — the guard only ever
    engages inside an active spawn session.
  - **Runaway-bounded (#114 class):** a per-session 2-nudge cap then **fails OPEN**, so
    a deliberate "stop with idle teammates" is never trapped; fails open on any error;
    `[spawn].coordinate_drive_guard = block (default) | warn | off`.
  - 9-case dedicated test (`hooks/tests/test_coordinate_drive_guard.sh`, wired into
    `hooks/tests/run.sh`) — fast-path, block, lead-vs-teammate-bound mail, runaway cap,
    config off/warn. Full suite **28/28**.
- **Wired into:** `agents/shepherd.md` (Hard prohibition #14 — no dispatch-boundary
  operator-pause; coordinate-mode active-drive; Step 2 confirm-liveness-then-drive),
  `agents/conductor.md` (teammate begins-on-boot), `commands/spawn.md` (`TeamCreate`
  kickoff wording; post-spawn confirmation is not a turn-end; active-drive responsibility
  row), `commands/start.md` (teammate begin-immediately), `doctrines/root-shepherd-
  orchestration.md §II`, `doctrines/claude-code-platform-alignment.md §V` (Stop-hook
  registration), `doctrines/spawn-escalation.md §XII`, `doctrines/README.md` index,
  `docs/configuration.md` (new `[spawn]` section).

### Caching + native-leverage hardening (live-docs rigor audit)

A documentation-rigor audit against the **live** Claude Code docs (Agent Teams / hooks /
sub-agents / Dynamic Workflows / prompt-caching, verified 2026-06-02) confirmed the
coordinate-active-drive claims (`Stop {"decision":"block"}`, `SendMessage` lead
auto-resume v2.1.77, the event-driven wake model, no `team_name` on subagents) and
surfaced these fixes:

- **`TeammateIdle` routing hardened.** The live payload carries `session_id` (+ optional
  `agent_id`/`agent_type`) but **not** `teammate_name`; `teammate_idle.sh` now routes by
  `teammate_name` when present, **falls back to `session_id`**, and **fails loud** if
  neither matches — so the coordinate-drive backstop can't silently no-op on schema drift.
- **Dead heartbeat machinery retired.** The v5.1.7 per-tool teammate-heartbeat emission in
  `subagent_telemetry.sh` keyed on `$CLAUDE_TEAMMATE_NAME` (empty on the live platform) and
  never fired — removed in favor of native `TeammateIdle`-driven liveness + the
  `shctx teammate liveness` staleness poll. `spawn-escalation.md §V` +
  `claude-code-platform-alignment.md §V` reconciled.
- **Caching corrected + optimized.** `brief-cache-discipline.md` reframed — the prior
  "implicit breakpoints *inside* the brief" model was inaccurate; the genuinely-cached
  prefix is the agent system prompt (`agents/<role>.md`) + tools, and the brief's
  stable-first ordering earns *coherence* + a reusable conversation prefix. Biggest dollar
  lever is TTL: **`ENABLE_PROMPT_CACHING_1H=1`** for `--scope >= patch` (surfaced in
  `docs/configuration.md §[spawn]` + spawn preflight). Brief tails made deterministic
  (`open-issues.sql` `ORDER BY number`, dropped volatile `updated_at`) and the coder
  `[ROLE]` line made cross-sprint-stable (dropped `{sprint_branch}`).
- **Doc accuracy:** hook event count 29 → 31; `sqlite-canonical-state.md` path made
  namespace-neutral (`.shepherd` default); `workflow-compile-down.md` reconciled
  (binding *model* vs opt-in spike *backend*).

The 3 sanctioned mechanizations (adaptation/self-improvement, code-styles, context-DB
comms) were audited as cleanly mechanized + queryable-without-reindex — on-philosophy,
no change. hooks 28/28; context 37/37.

## v6.0.4 — 2026-05-31

### Adaptation + self-improvement loop, made SQLite-canonical (#94 / #95)

Closes the adaptation / self-improvement loop as a **thin behavioral layer over existing
substrate — no new engine**. The advisory markdown registry (`{paths.ctx}/sprint-patterns.md`)
is **retired**; its signal now lives in the project DB and flows back into planning
automatically.

- **New `shctx adapt` verb** (`skills/context/scripts/cmd_adapt.sh`, registered in `shctx`):
  - `adapt roll --sprint=<b> --grade=<G> [...]` — at CLOSE-FINALIZE, writes one
    `sprint_metrics` row **and** harvests this sprint's HIGH/CRITICAL `audit_findings` into
    `mem_entries(kind='prior')` lessons (deduped by concern → bounded growth). Idempotent.
  - `adapt priors --metrics|--lessons|--all [--json|--md]` — measured dispatch averages +
    recent lesson priors; graceful-empty (emits nothing on a cold store).
  - `adapt report [--md|--json]` — the materialized sprint-patterns view.
- **Schema** (migrations gap-filled by `cmd_migrate`): `0010_sprint_metrics.sql`
  (`sprint_metrics` + `v_sprint_metrics_avg`); `0011_mem_entries_prior_kind.sql` —
  recreate-table migration adding `'prior'` to the `mem_entries.kind` CHECK (preserving rows,
  both indexes, `v_mem_recent_7d`).
- **#94 adaptability:** spawn **Check 8** (`commands/spawn.md`) and engineer lane sizing read
  `shctx adapt priors --metrics` — measured `avg_sprint_minutes` / `avg_api_per_sprint` /
  `avg_lane_count` replace the static `90`/`200` defaults once history exists. The loop now
  shapes dispatch *sizing* mechanically, not just plan content.
- **#95 self-improvement:** harvested priors are injected as **cache-tail** variable content
  into the engineer + planter `[DB-CONTEXT]` blocks (`cmd_inject.sh`) and into `/shepherd:plant`
  + engineer Phase-0; a plan/seed that acts on a prior cites its `prior:<mem_id>` (the
  measurement signal).
- **Doctrine:** `adaptation-loop.md` rewritten advisory→SQLite-canonical; new
  `self-improvement.md` (harvest→inject contract); indexed in `doctrines/README.md`; referenced
  from `agent-excellence.md`. Stale `sprint-patterns.md` references across engineer/critic/
  auditor/discovery/worker references, `SKILL.md`, `flock.md`, `preflight-doctor.md`,
  `scope-scale-workload.md`, `flock-cohesion.md`, and the `session_open.sh` hook reconciled to
  the registry. Harvest source (`shctx audit insert` → `audit_findings`) reachable post the
  v6.0.3 0007-migration relocation fix.

### Lane-model reconciliation — few fat lanes over many thin sessions

Corrects a standing contradiction: `primitive-axis-binding.md` binds **Agent Teams = lanes,
Dynamic Workflows = step fan-out, subagents = steps**, yet the lane-count *minimums*
(M≥6 / L≥8 / XL 10–15, "more lanes is better") pushed lane granularity down to *step*
granularity — minting a Claude session where a subagent belongs.

- A lane is a **vertical slice run by a teammate-conductor that fans its wave-steps to a
  cluster of subagents / a Dynamic Workflow** — not one-session-per-step, not a per-wave stage.
- The inflated minimums become **few-fat-lanes guidance** (typically S 1–2, M 2–4, L 3–5,
  XL 4–6), sized to genuinely-isolable slices + measured `avg_lane_count` (#94), with **in-lane
  re-spawn per wave** for fresh context instead of more lanes.
- Minting a session per step is flagged `PRIMITIVE-INVERSION`; `@critic` now rejects
  **mis-sized** projections in either direction (too few disjoint slices, or too many thin
  sessions), replacing the one-directional "under-parallelized" reject.
- Reconciled across `agents/engineer.md` (canonical §Lane-count guidance), `critic.md`,
  `conductor.md`, `shepherd.md`, `seed-template.md`, `primitive-axis-binding.md`,
  `engineer.reference.md`, `flock.md`, `sprint-as-patch.md`, `SKILL.md`.

### Verification

- `bash skills/context/tests/run.sh` — 37/37 (incl. new `test_cmd_adapt.sh`).
- `bash hooks/tests/run.sh` — 27/27 (incl. modified `session_open.sh`).
- Fresh-DB migrate `0001 → 0011` clean; empty store ⇒ unchanged cold-start behavior.

---

## v6.0.3 — 2026-05-30

### Substrate-defect patch — Agent-Teams orchestration hardening (#97–#103)

Operational defects surfaced during live `/shepherd:spawn` runs on the v6.0.x native
substrate (Agent Teams + Dynamic Workflows). A diagnostic pass first isolated the failure
class: a 4-cell Dynamic-Workflow dispatch probe + a 16-way concurrent fan-out probe
confirmed that **`opus[1m]` resolves correctly in subagent dispatch and DW handles large
Sonnet fan-out cleanly** — the failures were neither the model nor the dispatch substrate,
but Agent-Teams *coordination* gaps. Fixes:

- **#97 — worktree pre-creation.** Root now `git worktree add`s every lane worktree and
  emits `[WORKTREE-READY]` *before* `TeamCreate`; the teammate boot prompt's INHERITED
  CONTEXT carries `worktree_status: pre-created`. Eliminates the boot-time
  `ANOMALY: worktree missing` round-trip that blocked every lane. (`commands/spawn.md`,
  `agents/shepherd.md`)
- **#98 — stall heartbeat.** Conductors must heartbeat at every phase boundary even when
  blocked on a background task, and on idle-without-`WAVE-COMPLETE` must send a status
  (`{phase, last_node, in_flight_task}`) within 1 turn. New canonical rule in
  `spawn-escalation.md §V`. (`agents/conductor.md`, `commands/spawn.md`)
- **#99 — `TEAMMATE-GIT-WRITE`.** Teammate git authority is bounded to its own
  worktree-branch commits; `git rebase`/`merge`/`push`/`worktree` halt with
  `TEAMMATE-GIT-WRITE`. Reinforced at every decision point (Hard prohibition #19,
  halt-codes table, Side-effect boundary) + new `dispatch-tier-separation.md §IV-bis.8`.
- **#100 — mechanical wave-gate.** Wave advancement is enforced by the task list, not
  prose: root TaskCreates a `wave-{N}-gate-{sprint_slug}` marker, each lane's next-wave
  IMPL task carries `addBlockedBy` (set via `TaskUpdate`, *not* a `TaskCreate` arg),
  released via `TaskUpdate(status: completed)` after the gate passes. A task with an
  unresolved `blockedBy` cannot be claimed, so no lane jumps the gate. New
  `WAVE-GATE-NOT-RELEASED` (root-side).
- **#102 — lane-task ownership.** New doctrine `lane-task-ownership.md`: every teammate
  task title is prefixed `"{lane_id}: "` and `TaskUpdate(owner:)`-set; root routes
  `TaskCompleted` by prefix; terminal tasks carry none. New `TASK-LANE-MISMATCH`
  (Hard prohibition #20).
- **#103 — engineer dispatch hardening.** New `ENGINEER-MODEL-FAIL`: root surfaces the
  raw error and PAUSEs instead of treating a null/error `@engineer` return as an empty
  plan. The `@engineer` `opus[1m]` pin is **retained** (probe-cleared; single
  once-per-sprint dispatch, not a large-set surface; 1M headroom for XL plan authorship).

No closed-flock contract change; no new commands. Patch-level: dispatch-logic + brief
templates + one new doctrine (`lane-task-ownership.md`) + two updated doctrines. The
tracked-for-v6.0.3 feature depth (#94/#95 adaptability + self-improvement) remains
operator-deferred to v6.0.4 (this cycle's foundation work is the prerequisite).

### Coherence remediation (full-repo passover)

A 7-concern read-only audit of the v6.0.x plugin surfaced ~35 coherence findings from the
rapid v6.0.0→v6.0.2 evolution. All fixed:

- **CRITICAL — migration foundation.** `schema/0007_canonical_state.sql` sat in `schema/`
  root, which `cmd_migrate.sh` never globs — so the v5.1.7 operational tables (`teammates`,
  `mailbox`, `escalations`, `deliverables`, `discovery_findings`, `audit_findings`,
  `heartbeats`) were **never created in any consumer DB**. Relocated to
  `migrations/0007_canonical_state.sql` (idempotent), removed its self-inserted
  `schema_versions` row, and switched the runner to **gap-fill** (apply any version absent
  from `schema_versions`, repairing DBs stranded past the orphan). Verified end-to-end.
- **HIGH — `shctx sprint open` unbroken.** `--mode=sprint` violated the `locks_history`
  CHECK (rc=19 every call); `0009_locks_mode_sprint.sql` recreates it with `sprint`/`spawn`.
- **CRITICAL — task-list contradictions.** `claude-code-platform-alignment.md` claimed the
  task list is "not consumed" (contradicting the #100/#102 wave-gate mechanics), and the
  "TaskCreated/TaskCompleted hook" routing in `spawn-escalation.md`/`lane-task-ownership.md`
  was a phantom (no such hook registered). Both reconciled: the task list is consumed for
  lane-routing + wave-gating; root routes by the `"{lane_id}: "` title prefix observed via
  `TeammateIdle`/`SendMessage`, not a hook.
- **Halt-code registry.** Added ~12 referenced-but-undefined codes to the canonical
  `conductor.md` table + `shepherd.md` root-side triage; canonicalized `SEED-DRIFT` into
  `-MECHANICAL`/`-SUBSTANTIVE`/`-DETECTED`; standardized `SCOPE OVERFLOW`.
- **Retired-mechanic purge.** `PAUSE-FOR-DEPENDENCY` (retired v6.0.1 #70) was still injected
  into every `@coder` brief + live in four doctrines — replaced with the native
  await-edge / `SendMessage` / finding-at-close pattern.
- **Doc sync.** Doctrine index completed (30→50 rows); `--auto` reaffirmed as a stable
  `--scope patch` alias (rescinded the never-honored removal); `workflow-compile-down.md`
  marked binding (the primary path); meta-orchestrator count corrected to three across
  `CLAUDE.md`/`README.md`/`SKILL.md`; v5.1.7 tables documented; stale §-anchors fixed.

Verification: both test harnesses green (context 36/36, hooks 27/27); fresh-DB migrate
applies 0001→0009 with every operational table present.

---

## v6.0.2 — 2026-05-29

### Groove-recovery patch — Wave 0: define the truth (ontology + primitive↔axis binding)

v6.0.1's slimming + the introduction of "lanes" blurred shepherd's core ontology and
broke its mapping of Claude-native primitives to their roles. In a live axiom session the
root spawned the conductor wave via **Dynamic Workflows** instead of **Agent Teams**, and
the teammates then failed to compile their step fan-out into workflows — each native
primitive used for the OTHER one's job (#89). Root cause: shepherd never pinned
primitive↔axis, and Dynamic Workflows is a ~1-day-old research-preview feature for which
the model has **no training prior**, so shepherd's (ambiguous) doctrines were its only
teacher. v6.0.2 is a four-wave, gated groove-recovery patch. **This entry covers Wave 0
(doctrine only) — the foundation that gates the mechanism (Wave 1), substrate (Wave 2),
and slim/validate (Wave 3) waves that follow.**

**A — canonical primitive↔axis binding (#89, #88).** New doctrine
`doctrines/primitive-axis-binding.md` pins every axis to one primitive and one unit:
planning → none → `waves × steps`; teammate-state/parallelization → **Agent Teams** →
one teammate-conductor per **lane**; execution → **Dynamic Workflows** → the compiled
script over **subagents**; worker → **subagents** → the **steps**. Spawning teammates =
Agent Teams (never a workflow); a teammate's gate-free fan-out = a compiled Dynamic
Workflow (never hand-rolled dispatch). **Never invert.** Cross-linked from
`claude-code-platform-alignment.md §VII`, `native-coordination.md`, and
`dispatch-tier-separation.md §I-bis` (the ontological tier ↔ unit mapping).

**B — ontology rewrite: `waves × steps`; lanes as a post-plan projection (#88).** The
engineer now authors the plan as **N sequential waves; each wave is X steps; each step ≈
one subagent**, with **NO lane concept**. A **lane** is a cohesive **vertical slice across
waves**, formed **only in spawn mode, after the plan**, owned by one teammate-conductor —
and it **never nests inside a wave**. Removed every `wave: <N>` field on a lane, every
"wave is a set of lanes", and every "min lanes per wave" tabulation across `engineer.md`
(+ `engineer.reference.md`), `references/seed-template.md`, `planter.md`, `pipeline.md`,
`flock.md`, `dispatch-tier-separation.md`, `SKILL.md`, `conductor.md`, `shepherd.md`,
`critic.md`, `root-shepherd-orchestration.md`, `sprint-as-patch.md`, `commands/spawn.md`,
`README.md`. The decomposition discipline split cleanly: planning = many narrow steps per
wave (substantive LOC floor); spawn = a **total** lane count (never per-wave).

**B-bis — lane refresh (durable lane, recyclable teammate).** One teammate-conductor
occupies a lane at a time, but at a wave boundary root MAY shut down an idle lane's
teammate and spawn a fresh one to take over the **same** lane for the next wave (fresh
context, lower compaction cost). Refreshing a lane's teammate is **not** a new lane — you
count lanes (constant across waves), never teammate-instances. This is the origin of the
retired "per lane per wave" phrasing (`primitive-axis-binding.md §II.1`).

**C — Phase-0 split (#88).** The pre-plan **discovery wave** runs at root BEFORE the
engineer (INTRO-COMBO-WAVE); the engineer now **consumes** its `[DISCOVERY-CONTEXT]` /
`[INTRO-AUDIT-CONTEXT]` as primary ground truth and verifies targeted gaps, rather than
re-running the full mesh itself (fixes the `engineer.md` Step 2 contradiction). The mesh
enumeration is the *coverage spec*; the engineer self-runs only when the wave is disabled
(XS / `intro_wave.enabled = false`). Carry-over / open-issue handling becomes a candidate
dedicated lane, not steps folded into the plan body.

**D — #67 / #20 reconciled.** `seed-template.md §6` (Deliverables, not "MUST-LAND lanes")
landed in v6.0.0; v6.0.2 fixes the residual §7 "coder lanes per wave" minimums and frames
the planter's seed-quality table around **deliverables** (lane decomposition is the
engineer's authority). The mandatory-`subagent_type` dispatch contract (#20) is verified
consistent across `SKILL.md §I`, `flock.md §I`, `conductor.md`, `shepherd.md`, and
`dispatch-tier-separation.md §IV-bis`.

**E — #75 reconciled.** Verified `doctrines/workflow-compile-down.md` is on-disk,
coherent, and cross-linked (`platform-alignment.md §VII`, `stage-graph.md`); all internal
doctrine references resolve.

**Gate 0 (green):** grep proves no live file nests "lane" in "wave" or tabulates "lanes
per wave" (every residual mention is a negation or the anti-pattern definition); the
binding table is canonical + referenced by 17 files; `SKILL.md` and the agent profiles
agree on the dispatch contract; #75 reconciled.

### Wave 1 — make it stick (mechanism) + hardening pass

Turns the Wave-0 truth into mechanical refusals, and folds in an operator-directed
hardening pass (doc validation against live Claude Code docs, a bug-hunt, description
hygiene, and the start/spawn boundary).

- **`hooks/scripts/dispatch_guard.sh` (new, PreToolUse Agent|Task).** Hard-blocks the
  dispatch-class violations: `DISPATCH-MISSING-SUBAGENT-TYPE` (omit / general-purpose /
  Explore / Chat), `DISPATCH-TEAMMATE-TYPE-MISMATCH` (a flock role carrying `team_name` —
  a step spawned as a lane, #66.1 / #61), `TEAMMATE-NESTING-ATTEMPT`, `WRONG-TIER-DISPATCH`
  (teammate → engineer/critic), `DISPATCH-OFF-FLOCK`. Enforces step→subagent /
  lane→teammate-conductor (#89, #66).
- **`bash_guard.sh`** gains the #89 **inversion-1** block (a `*.workflow.js` carrying
  teammate-spawn markers is refused — `PRIMITIVE-INVERSION`) and the #91 cargo
  sequential-gate block (`run_in_background:true` on a cargo gate is refused).
- **`doctrines/invariant-enforcement-matrix.md` (new, #86)** — the coverage map pairing
  every invariant with its mechanism + type (hard-block / flag / lint / auditor / doctrine)
  + status, surfacing the prose-only gaps that caused #66 / #59 / #74. Honest row-by-row
  status for the eight #66 violations (1/4 hard-blocked + tested; 2/3/6 flag-candidates;
  5/7 auditor; 8 doctrine + partial block) and the two #89 inversions (1 hard-blocked; 2
  flagged-by-design, hard block scoped to #85/Wave 2 since hand-rolled fan-out is a
  legitimate runtime-failure fallback).
- **`lint_agent_capabilities.sh`** extended for #84: least-privilege sweep across all nine
  agents pins that no agent carries a destructive MCP verb under `acceptEdits` (dual-use
  reads + release verbs are documented retentions); #74 read-only trio lint retained.
- **`hooks/tests/test_dispatch_guard.sh` (new)** + wired into `run.sh` — Gate 1 evidence:
  reproduces the two #89 inversions + dispatch-class #66 violations and proves each is
  blocked, with well-formed dispatches passing. **`hooks/tests/run.sh` 26/26 green.**
- **Doc validation (live `code.claude.com/docs`).** Confirmed Dynamic Workflows (CC ≥
  v2.1.154; ≤16 concurrent / ≤1000 total; no mid-run input; no FS/shell; `acceptEdits`;
  within-session resume; **orchestrates subagents only, cannot spawn teammates** — a
  platform-level reinforcement of the #89 binding, now cited in `primitive-axis-binding.md
  §III.1`), Agent Teams (v2.1.32 experimental), and subagents (no `description` char cap;
  "subagents cannot spawn subagents"). Surfaced discrepancy: the docs spawn teammates via
  natural-language lead instruction (not `Agent({team_name})`) and don't document
  `CLAUDE_TEAMMATE_NAME` — shepherd's convention; flagged for operator review, not yet
  rewritten.
- **Description hygiene.** All nine agent + both SKILL.md + six reference descriptions
  rewritten to single-line, **XML-free** (dropped `<example>`/`<commentary>` blocks),
  ≤200 chars; the shepherd SKILL.md description was 2414 chars — **over the documented
  1,536 skill cap** — now 187.
- **start/spawn boundary.** `/shepherd:spawn` is stated as the **primary** command
  (root + teammate-conductor lanes via Agent Teams + Dynamic Workflow execution);
  `/shepherd:start` is the **solo, lightweight** path (one sprint, no teams/lanes). Fixed a
  residual lane-per-wave construct in `commands/spawn.md`. Planter + seed-template made
  **spawn-aware** (deliverables decompose into file-disjoint vertical slices the engineer
  projects into lanes; the planter never defines lanes itself).
- **Bug-hunt fixes** (subagent review, no HIGH): case-fold consistency in dispatch_guard
  Check 3 (MEDIUM-1); anchored the workflow `team_name` marker to avoid false-blocking a
  comment mention (MEDIUM-2); added the `CLAUDE_PROJECT_SESSION_TYPE` teammate signal;
  single-quote in the workflow marker class; fixed a dangling `§V.2` cross-ref. Both
  MEDIUM fixes locked in with regression tests.

**Gate 1 (green):** `test_dispatch_guard.sh` reproduces the two #89 inversions + the
dispatch-class #66 violations and proves each mechanically blocked; allowlist lint green.

**Wave 1 follow-ups (gaps tracked in the matrix, not yet hard-mechanized):** #66.2/#66.3
cargo `CARGO_TARGET_DIR` / `--frozen` warns; #59 close-finalize since-last-commit gate;
#90 spawn boot-prompt SCOPE RULE.

### Wave 2 + finalization — native substrate, platform reconciliation, productionize

Operator-directed finalization: deliver the governance + context-management core by elegantly
composing Claude Code's native tools, update the README, and make the repo product-grade.
Much of the substrate already existed (`shctx graph compile` with a faithfulness diff); this
wave **reconciles it to the verified platform mechanism, completes the topology tooling, and
hardens the operational substrate.**

- **#93 RESOLVED — platform mechanism verified against live docs (2026-05-29).** Teammates
  spawn via the **`TeamCreate`** tool family + a natural-language lead instruction referencing
  the `shepherd:conductor` subagent definition — there is **no `team_name` parameter on
  `Agent`/`Task`** (those spawn subagents), and a teammate session exposes **no identity env
  var** (`anthropics/claude-code#35447`, closed not-planned); identity is delivered only in
  hook-input JSON. **Dynamic Workflows orchestrate subagents only — never teammates** (confirms
  the #89 binding; only the call-shape was wrong). Reconciled across `commands/spawn.md`,
  `agents/conductor.md`, `agents/shepherd.md`, `dispatch_guard.sh`,
  `claude-code-platform-alignment.md §I` (Open investigation → **Resolved**),
  `invariant-enforcement-matrix.md`, and `primitive-axis-binding.md §III.1/§IV`.
- **Honest, env-independent dispatch guard.** `dispatch_guard.sh` now detects a teammate
  session from the hook-input **`cwd`** (a `.worktrees/` path) — env-independent, since the
  platform exposes no teammate env var — with the `subagent_type` discipline as the mechanical
  floor and the `team_name`/teammate-tier checks documented as defence-in-depth (layered over
  the platform's structural no-nesting guarantee). New `cwd` regression in
  `test_dispatch_guard.sh`; **hooks 26/26 green.**
- **`shctx graph diagram` (new, #77 topology utility).** Emits a **Mermaid execution diagram**
  of the Stage Graph — seam vs fan-out classification (matching the compiler's φ-map), labeled
  edges, and an optional per-segment compiled-fan-out overlay — to
  `{workdir}/graph/diagrams/{sprint}.mmd` or stdout. Complements the existing
  `shctx graph compile` (Dynamic Workflow emission + soundness/completeness/determinism
  faithfulness diff + manifest seam-export) per `workflow-compile-down.md`.
- **Operational substrate: `$SHEPHERD_WORKDIR`.** New first-class resolver `resolve_workdir()`
  (`skills/context/scripts/_lib.sh`, mirrored in `hooks/scripts/_lib.sh`) honors
  `$SHEPHERD_WORKDIR` → existing `.shepherd` → existing `.artifacts` → default `.shepherd`.
  **Fixed a canonical-state split-brain bug:** five `cmd_*.sh` (escalate/deliverable/mailbox/
  report/teammate) and five hooks (teammate_idle/deliverable_check/subagent_telemetry/
  lock_guard/dedup_write_guard) hardcoded `.artifacts/root.db`, so a `.shepherd`-default project
  silently used the wrong DB — all now resolve through the namespace. The workdir ships its own
  `.gitignore` (secrets + runtime trimmed: `*.env`/`*.key`/`*.pem`/`secrets/`/…; design records
  under `docs/` preserved); the root `.gitignore` mirrors the `.shepherd/` runtime entries. New
  `skills/context/tests/test_workdir.sh` pins the precedence; documented in
  `docs/configuration.md`.
- **Root proactivity + compartmentalization (operator-emphasized).** `agents/shepherd.md`
  (Coordinate mode) and `root-shepherd-orchestration.md` now make **proactive idle-teammate
  pruning** a standing root behavior — once a teammate's wave payload is materialized, prune it
  (reclaim compute, avoid forced compaction) and **refresh** the lane with a fresh teammate at
  the next wave boundary. Compartmentalizing each wave into fresh context is the default.
- **#71 `release.yml` fixed** — `actions/checkout@v6`'s credential-persistence breaking change
  (PR #2286) broke the authenticated `git push` steps once the v6.0.1 `detect` regex fix let
  the pipeline proceed; pinned checkout to `@v5` + explicit `token:` + `persist-credentials`.
- **#72 critic false-positive fixed** — the critic's Necessity audit now resolves the full
  Cargo **feature graph** before flagging reachability (default sets, `foo = ["bar"]` chains,
  umbrella `full` rollups, optional-dep `dep:`/`x?/feat`, workspace/`--features`), so a
  transitively-enabled feature (e.g. `native-runtime` via `full`) no longer raises a spurious
  CRITICAL; genuinely dead features downgrade to a verify-first observation.
- **README** rewritten to the finalized v6.0.2 story; all six version sources confirmed synced.

**Gate (green):** `hooks/tests/run.sh` 26/26; `test_workdir.sh` passes; `shctx graph diagram`
verified end-to-end. (Context DB tests require `sqlite3`, absent in this environment —
environmental, not a regression.)

**Tracked for v6.0.3 (non-core depth — operator-deferred):** adaptability + self-improvement
mechanisms (filed as issues); the still-tracked matrix gaps (#59 close-gate hard hook, #90
boot-prompt SCOPE RULE, #66.2/#66.3 cargo warns, #66.6 dead-pane prune); the deeper cross-run
concurrency budget (#83); the full hand-rolled-mechanic deletion (#70/#53/#58); and
compile-down telemetry (#87). The governance core + native-substrate execution path are in
place; these add depth.

---

## v6.0.1 — 2026-05-29

### Reposition onto Claude Code's native substrate (Dynamic Workflows + Agent Teams + subagents)

Patch 1 of the v6 line repositions shepherd: **retain the governance core, slim
the hand-rolled orchestration mechanics, and adopt Claude Code's native
primitives as the primary execution substrate.** Dynamic Workflows (research
preview, 2026-05-28) finally make out-of-context agent fan-out a platform
capability; shepherd now contributes *discipline* (closed flock, hard-refusal
dispatch contract, audited Stage Graph, canonical SQLite+git state) while the
platform contributes *execution*. Epic #76.

**Invariants held** (unchanged by the slim): the closed flock + behavioral
contracts; mandatory `subagent_type` with refusal rules; the critic / wave /
close gate topology; SQLite + git as canonical state; the engineer-authored,
critic-gated Stage Graph as the dispatch contract.

**A — capability-enforced read-only reviewers (#74).** Dropped
`execute_sql` from `@auditor` / `@discovery` allowlists; `Write` is retained but
path-scoped by the existing `lock_guard.sh` PreToolUse hook (Option B). Added
`hooks/tests/lint_agent_capabilities.sh` — fails if a read-only reviewer regains
a mutating verb (or keeps un-scoped `Write`). The read-only contract is now
allowlist-enforced, holding even under a Dynamic Workflow runtime's `acceptEdits`
where no orchestrator is in the loop.

**B — `workflow-compile-down.md` doctrine landed (#75).** The compile-down
evaluation doctrine (the §IV faithfulness contract, §V φ node→construct map, §VI
canonical-state seam) with cross-links from `platform-alignment §VII`,
`stage-graph.md`, and the doctrine web.

**C — dispatch-contract consistency (#20, #67).** Verified the mandatory-
`subagent_type` flip and the seed-template lanes→deliverables rename already
landed in v6.0.0; reconciled the residual stale text (`specialist-dispatch.md`,
`agent-briefs.md`, planter density prose).

**D — `shctx graph compile` (#77).** Emits gate-free agent-fanout segments of the
Stage Graph as Dynamic Workflow scripts — the **primary** path for those
segments (not a toggle). Built on the existing `shctx plan extract` surface (one
source, two projections); bounded `Promise.all` (≤16 concurrent / ≤1000 total);
read-only steps carry no edit tools; CLOSE-SWARM is the default first target. The
§IV faithfulness diff (`--verify`: soundness / completeness / determinism) gates
every compiled segment. Wired as primary in `dispatch-cascade.md §IV-bis` and the
conductor walk; mode-agnostic (solo + teammate); runtime failure degrades to
in-context dispatch.

**E — native coordination (#78).** `native-coordination.md` maps the retired
mechanics onto native primitives (in-script ordering / Agent Teams `SendMessage`
/ subagents) and **demonstrates** parity before deletion.

**F — slim (#70, #53, #58).** Deleted pause-for-dependency entirely
(`agent_pause_detector.sh`, `cmd_pauses.sh`, `pause-for-dependency.md`, the
`shctx pauses` verb, the `PAUSE-FOR-DEPENDENCY` / `RESUME-LANE` node types, and
the satellite subgraph). Coders/workers now file a `BRIEF-AMENDMENT REQUEST` or a
finding at close; cross-lane deps are engineer-composed graph edges the compiled
segment `await`-orders. Heartbeat *auto-relay* (#53, never built) and
idle-*pruning* (#58) are documented as moot; teammate **liveness** + Agent Teams
state are intentionally kept. `hooks/tests/test_pause_retired.sh` proves no
residual dependency.

**G — version cycle + release workflow (#71).** Fixed the silently-skipping
release pipeline: the `detect` regex accepted only a space/EOL after the version
triple, so descriptive PR titles (`vX.Y.Z: <summary>`, the convention since
v6.0.0) never matched — the pipeline no-opped (the 9-second runs). The regex now
accepts the `:` delimiter. Corrected the README "Current version" line that had
drifted to 5.1.9 because the v6.0.0 bump step never ran.

Suites green: `hooks/tests` 25/25, `skills/context/tests` 35/35 (incl. the new
compile, capability-lint, and pause-retired tests).

---

## v6.0.0 — 2026-05-28

### Dispatch enforcement + planter authority excision

Major bump. v5.1.9 modernized the dispatch model (registry-loaded
`subagent_type` replaced inline body injection — issue #20) but removed the
old enforcement language without an equivalent replacement, leaving a
permissive fallback path that produced three consecutive failed sprints on
`fl03/axiom v0.3.4-dev.0/1/2` (2026-05-25..27). v6.0.0 closes the gap:

**Hard refusal contract (binding) — `doctrines/dispatch-tier-separation.md §IV-bis`:**

| Combination | Halt code |
|---|---|
| `subagent_type` missing OR `general-purpose` / `Explore` / `Chat` | `DISPATCH-MISSING-SUBAGENT-TYPE` |
| `team_name` set + `subagent_type ≠ shepherd:conductor` | `DISPATCH-TEAMMATE-TYPE-MISMATCH` |
| `subagent_type` outside closed-flock-six (no specialist clearance) | `DISPATCH-OFF-FLOCK` |
| Teammate-conductor constructs `team_name` (any value) | `TEAMMATE-NESTING-ATTEMPT` |
| Teammate-conductor dispatches `@engineer`/`@critic` | `WRONG-TIER-DISPATCH` |
| SOLO mode spawning OR TEAMMATE mode running SOLO ops | `MODE-MISUSE` |

These codes are terminal for the offending dispatch. Root does NOT
auto-resume on `WRONG-TIER-DISPATCH` or `TEAMMATE-NESTING-ATTEMPT` — the
teammate brief is malformed and needs operator review.

**Wave-tier model promoted to canonical doctrine** —
`doctrines/root-shepherd-orchestration.md §I-bis`:

- INTRODUCTION (§1) = root-direct subagents (`@discovery` × N + intro
  `@auditor` × 2 + `@engineer` + `@critic` + plan materialization +
  operator approval gate). No teammates spawned.
- BODY (§2) = teammate-conductors, one per lane per wave. Each conductor
  walks its lane's micro-Stage-Graph using its OWN subagent waves.
- CLOSE (§3) = root-direct subagents (`@auditor` × 3-5 close-swarm split
  by concern, on aggregated sprint output). CLOSE-FINALIZE git ops run at
  root.

**Planter authority excised** — `agents/planter.md §Authority boundary` +
`references/seed-template.md §6` (renamed from "MUST-LAND lanes" to
"Deliverables (issue-anchored)") closes FL03/shepherd #67:

- Lane numbering (`Lane N`) and sequencing (`sequential after Lane K`) are
  the engineer's exclusive authority in the plan. Removed from seed
  template.
- Wave composition table (§7) demoted to NON-BINDING recommendation. The
  engineer's `## Stage Graph` is the binding decomposition.
- Per-deliverable T-shirt sizes removed from seed template — engineer
  analyzes at plan-time.

**Scope is workload-scale, never a quality bar** —
`doctrines/version-scale-roadmap.md` + `scope-scale-workload.md` opening
notes are now binding:

- A planter may NOT defer or downscope work because "it's just a patch."
- A conductor may NOT come up short on lanes citing patch size.
- "Reshape as a `@worker` dispatch" framing for sprints that don't deliver
  their seed-promised work is forbidden — that is seed/implementation
  drift, gradeable as a `@critic` RECONSIDER or `@auditor completeness`
  C+ cap, NOT a sprint reclassification.

**New halt codes** — root-side (`agents/shepherd.md §Halt codes`) and
conductor-side (`agents/conductor.md §Halt codes`):

- `DISPATCH-MISSING-SUBAGENT-TYPE`
- `DISPATCH-TEAMMATE-TYPE-MISMATCH`
- `DISPATCH-OFF-FLOCK`
- `TEAMMATE-NESTING-ATTEMPT`
- `MODE-MISUSE`
- `MODE-DETECTION-AMBIGUOUS` (formalized; was implicit prior)

**Boot-prompt hardening** — `commands/start.md §Step T0 (--teammate path)`
now runs a four-check refusal block (INVOCATION-CONTEXT present,
`dispatcher == teammate-conductor`, lane brief slice present,
`ROOT-SESSION-NAME` populated) before any dispatch. SOLO `/shepherd:start`
unchanged.

**Spawn HARD PROHIBITIONS rephrased** — `commands/spawn.md §Build the
teammate prompt` rewrites the prohibition block from descriptive ("NO X")
to machine-checkable ("MUST REFUSE X and SendMessage halt_code: <code>,
blocking: true"). Same content, enforceable shape.

#### Closes / references

- Closes FL03/shepherd #65 (shepherd:coder dispatched as teammate)
- Closes FL03/shepherd #66 (root shepherd ignored feedback / dispatch
  protocol)
- Closes FL03/shepherd #67 (seed-template lane prescription)
- Downstream blast radius: axiom v0.3.4-dev.0/1/2 failed sprints, axiom
  issues #1487-#1494 (P0/P1 production fires opened 2026-05-26/27)

#### Migration

Projects on v5.1.x must update any direct Agent calls in custom doctrines
or hooks to set `subagent_type: "shepherd:<role>"` explicitly. The
permissive fallback to `general-purpose` is GONE — calls without it will
refuse at dispatch time. Hooks that compose dispatch briefs (e.g., custom
`agent_pause_detector.sh` extensions) should also be audited.

#### Files moved together

- `.claude-plugin/plugin.json` → 6.0.0
- `.claude-plugin/marketplace.json` → 6.0.0
- `skills/shepherd/SKILL.md` frontmatter → 6.0.0
- `skills/context/SKILL.md` frontmatter → 6.0.0
- `README.md` header
- `CHANGELOG.md` (this entry)

---

## v5.1.8 — 2026-05-21

### Platform-alignment patch

Adopts Claude Code v2.1+ hook primitives where they cover ground shepherd
previously had to handle by inference, ships the v5.1.7 carry-forward bug
fix, and documents how shepherd's teammate-coordination model maps to the
official **Agent Teams** primitive (Claude Code v2.1.32+). The flock model
and SQLite-canonical store are unchanged; this release is additive across
hooks, doctrines, and one helper-shim fix.

Closes #19, #21, #22, #23, #24, #26, #55. Documents the platform mapping
for #53 indirectly via the new alignment doctrine.

#### Hook surface (new events — Lane B)

- `CwdChanged` — `hooks/scripts/cwd_changed.sh` (59 lines). Informs the
  conductor when cwd drifts into a sub-worktree, paired with
  `doctrines/conductor-cwd.md §Ban 1`. Informational only; never blocks.
  Subagents (coder, auditor, etc.) are exempt — only conductor-role cwd
  drift fires the warning.
- `UserPromptSubmit` — `hooks/scripts/user_prompt_submit.sh` (88 lines).
  Auto-injects `shctx status --md` as `additionalContext` for
  `/shepherd:start` and `/shepherd:spawn` invocations; surfaces a friendly
  "no shepherd.toml" warning when the host project is unconfigured.
  `/shepherd:ctx` is intentionally not auto-primed (operator is about to
  query manually).
- `WorktreeCreate` / `WorktreeRemove` — `hooks/scripts/worktree_lifecycle.sh`
  (133 lines, single script registered for both events). Records worktree
  lifecycle in the new `worktrees` SQLite table; on remove, prunes the
  zombie `worktree-agent-*` ref if no HEAD pointer remains. Closes #22.
  Idempotent; never blocks. Defensive against schema drift — Claude Code
  docs don't yet specify the payload field structure, so the hook reads
  `.worktree.path` / `.worktree.branch` then falls back to pwd + current
  branch. Extraction is recorded in `<namespace>/logs/hooks/YYYY-MM-DD.jsonl`
  for drift audit.

#### Hook surface (new event types — first adoption of `type: agent`)

- **Agent-based hook** on `PostToolUse(Edit|Write)` with
  `if: "Edit(*.plan.md)"` / `if: "Write(*.plan.md)"`: **Phase 0 mesh
  verification**. Verifies every "landed in tree" / "confirmed at" /
  "in tree:" claim in a sprint plan against the sprint branch's
  `git log` (not file-content grep — that's what produced the false-landed
  L5/L6 claims on `fl03/axiom v0.3.2-dev.1`; see issue #23). Surfaces
  unverified claims as a warning so the engineer doesn't propagate false
  "done" markers to the next session's handoff. Closes #23. Default-on;
  `if` filter gates spawn so the hook only runs on plan-md writes (low
  frequency). Timeout 90 s, max 10 tool calls.
- **Agent-based hook** on `Stop`: **WAVE-GATE cherry-pick check**.
  Fast-paths via `git branch | grep -c '^  agent-'` (0 ⇒ ok, no further
  tools); on active sprint branches checks each `agent-*` branch for
  stray commits not reachable from sprint HEAD and surfaces a warning.
  Closes #21. Default-on; the fast-path keeps the per-turn cost bounded
  (~$0.001/turn Haiku when no agent branches exist; ~$0.005/turn during
  active multi-lane sprints). Timeout 30 s, max 5 tool calls.

#### Schema (Lane A)

- Migration `0008_worktrees.sql` — adds `worktrees` table
  (`id PK, path, branch, tool_use_id, agent_role, sprint, created_at,
  removed_at, status`) + 2 indexes (`status`, `sprint`). Additive only;
  no ALTER on existing tables, WAL mode preserved.

#### Doctrines (Lane D)

- **NEW** `skills/shepherd/doctrines/claude-code-platform-alignment.md`
  (617 lines) — maps shepherd's teammate / mailbox / heartbeat /
  escalation / deliverable primitives to the Claude Code v2.1.32+
  official **Agent Teams** primitive (opt-in via
  `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`). 22-row primitive map; 5
  bridging rules with owner / bridge / failure-mode triples; 8
  anti-patterns; 3-version migration roadmap (v5.1.8 document mapping →
  v5.2.0 evaluate `TaskCreated`/`TaskCompleted` consumption → v6.0.0
  evaluate `[teams].platform_backend` opt-in). Documents the mailbox
  bridging rule (shepherd persists across sessions; platform `SendMessage`
  is in-session only).

#### Bug fixes (Lane C)

- **#55** — `cmd_discovery.sh` legacy subverbs (`list`, `show`, `search`,
  `clear`) were broken because they called `resolve_namespace` /
  `current_sprint` helpers that live in `hooks/scripts/_lib.sh`, not in
  `skills/context/scripts/_lib.sh` (the lib sourced when these cmd
  scripts are invoked via bare `bash`). Fix: add cross-lib shims to the
  context lib so direct invocation works without cross-coupling to the
  hooks lib. New smoke test `skills/context/tests/test_helpers_in_ctx_lib.sh`
  regression-guards both helpers (sources lib, asserts `declare -F`,
  asserts non-empty output, asserts absolute path).

#### Session-open hardening (Lane E — v5.1.8 extension)

- **#24** — `session_open.sh` Anchor 5: agent-branch stray-commit survey.
  At SessionStart, walks `git branch | grep '^  agent-'` and runs
  `git rev-list --right-only --count "<sprint>...<branch>"` for each;
  surfaces any branch with stray commits not reachable from the sprint
  HEAD as a warning. Catches lost work from context-truncated prior
  sessions BEFORE the conductor reads the handoff and inherits a "complete"
  claim that is false on the sprint branch. Complements the WAVE-GATE Stop
  hook (which catches strays during the active session) — together they
  form a session-boundary safety net per the issue's recommendation.
- **#26** — `session_open.sh` Anchor 6: multi-plan.md reconciliation
  surface. When a sprint branch has more than one plan file (e.g.,
  `v0.3.2-dev.1.plan.md` + `v0.3.2-dev.1b.plan.md`), the file list is
  surfaced as a warning so the conductor reconciles all plans, not just
  the primary. Matches `^<sprint>([.-][a-z0-9]+)?\.plan\.md$` to catch
  the common addendum-suffix conventions (`.b`, `-b`, `-addendum`).
- **#19** — informational hook warning UI rendering. Added `[hooks].quiet_warnings`
  opt-out in `shepherd.toml` (default `false`, preserving v5.1.7 and prior
  behavior). When `true`, `emit_context` skips JSON emission while still
  calling `log_event` — operators can grep
  `<namespace>/logs/hooks/YYYY-MM-DD.jsonl` to recover the warning text
  out-of-band. `session_open.sh` refactored to route its final emission
  through `emit_context` so the opt-out gate applies uniformly.
  Documented in `docs/configuration.md §[hooks]`.

#### Plugin-manifest evaluation (decided non-features)

- **`settings.json` at plugin root with `agent: "shepherd"`** — evaluated
  and deliberately deferred. The platform key activates the named agent
  as the main-thread agent for every Claude Code session where the
  plugin is enabled, applying its system prompt, tool restrictions, and
  model globally. That would change main-chat behavior for every
  shepherd-installed session, breaking `/shepherd:start` solo mode's
  expectation that main chat behaves as a regular Claude. Better path:
  conditional activation on `/shepherd:spawn` only, which requires
  upstream Claude Code support we don't have today. Cited in alignment
  doctrine §VI.
- **`monitors/monitors.json`** — evaluated. shepherd already streams
  events into `<namespace>/logs/events-YYYY-MM-DD.jsonl`; a monitor
  `tail -F` over that file would create a noisy notification stream
  during every dispatch. Deferred; revisit if operators want it.
- **`.lsp.json`** — not applicable to shepherd's domain.
- **`bin/`** — evaluated. Exposing `shctx` directly on `$PATH` would
  shorten invocations. Deferred to v5.2.0 (multi-install conflict risk).

#### Known gaps (carry to v5.1.9 / v5.2.0)

- **TeammateIdle `tool_name` fidelity gap** — carry from v5.1.7; still
  open (`CLAUDE_TOOL_NAME` env var not set in `SubagentStop` context).
- **WorktreeCreate / WorktreeRemove payload schema** — Claude Code docs
  don't yet specify field structure. `worktree_lifecycle.sh` is
  defensive but actual fields may shift; log-stream the extracted
  payload to catch drift.
- **#47 / #53** — deferred to v5.2.0+ unchanged.

#### Deferred to v5.2.0+

- `TaskCreated` / `TaskCompleted` hook consumption (Claude Code Agent
  Teams primitives) — evaluation pending platform's experimental-flag
  removal.
- `SubagentStart` hook consumption — replaces inference of spawn time
  from `subagent_telemetry.sh` `SubagentStop` event; would unblock
  per-spawn telemetry rows.
- `PreCompact` / `PostCompact` hooks — auto-snapshot dispatch state for
  context-truncated session resume (mitigates lost-work landmines like
  #21 / #24 from a different angle).
- `bin/` directory with `shctx` on PATH.

---

## v5.1.7 — 2026-05-20

### SQLite-canonical operational state

Architectural shift: `.artifacts/root.db` becomes canonical for ephemeral
operational state (teammate liveness, heartbeats, mailbox, escalations,
deliverables, structured discovery/audit findings). Markdown reports are
materialized views over rows. File-canonical store is reserved for
human-authored durable artifacts (specs, plans, seeds, agent profiles,
doctrines, CHANGELOG, README).

Resolves the v5.1.5/v5.1.6 spawn-rollout defect cluster (#43, #44, #49,
#50, #51, #52) via the same shift — each bug was a file-bound symptom of
a missing canonical store; the cluster collapses once the store exists.
Also generalizes axiom's per-package feature CI feedback (#54) into a
workspace-tool-general doctrine.

#### Schema (Lane A1)
- New migration `0007_canonical_state.sql` adds 7 tables + 3 views:
  `teammates`, `heartbeats`, `mailbox`, `escalations`, `deliverables`,
  `discovery_findings`, `audit_findings`. Additive only — no ALTER on
  existing tables. WAL mode preserved.

#### Doctrine (Lane A2)
- New `doctrines/sqlite-canonical-state.md` — binding rule + allow-list
  + anti-patterns + migration guidance + back-compat statement.

#### shctx surface (Lanes A3, A4)
- New subcommands: `shctx teammate {register,heartbeat,status,liveness,
  prune,retire}`, `shctx mailbox {send,recv,ack,stale}`, `shctx escalate
  {<create>,list,resolve}`, `shctx deliverable {promise,complete,stalled}`,
  `shctx report <kind>`.
- Extended: `shctx discovery insert`, `shctx audit insert`.
- Tests under `skills/context/tests/test_cmd_*.sh` + `test_schema_0007.sh`.
- Shctx dispatcher whitelist updated to include the 5 new subcommands.

#### Agent profile amendments (Lanes B1, B2)
- `agents/discovery.md` — row-write Hard Prohibition (closes #43);
  `MISSING-RUN-ID` halt code.
- `agents/critic.md` — Step 0.5 deliverable promise/complete contract (closes #52).
- `agents/auditor.md` — Step 0 deliverable contract; new `Canonical gates
  (intro-mode regression)` section that runs `[gates].extra` from
  `shepherd.toml` (closes #52, #44).
- `agents/conductor.md` — Cargo discipline (binding under spawn) section
  mandating `CARGO_TARGET_DIR=target/.lanes/<lane-slug>` + `--frozen` on
  every cargo invocation in the flock (closes #50).
- `agents/shepherd.md` — `TEAMMATE-CRASHED` halt code + Crashed-teammate
  detection section (closes #49).
- `commands/spawn.md` — Cargo discipline (binding) block injected into the
  conductor brief template.

#### New command (Lane B3)
- `/shepherd:cleanup` — prunes stale/crashed teammates from canonical state
  via `shctx teammate prune` (closes #51). Operator-confirmed; never
  auto-prunes live entries.

#### Hook integration (Lane B4)
- `hooks/scripts/subagent_telemetry.sh` extended to emit teammate
  heartbeats when `CLAUDE_TEAMMATE_NAME` is set.
- `hooks/scripts/teammate_idle.sh` — new `TeammateIdle` hook marks
  status=idle, surfaces open escalations + stalled deliverables to lead.
- `hooks/scripts/deliverable_check.sh` — new `Stop` hook auto-marks
  promises stalled after 10 min.
- `hooks/hooks.json` — registers `TeammateIdle` and `Stop` entries.

#### Hotfix (Lane B5 — close-audit blockers)
- Fixed broken SQL escape idiom `${var//\'/\'\'}` (4-char artifact, not
  SQL-doubled apostrophe) across all 5 new v5.1.7 scripts AND 3
  pre-existing scripts that carried the same bug (`cmd_mem.sh`,
  `cmd_profile.sh`, `cmd_query.sh`). Replacement is now `''` (literal
  two-apostrophe SQL escape).
- Added numeric-id validation `[[ $id =~ ^[0-9]+$ ]]` to `mailbox ack`,
  `deliverable complete`, `escalate resolve` — closes a live SQL
  injection vector confirmed in audit.
- `cmd_report.sh` materializer switched from `|` separator to ASCII
  `\x1f` Unit Separator across all 4 query sites — fixes corruption when
  finding bodies contain markdown table chars or newlines.

#### Backlog hygiene (Lanes W1, W2)
- 22 open issues in #18–#39 triaged: 3 superseded, 13 still-valid,
  1 close-as-stale. Report at `.artifacts/docs/handoffs/2026-05-20-old-issue-triage.md`.
  Operator close review pending for #18, #25, #32, #39.
- v5.1.6 fixes verified in tree: #45 (dispatch-tier separation) and #46
  (in-process Agent tool restriction, upstream Claude Code #31977) both
  have grep-evidenced verification comments; recommended for close.

### Known gaps (carry to v5.1.8)
- `cmd_discovery.sh` and other legacy subverbs call `resolve_namespace` /
  `current_sprint` helpers that live in `hooks/scripts/_lib.sh` but not
  `skills/context/scripts/_lib.sh` — direct bash invocation of legacy
  subverbs breaks. Pre-existing bug surfaced by Lane A4. New v5.1.7
  insert paths bypass the broken precondition.
- Heartbeat hook fires on `SubagentStop` not per-tool-call; `tool_name`
  column always logs `unknown` because `CLAUDE_TOOL_NAME` env var is not
  set in that hook context. Liveness detection works; tool-name fidelity
  doesn't. Fix or accept in v5.1.8.

### New doctrine (also lands in v5.1.7 — reframe of #54)
- `doctrines/workspace-member-isolation-gate.md` — generalizes axiom's
  per-package feature CI feedback (#54) into a workspace-tool-general
  doctrine. The defect class ("workspace-unified passes, per-member
  isolated fails") affects cargo, pnpm, npm workspaces, turborepo, go
  work, bazel, gradle multi-project, maven reactor — any workspace-aware
  build tool. Doctrine specifies the acceptance contract; per-ecosystem
  realization is project-owned (typically via `shepherd.toml [gates].extra`
  consumed by the v5.1.7 intro-mode regression auditor extras gate).
  Closes #54.

### Deferred to v5.2.0+
- #47 — cross-patch `--scope=minor` / `--scope=version` enumeration
- #53 — `SendMessage heartbeat_payload` first-class runtime primitive
  (shctx infrastructure ready; upstream-dependent)

---

## v5.1.6 — 2026-05-19

### Root-shepherd tier + lane-per-conductor fanout + `--scope` flag

v5.1.6 introduces a **three-tier dispatch hierarchy** under `/shepherd:spawn`,
downgrades the conductor to Sonnet with dual-mode behavior (solo retains full
surface; teammate is restricted), restricts `@engineer` and `@critic` to
root-tier-exclusive dispatch under spawn, adds a `--scope` flag for workload
scaling, and lifts engineer plan minimums toward ultra-parallel composition
(M=6, L=8, XL=10–15 lanes per wave).

The primary new spawn pattern is **lane-per-conductor fanout**: the engineer
designs the plan as W waves × L_w lanes per wave; for each wave, root spawns
L_w teammate-conductors (one per lane). Each teammate gets a tiny stable
prefix (one lane's brief + the conductor profile body), pushing cache hit
rates higher and reducing context pollution. More small focused teammates
becomes both cheaper and higher-quality than fewer broad ones.

`/shepherd:start` and `/shepherd:spawn` remain two independent execution
paths. `/shepherd:start` (solo, main chat) is backward-compatible — full
pipeline, conductor profile, all six lanes dispatchable. `/shepherd:start
--teammate` (NEW) is the teammate-session entry point spawned by `/shepherd:spawn`:
skip Phase 0 / INTRO / engineer / critic (root already did those); read assigned
lane brief; execute lane; surface WAVE-COMPLETE.

#### New

- **`agents/shepherd.md`** — root-tier profile (model: inherit, color: gold).
  Adopted by main chat under `/shepherd:spawn` (operator-explicit only).
  Owns `@engineer` + `@critic` dispatch, artifact materialization from
  teammate payloads, cross-teammate dispute resolution, close-swarm
  coordination. Two-meta-loading with planter for delegated seed work.
- **`doctrines/root-shepherd-orchestration.md`** — root-tier behavioral
  contract: three modes (idle/dispatch/coordinate), responsibilities,
  prohibitions, escalation triage matrix, close-mode flow.
- **`doctrines/dispatch-tier-separation.md`** — binding three-tier matrix.
  Teammate-conductors CANNOT dispatch `@engineer`/`@critic` — surface
  `PLAN-AUTHORSHIP-REQUEST` / `PLAN-GATE-REQUEST` escalations instead.
  Solo-mode `/shepherd:start` retains full dispatch (exemption documented).
- **`doctrines/scope-scale-workload.md`** — `--scope` flag semantics, 4-tier
  mapping (sprint/patch/minor/version), composition with `--parallel`,
  preflight gating for minor/version (operator double-confirm), sprint
  enumeration algorithm.
- **`/shepherd:start --teammate`** flag — teammate-session entry point.
  Skips Phase 0/INTRO/engineer/critic (root did those); loads conductor
  in TEAMMATE mode; reads assigned lane brief from boot prompt; walks
  lane micro-Stage-Graph (DEDUP-GATE → IMPL → LANE-CLOSE); surfaces
  WAVE-COMPLETE via SendMessage.
- **`/shepherd:spawn --scope <value>`** flag — workload scale declaration:
  `sprint` (1 sprint, default), `patch` (≡ retired `--auto`), `minor`
  (experimental, requires `confirm minor`), `version` (experimental,
  requires `confirm version` + resource warning).
- **`/shepherd:spawn Check 0`** — operator-explicit invocation enforcement.
  Refuses nested spawn from teammate sessions (detects via
  `$CLAUDE_AGENT_TEAMMATE_NAME`, INVOCATION-CONTEXT, parent-session env).

#### Changed

- **`agents/conductor.md`** — `model: inherit` → `model: sonnet`. New
  "Conductor modes" section documents dual-mode behavior (solo vs teammate)
  + mode-detection signals. Three new hard prohibitions (#13–#15) for
  teammate mode: no engineer dispatch, no critic dispatch, no artifact
  writes. Lane-per-conductor model documented inline. Peer-to-peer
  messaging permissions defined. Side-effect boundary table split into
  SOLO and TEAMMATE mode sub-tables.
- **`agents/engineer.md`** + **`agents/critic.md`** — new
  `WRONG-TIER-DISPATCH` halt code; tier check is first prohibition in
  Step 0 of critic protocol. `[INVOCATION-CONTEXT]` brief field added.
  Engineer body gains "Ultra-parallel plan template (spawn mode)" section
  with lane structural requirements (`lane_id`, `wave`, `file_scope`,
  `parallel_with`, `steps`, `acceptance` in YAML form). Critic gains a
  seventh core duty: ultra-parallel discipline audit.
- **Engineer plan template** — minimum lane counts raised under spawn mode:
  M=6 (was 4), L=8 (was 6), XL=10–15/wave (was 6+/wave). Body LOC floor
  scaled accordingly (M=400, L=700, XL=1500+). Solo mode retains v5.1.5
  minimums.
- **`commands/spawn.md`** — new Check 0 (operator-only), new `--scope`
  flag section, main chat now adopts `agents/shepherd.md` (not
  `planter.md`) under spawn, boot prompt includes `INVOCATION-CONTEXT` +
  lane-fanout fields + `ROOT-SESSION-NAME`. Teammate first action is now
  `/shepherd:start --teammate` (not bare `/shepherd:start`). Hard-pause
  prompts for `--scope=minor` and `--scope=version`.
- **`commands/start.md`** — `--teammate` flag documented. Teammate path
  is a 5-step lane-execute walk distinct from the solo full pipeline.
- **`skills/shepherd/SKILL.md`** §I — three-tier meta table replaces the
  two-row planter/conductor table. §X invocation row updated for `--scope`.
  §XI see-also adds three new doctrine rows.
- **`skills/shepherd/flock.md`** §VI — three-tier meta table replaces
  two-row table; tier-separation cited.
- **`README.md`** — v5.1.6 section header, three-tier meta table, lane
  table updated with root-tier-exclusive notes on engineer/critic.
- **`CLAUDE.md`** — Shepherd plugin commands table updated with
  `/shepherd:start --teammate` and `--scope` flags. File-contracts section
  enumerates `agents/shepherd.md`.

#### Migration notes

- Operators running `/shepherd:start` in main chat see no behavior
  change — conductor profile remains the runner in SOLO mode. Tier
  separation does NOT apply solo. Backward-compatible with all v5.1.5
  and prior versions.
- Operators using `/shepherd:spawn` now have main chat adopt the
  `shepherd` root profile instead of `planter`. The planter profile is
  loaded only by `/shepherd:plant` or when seed authorship is delegated
  mid-spawn. Both profiles coexist (planter-loaded BEFORE spawn) — the
  shepherd is the outer frame, planter the inner.
- `--auto` is preserved as an alias for `--scope patch` to avoid breaking
  operator muscle memory. Deprecation in v5.2.0, removal in v6.0.0.
- The conductor model downgrade (`inherit` → `sonnet`) lowers cost for
  ALL conductor invocations, including `/shepherd:start` solo. Per
  operator request for cost discipline + Agent Teams behavioral consistency.

#### Known gaps (filed as GH issues)

- In-process teammates cannot dispatch the `Agent` tool (mirror of
  Claude Code #31977) — recommend `tmux` `teammateMode` for `/shepherd:spawn`
  until upstream lands.
- `--scope minor` and `--scope version` ship with sequential-only enforcement;
  cross-patch / cross-minor parallel walks deferred to v5.2.0.
- Peer-to-peer `SendMessage` between sibling teammates is permitted in tmux
  teammateMode; in-process support pending upstream.

---

## v5.1.5 — 2026-05-19

### Spawn flow optimization + flock normalization + token discipline

v5.1.5 is a surface-area optimization release. No new commands, no new agent
roles, no new doctrines. Four parallel lanes tightened the plugin's internal
consistency and token efficiency.

#### Lane A — spawn flow tightened

`commands/spawn.md` streamlined (1027 → 600 effective lines): cleaner dispatch
logic, new **Teammate tool feed** section documenting exactly what flows from
main chat to the teammate-conductor at spawn time. `spawn-escalation.md`
similarly trimmed (494 → 471). `commands/start.md` unchanged.

#### Lane B — conductor dispatch decision tree + specialist examples

`specialist-dispatch.md` expanded (152 → 530 lines) with a **DISPATCH DECISION
TREE** and four worked specialist examples. `conductor.md` reinforced with
three new anti-patterns (#28–30) strengthening flock-first defaults.
`Agent`, `ToolSearch`, and `SendMessage` added to the conductor tools list.

#### Lane C — flock agent normalization

All six flock agents (`engineer`, `critic`, `coder`, `auditor`, `worker`,
`discovery`) normalized to a cache-stable section order with a strive-higher
preamble, `## Adaptability`, and `## What I am NOT` sections. Model
assignments corrected: conductor remains `inherit`-only; flock restored to
original models (5× Sonnet 4.6, engineer Opus 1m).

#### Lane D — cache discipline + token conservation docs

`brief-cache-discipline.md` gained a **BRIEF ASSEMBLY CHECKLIST**.
`cache-telemetry.md` updated with per-role v5.1.5 hit-rate calibration.
`agent-excellence.md` added a sixth rule (token conservation).
`skills/shepherd/SKILL.md` gained a foundational **Token + cache discipline**
section.

### Changed

- `commands/spawn.md` — streamlined; new Teammate tool feed section
- `skills/shepherd/doctrines/spawn-escalation.md` — trimmed to essential content
- `skills/shepherd/doctrines/specialist-dispatch.md` — DISPATCH DECISION TREE + 4 worked examples
- `agents/conductor.md` — 3 new anti-patterns; Agent/ToolSearch/SendMessage in tool list
- `agents/{engineer,critic,coder,auditor,worker,discovery}.md` — normalized section order + model assignments
- `skills/shepherd/doctrines/brief-cache-discipline.md` — BRIEF ASSEMBLY CHECKLIST added
- `skills/shepherd/doctrines/cache-telemetry.md` — per-role v5.1.5 calibration
- `skills/shepherd/doctrines/agent-excellence.md` — sixth rule: token conservation
- `skills/shepherd/SKILL.md` — Token + cache discipline foundational section

---

## v5.1.4 — 2026-05-19

### Teammate-conductor + planter/conductor profile split

v5.1.4 introduces `/shepherd:spawn` for teammate-driven sprint execution and
extracts the orchestrator behavior into two canonical profile files at
`agents/conductor.md` (sprint-runner) and `agents/planter.md` (seed-author +
ambient babysitter). Main chat stays lean as the planter while a spawned
teammate runs the sprint as conductor. `/shepherd:autorun` and
`/shepherd:parallel` retire into `/shepherd:spawn --auto` and
`/shepherd:spawn --parallel <N>` respectively — consolidated command surface
is `{plant, start, spawn, ctx}`.

#### New

- **`agents/conductor.md`** (445 lines, cyan, inherit model) — canonical
  sprint-runner profile adopted by `/shepherd:start` whether main chat or a
  spawned teammate is the runner. Lifts ~620 lines of orchestrator behavior
  from `SKILL.md`, `pipeline.md`, `flock.md`, `autorun.md`, `parallel.md`.
  Strict side-effect boundary (Hard Prohibition #12: no git writes, no
  filesystem cleanup outside dispatch). Tools list trimmed to GitHub
  read-only.
- **`agents/planter.md`** (582 lines, violet, `opus[1m]`) — dual-mode
  profile (plant + spawn babysitter). Lifts ~280 lines from
  `skills/shepherd/planter.md` + `commands/plant.md`. Adds 6/6 net-new
  babysitter subsections: escalation triage, git custody, cleanup
  stewardship, concurrent-write discipline, hand-back timing, observation
  contract. Tools list includes GitHub write tools per side-effect
  ownership.
- **`commands/spawn.md`** (995 lines) — `/shepherd:spawn` command with
  `--parallel <N>` (fan out N sibling teammate-conductors with planter-side
  dev-order merge gate, cap N ≤ 4) and `--auto` (sequential autopilot,
  fresh teammate context window per sprint, planter handles inter-sprint
  cleanup + git + handoff). Platform compatibility note for GitHub issue
  #31977.
- **`skills/shepherd/doctrines/spawn-escalation.md`** (750 lines) —
  canonical teammate↔planter escalation contract: SendMessage primary
  channel, filesystem durable fallback at `~/.claude/tasks/{team}/`,
  `PostToolUse`-driven heartbeat row in shctx, wave-boundary commit
  discipline (≤ 1 wave loss horizon for in-process teammates with no
  `/resume`).

#### Retired

- `/shepherd:autorun` → use `/shepherd:spawn --auto`
- `/shepherd:parallel` → use `/shepherd:spawn --parallel <N>`
- `commands/{autorun,parallel}.md` collapsed to thin delta notes
- `skills/shepherd/{autorun,parallel,planter}.md` collapsed to thin
  redirects pointing at the canonical successors

#### Refactored (thin-loader pattern)

- `commands/start.md`: 99 → 52 lines. Loads `agents/conductor.md` as a
  system-prompt addendum; Step 0 bootstrap preserved (shepherd.toml,
  branch detect, doctrines, handoff, CLAUDE.md).
- `commands/plant.md`: 138 → 52 lines. Loads `agents/planter.md`; Opus
  model gate preserved.
- `skills/shepherd/SKILL.md`: dispatch-procedure block collapsed to a
  pointer at `agents/conductor.md` (mitigates the R3 triple-drift risk
  surfaced by the D-LIFT survey).
- `skills/shepherd/flock.md`: new §VI Meta tier section listing planter
  and conductor profiles.
- `skills/shepherd/pipeline.md`: §IX/§X autorun-walk + parallel-walk now
  correctly attribute loop/fanout control to the **planter** (the
  conductor doesn't loop itself under `--auto`).
- `CLAUDE.md`: flock count corrected to six domain agents + two meta
  orchestrators; commands table updated with spawn row + retirement
  notice; file contracts expanded with `agents/conductor.md` and
  `agents/planter.md` invariants.

#### Phase 0 discovery reports

- `2026-05-19-teammate-api-discovery.md` (D-API) — Agent Teams platform
  surface: `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=true`, in-process
  teammateMode, SendMessage mailbox, `TeammateIdle`/`TaskCreated`/
  `TaskCompleted` hooks. Hard limits documented.
- `2026-05-19-profile-lift-survey.md` (D-LIFT) — ~620 + ~280 lines of
  lift identified by file:line range; 6 babysitter gaps cataloged as
  net-new; 5 overlap questions adopted with operator resolutions.
- `2026-05-19-teammate-subagent-roadmap.md` (R-ROADMAP) — GitHub issue
  #31977 (open, labeled `bug`) is the load-bearing constraint;
  tmux-mode teammates already have Agent tool. Verdict YES-EVENTUAL /
  MEDIUM. Design is forward-compatible — no spawn-side redesign when
  the bug fixes.
- `2026-05-19-flock-teammate-efficacy.md` (R-FLOCK) — per-agent matrix.
  Top-3 leaf-teammate candidates: `@discovery` > `@worker` > `@engineer`.
  Pattern B (peer-to-peer flock teammates) NOT recommended for v5.1.4 (no
  role attestation; deps already file-mediated).

#### Known limitations

- **In-process `teammateMode` + GitHub #31977**: teammate sessions in
  in-process mode do not expose the `Agent` tool, so a spawned teammate
  cannot dispatch the flock the way main chat can. **Workaround**: use
  tmux `teammateMode` for full functionality, or stay on `/shepherd:start`
  in main chat until the bug lands. See `commands/spawn.md
  §Platform compatibility` for the full table.

---

## v5.1.3 — 2026-05-19

### Cleanup, cache discipline, dispatch telemetry

v5.1.3 fixes the base. No new conductor capabilities, no new agent roles, no
semantic changes to the dispatch pipeline. The sprint is a focused sweep:
smaller, more stable agent prefixes; brief ordering that puts variable
content last so prompt caching can do its job; SubagentStop telemetry that
proves the wins are real; and a sweep of accumulated cruft.

#### Agent restructure (Lanes A1 + A2)

- **Five-agent prefix/reference split** — `agents/{engineer,coder,critic,worker,discovery}.md`
  trimmed to the cacheable prefix (frontmatter, identity, prohibitions,
  halt codes, mandatory protocol, report shape, "What you are NOT"); verbose
  reference catalogs extracted to `skills/shepherd/agents/<role>.reference.md`
  loaded on demand via Skill at agent startup.
- **`agents/auditor.md` trim** — same restructure; reference content extracted
  to `skills/shepherd/agents/auditor.reference.md`.
- **Inline `Greatness is the bar` preamble removed** — replaced with a single
  `> See doctrines/agent-excellence.md.` line per agent (doctrine already
  existed; the inline duplication just bloated every dispatch).
- **`tools:` frontmatter audit** — each agent's MCP tool list now contains
  only tools actually invoked by its documented protocol.

#### Brief assembly discipline (Lane B)

- **New doctrine `doctrines/brief-cache-discipline.md`** — stable framing first
  (`[ROLE]` → `[SKILLS]` → `[DOCTRINES]` → `[PROTOCOL-REMINDERS]`), variable
  content last (`[FILE-SCOPE]` → `[CONTEXT-INVENTORY]` → `[DO-NOT-DUPLICATE]` →
  `[ACCEPTANCE]` → `[NON-GOALS]` → `[WORKTREE]` → `[BASE-COMMIT-EXPECTED]`).
  Enforcement is post-hoc via the completeness auditor.
- **`pipeline.md` §V** gains a "Cache-first brief ordering" subsection citing
  the new doctrine.

#### Dispatch telemetry (Lane C)

- **New hook `hooks/scripts/subagent_telemetry.sh`** — captures cache stats
  per subagent dispatch (`cache_read_input_tokens`,
  `cache_creation_input_tokens`, `ephemeral_5m_input_tokens`,
  `ephemeral_1h_input_tokens`, `hit_rate`). Non-blocking on any failure;
  emits `parse_error` rows rather than silently no-op.
- **Registry schema migration 0006** — new `index_cache_usage` table and
  `v_cache_usage` view aggregating per sprint + role.
- **New `shctx query cache-usage`** — surfaces hit-rate per sprint + role.
- **`shctx refresh --scope=telemetry`** — ingests JSONL events into the
  registry idempotently.
- **New doctrine `doctrines/cache-telemetry.md`** — what's captured, where it
  lands, how it surfaces in close reports, threshold guidance (exploratory
  baseline for the first 2–3 sprints; < 40% aggregate hit-rate is a MEDIUM
  finding flag once baselines settle).

#### Cleanup (Lane D)

- Dead command-script sweep (no scripts removed; all `cmd_*.sh` reachable
  through the `shctx` dispatcher's dynamic dispatch or via internal stage
  composition in `cmd_sprint.sh`).
- Stale-reference audit across `skills/shepherd/doctrines/` and
  `skills/shepherd/{pipeline,planter,SKILL}.md` — all `v4.x` / `v5.0.x`
  references are legitimate historical-origin annotations; no operative
  references to removed mechanisms were found.
- `_candidates/` directory contains only its README (the promotion-pipeline
  doc); no orphan candidates to promote or delete.
- Gitignored-but-tracked sweep: zero hits.
- Version-source-of-truth files verified at 5.1.3 across `plugin.json`,
  `marketplace.json`, both SKILL frontmatters, README, and this changelog.

#### Version-scale roadmap doctrine (Lane E)

- **New doctrine `doctrines/version-scale-roadmap.md`** — codifies the
  four-tier scale factor: major `vX` (~1000 sprints, vision), minor `vX.Y`
  (~100 sprints, roadmap), patch `vX.Y.Z` (≤ 10 sprints, the planning unit),
  dev `vX.Y.Z-dev.N` (1 sprint, the execution branch — cut from the patch
  branch as a cushion). Extends `sprint-as-patch.md` upward by naming the
  three levels above the dev sprint.
- **`planter.md` §0** updated to anchor seed authorship at PATCH scope
  (seeds do not carry dev.N suffix).
- **`agents/engineer.md`** updated to cite the doctrine and clarify the
  engineer operates at DEV scope (decomposing the patch seed).

---

## v5.1.2 — 2026-05-17

### Hook teeth, anti-laziness preambles, dir-watch, specialist dispatch, slug naming, discovery registry

The v5.1.1 release landed the new doctrines + agent contracts; v5.1.2 lands
the matching hook teeth, registries, and consistency sweeps. Doctrines from
v5.1.1 now have machine-enforced guardrails instead of being agent-prompt
discipline alone.

#### Hook hardening

- **New `hooks/scripts/_lib.sh`** — shared library every hook sources.
  Exports `is_shepherd_project`, `resolve_namespace`, `json_field`,
  `json_response`, `emit_context`, `emit_deny`, `pass_silent`, `log_event`,
  `current_role`, `current_sprint`, `sprint_root`, `in_subworktree`.
  jq-preferred with python3 fallback. Every emit goes through `log_event`,
  which appends a JSONL entry to `<ns>/logs/hooks/YYYY-MM-DD.jsonl`.
- **New `hooks/scripts/agent_invocation_tagger.sh`** — `PreToolUse(Agent|Task)`
  parses the agent body's `# @<role>` header and writes
  `<ns>/dispatch/<sprint>/<tool_use_id>.json` so downstream hooks can make
  role-conditional decisions without re-parsing prompts.
- **New `hooks/scripts/discovery_capture.sh`** — `PostToolUse(Agent|Task)`
  indexes `## DISCOVERY REPORT` blocks to `<ns>/discoveries/<sprint>/<id>.json`
  for cross-sprint reuse.
- **New `hooks/scripts/dedup_write_guard.sh`** — `PreToolUse(Write|Edit)`
  scans @coder-emitted content for new public symbol declarations
  (rust / python / ts/js / go) and BLOCKS if the symbol already exists
  elsewhere in the workspace. The hook layer's expression of
  zero-duplicate-tolerance — the conductor's pre-dispatch DEDUP-GATE
  remains the primary check; this catches what slips through.
- **`bash_guard.sh` extensions** — adds three role-conditional BLOCK checks
  on top of the v5.1.0 commit-on-lane block: auditor invoking gates from a
  sub-worktree (false-CRITICAL prevention), @discovery invoking
  state-modifying Bash (read-only enforcement), parallel cargo invocations
  WARN, cd-into-worktree WARN.
- **`lock_guard.sh` extensions** — role-based write-path enforcement:
  @discovery may only Write to `{paths.reports}/<date>-discovery-*.md`;
  @auditor may only Write to `{paths.reports}/<date>-(intro-)audit-*.md`;
  @coder Write must land inside the recorded `[WORKTREE].Path` from
  `agent_invocation_tagger`'s dispatch record. Sprint-lock conflict still
  WARN-only (does not block).
- **`agent_pause_detector.sh` extension** — beyond writing the structured
  pause record to `<ns>/pauses/<id>.json`, the hook now ALSO auto-drafts a
  near-complete dispatch brief stub at `<ns>/pauses/<id>.brief.md` per
  the satellite role (coder / discovery / worker / auditor). The conductor
  reads a ready-to-fire brief instead of composing one from scratch.
- **`session_open.sh` extension** — fourth check: when HEAD matches the
  sprint branch pattern, verify the corresponding `plan.md` exists (slug
  OR legacy dotted form). Surfaces missing-plan as a warning so engineer
  dispatch isn't silently skipped.
- **`bash_post.sh` extension** — cwd-drift detection post-Bash; surfaces
  when the conductor's cwd has migrated into a sub-worktree.

#### Anti-laziness — `agent-excellence` doctrine + strive-higher preambles

- **New doctrine** `skills/shepherd/doctrines/agent-excellence.md` — every
  agent must aim higher than "ship code that compiles". Refuse lazy
  duplication, honor language idioms, halt rather than ship sub-standard
  work. Pairs with `dedup_write_guard.sh` (the hook teeth) and the
  zero-duplicate-tolerance doctrine.
- **Strive-higher preamble** prepended to all six `agents/*.md` so every
  flock-agent loads the excellence contract before the role-specific
  instructions.

#### Slug naming convention

- **New doctrine** `skills/shepherd/doctrines/seed-naming.md` — branches
  keep dots (`v5.1.2-dev.3`); filenames collapse them (`v512-dev3.seed.md`).
  Origin: operator caught the planter producing `v0.3.2-dev.5.seed.md`
  (dotted form bleeding from `{sprint_branch}`) when the convention had
  been the slug.
- **`shepherd.toml` schema extension** — `[branching].patch_slug_pattern`
  and `sprint_slug_pattern` added. If absent, framework falls back to
  branch pattern with a deprecation warning.
- **Templates + briefs migrated** to use `{sprint_slug}` / `{patch_slug}`
  for filename construction in `skills/shepherd/references/seed-template.md`,
  `skills/shepherd/references/agent-briefs.md`, `skills/shepherd/SKILL.md`,
  `skills/shepherd/pipeline.md`, `skills/shepherd/doctrines/preflight-doctor.md`,
  `skills/shepherd/doctrines/mid-flight-operator-amendment.md`,
  `skills/shepherd/doctrines/gates-restoration.md`, `commands/plant.md`,
  `commands/parallel.md`, `agents/engineer.md`.
  Branch placeholders preserved where the value is the literal branch
  (git commands, dispatch dir key, milestone target, etc.).
- **Examples in `examples/{axiom,minimal}/shepherd.toml`** include the new
  slug pattern keys.
- **`docs/configuration.md` §[branching]`** documents both pattern pairs.

#### Dir-watch — content-hash gating

- **New migration** `skills/context/schema/migrations/0005_watch_paths.sql` —
  registers watched directories and their last-seen content hash.
- **New `skills/context/scripts/cmd_watch.sh`** — `shctx watch
  add/mark/status/list/remove` over the watch_paths table.
- **New doctrine** `skills/shepherd/doctrines/dir-watch.md` — semantics,
  hashing strategy, integration points (engineer mesh, conductor pre-MESH
  fast-path).

#### Specialist dispatch

- **New doctrine** `skills/shepherd/doctrines/specialist-dispatch.md` —
  framework is "closed at six + specialist exceptions". The flock proper
  remains six; a specialist agent (security-reviewer, perf-analyzer, etc.)
  may be dispatched in addition when the seed names one explicitly.
- **`skills/shepherd/SKILL.md`** + **`skills/shepherd/flock.md`** language
  updated from "closed flock" to "closed at six + specialist exceptions".

#### Discovery registry CLI

- **New `skills/context/scripts/cmd_discovery.sh`** — `shctx discovery
  list/show/search/clear` over the `<ns>/discoveries/<sprint>/<id>.json`
  files captured by `discovery_capture.sh`. Engineer pulls cross-sprint
  discoveries at MESH without re-parsing report markdown.
- **`shctx` dispatcher** routes `discovery` and `watch` subcommands to
  their new handlers.

#### Plugin description trim

The verbose multi-version description in `.claude-plugin/plugin.json` and
`.claude-plugin/marketplace.json` collapsed to a single capability
statement. Per-version detail lives here in CHANGELOG.md.

#### Deferred to v5.1.3

- **Lane B — CLI subcommand reorg** (`shctx workspace/brief/lane/discovery/
  watch/pauses` groups). Scope comparable to all six landed lanes
  combined; better as an isolated refactor.
- **`cmd_doctor.sh` extension** for v5.1.1+ surfaces (`<ns>/discoveries/`,
  `<ns>/dispatch/`, `<ns>/logs/hooks/` writability, intro-wave plan-node
  presence detection). The doctor exists at v5.0.4 baseline; v5.1.1
  surfaces uncovered.
- **`agent_insight_capture.sh` refactor to `_lib.sh`** — v5.0.9 logic still
  functions; refactor risk not worth the cleanup this patch.

---

## v5.1.1 — 2026-05-15

### Discovery agent + INTRO-COMBO-WAVE + hypothesis-driven auditor + sprint-as-patch

Per operator request: introduce `@discovery` (read-only orientation, no
terminal-mutating Bash, sole task is to comprehend) so the conductor and
engineer don't burn context on exploratory reads. Pair with an intro-mode
parallel wave at sprint open. Tighten auditor methodology via
`superpowers:systematic-debugging`. Reframe sprint scope as patch-equivalent
("every dev.N sprint IS a patch in scope").

- **New agent** `agents/discovery.md` — sixth lane in the flock. Sonnet, `thinking: high`, color blue. Tools: Read/Grep/Glob/NotebookRead/LSP, read-only Bash, MCP read-only, Web*, Skill, ToolSearch, TaskCreate/Get/List/Update, and Write restricted to `{paths.reports}/<date>-discovery-<id>.md`. NEVER: Edit, MCP write, Agent dispatch. Five canonical use-case patterns: PRE-MESH-DISCOVERY, PRE-HOTFIX-DISCOVERY, ARCHITECTURE-DISCOVERY, DOCTRINE-RECONCILIATION-DISCOVERY, MCP-STATE-DISCOVERY.
- **New doctrine** `skills/shepherd/doctrines/discovery-readonly.md` — `@discovery` contract, role boundaries vs `@worker` / `@auditor` / `@critic`, max-concurrent rules, report shape, cross-sprint reuse via `<ns>/discoveries/<sprint>/<id>.json`.
- **New doctrine** `skills/shepherd/doctrines/intro-combo-wave.md` — INTRO-COMBO-WAVE between SEED-VERIFY and MESH. Default composition: 3 discoveries (prior-close-audit-summary, canonical-types-freshness, gh-state-inventory) + 2 intro-mode auditors (regression, carry-forward-disposition). All read-only, all in one Agent batch. Engineer reads outputs as `[DISCOVERY-CONTEXT]` + `[INTRO-AUDIT-CONTEXT]` in its MESH brief.
- **New doctrine** `skills/shepherd/doctrines/auditor-hypothesis-driven.md` — every finding now carries Hypothesis + Falsification attempt + Confidence. LOW-confidence findings land under `## Open questions`, not as GH issues. Bayesian finding-class weighting from sprint-patterns registry. Auditor loads `superpowers:systematic-debugging` as Step 1.
- **`agents/auditor.md` rewrite** — Step 1 loads `superpowers:systematic-debugging`. Three modes: `close` (grades), `regression` (intro mode, no grade), `carry-forward-disposition` (intro mode, no grade). Per-finding contract requires the hypothesis triple. Per-concern emphasis sections now lead with a hypothesis-first prompt. New `## Verifications` section for disproved hypotheses.
- **New doctrine** `skills/shepherd/doctrines/sprint-as-patch.md` — every `dev.N` sprint is operator-equivalent to a full patch. Planter sizes seeds at patch-grade; engineer authors plans at patch-grade body depth; critic rejects under-scoped seeds; auditor grades against patch-grade output expectation. T-shirt lane minimums revised: M → 4, L → 6, XL → 6/wave.
- **`skills/shepherd/planter.md` §0** — sprint-as-patch sizing made binding for planter seed authorship.
- **New doctrine** `skills/shepherd/doctrines/hook-event-log.md` — `<ns>/logs/hooks/YYYY-MM-DD.jsonl` schema, jq queries, retention guidance, anti-patterns (no live tailing, no secret logging).
- **New doctrine** `skills/shepherd/doctrines/preflight-doctor.md` — `shctx doctor` preflight semantics, exit-code matrix, integration with `/shepherd:start`.
- **`skills/shepherd/SKILL.md`** — six-agent flock table, INTRO-COMBO-WAVE in §1 INTRO checklist, sprint-as-patch impactfulness contract made binding, six new doctrines indexed in §XI file map, six new anti-patterns (#23–#28).
- **`skills/shepherd/flock.md`** — new `## @discovery` section between `@critic` and `@worker`. Six-agent flock language throughout.
- **`skills/shepherd/pipeline.md`** — `DISCOVERY` and `INTRO-COMBO-WAVE` node types added to §II stage taxonomy. New edge predicates: `on-research-complete`, `on-intro-wave-complete`, `on-intro-audit-complete`.
- **`skills/shepherd/references/agent-briefs.md`** — six discovery brief templates (D-A through D-F) + intro-mode auditor templates + INTRO-COMBO-WAVE single-message dispatch pattern.

#### Hook hardening + preflight (initial scope; full hook overhaul deferred to v5.1.1)

The v5.1.0 release lands the new doctrines + agent contracts; the matching
hook teeth + `shctx doctor` ship in v5.1.1. Doctrines/agent contracts are
the load-bearing change; hooks are the guardrail. Operator can adopt v5.1.0
with hooks left at v5.1.0-baseline; v5.1.1 will add:

- `hooks/scripts/_lib.sh` shared library (jq/python fallback, log_event)
- `hooks/scripts/agent_invocation_tagger.sh` (PreToolUse on Agent|Task)
- `hooks/scripts/discovery_capture.sh` (PostToolUse on Agent|Task)
- `bash_guard.sh` extension (auditor cwd guard + discovery state-modify block)
- `lock_guard.sh` extension (role-based write-path enforcement)
- `agent_pause_detector.sh` extension (auto-draft satellite brief stub)
- `skills/context/scripts/cmd_doctor.sh` (`shctx doctor` preflight)
- `<ns>/logs/hooks/YYYY-MM-DD.jsonl` event log activation

Doctrines/agent contracts are the load-bearing change; hooks are the
guardrail. Operator can adopt v5.1.1 with hooks left at the v5.1.0 baseline.

---

## v5.1.0 — released

### Flock cohesion — shared substrate across agents

Per operator observation: "every agent feels isolated rather than acting as part of a larger group so the agents feel like they need to re-invent everything every time from scratch." This release names the structural gap and lands the substrate.

- **New doctrine** `skills/shepherd/doctrines/flock-cohesion.md` — verbalizes the shared-substrate model. Four channels: canonical-types (static "what exists where"), graph state + trace (mechanical "who is doing what now"), pauses (synchronous "I need this"), and insights (asynchronous "I noticed this"). All four are read at MESH; written at DISPATCH and REPORT.
- **`[SIBLING-LANES]` brief block** (`skills/shepherd/references/agent-briefs.md`) — every wave dispatch brief now lists the other lanes in the wave with their `[FILE-SCOPE]` summaries and the symbols/artifacts they produce. The single most-requested affordance: agents finally see what their siblings are doing. Validity checklist updated.
- **`## INSIGHTS` report section** (`agents/coder.md`, `agents/worker.md`) — optional cross-lane observations any agent can append to their final report. Canonical kinds: `relocation`, `extension`, `duplication`, `consolidation`, `gap`, `nit`. Replaces the absent "I saw something interesting" channel.
- **New hook** `hooks/scripts/agent_insight_capture.sh` — `PostToolUse(Agent|Task)` parses `## INSIGHTS` blocks, writes one JSON record per entry to `<ns>/insights/<sprint>/<id>.json`. Silent when no INSIGHTS block is present.
- **New: `shctx insights <list|show|export|clear>`** (`skills/context/scripts/cmd_insights.sh`) — registry CLI. `export --md` renders as markdown for engineer mesh row 13 consumption.
- **`agents/engineer.md` Phase 0 mesh row 13** — engineer reads the prior sprint's insights at next-sprint mesh; decides per-kind how to action (relocation → consider scoping a lane; nit → aggregate before acting; etc.). Insights NOT actioned are surfaced under "Cross-lane insights not scoped this sprint" — operator visibility is the rule.

### Dispatch cascade — Stage Graph as rule engine

Per operator request: "create some type of rule engine layer that would allow the conductor to dispatch all agents using conditional links so agents cascade through the plan." The plan is now extractable into a machine-readable topology that `shctx graph` walks deterministically — the conductor's only LLM-driven step per tick is brief authoring + edge-label selection; routing is mechanical.

- **New doctrine** `skills/shepherd/doctrines/dispatch-cascade.md` — the plan IS the program; the conductor IS the interpreter; the Stage Graph IS the topology.
- **New: `shctx plan <extract|topology|validate>`** (`skills/context/scripts/cmd_plan.sh`) — parse plan.md's `## Stage Graph` YAML block, materialize `<ns>/graph/state.json`, pretty-print topology, run structural validation (acyclic, predicates resolve, parallel_with mutual).
- **New: `shctx graph <status|next|mark|trace|reset>`** (`skills/context/scripts/cmd_graph.sh`) — the walker. `next` returns the next-eligible batch honoring `parallel_with` cliques. `mark <id> --state=done --exit=<edge>` advances state and auto-promotes downstream nodes when their in_predicates are satisfied. `trace` is append-only at `<ns>/graph/trace.jsonl`.
- **New: `shctx pauses <list|show|resolve|clear>`** (`skills/context/scripts/cmd_pauses.sh`) — the PAUSE-FOR-DEPENDENCY registry. Hook captures pauses; conductor reads structured records via `show`; `resolve --satellite-sha=<sha>` marks completion.
- **New hook** `hooks/scripts/agent_pause_detector.sh` — `PostToolUse(Agent|Task)` parses agent output for `Halt code: PAUSE-FOR-DEPENDENCY`, extracts the structured satellite request, writes `<ns>/pauses/<id>.json`, and surfaces an `additionalContext` alert. Eliminates the LLM re-parsing step.
- **`adaptation-loop.md §V-bis`** — node-level telemetry from `trace.jsonl` (duration, exit-edge frequency, halt rate per node-type) feeds the sprint-pattern registry with finer-grained signal than sprint-level summaries.
- **`pipeline.md §V`** — walk algorithm now references the `shctx graph` runtime mechanization.

### Field feedback from v5.0.8 / axiom v0.3.2-dev.0

**§1 — `PAUSE-FOR-DEPENDENCY` primitive (most requested).** First-class Stage Graph escape hatch for mid-lane out-of-scope dependencies. Coder emits a structured halt → conductor dispatches an XS/S satellite `@coder` → `SendMessage` resumes the paused lane. Cap: 2 satellites/lane. Cherry-pick order invariant: satellite commit lands before resumed-lane commit.
- New: `skills/shepherd/doctrines/pause-for-dependency.md`
- `agents/coder.md` — `PAUSE-FOR-DEPENDENCY` halt code, trigger protocol, report shape
- `skills/shepherd/pipeline.md` — `PAUSE-FOR-DEPENDENCY` + `RESUME-LANE` stage taxonomy; `on-pause-dep` edge predicate; `§XV-quint` subgraph walkthrough

**§2 — Coder lane file-scope cap.** `agents/engineer.md` — soft cap of ≤3 files per lane MAY-MODIFY; single-file exception at >300 LOC.

**§3 — Parallel cherry-pick conflict documentation.** `skills/shepherd/references/branching-model.md §VII-bis` — file overlap between parallel lane branches is expected; how to resolve; STAGE-GRAPH-VIOLATION vs legitimate conflict.

**§4 — Conductor anchor drift hygiene.**
- New: `hooks/scripts/bash_post.sh` — `PostToolUse(Bash)` detects cwd drift into sub-worktrees
- `hooks/hooks.json` — wires the new PostToolUse hook
- `hooks/scripts/session_open.sh` — adds sprint-patterns.md absence warning
- `hooks/scripts/bash_guard.sh` — adds `cd`-into-worktree warning + corrected cargo-parallel regex (no longer false-positives on `cargo check && cargo test`)

**§5 — Cargo sequential gates doctrine.**
- New: `skills/shepherd/doctrines/cargo-sequential-gates.md`
- `skills/shepherd/pipeline.md §XV-sext` — referenced at WAVE-GATE
- `skills/shepherd/SKILL.md §2 BODY` — cross-referenced from gate sequence
- `hooks/scripts/bash_guard.sh` — Check 2: warn on backgrounded cargo invocations (`&` not `&&`)

**§6/§7 — /reload-plugins escape hatch + MCP preference.**
- New: `skills/shepherd/doctrines/plugin-reload-escape.md`
- `skills/shepherd/pipeline.md §XV-sept` — Phase 0 MCP availability + reload note

**§8 — Programmatic GH issue triage (`shctx issues classify`).** Replaces the per-sprint LLM enumeration pass with deterministic label/milestone/severity bucketing from the cached `index_issues` table.
- New: `skills/context/scripts/cmd_issues.sh` — subcommands `classify` and `list`; buckets `blocking-this-sprint`, `labeled-non-issue`, `tracking-future`, `drift-risk`, `unclassified`; `--unclassified-only` for focused LLM review
- `skills/context/scripts/shctx` — registers `issues` subcommand under the `<noun> <verb>` convention
- `agents/engineer.md` Phase 0 mesh row 1 — preferred path is `shctx issues classify`; MCP/gh enumeration is the fallback when cache is stale

**§9 — Sprint-patterns registry verification.**
- `hooks/scripts/session_open.sh` — surfaces `sprint-patterns.md` absence at session start
- `skills/shepherd/SKILL.md §1` — existence check added to INTRODUCTION checklist
- `skills/shepherd/doctrines/adaptation-loop.md` — on-first-close creation protocol

**§10 — Feedback classification.** `skills/shepherd/doctrines/adaptation-loop.md §VI-bis` — framework-generic vs project-specific feedback rule; framework-generic candidates are flagged in close reports for doctrine promotion.

### Fix: prevent dual-namespace split-brain between `.shepherd/` and `.artifacts/`

The root cause: `shctx init` (no flags) defaulted to `.shepherd/` on a fresh project while example `shepherd.toml` files had `[paths]` entries referencing `.artifacts/`. The conductor's Write calls then created `.artifacts/` as a directory side effect, leaving both namespaces present. `shctx_artifacts_root()` always preferred `.shepherd/` while the conductor kept reading `.artifacts/*` — split-brain until the operator migrated by hand.

- `scaffold.sh` — guard refuses to scaffold namespace X when namespace Y already carries the shctx `.gitignore` marker and X does not yet exist. Emits a clear error with remediation steps.
- `_lib.sh` — `shctx_artifacts_root()` now emits a stderr warning when both directories coexist; suppressed via `SHCTX_QUIET=1` in callers that handle this themselves.
- `cmd_doctor.sh` — reports the dual-namespace state as a `WARN` check with a fix instruction.
- `examples/minimal/shepherd.toml` — `[paths]` updated from `.artifacts/` to `.shepherd/` (the v5.0.0+ default); comment added explaining the namespace coupling.
- `examples/axiom/shepherd.toml` — comment added explaining `.artifacts/` is the legacy namespace for that project.
- `skills/context/SKILL.md`, `skills/shepherd/SKILL.md` — hardcoded `.artifacts/` references replaced with namespace-neutral `<namespace>/`.

---

## v5.0.7 — 2026-05-12

**Hotfix: hooks schema.** `hooks/hooks.json` was missing the top-level `"hooks"` wrapper key, causing plugin load failure (`expected record, received undefined`). All event handlers now correctly nested under `{"hooks": {...}}`. Version refs bumped across all five sources of truth.

---

## v5.0.6 — 2026-05-12

**Single-plugin-repo migration + conductor anchor discipline.** Two
independent threads:

1. **Repo isolation.** The plugin tree moved out of `plugins/shepherd/`
   to the repo root in earlier commits; this release finishes the
   migration so manifests, docs, the `shctx release` pipeline, and the
   test suite all agree the repo IS the plugin.
2. **Conductor anchor discipline.** Field feedback flagged a failure
   mode beyond the v5.0.3 cwd ban: the conductor's `git switch <agent-branch>`
   (for "inspection") and `git worktree add` from inside an existing
   worktree silently produced **worktrees-within-worktrees** state.
   v5.0.6 codifies the broader anchor invariant.

### Changed — doctrines

- **`doctrines/conductor-cwd.md` extended to anchor discipline.** Title
  + scope broadened from "conductor cwd" to "conductor anchor (cwd +
  HEAD + worktree context)". Three explicit bans with the correct
  alternative for each:
  - Ban 1 — `cd`/`pushd` into a worktree (the v5.0.3 cwd rule, preserved).
  - Ban 2 — `git switch` / `git checkout` to an `agent-*` lane branch.
    The conductor's HEAD MUST remain `{sprint_branch}` (or `{patch_branch}`/
    `{main_branch}` during release plumbing). Inspect agent branches via
    `git -C <worktree-path>` only.
  - Ban 3 — `git worktree add` from inside a worktree. Always run from
    the sprint root, or use `shctx worktree create-batch` which assumes it.
  Mandatory three-check verification (`pwd` / `git rev-parse --abbrev-ref
  HEAD` / `git rev-parse --git-dir == --git-common-dir`) added to the
  doctrine and wired into the §1 INTRO conductor checklist.

### Added — anti-pattern

- **SKILL.md anti-pattern #22** — `Conductor git switch/git checkout to an
  agent-* lane branch → HEAD drift → wrong-base worktrees → nesting`.
  Cross-references `doctrines/conductor-cwd.md` Ban 2 + Ban 3.

### Changed — anti-pattern

- **SKILL.md anti-pattern #15** sharpened to specify the drift mode (cwd)
  and link to `doctrines/conductor-cwd.md` Ban 1 — distinguishing it from
  the new HEAD-drift case in #22.

### Changed — repo isolation (single-plugin-repo migration finish)

- `.claude-plugin/marketplace.json` — drop the `fl03-skills` entry;
  shepherd `source` is now `.`; homepage URLs point at the repo root.
- `.claude-plugin/plugin.json` — homepage URL fixed; the `.shepherd/root.db`
  description typo corrected to `.artifacts/root.db`.
- `CLAUDE.md` rewritten for the root-level layout (the repo *is* the
  plugin; no more `plugins/shepherd/` prefix).
- `README.md` install section now leads with `/plugin marketplace add
  fl03/shepherd` and symlinks the repo root, not the old subpath.
- `CHANGELOG.md` no longer claims to cover `fl03-skills` (which now lives
  in its own repo).
- `examples/axiom/CLAUDE-snippet.md` — plugin URL + version pin fixed.
- `skills/shepherd/flock.md` — rephrased the `code-style` reference now
  that `fl03-skills/skills/code-style/` lives outside this repo.
- `skills/context/SKILL.md`, `skills/context/schema/0001_init.sql` —
  doctrine + schema header comments updated to the new layout.
- `skills/context/scripts/cmd_release.sh` — `VERSION_FILES` and
  `CHANGELOG_PATH` rebuilt against the root-level manifest set.
- `skills/context/scripts/cmd_doctor.sh` — config-doc pointer updated.
- `skills/context/tests/test_release.sh` — fixtures match the new bump
  targets.

### Added — adaptation loop (self-improvement)

- **`doctrines/adaptation-loop.md`** (new) — sprint pattern registry (`{paths.ctx}/sprint-patterns.md`): append-only, per-sprint. Write protocol: completeness auditor at CLOSE-SWARM. Read protocol: `@engineer` mesh row 10, `@planter` seed context. Conductor fires `[TREND]` alert at PAUSE when 3+ same-concern CRITICAL/HIGH across 3 consecutive sprints.
- **`agents/engineer.md`** — mesh row 10 (sprint-pattern registry), four action triggers (systemic risks / chronic carry-forwards / recurring halts / clean-streak concerns), plan-quality bar item, ENGINEER REPORT field.
- **`agents/engineer.md`** — mesh row 11 (prior close-audit reports self-learning hook): reads `{paths.reports}/*-audit-*.md`, surfaces `HF-this-sprint=no, carry=yes` findings into the carry-forward checklist; recurring deferred findings flagged `[CHRONIC-CANDIDATE]`.
- **`agents/critic.md`** — §6 sprint-pattern awareness, Pattern Echoes output section, clarified PROCEED WITH CHANGES vs RECONSIDER boundary.
- **`agents/auditor.md`** — completeness concern writes sprint-pattern journal entry (5-step); `## Pattern delta` report section.
- **`agents/worker.md`** — Pattern 5: sprint pattern registry backfill brief template.
- **`skills/shepherd/planter.md`** — mesh row 12 names `sprint-patterns.md`; §VI.A sprint-pattern seed-action table.

### Added — operator communication + session continuity

- **`skills/shepherd/SKILL.md` §VIII** — Operator communication norms: mandatory surface moments, status line format `[NODE] {node-id} → {outcome} | {one-sentence key finding}`, no-silent-proceeding rule, no walls-of-text rule.
- **`skills/shepherd/SKILL.md` §IX** — Session continuity: 5-step mid-sprint recovery protocol (locate plan → read walk trace → survey git log → check orphan worktrees → reconstruct walk position).

### Changed — language-agnostic gates

- `skills/shepherd/SKILL.md` §III and `skills/shepherd/flock.md` — gate sequence now uses `{gates.format}`, `{gates.check}`, `{gates.lint}` from `shepherd.toml [gates]` instead of hardcoded `cargo` commands. Language-skill auto-fix note added.
- `skills/shepherd/flock.md` — anti-pattern #17: missing sprint-pattern registry read at mesh time.

### Added — doctrines (axiom dev.8a field feedback)

- **`doctrines/work-bound-to-tracking.md`** (new) — every intentional gap in production code cites a GH issue number via a language-native stub primitive (`todo!("see #N")` / `throw new Error("TODO see #N")` / `raise NotImplementedError("see #N")` / `panic("TODO see #N")`). Enforcement: `@engineer` counts stubs at mesh, `@coder` must pair stub with GH issue, `@auditor` greps for naked TODO/FIXME/XXX/HACK.
- **`doctrines/mid-flight-operator-amendment.md`** (new) — four amendment types (clarification, feature addition, production regression, architectural decision) with defined conductor responses; dispatcher-patch ledger at `{paths.ctx}/dispatcher-patches/{sprint_branch}-pc-{N}.md`; HARD-STOP triggers (secret rotation, north-star change, security rollback).
- **`doctrines/_candidates/README.md`** (new) — promotion pipeline from project-specific memory to framework-intrinsic doctrine; candidate template with frontmatter; promotion checklist.
- **`doctrines/worktree-base-drift.md`** — `§Canonical no-isolation workaround (v5.0.6)`: when `isolation:"worktree"` defaults to `main`, drop isolation entirely; rely on file-disjoint `[FILE-SCOPE]`; coders commit directly to sprint branch. Documents what you lose (cherry-pick barrier, worktree-confinement enforcement) and mitigations (disjoint plan + post-wave `git diff --stat`).
- **`doctrines/conductor-cwd.md`** — `§HEAD advancement in no-isolation mode`: HEAD advancing as coders commit to the sprint branch is NOT a doctrine violation; the invariant is "HEAD stays on `{sprint_branch}`", not "HEAD stays pinned to dispatch-time SHA".

### Added — pipeline stages + dispatch patterns

- **`skills/shepherd/pipeline.md`** — `HOTFIX-DYNAMIC` stage type: variable-cardinality `@coder` batch derived from gate-error cluster analysis at walk-time (vs. pre-declared HOTFIX). Stage Graph YAML example included.
- **`skills/shepherd/pipeline.md` §XIII-bis** — Structured gate output + parallel HF dispatch: `--message-format=json --keep-going` collects full error surface; errors parsed and clustered by file-disjoint scope; one `@coder` per cluster dispatched in a single batch. Gate JSON artifacts stored in `.shepherd/runs/`.

### Added — standard worker dispatch templates

- **`skills/shepherd/references/agent-briefs.md`** — W-A/B/D/E standard worker brief templates:
  - **W-A** — test-surface audit (classify all tests into 4 buckets; 10 min, 30 calls)
  - **W-B** — Phase 0 mesh validation (GH issues + Sentry + deploy status; 15 min, 20 calls)
  - **W-D** — bulk GH issue triage + close script generation (20 min, 60 calls)
  - **W-E** — production diagnostic for regression amendments (15 min, 40 calls)

### Added — plugin hooks

- **`hooks/hooks.json`** (new) — plugin-shipped hooks activating automatically on install; three guards:
  - `SessionStart` → `session_open.sh`: verifies conductor HEAD is not on `agent-*`/`lane-*` branch and cwd is the primary worktree; warns on orphan sub-worktrees.
  - `PreToolUse(Bash)` → `bash_guard.sh`: blocks `git commit` when HEAD is on an agent/lane branch (`permissionDecision: deny`).
  - `PreToolUse(Write|Edit)` → `lock_guard.sh`: warns when `.artifacts/shepherd.lock` or `.shepherd/shepherd.lock` is held by a different session ID.

### Notes for upgraders

- The doctrine extension is **behavioral**, not schema-level — no
  migrations, no config changes, no breaking interface for consumer
  `shepherd.toml` files. Conductors that already honored `conductor-cwd.md`
  inherit Ban 2 + Ban 3 as the same intent, now explicit.
- Subagents (coders, auditors, workers) **may continue to freely inhabit
  worktrees**. The doctrine binds the conductor's session only; this is
  called out explicitly in the "When the rule does not apply" section.
- The session-open verification adds three `git rev-parse` calls. Negligible
  cost; catches drift before it produces silent breakage.
- **Hooks require jq or python3** in the shell environment at hook execution time. Both are standard on macOS and common Linux distributions.

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
