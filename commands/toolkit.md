---
name: toolkit
description: Surface and manage the project toolkit registry — MCP servers, CLI targets, skills, plugins. Keeps Claude tool-aware every session without re-explanation.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Skill
---

# /shepherd:toolkit — Toolkit Registry

Thin command shim. The registry contract is documented at
`${CLAUDE_PLUGIN_ROOT}/skills/shepherd/doctrines/toolkit.md`.

## Background

The toolkit is a two-tier tool-memory registry:

- **Local** — `<workdir>/toolkit.json` (project-specific; version-controlled)
- **Global** — `${XDG_CONFIG_HOME:-$HOME/.config}/shepherd/toolkit.json`
  (user-wide; all projects)

At every `SessionStart`, `hooks/scripts/toolkit_surface.sh` merges both tiers
and injects a compact roster into Claude's context — pinned entries first, cap
12. `shctx inject engineer|coder|planter` appends the same roster to each
planning brief. The payoff: Claude begins every session already knowing "you
can ssh pzzld@laptop" or "use context7 for library docs" — no re-telling.

## Step 0 — Orient

Resolve the CLI path: `${CLAUDE_PLUGIN_ROOT}/skills/context/scripts/shctx`.

## Step 1 — Run

Pass arguments through to `shctx toolkit`. Common invocations:

**Inspect:**
- `shctx toolkit list` — show local toolkit
- `shctx toolkit list --scope=all` — show merged global ∪ local view
- `shctx toolkit md --scope=all` — emit the compact markdown roster (what
  the hook and inject pipeline surface to Claude)

**Add / remove:**
- `shctx toolkit add <name> --type=<mcp|cli|skill|plugin|api> --desc="…"` —
  register a tool in the local registry
- `shctx toolkit add <name> --type=cli --desc="…" --global` — register
  user-wide (global tier)
- `shctx toolkit rm <name>` — remove from local registry
- `shctx toolkit rm <name> --global` — remove from global registry

**Pin / unpin:**
- `shctx toolkit pin <name>` — pin entry (always surfaces first; immune to
  12-entry cap ordering)
- `shctx toolkit unpin <name>` — remove pin

## Notes

- The `SessionStart` hook auto-surfaces the merged toolkit every session;
  no manual invocation needed for day-to-day use.
- `toolkit.json` is **not** a secrets store — never put credentials or API
  keys in it.
- Registering a tool here does not install it. MCP servers must still be
  configured in `~/.claude/settings.json`; skills must be installed via
  `/plugin install`.
- For the full entry schema and worked examples, read
  `skills/shepherd/doctrines/toolkit.md`.
