# shepherd — v6.0.4

Sprint-by-sprint version-cycle conductor. A production-grade orchestration framework that turns a single Claude Code session into a disciplined release engineer driving a closed six-agent flock (engineer, critic, coder, auditor, worker, discovery) through repeatable sprint pipelines.

```bash
┌──────────────────────────────────────────────────────────────────────┐
│  /shepherd:plant     Opus-pinned seed authorship (upstream)          │
│  /shepherd:start     One sprint end-to-end, then PAUSE               │
│                       --teammate    lane-execute (spawned sessions)  │
│  /shepherd:spawn     Root-shepherd + teammate-conductors             │
│                       --scope <sprint|patch|minor|version>           │
│                       --parallel <N>      sprint-level fanout        │
│                       --auto              alias: --scope patch       │
│  /shepherd:ctx       Inspect / refresh the per-project SQLite ctx    │
│  /shepherd:cleanup   Post-sprint worktree + lock cleanup             │
└──────────────────────────────────────────────────────────────────────┘
```

## v6.0.3 — Agent-Teams orchestration hardening

A substrate-defect patch closing operational gaps (#97–#103) found in live `/shepherd:spawn` runs on the v6.0.x native substrate. Diagnostics confirmed the failures were Agent-Teams *coordination* gaps — **not** the model and **not** Dynamic-Workflow dispatch (`opus[1m]` and 16-way Sonnet fan-out both probed clean). Worktrees are now pre-created before `TeamCreate`; wave-gates are mechanically enforced via task `addBlockedBy` (a `TaskUpdate` field); teammate git-writes, lane-task ownership, stall heartbeats, and engineer-dispatch errors are codified with halt codes (`TEAMMATE-GIT-WRITE`, `TASK-LANE-MISMATCH`, `WAVE-GATE-NOT-RELEASED`, `ENGINEER-MODEL-FAIL`). The `@engineer` `opus[1m]` pin is retained (probe-cleared; single once-per-sprint dispatch). Full detail in the [CHANGELOG](CHANGELOG.md).

## v6.0.2 — Ontology recovery, mechanical enforcement & native-substrate adoption

v6.0.1's slimming + the introduction of "lanes" blurred shepherd's core ontology
and broke its mapping of Claude-native primitives to their roles. v6.0.2 restores
the truth as **canonical doctrine** —
[`doctrines/primitive-axis-binding.md`](skills/shepherd/doctrines/primitive-axis-binding.md):

| Axis | Native primitive | Unit |
|---|---|---|
| **Planning** (engineer-authored, no parallelism) | — | **waves × steps** |
| **Teammate-state / parallelization** (lanes) | **Agent Teams** | one teammate-conductor per **lane** |
| **Execution** (gate-free step fan-out) | **Dynamic Workflows** (compiled) | the script over **subagents** |
| **Worker** | **subagents** | the **steps** themselves |

- A plan is **N sequential waves; each wave is X steps; each step ≈ one subagent.**
  Gates run **between** waves. The engineer authors `waves × steps` with **no lane
  concept**.
- A **lane** is a cohesive **vertical slice across waves**, formed **only in spawn
  mode, after the plan**, owned by one teammate-conductor. Lanes never nest inside a
  wave. A lane's teammate may be **refreshed** between waves (fresh context) — that is
  not a new lane.
- **Spawning teammates = Agent Teams, never a workflow.** A teammate's gate-free
  fan-out = **compile to a Dynamic Workflow**, never hand-rolled dispatch. Never invert
  (the v6.0.1 field regression, [#89](https://github.com/FL03/shepherd/issues/89)).

**Mechanical enforcement (not prose).** Every load-bearing invariant is paired with a
mechanism in
[`doctrines/invariant-enforcement-matrix.md`](skills/shepherd/doctrines/invariant-enforcement-matrix.md)
([#86](https://github.com/FL03/shepherd/issues/86)). A PreToolUse guard
(`hooks/scripts/dispatch_guard.sh`) hard-refuses the dispatch-class drift behind
[#66](https://github.com/FL03/shepherd/issues/66) — missing/`general-purpose`
`subagent_type`, off-flock impersonation, wrong-tier `@engineer`/`@critic` from a teammate;
`bash_guard.sh` blocks the workflow→teammate inversion and backgrounded cargo gates; a
capability lint pins read-only + least-privilege allowlists across all nine agents
([#74](https://github.com/FL03/shepherd/issues/74) /
[#84](https://github.com/FL03/shepherd/issues/84)). Reproduced and proven in `hooks/tests/`.

**Platform mechanism verified ([#93](https://github.com/FL03/shepherd/issues/93)).** Against
the live Claude Code docs: teammates spawn via the **`TeamCreate`** tool family + a
natural-language lead instruction referencing the `shepherd:conductor` subagent definition —
there is **no `team_name` parameter on `Agent`/`Task`** (those spawn subagents), and a
teammate session exposes **no identity env var**
([`anthropics/claude-code#35447`](https://github.com/anthropics/claude-code/issues/35447));
identity arrives only in hook-input JSON. **Dynamic Workflows orchestrate subagents only —
never teammates.** The spawn command, conductor profile, and guards are reconciled to this;
the binding above is confirmed (only the call-shape was ever wrong).

**Native substrate (slim, not bespoke).** Execution rides Claude Code's own primitives:
`shctx graph compile` emits the gate-free fan-out segments of the critic-gated Stage Graph
as **Dynamic Workflow** scripts (with a soundness / completeness / determinism faithfulness
diff), and `shctx graph diagram` renders the graph as a **Mermaid execution diagram** (seam
vs fan-out, with a per-segment overlay). Coordination maps onto the native axes per
[`doctrines/native-coordination.md`](skills/shepherd/doctrines/native-coordination.md);
shepherd keeps only the governance core (closed flock, dispatch contract, audited plan,
SQLite + git canonical state) and proactively prunes idle teammates to compartmentalize work
and cut compute.

**Operational substrate.** A project-local work directory, named by `$SHEPHERD_WORKDIR`
(default `.shepherd`; `.artifacts` accepted), holds the per-project SQLite registry, logs,
mailbox, escalations, and indexes, and ships its own `.gitignore` (secrets + runtime trimmed,
design records preserved). Path resolution was hardened so the commands and hooks that
hardcoded `.artifacts/root.db` no longer split-brain a `.shepherd` project.

**Also fixed:** the release workflow
([#71](https://github.com/FL03/shepherd/issues/71)) and the critic's false-positive on
transitively-reachable Cargo features
([#72](https://github.com/FL03/shepherd/issues/72)).

## v6.0.0 — Dispatch enforcement + planter authority excision

v6.0.0 closes the dispatch-enforcement gap that v5.1.9 opened. The
`subagent_type` field is now MANDATORY on every flock dispatch — missing,
`general-purpose`, `Explore`, or `Chat` is a `DISPATCH-MISSING-SUBAGENT-TYPE`
refusal, not a silent degradation. The full forbidden-combination matrix
lives in
[`skills/shepherd/doctrines/dispatch-tier-separation.md §IV-bis`](skills/shepherd/doctrines/dispatch-tier-separation.md).

Additionally:

- **Wave-tier model is now canonical doctrine.** Under `/shepherd:spawn`:
  INTRO + plan-gate + CLOSE-SWARM are root-direct subagents; BODY is
  teammate-conductors, each running their own subagent waves for their
  assigned lane. See
  [`doctrines/root-shepherd-orchestration.md §I-bis`](skills/shepherd/doctrines/root-shepherd-orchestration.md).
- **Planter authority is bounded.** Per FL03/shepherd #67, the seed
  template's old §6 ("MUST-LAND lanes — numbered, issue-anchored")
  becomes "Deliverables (issue-anchored)" — no `Lane N` numbering, no
  `Sequencing:` directives. Lane decomposition is the engineer's
  exclusive authority.
- **Scope is workload-scale, not a quality bar.** `/shepherd:spawn --scope
  patch` delivers what each sprint's seed promises. "It's just a patch"
  is framework-recognized malpractice. See
  [`doctrines/version-scale-roadmap.md`](skills/shepherd/doctrines/version-scale-roadmap.md)
  opening note.

**Breaking change:** projects relying on the v5.1.5 → v5.1.9 permissive
fallback (Agent calls without `subagent_type`) will now refuse to fire.
Update affected dispatches to `Agent({subagent_type: "shepherd:<role>", ...})`.

## v5.1.6 — Root-Shepherd Tier + Lane-Per-Conductor Fanout

v5.1.6 introduces a **three-tier dispatch hierarchy** under `/shepherd:spawn`:

- **Tier 3 (root)** — `agents/shepherd.md`. Main chat adopts this profile when `/shepherd:spawn` is invoked. Owns `@engineer` + `@critic` dispatch, artifact materialization from teammate-returned payloads, cross-teammate dispute resolution, and close-swarm coordination.
- **Tier 2 (meta)** — `agents/conductor.md` (downgraded to **model: sonnet** in v5.1.6). Dual-mode: **solo mode** under `/shepherd:start` retains full dispatch + writes (backward-compatible); **teammate mode** under `/shepherd:spawn` is restricted (no engineer/critic dispatch, no artifact writes — returns structured payloads via `SendMessage`).
- **Tier 1 (flock)** — closed at six (coder, auditor, worker, discovery, engineer, critic). Engineer + critic become root-tier-exclusive under spawn.

The spawn pattern is **lane-per-conductor fanout** (clarified in v6.0.2): the engineer authors the plan as `waves × steps` (no lanes); then, **post-plan and spawn-only**, the plan is sliced **vertically across waves** into **lanes** (one teammate-conductor each, via Agent Teams). Root spawns one teammate-conductor **per lane** — the lane count, constant across waves (a lane's teammate may be refreshed per wave for fresh context; that is not a new lane). Many small focused lanes beat fewer broad ones — cache hit rates climb when each teammate's stable prefix is small. See [`doctrines/primitive-axis-binding.md`](skills/shepherd/doctrines/primitive-axis-binding.md).

`--scope sprint|patch|minor|version` (default `sprint`) scales workload per the 4-tier roadmap. `--scope patch` replaces the retired `--auto` (preserved as alias). `minor` and `version` are experimental — require operator double-confirmation.

See [`docs/configuration.md`](docs/configuration.md), [`agents/shepherd.md`](agents/shepherd.md), and [`skills/shepherd/doctrines/dispatch-tier-separation.md`](skills/shepherd/doctrines/dispatch-tier-separation.md) for full details.

## v5.0.0 — Context Registry

`/shepherd:ctx` introduces a per-project SQLite registry at `.artifacts/root.db`. It indexes:

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

See [`skills/context/SKILL.md`](skills/context/SKILL.md) for the full CLI.

### Per-language style files

Project-local code-style overrides live at `.artifacts/styles/<lang>.md` (rust, python, typescript, go, shell, sql). They are tracked in git and complement — never replace — the user-level `code-style` skill. The conductor mechanically injects the matching style file as a `[CODE-STYLE]` block into every coder brief whose `[FILE-SCOPE]` touches that language; the auditor's `completeness` check fails any code-touching lane that omits it.

```bash
shctx style init --all       # scaffold all six language files from bundled defaults
shctx style init rust        # scaffold a single language
shctx style list             # show which languages have a project-local file
shctx style show rust        # print the current rust style
shctx style edit rust        # open in $EDITOR
```

Bundled defaults ship at [`skills/context/styles/<lang>.md`](skills/context/styles/); `shctx style init` copies them into the consumer project's `.artifacts/styles/`.

## What it is

Shepherd is the framework. **Three meta tiers** orchestrate a closed **six-agent flock** through repeatable sprint pipelines.

**Meta tiers** (v5.1.6+):

| Tier | Profile | Model | Adopted by | Role |
| ---- | ------- | ----- | ---------- | ---- |
| 3 (root) | `agents/shepherd.md` | inherit | Main chat under `/shepherd:spawn` | Engineer/critic dispatch, artifact materialization, dispute resolution, close-swarm |
| 2 (meta) | `agents/conductor.md` | sonnet | Main chat under `/shepherd:start` (solo) OR teammate session (teammate) | Sprint/lane execution; dual-mode |
| PARALLEL | `agents/planter.md` | opus[1m] | Main chat under `/shepherd:plant`; mid-spawn delegated | Seed authorship + cleanup stewardship |

**The flock** (closed at six):

| Lane | Model | Mode | Job |
| ---- | ----- | ---- | --- |
| `@engineer` | Opus | Single, once per sprint | Phase 0 mesh + sprint plan authorship. **Root-tier-exclusive under `/shepherd:spawn`.** |
| `@critic` | Sonnet | Single, sequential gate | Adversarial review of plans, money-paths, merges. **Root-tier-exclusive under `/shepherd:spawn`.** |
| `@coder` | Sonnet | Parallel waves | Implementation; one per disjoint file scope |
| `@auditor` | Sonnet | Swarm of 3–5 | Read-only review at sprint close, split by concern |
| `@worker` | Sonnet | Single or parallel | Bounded execution: monitoring, research, ops |
| `@discovery` | Sonnet | Single or parallel | Read-only orientation, comprehension, synthesis |

The flock is **closed**. Plus an upstream **planter** mode (Opus, conductor variant — not a sixth lane) that authors drift-resistant seeds.

## What it solves

Naive `claude` sessions on long-running engineering work suffer:

- **Tunnel vision** — the conductor sees the current sprint deliverable and ignores the 200-issue ledger underneath.
- **Duplication** — types, traits, helpers re-invented because nobody grepped first.
- **Silent scope drift** — sprints add features that weren't seeded.
- **Audit theater** — code "passes review" because the reviewer was the same context that wrote it.
- **Release pipeline malpractice** — squash-merging unsigned, untested, un-tagged commits.

Shepherd's answer:

- **Phase 0 mesh** — every sprint opens with a ground-truth audit (open issues, recent PRs, Sentry/Fly/Supabase state, prior carry-forwards). Engineer can't skip it; auditors verify it.
- **Issue-ledger awareness** — every sprint's Phase 0 enumerates the FULL open-issue ledger (not just the current milestone) and surfaces non-current-milestone CRITICAL/HIGH items as drift risks.
- **Anti-duplication grep gate** — every coder brief carries `[DO-NOT-DUPLICATE]` greps the coder runs BEFORE writing new code. `must-be-zero` violations halt the lane.
- **Wrapper-grep gate** — every sprint close greps for hollow wrapper structs introduced in lane scope (per `feedback_wrapper_must_earn_its_existence.md`).
- **SUBTRACT-DON'T-ADD doctrine** — every sprint MUST end net-negative on (deps, abstractions, LOC). Auditor fails the close on violation.
- **Adversarial critic** — every plan above XS scope, every money-path change, every merge to main is gated by `@critic` first.
- **Read-only auditor swarm** — 3–5 auditors split by concern, dispatched in parallel with Wave 2 coders (Pattern B overlap).
- **Carry-forward refresh** — `completeness` auditor diffs the GH ledger against the sprint's seed, files chronic items at ≥ 2 patch crossings.

## Install

### From the Claude Code marketplace (recommended)

```text
/plugin marketplace add fl03/shepherd
/plugin install shepherd@fl03
```

This registers the self-hosted marketplace manifest at the repo root, then pulls in shepherd as a managed plugin. Subsequent updates flow through `/plugin update shepherd@fl03`.

### Personal install via symlink (current user only)

```bash
# Clone once, then symlink the repo root into your user plugin directory.
git clone https://github.com/FL03/shepherd.git ~/src/FL03/shepherd
ln -s ~/src/FL03/shepherd ~/.claude/plugins/shepherd
```

The repo root IS the plugin — `.claude-plugin/plugin.json` lives there.

### Per-project pin (checked into the consumer repo)

```bash
# From the consumer project root
mkdir -p .claude-plugin
ln -s /path/to/FL03/shepherd .claude-plugin/shepherd
```

## Configure

Shepherd is project-agnostic. Create `.claude/shepherd.toml` at the project root to bind it to your repo's branch convention, gate commands, and artifact paths. See [`docs/configuration.md`](docs/configuration.md) for the full schema.

Minimal example (drop into `.claude/shepherd.toml`):

```toml
[project]
name        = "axiom"
language    = "rust"

[branching]
# Branch pattern. {X}/{Y}/{Z}/{N} are placeholders the framework reads.
patch_branch_pattern  = "v{X}.{Y}.{Z}"
sprint_branch_pattern = "v{X}.{Y}.{Z}-dev.{N}"
sprints_per_patch     = 10
main_branch           = "main"

[gates]
# Commands that run between coder waves and at sprint close.
# Empty = framework skips the gate.
check  = "cargo check --workspace --features full"
lint   = "cargo clippy --workspace --features full -- -D warnings"
format = "cargo fmt --all"

[paths]
plans   = ".artifacts/plans"
reports = ".artifacts/reports"
docs    = ".artifacts/docs"
ctx     = ".artifacts/ctx"

[skills]
# Per-language skills that EVERY coder brief MUST include in [SKILLS].
# code-style is mandatory; the rest are domain-driven.
mandatory  = ["code-style"]
by_domain  = { rust = ["rust"], wasm = ["webassembly"], finance = ["finance"], supabase = ["supabase:supabase"] }

[release]
# Whether the conductor should drive the squash-to-main release pipeline at dev.9.
# Most projects pin this to false and rely on a GH workflow triggered on tag.
conductor_drives_release = false
```

A working example for the Axiom project lives at [`examples/axiom/shepherd.toml`](examples/axiom/shepherd.toml).

## Usage

```bash
# Author seeds for upcoming sprints (Opus session required)
/shepherd:plant
/shepherd:plant dev.5
/shepherd:plant arc

# Run a single sprint, then pause for sign-off
/shepherd:start

# Spawn a teammate-conductor (planter stays lean as babysitter)
/shepherd:spawn

# Sequential autopilot: fresh context window per sprint
/shepherd:spawn --auto

# Fan out N disjoint sprints across git worktrees
/shepherd:spawn --parallel 3
```

For first-time use:

1. Author your project's `shepherd.toml` (see above).
2. (Optional) author a patch-arc seed by hand at `.artifacts/plans/v{X}.{Y}.{Z}.seed.md` describing the patch's theme.
3. Run `/shepherd:plant` in an Opus session to author the dev.0 seed.
4. Switch back to Sonnet and run `/shepherd:start`.

## File map

| Path | What it is |
| ---- | ---------- |
| `.claude-plugin/plugin.json` | Plugin manifest |
| `commands/{plant,start,spawn,ctx,cleanup}.md` | Active slash commands (`autorun` + `parallel` are retired thin redirects) |
| `agents/{engineer,critic,coder,auditor,worker,discovery}.md` | Closed flock — domain agent system prompts |
| `agents/{shepherd,conductor,planter}.md` | Three meta-orchestrators (root shepherd, conductor, planter) |
| `skills/shepherd/SKILL.md` | Conductor quick reference (loaded by every command) |
| `skills/shepherd/{flock,autorun,parallel}.md` | Operational detail; `planter.md` is a retired redirect → `agents/planter.md` (v5.1.4+) |
| `skills/shepherd/references/branching-model.md` | Authoritative branch lifecycle + rollover algorithm |
| `skills/shepherd/references/seed-template.md` | Canonical seed shape (what the engineer parses) |
| `skills/shepherd/references/agent-briefs.md` | Copy-paste brief templates + grade cutoffs |
| `skills/shepherd/doctrines/*.md` | Framework-intrinsic doctrines (subtract-don't-add, wrapper-must-earn, etc.) |
| `examples/axiom/` | Concrete Axiom-project bindings (config, CLAUDE.md snippet, custom doctrines) |
| `docs/{configuration,integration,customization}.md` | Operator-facing documentation |

## Integration with local skills

Shepherd is designed to integrate with — not replace — locally developed skills:

- **`code-style`** — every coder brief includes this in `[SKILLS]` by default. Code-style holds your personal language-by-language preferences (Rust idioms, comment discipline, naming conventions). Shepherd's framework provides the orchestration; `code-style` provides the per-keystroke voice.
- **`rust` / `webassembly` / `finance` / `supabase` / domain skills** — wired into the Required-Skills Matrix in `flock.md` §II.@coder. Shepherd reads `[skills.by_domain]` from `shepherd.toml` to know which domain skills to attach when the coder's file scope touches that domain.
- **`superpowers:brainstorming` + `superpowers:writing-plans`** — the engineer loads these from inside its own dispatch (not the conductor calling them). The plan-quality contract depends on these.

See [`docs/integration.md`](docs/integration.md) for the detailed integration model.

## Versioning + compatibility

Shepherd follows semver:

- **MAJOR** bumps when the closed-flock contract changes (e.g., adding a sixth lane, removing the planter, flipping critic to parallel).
- **MINOR** bumps add new commands, new doctrines, new config keys (backward-compatible).
- **PATCH** bumps fix bugs in dispatch logic, doctrines, brief templates.

Current version: **6.0.4**

See [`CHANGELOG.md`](CHANGELOG.md) for the per-version history.

## License

Apache-2.0. See `LICENSE` at the repo root.
