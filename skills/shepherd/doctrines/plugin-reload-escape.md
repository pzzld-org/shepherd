---
title: plugin reload escape hatch
description: |
  When MCP tools listed in shepherd.toml aren't loadable at session start, the
  operator can run /reload-plugins to refresh the catalog. The conductor MUST
  flag tool unavailability explicitly rather than silently degrading to shell
  fallbacks.
introduced: v5.0.9
field_origin: shepherd v5.0.8 conductor feedback (axiom v0.3.2-dev.0) §8
---

# Doctrine — Plugin Reload Escape Hatch

## What this is

`/reload-plugins` is a Claude Code operator command that refreshes the MCP
tool catalog for the current session without restarting the session. It re-
discovers which MCP servers are loadable, re-fetches their tool schemas, and
makes their tools callable.

It is an **operator-level escape hatch**, not a conductor-triggered operation.
The conductor cannot call `/reload-plugins` itself — it can only flag the need
and wait for the operator to run it.

## When to flag (conductor behavior)

At session start, after loading `shepherd.toml`, the conductor reads
`[mcp]` keys (e.g., `mcp.supabase = true`, `mcp.sentry = true`) and
verifies that the corresponding tool prefixes are callable.

A practical check:

```
# Verify mcp.supabase tools are available:
# Try to list mcp__plugin_supabase_supabase__* — if no tool found → flag
```

If a tool listed as `true` in `[mcp]` is not loadable:

**Surface this explicitly to the operator:**

```
[SHEPHERD] MCP tool unavailability detected:
  • mcp.supabase = true but mcp__plugin_supabase_supabase__* tools are not
    visible in this session.
Run /reload-plugins to refresh the tool catalog. If tools remain unavailable
after reload, shepherd will fall back to CLI/shell equivalents (degraded mode).
```

Do NOT silently degrade to shell fallbacks without this alert. Silent
degradation hides the misconfiguration and produces lower-quality mesh results
(shell psql cannot match the structured row arrays and advisor findings that
the Supabase MCP tools return).

## After the operator runs /reload-plugins

Once the operator confirms reload is complete:

1. Re-verify the `[mcp]` tool availability.
2. If tools are now loadable: proceed normally; note "MCP tools active" in
   the Phase 0 mesh report.
3. If tools are still unavailable after reload: degrade gracefully, noting
   which surfaces are unavailable in the mesh report. The conductor uses
   CLI/shell equivalents and annotates findings accordingly.

## Phase 0 mesh behavior (Supabase example — §7 field feedback)

Per the v5.0.8 field report: when `mcp.supabase = true` but the Supabase
MCP tools weren't loaded, the conductor fell back to `psql "$DATABASE_URL_NON_POOLING"`.
After a `/reload-plugins` run, the proper tools became available.

The preferred ordering for Supabase mesh access is:

1. `mcp__plugin_supabase_supabase__execute_sql` (structured, safe, advisory-aware)
2. `mcp__plugin_supabase_supabase__get_advisors` (security + performance advisors)
3. Shell `psql` (degraded fallback only — flag it in the mesh report)

This preference holds for any MCP surface: always prefer the structured MCP
tool over a shell equivalent; flag when the MCP is unavailable; reload before
falling back.

## See also

- `pipeline.md §XV-quint` — Supabase MCP preference note in Phase 0
- `agents/engineer.md` — Phase 0 mesh, MCP availability verification
- `doctrines/use-mcp-not-cli.md` — the underlying MCP-first principle
