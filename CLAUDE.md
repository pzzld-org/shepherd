# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A dedicated repository for the **shepherd** Claude Code plugin, authored by FL03 (github.com/FL03). The plugin lives at the repo root — the repo *is* the plugin. A self-hosted marketplace manifest at `.claude-plugin/marketplace.json` makes it installable via `/plugin marketplace add fl03/shepherd`.

Shepherd is a sprint-by-sprint version-cycle conductor. A six-agent flock (engineer, critic, coder, auditor, worker, discovery) on a three-section pipeline (INTRODUCTION → BODY → CLOSE), with three meta-orchestrators above (root shepherd, conductor, planter), driven by a project-local `shepherd.toml` in each consumer repo.

There is no build system. Plugin assets are markdown briefs, YAML frontmatter, and shell scripts under `skills/context/scripts/` (the `shctx` runtime).

## Repository layout

```bash
.claude-plugin/
  plugin.json                  # shepherd plugin manifest (this repo IS the plugin)
  marketplace.json             # single-plugin marketplace; source = {"source":"github","repo":"FL03/shepherd"}

agents/{engineer,critic,coder,auditor,worker,discovery}.md   # full system prompts per flock lane
agents/{shepherd,conductor,planter}.md                      # meta-orchestrator profiles (shepherd: root v5.1.6+; conductor + planter: v5.1.4+)
commands/{plant,start,spawn,ctx,cleanup}.md                 # slash-command entry points
commands/{autorun,parallel}.md                              # retired commands (thin delta notes; v5.1.4+)
docs/                          # operator docs (configuration, integration, customization)
examples/{axiom,minimal}/      # binding examples (shepherd.toml + CLAUDE-snippet)

hooks/
  hooks.json                   # event registrations — wires Claude Code lifecycle events to scripts
  scripts/                     # hook implementations (bash, sourced from `_lib.sh`)
  tests/                       # `bash hooks/tests/run.sh` smoke harness

skills/
  shepherd/                    # conductor quick-reference + doctrines + references
    SKILL.md                   # entry point for every /shepherd:* invocation
    {flock,pipeline}.md                          # active skill support files
    planter.md                                   # retired redirect → agents/planter.md (v5.1.4+)
    {autorun,parallel}.md                        # thin delta notes; behaviors retired to /shepherd:spawn (v5.1.4+)
    doctrines/*.md             # framework-intrinsic rules
    references/*.md            # branching-model, seed-template, grading-rubric, etc.
  context/                     # shctx runtime (SQLite registry, queries, scripts)
    SKILL.md
    schema/                    # SQL migrations + views
    scripts/                   # shctx + cmd_* implementations (bash)
    queries/                   # canonical SQL views materialized for briefs
    references/                # schema docs, naming conventions, profiles
    examples/                  # inject-coder, profile-modifier, journal entries
    styles/                    # bundled per-language code-style defaults
    tests/                     # bash test harness — `bash skills/context/tests/run.sh`

.artifacts/                    # self-dogfooded ctx artifacts (this repo runs shctx on itself)
  docs/{specs,plans,handoffs,journal,diagrams}/  # tracked; historical design records
  styles/                      # tracked; per-language style overrides
  root.db, shepherd.lock       # gitignored runtime state

.github/                       # workflows + issue templates + dependabot
```

## Installing locally

Three install paths, in increasing order of integration:

```bash
# (a) Direct symlink — fastest dev iteration
ln -s "$PWD" ~/.claude/plugins/shepherd

# (b) Marketplace add via Claude Code (recommended for consumers)
# Inside a Claude Code session:
#   /plugin marketplace add fl03/shepherd
#   /plugin install shepherd@fl03

# (c) Manual marketplace registration (no GitHub round-trip)
mkdir -p ~/.claude/plugins/marketplaces/fl03
cp -r ./.claude-plugin ~/.claude/plugins/marketplaces/fl03/
# Then add a "fl03" entry pointing at that path in ~/.claude/settings.json
```

## Shepherd plugin commands

| Command | Model | What it does |
|---|---|---|
| `/shepherd:plant [scope]` | **Opus required** | Author drift-resistant sprint seeds upstream of execution |
| `/shepherd:start` (solo) | Sonnet | Run one sprint end-to-end in main chat (conductor SOLO mode), then pause |
| `/shepherd:start --teammate` (v5.1.6+) | Sonnet | Lane-execute mode for spawned teammate sessions; skip INTRO/engineer/critic; read assigned lane brief from boot prompt; walk lane micro-Stage-Graph |
| `/shepherd:spawn [sprint_slug] [--scope <sprint\|patch\|minor\|version>] [--parallel <N> \| --auto]` | Sonnet | Main chat adopts **root-shepherd profile** (v5.1.6+); spawns teammate-conductors per the plan's lane-per-conductor structure. `--scope` declares workload scale (default `sprint`). `--auto` aliases `--scope patch`. `--parallel <N>` fans out N sibling sprints for `--scope >= patch`. **Operator-explicit only** — refuses from teammate sessions. See `commands/spawn.md`. |
| `/shepherd:ctx` | Sonnet | Inspect / refresh the per-project SQLite context registry |

> **Retired (v5.1.4):** `/shepherd:autorun` is superseded by `/shepherd:spawn --auto` (which itself aliases `--scope patch` in v5.1.6+). `/shepherd:parallel` is superseded by `/shepherd:spawn --parallel <N>`. Command files retained as thin delta references only.

> **v5.1.6 dispatch tier separation:** under `/shepherd:spawn`, `@engineer` and `@critic` become **root-tier-exclusive** (only the root shepherd in main chat may dispatch them). Teammate-conductors surface `PLAN-AUTHORSHIP-REQUEST` / `PLAN-GATE-REQUEST` escalations instead. Under `/shepherd:start` solo mode this restriction does NOT apply — conductor IS root in solo. See `skills/shepherd/doctrines/dispatch-tier-separation.md`.

Shepherd is project-agnostic. Each consumer project configures it via `.claude/shepherd.toml`. The full schema is at `docs/configuration.md`. A working example lives at `examples/axiom/shepherd.toml`; a stripped-down template at `examples/minimal/shepherd.toml`.

## Shepherd file contracts

When editing shepherd, these invariants must hold:

- **`skills/shepherd/SKILL.md`** is the conductor quick reference — the entry point for every `/shepherd:*` invocation. All runtime references resolve relative to `${CLAUDE_PLUGIN_ROOT}` (which is the repo root, post-migration).
- **`.claude-plugin/plugin.json`** is the plugin manifest. Version bumps must stay in sync with `README.md`, `skills/shepherd/SKILL.md` frontmatter, `skills/context/SKILL.md` frontmatter, `.claude-plugin/marketplace.json`, and `CHANGELOG.md`. `shctx release` automates this; see `skills/context/scripts/cmd_release.sh`.
- **`agents/<role>.md`** — each file is the full system prompt injected into the corresponding flock-agent brief. Do not abbreviate or inline these; the conductor reads them at dispatch time.
- **`agents/shepherd.md`** (v5.1.6+) — canonical **root-tier** profile. Adopted by main chat under `/shepherd:spawn`. Owns engineer/critic dispatch, artifact materialization from teammate payloads, dispute resolution, close-swarm coordination. Single source of truth for root-tier behavior.
- **`agents/conductor.md`** — canonical conductor profile (Tier 2). Adopted by `/shepherd:start` (SOLO mode) and by spawned teammate sessions (TEAMMATE mode). Dual-mode behavior is binding (v5.1.6+): solo retains full surface; teammate is restricted. **Model: sonnet** (downgraded v5.1.6 from `inherit`).
- **`agents/planter.md`** — canonical planter profile (parallel meta). Adopted by `/shepherd:plant`; also loaded by shepherd profile mid-spawn for delegated seed work. Covers escalation response, git custody, cleanup stewardship.
- **`skills/shepherd/doctrines/*.md`** — framework-intrinsic rules. New doctrines go here; project-specific doctrines go in the consumer repo's `.claude/doctrines/`. v5.1.6 doctrines: `root-shepherd-orchestration.md`, `dispatch-tier-separation.md`, `scope-scale-workload.md`. v5.1.7 doctrine: `sqlite-canonical-state.md`. v5.1.8 doctrine: `claude-code-platform-alignment.md` (maps shepherd's teammate model to Claude Code v2.1.32+ Agent Teams).
- **`hooks/hooks.json`** — wires Claude Code lifecycle events to shepherd's hook scripts. As of v6.0.6 (events unchanged from v5.1.8), registered events: `SessionStart`, `PreToolUse` (Bash/Write/Edit/Agent/Task), `PostToolUse` (Bash/Agent/Task/Edit|Write), `SubagentStop`, `TeammateIdle`, `Stop`, `CwdChanged` (v5.1.8+), `UserPromptSubmit` (v5.1.8+), `WorktreeCreate` (v5.1.8+), `WorktreeRemove` (v5.1.8+). v5.1.8 also introduces shepherd's first uses of `type: "agent"` hooks — embedded prompts that spawn a Haiku subagent to verify Phase 0 mesh "landed in tree" claims (`PostToolUse(Edit|Write)` with `if: "Edit(*.plan.md)"`) and wave-gate cherry-pick state on `Stop`. Both fast-path to `ok: true` when no work is needed; default-on but bounded in cost. **v6.0.6** adds `hooks/scripts/coordinate_drive_guard.sh` as a `Stop` consumer (command type): under `/shepherd:spawn` it blocks a premature root halt while teammates are idle / lead mail is unread (the dispatch-boundary passive-wait bug, `doctrines/coordinate-active-drive.md`); it fast-paths to exit 0 outside spawn sessions, is runaway-bounded (2-nudge cap, fail-open), and is config-gated via `[spawn].coordinate_drive_guard`. Note: the `PostToolUse(Edit|Write)` `type: "agent"` hook fires on both `Edit` and `Write` tool calls matching `*.plan.md`. Note: `TaskCreated` and `TaskCompleted` events fire on the platform when Agent Teams are enabled but are NOT currently handled by a registered hook script; root must route via the task title prefix observed in `TeammateIdle` or via `SendMessage` WAVE-COMPLETE payloads. See `skills/shepherd/doctrines/claude-code-platform-alignment.md §V`.
- **`skills/context/styles/<lang>.md`** are the bundled per-language style defaults shipped with the plugin. `shctx style init <lang>` copies them into a consumer project's `.artifacts/styles/<lang>.md`. The conductor auto-injects the project-local copy into every coder brief whose `[FILE-SCOPE]` matches.
- The flock remains closed at six domain agents (engineer, critic, coder, auditor, worker, discovery), with **three meta-orchestrators** above (v5.1.6+): root `agents/shepherd.md`, conductor `agents/conductor.md`, parallel-meta `agents/planter.md`. The meta tier does NOT open the closed-flock contract. Non-code work goes to `@worker` per `skills/shepherd/doctrines/worker-patterns.md`.

## Skill SKILL.md frontmatter

Every skill's entry point is a `SKILL.md` with required YAML frontmatter:

```yaml
---
name: <slug>
slug: <slug>
version: <semver>
description: |
  ...
metadata:
  triggers:
    - "/skill-name"
---
```

The `triggers` list is what Claude Code uses to match slash commands to skills.

## Sprint orchestration (when running shepherd on this repo)

Shepherd is the *product* here, but this repo dogfoods its own ctx runtime. If you run a `/shepherd:*` sprint on this repo, ensure `.claude/shepherd.toml` exists first (copy from `examples/minimal/shepherd.toml` and adjust). The `.artifacts/` tree is already scaffolded for ctx.

## Versioning

- Shepherd follows semver. MAJOR = closed-flock contract change. MINOR = new commands/doctrines/config keys. PATCH = dispatch logic / brief template fixes.
- Tag format: `v{X}.{Y}.{Z}` (e.g. `v5.0.5`). Docker image is published via `.github/workflows/docker.yml` on `repository_dispatch` or manual trigger.
- Version sources of truth (must move together): `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `skills/shepherd/SKILL.md` frontmatter, `skills/context/SKILL.md` frontmatter, `README.md` header, `CHANGELOG.md`. `shctx release` plans the bump; review the dry-run before letting it execute.

## Repo invariants — v5.0.0 additions

- `.artifacts/root.db` is the per-project SQLite registry. Schema lives in `skills/context/schema/`.
- `.artifacts/shepherd.lock` coordinates concurrent shepherd sessions. Always JSON; never edit by hand.
- `.artifacts/docs/specs/*.spec.md` and `*.design.md` are design documents; track in git. Naming: `YYYY-MM-DD-<topic>-{design|spec}.md`.
- `.artifacts/docs/journal/YYYY-MM-DD.md` are operator-editable daily notes; one file per day, append-mode.
- `.artifacts/logs/events-YYYY-MM-DD.jsonl` are append-only event streams; gitignored.
- `.artifacts/tmp/` and `.artifacts/logs/` are gitignored. `.artifacts/profiles/`, `.artifacts/docs/`, `.artifacts/plans/`, `.artifacts/reports/`, `.artifacts/ctx/` are tracked.
