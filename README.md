# shepherd

[![GitHub License](https://img.shields.io/github/license/FL03/shepherd?style=for-the-badge&logo=github)](LICENSE)
[![GitHub Release](https://img.shields.io/github/v/release/FL03/shepherd?style=for-the-badge&logo=github)](https://github.com/FL03/shepherd/releases)

---

Welcome, the **shepherd** plugin is *an adaptive, sprint-by-sprint version-cycle conductor* designed for Claude Code. Shepherd turns a single session into a disciplined release engineer driving a closed six-agent flock through repeatable, audited sprint pipelines — with mechanical enforcement, SQLite-backed context, and zero passive waits.

```text
┌──────────────────────────────────────────────────────────────────────┐
│  /shepherd:plant     Seed authorship — Opus recommended (upstream)   │
│  /shepherd:start     One sprint end-to-end, then PAUSE               │
│                       --teammate    lane-execute (spawned sessions)  │
│  /shepherd:spawn     Root-shepherd + teammate-conductors             │
│                       --scope <sprint|patch|minor|version>           │
│                       --parallel <N>      sprint-level fanout        │
│                       --auto              alias: --scope patch       │
│  /shepherd:loop      Bounded loop-until-done (per-role templates)    │
│  /shepherd:toolkit   Tool registry — never forget a capability       │
│  /shepherd:ctx       Inspect / refresh the per-project SQLite ctx    │
│  /shepherd:cleanup   Post-sprint worktree + lock cleanup             │
└──────────────────────────────────────────────────────────────────────┘
```

## Overview

Shepherd is an orchestration framework for long-running engineering work in Claude Code. It provides:

- A **closed six-agent flock** with fixed roles and dispatch contracts
- A **three-tier meta layer** that authors seeds, executes sprints, and coordinates teammate-conductors
- A **three-section pipeline** (INTRODUCTION → BODY → CLOSE) with wave-gated execution
- **Mechanical enforcement** via hooks that refuse dispatch drift before it happens
- A **per-project SQLite registry** that indexes symbols, issues, artifacts, and memories
- A **tool toolkit** (`toolkit.json`, project-local ⊕ user-global) that remembers your commonly-used MCP/skill/plugin/CLI tools — so a session never forgets a capability exists
- A **project-agnostic config** via `shepherd.toml` — branch topology, gates, paths, and skill wiring live in your repo, not in the framework

Shepherd is a plugin for Claude Code installed via the marketplace or a symlink. There is no build system — assets are markdown briefs, YAML frontmatter, and shell scripts.

## Architecture

### Three meta tiers

| Tier | Profile | Model | Adopted by | Role |
| :--: | :-----: | :---: | :--------: | :--: |
| 3 — root | `agents/shepherd.md` | inherit | Main chat under `/shepherd:spawn` | Engineer/critic dispatch, artifact materialization, dispute resolution, close-swarm coordination |
| 2 — conductor | `agents/conductor.md` | sonnet | Main chat under `/shepherd:start` (solo) or a spawned teammate session | Sprint/lane execution; dual solo/teammate mode |
| parallel — planter | `agents/planter.md` | inherit; opus (recommended) | Main chat under `/shepherd:plant`; mid-spawn delegated | Seed authorship, git custody, cleanup stewardship |

> **Planter model policy:** Fable 5 is superior; Opus (`claude-opus-4-8`) is the recommended default; Sonnet/Haiku are allowed but produce a degraded-seed advisory.

### The closed flock (six agents)

| Agent | Model | Dispatch | Role |
| :-------: | :-------: | :----------: | :------: |
| `@engineer` | Opus | Single, once per sprint | Phase 0 mesh + sprint plan authorship. Root-tier-exclusive under `/shepherd:spawn`. |
| `@critic` | Sonnet | Single, sequential gate | Adversarial review of plans, money-paths, merges. Root-tier-exclusive under `/shepherd:spawn`. |
| `@coder` | Sonnet | Parallel waves | Implementation; one per disjoint file scope |
| `@auditor` | Sonnet | Swarm of 3–5 | Read-only review at sprint close, split by concern |
| `@worker` | Sonnet | Single or parallel | Bounded execution: monitoring, research, ops |
| `@discovery` | Sonnet | Single or parallel | Read-only orientation, comprehension, synthesis |

The flock is **closed** — the contract changes only on a MAJOR version bump. Non-code work goes to `@worker`; research to `@discovery`. Adding agents outside these six is a framework violation.

### The pipeline

Every sprint runs three sections:

1. **INTRODUCTION** — Phase 0 mesh (ground-truth audit), plan authorship by `@engineer`, adversarial gate by `@critic`
2. **BODY** — coder waves with between-wave gates (`check`, `lint`, `format`); auditor swarm overlaps Wave 2 (Pattern B)
3. **CLOSE** — merge, tag, squash-to-main, carry-forward refresh, close report

Under `/shepherd:spawn`, the BODY is fanned out as **lanes** (vertical slices across waves), each owned by one teammate-conductor running via Agent Teams. Gate-free agent fan-out — coder waves, audit swarms, **and discovery/intro waves** — compiles to Dynamic Workflows. Root stays active between waves — no passive waits.

---

## What it solves

Naive long-running Claude sessions suffer predictable failure modes. Shepherd addresses each mechanically:

| Problem | Shepherd's answer |
| :---------: | :-------------------: |
| **Tunnel vision** — conductor ignores the 200-issue ledger underneath | Phase 0 mesh enumerates ALL open issues, surfaces CRITICAL/HIGH outside the current milestone as drift risks |
| **Duplication** — types and helpers re-invented because nobody grepped first | `[DO-NOT-DUPLICATE]` grep gate in every coder brief; `must-be-zero` violations halt the lane |
| **Silent scope drift** — sprints add features that weren't seeded | Every brief is issued-anchored to the seed; auditor's `completeness` concern fails any lane that drifted |
| **Audit theater** — "passes review" because the reviewer is the same context that wrote it | Read-only `@auditor` swarm (3–5 agents, split by concern) runs in parallel, dispatched from root |
| **Wrapper bloat** — hollow structs added for structure's sake | Wrapper-grep gate at sprint close; `SUBTRACT-DON'T-ADD` doctrine requires net-negative LOC/dep/abstraction |
| **Release malpractice** — squash-merging unsigned, untested, un-tagged commits | Conductor drives the full squash-to-main pipeline with gate sequencing and signed commits |
| **Passive dispatch boundary waits** — root stalls after spawning teammates | Coordinate-active-drive doctrine + `coordinate_drive_guard.sh` hook mechanically blocks premature halt |
| **Context bleed between coders** — parallel coders see each other's drift | Each coder scoped to a disjoint file set; anti-duplication greps prevent cross-scope re-invention |

---

## Key features

### Phase 0 mesh

Every sprint opens with a structured ground-truth audit: open issues + PRs, recent Sentry/Supabase/Fly state, carry-forwards from prior sprints. The engineer can't skip it; auditors verify the mesh was complete.

### SQLite context registry

`/shepherd:ctx` manages a per-project SQLite database at `.shepherd/shepherd.db` (legacy `.artifacts/root.db` is auto-detected). It indexes code symbols, GitHub issues/PRs/releases, artifact files, project memories, flock profiles, lock history, and the event log.

```bash
shctx init                   # scaffold .shepherd/ (standard layout), create shepherd.db
shctx refresh --scope=all    # populate caches
shctx status                 # verify
shctx style init --all       # scaffold per-language code-style files
```

The workdir follows a standardized internal layout (v6.1.2) — `docs/{plans,reports,diagrams,handoffs,specs,journal}/`, `logs/`, `archive/`, `cache/`, `scripts/`, `templates/`, `types/`, plus `toolkit.json` and `shepherd.db`. Projects on the legacy shape (top-level `plans/`+`reports/`, `root.db`, `.artifacts/`) keep working untouched; `shctx migrate --layout v2` performs the opt-in move.

### Tool toolkit

The toolkit (`toolkit.json`) is a mutable registry of commonly-used tools so a session never forgets a capability exists — the tool-memory sibling of the self-improvement loop's lesson-memory. Two tiers, merged at read time (local overrides global on name):

- **local** — `<namespace>/toolkit.json` (tracked): project-specific tools
- **global** — `$XDG_CONFIG_HOME/shepherd/toolkit.json`: cross-project tools reused in every repo (your ssh dev box, `context7`, …)

Each entry is `{ name, scope, type (mcp|skill|plugin|cli), capabilities[], description }` (+ optional `invocation`, `when`, `tags`, `pinned`). It surfaces three ways: a **SessionStart hook** injects a compact roster every session, the `shctx toolkit` CLI manages it, and a `[TOOLKIT]` block is injected into engineer/coder/planter briefs.

```bash
shctx toolkit add --name=pzzld-laptop --type=cli --scope=global \
  --description="ssh pzzld@laptop — self-hosted dev surface" --capabilities=remote-shell
shctx toolkit add --name=context7 --type=mcp --scope=global \
  --description="library docs; prefer over web search" --pin
shctx toolkit list --scope=all
```

Never store secrets or credentials in the toolkit. See [`skills/shepherd/doctrines/toolkit.md`](skills/shepherd/doctrines/toolkit.md).

### Per-role loop templates

`/shepherd:loop` runs Pattern 6 (Loop-Until-Done) as a first-class, bounded loop. Each flock role gets a ready-made template in [`skills/shepherd/references/loop-templates.md`](skills/shepherd/references/loop-templates.md) — `@coder` fix-until-green (CODER-CONVERGENCE), `@discovery` research-until-comprehensive (DISCOVERY-EXHAUST), `@worker` monitor/reconcile (WORKER-WATCH / WORKER-CONVERGENCE), `@auditor` progressive-audit (AUDITOR-REFINE), plus the orchestrator's own FOCUS-LOOP. Every template declares a hard `--max` cap and a measurable termination predicate — loops are never open-ended.

### Per-language style files

Project-local code-style overrides live at `.shepherd/styles/<lang>.md` (rust, python, typescript, go, shell, sql). Tracked in git. The conductor injects the matching style file into every coder brief whose file scope touches that language.

```bash
shctx style init rust        # scaffold from bundled defaults
shctx style show rust        # print current style
shctx style edit rust        # open in $EDITOR
```

### Mechanical enforcement hooks

Shepherd ships a full hook suite wired via `hooks/hooks.json`:

- **`dispatch_guard.sh`** — PreToolUse guard that hard-refuses missing/wrong `subagent_type`, off-flock impersonation, and wrong-tier `@engineer`/`@critic` dispatch from teammates
- **`bash_guard.sh`** — blocks workflow→teammate dispatch inversion and backgrounded cargo gates
- **`coordinate_drive_guard.sh`** — Stop hook that blocks premature root halt while teammates are idle or lead mail is unread
- **`close_finalize_check.sh`** — validates close-finalize preconditions (close report committed, sprint branch still on origin) before the stop event fires
- **`_lib.sh`** — shared resolution: `SHEPHERD_WORKDIR` override → `SHCTX_ROOT_OVERRIDE` → pre-existing `.shepherd/` → pre-existing `.artifacts/` → default `.shepherd/`

### Scope-scaled workload

`/shepherd:spawn --scope <sprint|patch|minor|version>` scales workload per a four-tier roadmap. `--scope patch` runs sequential sprints to patch completion; `--parallel <N>` fans out N disjoint sprints across git worktrees. `--auto` aliases `--scope patch`.

### Carry-forward refresh

The `completeness` auditor diffs the GitHub issue ledger against the sprint's seed at sprint close and files chronic items at ≥ 2 patch crossings — nothing falls through permanently.

### Doctrines

Framework-intrinsic behavioral rules live in `skills/shepherd/doctrines/`. These are not prose guidance — each doctrine is paired with a mechanism (hook, guard, or halt code) in the invariant-enforcement matrix. Current doctrines include: `subtract-dont-add`, `wrapper-must-earn`, `dispatch-tier-separation`, `coordinate-active-drive`, `hotfix-dispatch`, `workflow-patterns`, `loop-templates`, `toolkit`, `self-improvement`, `adaptation-loop`, `sqlite-canonical-state`, `brief-cache-discipline`, and 25+ others.

---

## Install

### From the Claude Code marketplace (recommended)

```text
/plugin marketplace add fl03/shepherd
/plugin install shepherd@fl03
```

Registers the self-hosted marketplace manifest and pulls shepherd as a managed plugin. Updates via `/plugin update shepherd@fl03`.

### Personal install via symlink

```bash
git clone https://github.com/FL03/shepherd.git ~/src/FL03/shepherd
ln -s ~/src/FL03/shepherd ~/.claude/plugins/shepherd
```

### Per-project pin

```bash
mkdir -p .claude-plugin
ln -s /path/to/FL03/shepherd .claude-plugin/shepherd
```

---

## Configure

Create `.claude/shepherd.toml` at the project root. Shepherd surfaces a warning at every invocation until one exists.

Config search order (first found wins):

```text
.claude/shepherd.toml         ← project-pinned, checked into the repo
.claude/shepherd.local.toml   ← project-pinned, gitignored (operator overrides)
$XDG_CONFIG_HOME/shepherd.toml ← user-global default
```

### Minimal example

```toml
[project]
name        = "my-project"
language    = "rust"          # rust | python | typescript | go | mixed

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
mandatory  = ["code-style"]
by_domain  = { rust = ["rust"], wasm = ["webassembly"] }
```

See [`docs/configuration.md`](docs/configuration.md) for the full schema including `[gates.extra]`, `[spawn]`, `[release]`, and the language matrix.

A working example for a multi-crate Rust service lives at [`examples/rust-service/shepherd.toml`](examples/rust-service/shepherd.toml).

---

## Usage

### First-time setup

1. Create `shepherd.toml` (see above).
2. Run `/shepherd:ctx` to initialize the SQLite registry.
3. Optionally author a patch-arc seed at `.shepherd/docs/plans/v{X}.{Y}.{Z}.seed.md` describing the patch's theme.
4. Run `/shepherd:plant` (Opus recommended — Fable 5 superior; Sonnet/Haiku allowed with degraded-seed advisory) to author the dev.0 sprint seed.
5. Switch to Sonnet and run `/shepherd:start` for your first sprint.

### Common commands

```bash
# Author seeds for upcoming sprints
/shepherd:plant
/shepherd:plant dev.5
/shepherd:plant arc

# Run a single sprint end-to-end, then pause for operator sign-off
/shepherd:start

# Spawn teammate-conductors (full lane-per-conductor fanout)
/shepherd:spawn

# Sequential autopilot — fresh context per sprint, through patch completion
/shepherd:spawn --auto

# Fan out N disjoint sprints in parallel across git worktrees
/shepherd:spawn --parallel 3

# Inspect/refresh the context registry
/shepherd:ctx

# Clean up post-sprint worktrees and lock files
/shepherd:cleanup
```

---

## Integration with local skills

Shepherd is designed to compose with your locally developed skills, not replace them:

- **`code-style`** — injected into every coder brief by default. Provides your personal per-language preferences (idioms, comment discipline, naming conventions). Shepherd provides orchestration; `code-style` provides the per-keystroke voice.
- **Domain skills** (`rust`, `webassembly`, `finance`, `supabase`, etc.) — wired into the Required-Skills Matrix via `[skills.by_domain]` in `shepherd.toml`. Attached automatically when the coder's file scope matches.
- **`superpowers:brainstorming` + `superpowers:writing-plans`** — loaded by `@engineer` from inside its own dispatch. Plan quality depends on these.

See [`docs/integration.md`](docs/integration.md) for the full integration model including MCP bindings, Sentry/Supabase/Fly state injection, and custom doctrine authorship.

---

## File map

| Path | Purpose |
| :------: | :---------: |
| `.claude-plugin/plugin.json` | Plugin manifest |
| `.claude-plugin/marketplace.json` | Self-hosted marketplace entry |
| `agents/{engineer,critic,coder,auditor,worker,discovery}.md` | Closed flock — full system prompts per lane |
| `agents/{shepherd,conductor,planter}.md` | Three meta-orchestrators |
| `commands/{plant,start,spawn,loop,toolkit,ctx,cleanup}.md` | Active slash-command entry points |
| `skills/shepherd/SKILL.md` | Conductor quick reference (loaded by every `/shepherd:*` invocation) |
| `skills/shepherd/doctrines/*.md` | Framework-intrinsic behavioral rules |
| `skills/shepherd/references/` | Branching model, seed template, agent-brief templates, grading rubric |
| `skills/context/SKILL.md` | `shctx` runtime entry point |
| `skills/context/schema/` | SQL migrations + views for the SQLite registry |
| `skills/context/scripts/` | `shctx` + `cmd_*` implementations (bash) |
| `skills/context/styles/<lang>.md` | Bundled per-language code-style defaults |
| `skills/context/references/toolkit.schema.json` | Toolkit entry JSON Schema (v6.1.2) |
| `skills/shepherd/references/loop-templates.md` | Per-flock-role loop catalog (v6.1.2) |
| `hooks/hooks.json` | Event registrations wiring Claude Code lifecycle → hook scripts |
| `hooks/scripts/` | Hook implementations (sourced from `_lib.sh`) |
| `hooks/tests/` | Smoke harness — `bash hooks/tests/run.sh` |
| `docs/{configuration,integration,customization}.md` | Operator-facing documentation |
| `examples/rust-service/` | Working multi-crate Rust service bindings (config + CLAUDE.md snippet) |
| `examples/minimal/` | Stripped-down starter config |

---

## Versioning

Shepherd follows semver:

- **MAJOR** — closed-flock contract changes (adding/removing a lane, flipping critic to parallel)
- **MINOR** — new commands, doctrines, or config keys (backward-compatible)
- **PATCH** — dispatch logic, doctrine, or brief-template fixes

Version sources of truth that must move together: `plugin.json`, `marketplace.json`, `skills/shepherd/SKILL.md` frontmatter, `skills/context/SKILL.md` frontmatter, `README.md` header, `CHANGELOG.md`. `shctx release` automates the five non-CHANGELOG files.

Current version: **6.2.0**. See [`CHANGELOG.md`](CHANGELOG.md) for the per-version history.

---

## License

Apache-2.0. See [`LICENSE`](LICENSE) at the repo root.
