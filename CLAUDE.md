# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A dedicated repository for the **shepherd** Claude Code plugin, authored by FL03 (github.com/FL03). The plugin lives at the repo root — the repo *is* the plugin. A self-hosted marketplace manifest at `.claude-plugin/marketplace.json` makes it installable via `/plugin marketplace add fl03/shepherd`.

Shepherd is a sprint-by-sprint version-cycle conductor. A five-agent flock (engineer, critic, coder, auditor, worker) on a three-section pipeline (INTRODUCTION → BODY → CLOSE), driven by a project-local `shepherd.toml` in each consumer repo.

There is no build system. Plugin assets are markdown briefs, YAML frontmatter, and shell scripts under `skills/context/scripts/` (the `shctx` runtime).

## Repository layout

```
.claude-plugin/
  plugin.json                  # shepherd plugin manifest (this repo IS the plugin)
  marketplace.json             # single-plugin marketplace; source = "."

agents/{engineer,critic,coder,auditor,worker}.md   # full system prompts per flock lane
commands/{plant,start,autorun,parallel,ctx}.md     # slash-command entry points
docs/                          # operator docs (configuration, integration, customization)
examples/{axiom,minimal}/      # binding examples (shepherd.toml + CLAUDE-snippet)

skills/
  shepherd/                    # conductor quick-reference + doctrines + references
    SKILL.md                   # entry point for every /shepherd:* invocation
    {flock,pipeline,planter,autorun,parallel}.md
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

| Command | Model required | What it does |
|---|---|---|
| `/shepherd:plant [scope]` | **Opus** | Author drift-resistant sprint seeds upstream of execution |
| `/shepherd:start` | Sonnet | Run one sprint end-to-end, then pause |
| `/shepherd:autorun` | Sonnet | Run sprints sequentially with no inter-sprint pause |
| `/shepherd:parallel` | Sonnet | Fan out multiple disjoint sprints across git worktrees |
| `/shepherd:ctx` | Sonnet | Inspect / refresh the per-project SQLite context registry |

Shepherd is project-agnostic. Each consumer project configures it via `.claude/shepherd.toml`. The full schema is at `docs/configuration.md`. A working example lives at `examples/axiom/shepherd.toml`; a stripped-down template at `examples/minimal/shepherd.toml`.

## Shepherd file contracts

When editing shepherd, these invariants must hold:

- **`skills/shepherd/SKILL.md`** is the conductor quick reference — the entry point for every `/shepherd:*` invocation. All runtime references resolve relative to `${CLAUDE_PLUGIN_ROOT}` (which is the repo root, post-migration).
- **`.claude-plugin/plugin.json`** is the plugin manifest. Version bumps must stay in sync with `README.md`, `skills/shepherd/SKILL.md` frontmatter, `skills/context/SKILL.md` frontmatter, `.claude-plugin/marketplace.json`, and `CHANGELOG.md`. `shctx release` automates this; see `skills/context/scripts/cmd_release.sh`.
- **`agents/<role>.md`** — each file is the full system prompt injected into the corresponding flock-agent brief. Do not abbreviate or inline these; the conductor reads them at dispatch time.
- **`skills/shepherd/doctrines/*.md`** — framework-intrinsic rules. New doctrines go here; project-specific doctrines go in the consumer repo's `.claude/doctrines/`.
- **`skills/context/styles/<lang>.md`** are the bundled per-language style defaults shipped with the plugin. `shctx style init <lang>` copies them into a consumer project's `.artifacts/styles/<lang>.md`. The conductor auto-injects the project-local copy into every coder brief whose `[FILE-SCOPE]` matches.
- The flock remains closed at five (engineer, critic, coder, auditor, worker). Non-code work goes to `@worker` per `skills/shepherd/doctrines/worker-patterns.md`.

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
- Tag format: `v{X}.{Y}.{Z}` (e.g. `v5.0.4`). Docker image is published via `.github/workflows/docker.yml` on `repository_dispatch` or manual trigger.
- Version sources of truth (must move together): `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `skills/shepherd/SKILL.md` frontmatter, `skills/context/SKILL.md` frontmatter, `README.md` header, `CHANGELOG.md`. `shctx release` plans the bump; review the dry-run before letting it execute.

## Repo invariants — v5.0.0 additions

- `.artifacts/root.db` is the per-project SQLite registry. Schema lives in `skills/context/schema/`.
- `.artifacts/shepherd.lock` coordinates concurrent shepherd sessions. Always JSON; never edit by hand.
- `.artifacts/docs/specs/*.spec.md` and `*.design.md` are design documents; track in git. Naming: `YYYY-MM-DD-<topic>-{design|spec}.md`.
- `.artifacts/docs/journal/YYYY-MM-DD.md` are operator-editable daily notes; one file per day, append-mode.
- `.artifacts/logs/events-YYYY-MM-DD.jsonl` are append-only event streams; gitignored.
- `.artifacts/tmp/` and `.artifacts/logs/` are gitignored. `.artifacts/profiles/`, `.artifacts/docs/`, `.artifacts/plans/`, `.artifacts/reports/`, `.artifacts/ctx/` are tracked.
