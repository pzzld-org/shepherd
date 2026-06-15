---
title: capability-discovery
description: |
  Shepherd auto-detects the Claude Code plugins/skills/tools available in the
  current environment and adapts to them — surfacing and integrating them
  without the operator wiring anything. A cheap one-time SessionStart probe
  writes an EPHEMERAL capability roster, kept strictly DISTINCT from the
  curated toolkit.json, that the [TOOLKIT] surfaces merge in (clearly labeled
  auto-discovered). Guarded integrations degrade cleanly when a plugin is
  absent; shepherd never hard-depends on a third-party plugin. The probe also
  records native Workflow-tool presence so spawn/loop degrade to in-context
  Agent(...) when it is omitted (web/remote sessions). Zero hot-path cost.
introduced: v6.1.5
---

# Capability Discovery — adapt to what's actually available

> Origin: v6.1.5 (#146). Operator: "Shepherd should auto-detect the Claude Code
> plugins/skills available in the current environment and adapt to them —
> surfacing and integrating them without the operator wiring anything."

## Principle

The toolkit registry (`doctrines/toolkit.md`) is **operator-curated**: the
operator registers a tool once and shepherd resurfaces it. But every session
also runs inside an *environment* that carries capabilities the operator never
wired — installed plugins (`/remember`, `superpowers`, `pr-review-toolkit`),
skills, MCP servers. Capability discovery makes adopting those **automatic**:
a cheap probe enumerates what is present and shepherd adapts, without the
operator wiring anything and without ever hard-depending on a plugin.

This is the discovery sibling of the curated toolkit (`doctrines/toolkit.md`),
the adaptation loop's sprint-pattern memory (`doctrines/adaptation-loop.md`),
and the self-improvement loop's lesson memory (`doctrines/self-improvement.md`)
— all answer *what does the flock need to remember / observe across sessions?*

---

## I. The probe — `capability_discovery.sh` (SessionStart)

`hooks/scripts/capability_discovery.sh` fires at every `SessionStart`, registered
after `toolkit_surface.sh`. Its contract:

- **Config-gated:** `[discovery].auto_capabilities` — `on` (default) | `off`.
  Off only when explicitly set to a false-y value (`off`/`false`/`0`/`no`).
- **One-time per session:** a short-TTL marker (`<ns>/cache/.capdisc-<session>.probed`,
  TTL 1h) makes the probe a single cheap pass per session — **ZERO hot-path
  cost is non-negotiable**. Re-fires only after the marker ages out.
- **Fail-open everywhere:** not-a-shepherd-project, `jq` absent, any error →
  silent `exit 0`. Discovery failure must never block a session.
- **Writes an EPHEMERAL roster:** `<ns>/cache/discovered-capabilities.json`
  (gitignored cache — NEVER the tracked `toolkit.json`).

### What a hook CAN vs CANNOT see (honest enumeration)

A SessionStart hook is **not the agent**. It cannot inspect the agent's visible
tool list and it cannot call `ToolSearch`. The probe is honest about this:

| | The hook records it |
|---|---|
| Installed plugins (`~/.claude/plugins/*`, marketplace tree) | ✅ directly |
| Installed skills (`~/.claude/skills/*`, project `.claude/skills/*`) | ✅ directly |
| Env signals (e.g. `CLAUDE_CODE_ENTRYPOINT` web/remote hint) | ✅ directly |
| **The visible tool list** (is `Workflow` present?) | ❌ — agent fills in |
| **Deferred tools** (specialist agents/MCP via `ToolSearch`) | ❌ — agent fills in |

For the rows the hook cannot enumerate, the roster carries an `agent_fillin`
contract — a documented hand-off asking the agent to record those on first
`/shepherd:*` (see §IV). This keeps the probe cheap and the enumeration honest.

---

## II. The ephemeral roster vs the curated toolkit

The two layers are surfaced together but kept **strictly distinct** — discovery
must never silently overwrite operator intent:

| | Curated (`toolkit.json`) | Auto-discovered (cache roster) |
|---|---|---|
| Authored by | operator (`shctx toolkit add`) | the SessionStart probe |
| Tracked in git | yes | no (gitignored cache) |
| Surface label | "🧰 Project toolkit" | "🔎 Auto-discovered (ephemeral)" |
| Authority | operator intent | best-effort observation |
| Bound | 12 entries | 12 entries |

Roster shape (`<ns>/cache/discovered-capabilities.json`):

```json
{
  "version": 1,
  "source": "auto-discovered",
  "probed_at": 1750000000,
  "session_id": "…",
  "capabilities": [
    { "name": "superpowers", "type": "plugin",
      "description": "brainstorming / TDD / systematic-debugging skills — route at the right seams",
      "capabilities": ["brainstorming","tdd","debugging"],
      "source": "auto", "origin": "plugins:superpowers" }
  ],
  "count": 1,
  "agent_fillin": { "workflow_tool": { "present": null, … }, "deferred_specialists": { … } }
}
```

**Promotion path:** when a discovered capability proves persistently useful,
the operator *promotes* it into the curated registry with `shctx toolkit add`.
Discovery never does this automatically.

---

## III. Surfacing — three places, all read-time merge, all bounded

The ephemeral roster is merged with the curated toolkit **at read time**,
clearly labeled, never written back:

1. **SessionStart roster** — `hooks/scripts/toolkit_surface.sh` appends a
   "🔎 Auto-discovered capabilities (N, ephemeral — NOT operator-curated)"
   section after the curated "🧰 Project toolkit" block. Either block may be
   empty independently; silent only when BOTH are empty.
2. **`[TOOLKIT]` brief injection** — `shctx inject {engineer,coder,planter}`
   appends a "### Auto-discovered capabilities (ephemeral — NOT operator-curated)"
   block at the variable tail (cache-prefix preserved per
   `doctrines/brief-cache-discipline.md`).
3. **CLI** — `shctx toolkit discovered` emits the same compact markdown on
   demand (read-only; graceful-empty).

All three are capped at 12 and graceful-empty (no probe / empty roster ⇒ no
output) — identical to the curated toolkit's bounded contract.

---

## IV. Guarded-integration pattern — "if available, else native"

Doctrines reference opportunistic integrations **guardedly** so behavior
degrades cleanly when a plugin is absent. The shape is always *if X is
available, use it; else shepherd-native*:

| Integration | If available | If absent (degrade) |
|---|---|---|
| **`/remember`** (memory continuity) | record/recall at handoff, CLOSE-FINALIZE, and on resume | shepherd-native handoff records (`shctx handoff`) + focus rehydrate |
| **`superpowers`** (brainstorming / TDD / systematic-debugging) | route at the right seams — brainstorm at plant/mesh, TDD on coder lanes, systematic-debugging on stuck loops | flock-native lanes (`@engineer` mesh, `@coder` tests, `@worker` triage) |
| **`pr-review-toolkit`** / specialist agents | surface per `doctrines/specialist-dispatch.md` Q3 (augmentation, not replacement) | `@auditor` / `@worker` flock lanes |

The rule is binding: **NEVER hard-depend on a third-party plugin.** Every
integration must have a shepherd-native fallback, and the absence of the plugin
must be a clean degrade, not an error.

---

## V. Workflow-tool-presence detection (#146 — the structural fix)

`references/glossary.md` once asserted the native `Workflow` tool is "always
present" on a supporting build. It is not: **Claude-Code-on-the-web /
remote-execution sessions omit it even on a supporting build** (presence is
environment-dependent). The probe folds this in:

- The hook records an **env hint** (`agent_fillin.workflow_tool.env_hint`):
  `likely-omitted` for web/remote entrypoints, `likely-present-verify`
  otherwise. This is advisory only.
- The **agent confirms** presence by the one authoritative test — *is `Workflow`
  in the visible tool list?* — and records `present: true|false`. The hook
  cannot do this (it is not the agent).
- When **absent**, `/shepherd:spawn` and `/shepherd:loop` degrade to in-context
  `Agent(...)` fan-out (the documented degraded path, glossary sense 1).
  **NEVER `ToolSearch` for `Workflow`** — a nothing-result means you looked in
  the wrong place, not that the feature is broken.

Cross-ref: `references/glossary.md` §1 (the native Workflow tool) and
§"Other collision-prone terms".

---

## VI. Adaptation memory tie-in

Which integrations actually *helped* is sprint-pattern memory. When a discovered
integration measurably improved a sprint (e.g. `superpowers:systematic-debugging`
broke a stuck loop), note it the same way the adaptation loop notes any pattern:
a `feedback_*.md` memory (`shctx mem add`) at close, classified per
`doctrines/adaptation-loop.md` §VIII. Framework-generic wins ("every project
with `/remember` should use it at CLOSE-FINALIZE") are flagged as doctrine-
promotion candidates; the conductor never pushes doctrine changes upstream.

Cross-ref: `doctrines/adaptation-loop.md` (sprint-pattern memory),
`doctrines/self-improvement.md` (lesson memory).

---

## VII. Guardrails (binding)

- **Zero hot-path cost.** The probe is a cheap one-time-per-session pass behind
  fast-paths; the marker TTL guarantees it never re-runs in a hot loop.
- **Never hard-depend.** Every integration degrades to a shepherd-native path
  when the plugin is absent. Absence is a clean degrade, never an error.
- **Distinguish auto-discovered from operator-curated.** The ephemeral roster
  is gitignored and labeled "🔎 Auto-discovered (ephemeral)"; discovery NEVER
  writes into the curated `toolkit.json`. Operator intent is never silently
  overwritten.
- **Fail-open.** Any probe error → silent no-op. The session proceeds exactly
  as it would with discovery disabled.
- **Bounded & graceful-empty.** Capped at 12; no probe / empty roster ⇒ no
  output anywhere — identical to today's behavior on a cold environment.

---

## VIII. Cross-doctrine references

- `doctrines/toolkit.md` — the operator-curated sibling; the curated-vs-ephemeral
  distinction and the promotion path
- `doctrines/specialist-dispatch.md` — how discovered specialist agents are
  surfaced and gated (Q3); discovery feeds the available-agents enumeration
- `doctrines/adaptation-loop.md` / `doctrines/self-improvement.md` — adaptation
  memory: which integrations helped
- `references/glossary.md` — the native `Workflow` tool, its environment-
  dependent presence (#146), and why you must NOT `ToolSearch` for it
- `doctrines/brief-cache-discipline.md` — why the discovered block is appended
  at the variable tail of the `[TOOLKIT]` injection
- `hooks/scripts/capability_discovery.sh` — the probe; `hooks/scripts/toolkit_surface.sh`
  + `skills/context/scripts/cmd_inject.sh` — the read-time merge surfaces
