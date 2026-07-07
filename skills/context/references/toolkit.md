---
title: toolkit
description: |
  Two-tier tool-memory registry plus SessionStart auto-discovery probe for installed
  capabilities. Use when registering, listing, or citing tools/MCP/skills at session
  start or brief injection.
---

# Toolkit — persistent tool-memory + auto-discovery

## Principle

Every time an operator says "you can ssh pzzld@laptop" or "use context7 for library
docs" they pay a re-explanation tax. The toolkit registry removes it mechanically: the
operator registers a tool once; the SessionStart hook and the inject pipeline resurface
it at every session and every planning brief, without prompting. A second, ephemeral
layer — auto-discovery — removes the same tax for capabilities the operator never
wired at all (installed plugins/skills/MCP servers already present in the environment).

## Two tiers — curated `toolkit.json`

| Tier | Path | Scope | Wins on collision |
|---|---|---|---|
| Global | `${XDG_CONFIG_HOME:-$HOME/.config}/shepherd/toolkit.json` | all projects for this user | overridden by local |
| Local | `<workdir>/toolkit.json` | this project only | wins on `name` collision |

Surface time reads both, merges (global ∪ local, local wins), sorts pinned-first, caps
at 12 entries.

**Entry schema** — required: `name` (unique), `scope` (`local`/`global`), `type`
(canonical `mcp`/`skill`/`plugin`/`cli`; other values WARN at `validate`),
`capabilities` (array, empty permitted but WARN), `description`. Optional:
`invocation`, `when`, `tags`, `pinned` (bool, immune to the 12-cap ordering),
`added`. Top-level `version` is always `1`.

## `shctx toolkit` CLI

| Verb | Effect |
|---|---|
| `add --name=<n> --type=<t> --desc="…" [--global] [--pin]` | register (local unless `--global`); refuses a duplicate name in-scope |
| `list [--scope=all\|local\|global]` | full inventory, uncapped |
| `pin <name>` / `unpin` | toggle pinned flag |
| `rm <name> [--global]` | remove |
| `md [--scope=all\|local\|global]` | compact markdown roster (pinned-first, capped 12) — what `inject` calls |

Flag aliases: `--desc`≡`--description`, `--global`≡`--scope=global`,
`--local`≡`--scope=local`.

**Two surfaces consume the registry:** the SessionStart hook
(`hooks/scripts/toolkit_surface.sh`) emits `🧰 Project toolkit (N tool(s))`; and
`shctx inject <engineer|coder|planter>` calls `toolkit md --scope=all` and appends a
`## Toolkit` section to `[DB-CONTEXT]` at the variable tail (cache-prefix preserved —
`skills/shepherd/references/flock.md §Brief assembly`). Both are silent on an empty
merged set.

## Auto-discovery — the ephemeral sibling

`hooks/scripts/capability_discovery.sh` fires at every `SessionStart`, after
`toolkit_surface.sh`. Contract:

- **Config-gated:** `[discovery].auto_capabilities` — `on` (default) / `off`.
- **One-time per session:** a 1h-TTL marker `<ns>/cache/.capdisc-<session>.probed`
  makes it a single cheap pass. **Zero hot-path cost is non-negotiable.**
- **Fail-open:** not-a-shepherd-project, `jq` absent, or any error → silent `exit 0`.
- **Writes an ephemeral roster:** `<ns>/cache/discovered-capabilities.json`
  (gitignored — NEVER the tracked `toolkit.json`).

A hook is not the agent: it directly sees installed plugins/skills/env signals, but
CANNOT see the visible tool list, the specialist-agent list, or deferred MCP/
ToolSearch tools. Those three carry an `agent_fillin` contract asking the agent to
record them on first `/shepherd:*`.

Three surfaces, all read-time merge, never written back, all capped at 12 and
graceful-empty: (1) SessionStart appends "🔎 Auto-discovered capabilities (N,
ephemeral)" after the curated block; (2) `[TOOLKIT]` brief injection appends the same
under `### Auto-discovered capabilities`; (3) `shctx toolkit discovered` on demand.
**Promotion:** the operator promotes a discovered capability into the curated registry
with `shctx toolkit add`; discovery NEVER writes into `toolkit.json`.

**Adaptation memory tie-in:** when a discovered integration measurably helps a sprint
(e.g. a plugin skill breaks a stuck loop), record it as a `feedback_*.md` memory via
`shctx mem add` at close — see `skills/adaptation/SKILL.md §Loop contract` for the
harvest→store→inject→cite mechanism this feeds.

## Curated vs auto-discovered (canonical table)

| | Curated (`toolkit.json`) | Auto-discovered (cache roster) |
|---|---|---|
| Authored by | operator (`shctx toolkit add`) | the SessionStart probe |
| Tracked in git | yes | no (gitignored cache) |
| Surface label | "🧰 Project toolkit" | "🔎 Auto-discovered (ephemeral)" |
| Authority | operator intent | best-effort observation |
| Bound | 12 entries | 12 entries |

## Guarded-integration pattern — "if available, else native"

| Integration | If available | If absent |
|---|---|---|
| `/remember` | record/recall at handoff, CLOSE-FINALIZE, resume | `shctx handoff` + focus rehydrate |
| `superpowers` | brainstorm at plant/mesh; TDD on coder lanes; systematic-debugging on stuck loops | flock-native lanes |
| `pr-review-toolkit` / specialists | surface per specialist-dispatch gating | `@auditor` / `@worker` |

Shepherd MUST NEVER hard-depend on a third-party plugin — every integration needs a
native fallback, and absence MUST degrade cleanly, never error.

## Invariants

- **Bounded** — injected surfaces cap at 12; interactive `list`/`discovered` uncapped.
- **Pinned-first** — pinned entries survive the cap longest.
- **Graceful-empty** — empty registry/roster → no output anywhere.
- **Fail-open** — any hook error → silent no-op, never blocks a session.
- **No silent overwrite** — `toolkit add` on an existing name in-scope errors, directing
  to `rm` first.
- **Curated ≠ discovered, always** — discovery NEVER writes `toolkit.json`.

## What the toolkit is NOT

Not a secrets store (never credentials/tokens/passwords). Not a replacement for
MCP/skill install (registering ≠ wiring). Not auto-invoked (a reminder, not a
trigger). Not a log (no historical snapshots — see `skills/context/SKILL.md §Event
log` for per-session telemetry).

## Elsewhere

Workflow-tool presence, entrypoint truth, and the NEVER-`ToolSearch`-for-`Workflow`
rule are platform-capability content owned by `skills/harness/SKILL.md §Tool
presence` — not restated here.
