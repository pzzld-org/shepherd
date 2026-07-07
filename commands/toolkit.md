---
name: toolkit
description: Surface and manage the project toolkit registry — MCP servers, CLI targets, skills, plugins. Keeps Claude tool-aware every session without re-explanation.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Skill
---

# /shepherd:toolkit — Toolkit Registry

Thin command shim. The full CLI contract is documented at
`${CLAUDE_PLUGIN_ROOT}/skills/context/references/toolkit.md`.

## Background

Two-tier tool-memory registry: **local** `<workdir>/toolkit.json` (project-specific,
version-controlled) and **global** `${XDG_CONFIG_HOME:-$HOME/.config}/shepherd/toolkit.json`
(user-wide). Every `SessionStart`, `hooks/scripts/toolkit_surface.sh` merges both tiers and
injects a compact roster — pinned entries first, cap 12. `shctx inject engineer|coder|planter`
appends the same roster to planning briefs.

## Step 0 — Orient

Resolve the CLI path: `${CLAUDE_PLUGIN_ROOT}/skills/context/scripts/shctx`.

## Step 1 — Run

Pass arguments through to `shctx toolkit`.

**Inspect:**
- `shctx toolkit list` — show local toolkit
- `shctx toolkit list --scope=all` — merged global ∪ local view
- `shctx toolkit md --scope=all` — compact markdown roster (what the hook and inject pipeline surface)

**Add / remove:**
- `shctx toolkit add --name=<name> --type=<mcp|cli|skill|plugin> --desc="…" [--capabilities=a,b]` — register in the local registry. `--name`/`--type`/`--description` are required; `--desc` aliases `--description`.
- `shctx toolkit add --name=<name> --type=cli --desc="…" --global` — register user-wide. `--global` aliases `--scope=global`.
- `shctx toolkit rm <name>` / `shctx toolkit rm <name> --global` — remove from local / global registry.

**Pin / unpin:**
- `shctx toolkit pin <name>` — pin entry (surfaces first; immune to the 12-entry cap ordering)
- `shctx toolkit unpin <name>` — remove pin

## Notes

- The `SessionStart` hook auto-surfaces the merged toolkit every session; no manual invocation needed for day-to-day use.
- `toolkit.json` is NEVER a secrets store — never put credentials or API keys in it.
- Registering a tool here does NOT install it. MCP servers still need `~/.claude/settings.json`; skills still need `/plugin install`.
- Full entry schema and worked examples: `skills/context/references/toolkit.md`.
