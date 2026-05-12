# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A Claude Code plugin and skills repository authored by FL03 (github.com/FL03). It ships two plugins via a self-hosted marketplace manifest at `.claude-plugin/marketplace.json`:

- **`plugins/shepherd`** — Sprint-by-sprint version-cycle conductor. A five-agent flock (engineer, critic, coder, auditor, worker) on a three-section pipeline, driven by a project-local `shepherd.toml`. 

There is no build system. All content is markdown. The "artifacts" are the plugin directories themselves and the zip archives under `skills/skills/`.

## Repository layout

```
plugins/
  shepherd/                    # shepherd plugin source
    .claude-plugin/plugin.json # plugin manifest
    agents/{engineer,critic,coder,auditor,worker}.md
    commands/{plant,start,autorun,parallel}.md
    skills/shepherd/           # conductor quick-reference + doctrines
    docs/                      # operator docs (configuration, integration, customization)
    examples/                  # axiom + minimal binding examples
  fl03-skills/                 # fl03-skills plugin source
    .claude-plugin/plugin.json
    skills/{code-style,rust,webassembly,finance,polymarket,trader,workflow,shepherd}/

skills/
  skills/                      # zipped distribution archives (per-skill .zip)
  shepherd.zip                 # shepherd plugin zip (root-level)
  .archive/                    # dated snapshots

.claude-plugin/
  marketplace.json             # marketplace manifest — lists both plugins
```

## Installing locally

```bash
# Symlink shepherd into user plugin directory
ln -s "$PWD/plugins/shepherd" ~/.claude/plugins/shepherd

# Or register the whole marketplace (both plugins)
mkdir -p ~/.claude/plugins/marketplaces/fl03
cp -r ./.claude-plugin ~/.claude/plugins/marketplaces/fl03/
cp -r ./plugins ~/.claude/plugins/marketplaces/fl03/
```

The `.claude/settings.local.json` pre-approves the `cp -r` commands above for one-shot installation.

## Shepherd plugin commands

| Command | Model required | What it does |
|---|---|---|
| `/shepherd:plant [scope]` | **Opus** | Author drift-resistant sprint seeds upstream of execution |
| `/shepherd:start` | Sonnet | Run one sprint end-to-end, then pause |
| `/shepherd:autorun` | Sonnet | Run sprints sequentially with no inter-sprint pause |
| `/shepherd:parallel` | Sonnet | Fan out multiple disjoint sprints across git worktrees |

Shepherd is project-agnostic. Each consumer project configures it via `.claude/shepherd.toml`. The full schema is at `plugins/shepherd/docs/configuration.md`. A working example lives at `plugins/shepherd/examples/axiom/shepherd.toml`.

## Shepherd file contracts

When editing shepherd, these invariants must hold:

- **`plugins/shepherd/skills/shepherd/SKILL.md`** is the conductor quick reference — the entry point for every `/shepherd:*` invocation. All runtime references resolve relative to `${CLAUDE_PLUGIN_ROOT}`.
- **`plugins/shepherd/.claude-plugin/plugin.json`** and **`plugins/fl03-skills/.claude-plugin/plugin.json`** are the plugin manifests — version bumps here must stay in sync with `README.md`.
- **`plugins/shepherd/agents/<role>.md`** — each file is the full system prompt injected into the corresponding flock-agent brief. Do not abbreviate or inline these; the conductor reads them at dispatch time.
- **`plugins/shepherd/skills/shepherd/doctrines/*.md`** — framework-intrinsic rules. New doctrines go here; project-specific doctrines go in the consumer repo's `.claude/doctrines/`.
- **`skills/skills/*.zip`** — distribution zips are manually re-packaged after changes. They are not auto-generated.
- `.artifacts/styles/<lang>.md` are project-local code style overrides; tracked in git. Languages: rust, python, typescript, go, shell, sql. Bundled defaults at `plugins/shepherd/skills/context/styles/`. The conductor auto-injects these into every coder brief whose `[FILE-SCOPE]` matches.
- The flock remains closed at five (engineer, critic, coder, auditor, worker). Non-code work goes to `@worker` per `doctrines/worker-patterns.md`.

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

## Sprint orchestration (when using shepherd in this repo)

This repo does not currently have its own `shepherd.toml` — shepherd is the *product*, not the *consumer* here. If you ever run a shepherd sprint on this repo, create `.claude/shepherd.toml` first (see `plugins/shepherd/examples/minimal/shepherd.toml` for a template).

## Versioning

- Shepherd follows semver. MAJOR = closed-flock contract change. MINOR = new commands/doctrines/config keys. PATCH = dispatch logic / brief template fixes.
- Both plugins are versioned independently (`plugin.json` + `README.md`).
- Tag format: `v{X}.{Y}.{Z}` (e.g. `v4.0.0`). Docker image is published via `.github/workflows/docker.yml` on `repository_dispatch` or manual trigger.

## Repo invariants — v5.0.0 additions

- `.artifacts/root.db` is the per-project SQLite registry. Schema lives in `plugins/shepherd/skills/context/schema/`.
- `.artifacts/shepherd.lock` coordinates concurrent shepherd sessions. Always JSON; never edit by hand.
- `.artifacts/docs/specs/*.spec.md` and `*.design.md` are design documents; track in git. Naming: `YYYY-MM-DD-<topic>-{design|spec}.md`.
- `.artifacts/docs/journal/YYYY-MM-DD.md` are operator-editable daily notes; one file per day, append-mode.
- `.artifacts/logs/events-YYYY-MM-DD.jsonl` are append-only event streams; gitignored.
- `.artifacts/tmp/` and `.artifacts/logs/` are gitignored. `.artifacts/profiles/`, `.artifacts/docs/`, `.artifacts/plans/`, `.artifacts/reports/`, `.artifacts/ctx/` are tracked.
