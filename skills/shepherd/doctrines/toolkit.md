---
title: toolkit
description: |
  The operator registers tools once; shepherd re-surfaces them every session.
  A project-local toolkit.json and a user-global counterpart form two tiers of
  tool-memory — MCP servers, CLI targets, skills, plugins — merged and injected
  into Claude's context at SessionStart and into engineer/coder/planter briefs.
  Bounded, graceful-empty, never a secrets store.
introduced: v6.1.2
---

# Toolkit — persistent tool-memory, surfaced every session

## Principle

Every time a user tells Claude "you can ssh pzzld@laptop" or "use context7 for
library docs" they are paying a re-explanation tax. The toolkit registry
eliminates that tax **mechanically**: the operator registers a tool once; the
SessionStart hook and the inject pipeline resurface it at every session and at
every planning/seeding brief, without prompting.

This is the tool-memory sibling of the adaptation loop's sprint-pattern memory
and the self-improvement loop's prior-lesson memory. All three answer the same
question differently — *what does the flock need to remember across sessions?*
See `doctrines/adaptation-loop.md` and `doctrines/self-improvement.md`.

---

## Two tiers — scope-routed

| Tier | Path | Scope | Wins on collision |
|---|---|---|---|
| **Global** | `${XDG_CONFIG_HOME:-$HOME/.config}/shepherd/toolkit.json` | `"scope":"global"` — all projects for this user | Overridden by local |
| **Local** | `<workdir>/toolkit.json` (`resolve_namespace` precedence) | `"scope":"local"` — this project only | Wins on name collision |

At surface time both files are read, merged (global ∪ local, local wins on
`name` collision), sorted pinned-first, and capped at 12 entries for the
session header — keeping the injection frugal per
`doctrines/brief-cache-discipline.md`.

---

## Entry schema

Required fields (enforced by `shctx toolkit validate` and the JSON schema):

| Field | Type | Meaning |
|---|---|---|
| `name` | string | Unique identifier; collision key for merge |
| `scope` | string | `"local"` or `"global"` (`add` defaults to `local`) |
| `type` | string | Canonical: `mcp` / `skill` / `plugin` / `cli`. Other values (e.g. `api`, `service`) are permitted but `validate`-flagged with a WARN |
| `capabilities` | array | Short capability tags (e.g. `["library-docs"]`). Must be present; an empty array is permitted but `validate`-warned |
| `description` | string | One-line human description (surfaced verbatim) |

> When authoring `toolkit.json` by hand, include all five required fields. The
> `add` subcommand fills `scope` (default `local`) and `capabilities` (default
> `[]`) for you, so `--name`, `--type`, and `--description` are the only
> mandatory flags.

Optional fields:

| Field | Type | Meaning |
|---|---|---|
| `invocation` | string | How to call it (e.g. `mcp__Context7__query-docs`) |
| `when` | string | Heuristic guidance — when to reach for this tool |
| `tags` | array | Free-form labels |
| `pinned` | bool | `true` → always surfaces first; immune to the 12-cap ordering |
| `added` | string | ISO date added (informational) |

Top-level file shape (version is always `1`):

```json
{
  "version": 1,
  "scope": "local",
  "updated_at": 1749600000,
  "tools": [ … ]
}
```

---

## Three surfaces

### 1. SessionStart hook auto-reminder

`hooks/scripts/toolkit_surface.sh` fires at every `SessionStart`. It merges
global ∪ local, sorts pinned entries first, caps at 12, and emits:

```
🧰 Project toolkit (N tool(s)) — consult before assuming a capability is unavailable:
• context7 (mcp) — fetch current library documentation on demand
• pzzld-laptop (cli) — ssh pzzld@laptop — self-hosted dev surface
```

Empty merged set → silent exit 0 (graceful, no noise, today's behavior
preserved). Honors `[hooks].quiet_warnings = true` via `emit_context`.

### 2. `shctx toolkit` CLI

The `shctx toolkit` subcommand manages the registry:

| Verb | Effect |
|---|---|
| `shctx toolkit add --name=<n> --type=<t> --desc="…" [--global] [--pin]` | Register a tool in local (or global with `--global`) registry. `--name`/`--type`/`--description` required; refuses a duplicate name in-scope |
| `shctx toolkit list [--scope=all\|local\|global]` | Show registered tools (full inventory — uncapped) |
| `shctx toolkit pin <name>` / `unpin` | Toggle pinned flag |
| `shctx toolkit rm <name> [--global]` | Remove a tool |
| `shctx toolkit md [--scope=all\|local\|global]` | Emit compact markdown roster (used by inject — pinned-first, capped at 12) |

> Flag aliases: `--desc` ≡ `--description`; `--global` ≡ `--scope=global`;
> `--local` ≡ `--scope=local`.

### 3. `[TOOLKIT]` brief injection — engineer, coder, planter

`shctx inject <role>` calls `shctx toolkit md --scope=all` and, when non-empty,
appends a `## Toolkit (available tools — consult before assuming unavailable)`
section to the `[DB-CONTEXT]` block for **engineer**, **coder**, and
**planter** roles. Appended at the variable tail (after priors/recommend) so
the cacheable prefix is preserved per `doctrines/brief-cache-discipline.md`.

---

## Bounded & graceful — the invariants

- **Bounded:** the injected surfaces (the SessionStart hook and `md`, which
  feeds brief injection) cap at 12 entries to prevent context bloat. Interactive
  `list` is uncapped — it is the full inventory on demand.
- **Pinned-first:** pinned entries sort ahead of unpinned at every surface, so
  within the 12-entry cap they are the last to be dropped. (If a registry ever
  holds more than 12 *pinned* entries, the cap still applies after the
  pinned-first sort — pin sparingly.)
- **Graceful-empty:** an empty merged toolkit produces no output at any surface
  point. Empty toolkit == today's behavior everywhere. No operator action
  required on cold projects.
- **Fail-open:** the hook exits 0 on any error (missing `jq`, malformed JSON,
  unreadable file). Tool-memory failure must never block a session.
- **No silent overwrite:** `shctx toolkit add` on an existing name in the same
  scope fails with an error directing you to `rm` first. This prevents a typo
  from clobbering a registered tool; it never silently duplicates or replaces.

---

## Worked example — global file

`~/.config/shepherd/toolkit.json`:

```json
{
  "version": 1,
  "scope": "global",
  "updated_at": 1749600000,
  "tools": [
    {
      "name": "context7",
      "scope": "global",
      "type": "mcp",
      "capabilities": ["library-docs"],
      "description": "fetch current library documentation on demand",
      "invocation": "mcp__Context7__query-docs",
      "when": "any library API / framework / SDK question — prefer over web search",
      "tags": ["docs"],
      "pinned": true,
      "added": "2026-06-11"
    },
    {
      "name": "pzzld-laptop",
      "scope": "global",
      "type": "cli",
      "description": "ssh pzzld@laptop — self-hosted dev surface (build server, local services)",
      "invocation": "ssh pzzld@laptop",
      "when": "running builds, checking local services, inspecting files on the dev machine",
      "tags": ["ssh", "self-hosted"],
      "pinned": false,
      "added": "2026-06-11"
    }
  ]
}
```

At session start Claude sees both entries. In a project that has its own
`toolkit.json` with a `context7` entry, the local definition wins; `pzzld-laptop`
merges in unchanged.

---

## Curated vs auto-discovered (v6.2.0, #146)

The toolkit registry is **operator-curated** — deliberate, version-controlled
intent. As of v6.2.0 it has an **ephemeral sibling**: the SessionStart
`capability_discovery.sh` probe enumerates capabilities present in the
environment (installed plugins, skills) and writes them to a gitignored
`<workdir>/cache/discovered-capabilities.json` roster. The two are surfaced
together but kept **strictly distinct**:

| | Curated (`toolkit.json`) | Auto-discovered (cache roster) |
|---|---|---|
| Authored by | operator (`shctx toolkit add`) | the SessionStart probe |
| Tracked | yes (git) | no (gitignored cache) |
| Label at surface | "🧰 Project toolkit" | "🔎 Auto-discovered (ephemeral)" |
| Authority | operator intent | best-effort observation |

Discovery **never** writes into `toolkit.json` — it must not silently overwrite
intent. When a discovered capability proves persistently useful, the operator
*promotes* it by registering it with `shctx toolkit add`. See
`doctrines/capability-discovery.md` for the full probe contract, the
guarded-integration pattern, and the degrade-cleanly guardrails.

**Guarded-integration shorthand:** *if* `/remember` is auto-discovered, use it
at handoff / CLOSE-FINALIZE and on resume; *else* fall back to shepherd-native
handoff records. The same "if available, else native" shape applies to every
opportunistic integration — shepherd never hard-depends on a third-party plugin.

---

## What the toolkit is NOT

- **Not a secrets store.** Never put credentials, API keys, tokens, or passwords
  in `toolkit.json`. It is checked into the project (local scope) or stored in
  the user config tree — neither location is secret. Tool invocation strings
  (`invocation`) should be safe to surface in context.
- **Not a replacement for MCP/skill config.** Registering a tool here does not
  install it or wire it up. The MCP server must be configured in
  `~/.claude/settings.json`; the skill must be installed. The toolkit entry is a
  *memory guide* that tells Claude the tool exists and when to reach for it.
- **Not auto-invoked.** A toolkit entry is a reminder, not a trigger. Claude
  reads the roster and decides — the toolkit does not silently call tools on
  the operator's behalf.
- **Not a log.** The toolkit is a living registry; historical snapshots are not
  kept. For per-session tool-call telemetry see `doctrines/hook-event-log.md`.

---

## Cross-doctrine references

- `doctrines/adaptation-loop.md` — sprint-pattern memory sibling (#94); both
  live on bounded registries surfaced at session/plan open
- `doctrines/self-improvement.md` — prior-lesson memory sibling (#95); same
  graceful-empty / bounded contract
- `doctrines/brief-cache-discipline.md` — why toolkit injection is appended at
  the variable tail (cache-prefix preservation)
- `doctrines/sqlite-canonical-state.md` — `toolkit.json` is NOT in the DB; it
  is a flat JSON file managed by `shctx toolkit`, intentionally outside SQLite
  so it can be version-controlled and edited directly
- `doctrines/capability-discovery.md` — the ephemeral auto-discovery sibling
  (#146): the SessionStart probe, the curated-vs-ephemeral distinction, the
  guarded-integration pattern, and the Workflow-tool-presence detection tie-in
