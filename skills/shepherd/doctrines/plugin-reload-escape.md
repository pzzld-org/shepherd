---
title: plugin reload escape hatch
description: |
  When MCP tools declared in shepherd.toml [mcp] are not loadable at session
  start, the operator runs /reload-plugins to refresh the catalog. The
  conductor flags unavailability explicitly rather than silently falling back
  to shell — degraded surfaces produce lower-fidelity mesh evidence.
introduced: v5.0.9
field_origin: shepherd v5.0.8 conductor feedback (downstream Rust service) §7, §8
---

# Doctrine — /reload-plugins Escape Hatch

## What it is

`/reload-plugins` is an **operator-only** Claude Code command that re-
discovers MCP servers and re-fetches their tool schemas without restarting
the session. The conductor cannot call it; it can only flag the need.

## When the conductor flags it

At session open, after reading `shepherd.toml`, for each `[mcp].<surface> =
true` whose tool prefix (`mcp__plugin_<surface>__*`) is not visible:

```
[SHEPHERD] MCP tool unavailability detected:
  • mcp.<surface> = true but mcp__plugin_<surface>__* tools are not visible.
Run /reload-plugins to refresh the tool catalog. If still unavailable after
reload, shepherd degrades to CLI/shell fallback (lower fidelity).
```

**Do NOT silently degrade.** Shell `psql`, `sentry-cli`, etc. cannot match the
structured row arrays + advisor findings the MCP tools return; silent fallback
hides the misconfiguration and produces weaker Phase 0 mesh evidence.

## After reload

1. Re-check tool visibility.
2. If now loadable → proceed; note "MCP <surface> active" in Phase 0 mesh.
3. If still unavailable → degrade to CLI/shell, annotate the mesh report
   with the degraded surface so the operator can fix it post-sprint.

## MCP-first preference (the rank)

For any surface (Supabase shown; same shape applies to Sentry, etc.):

1. `mcp__plugin_supabase_supabase__execute_sql` — structured, safe, advisory-aware
2. `mcp__plugin_supabase_supabase__get_advisors` — security + perf advisors
3. Shell `psql` — degraded fallback only; flag it

## See also

- `pipeline.md §XV-sept` — Phase 0 MCP availability + reload reference
- `doctrines/use-mcp-not-cli.md` — underlying MCP-first principle
- `agents/engineer.md §Phase 0` — mesh-row MCP probe ordering
