---
name: harness
description: "Operate Claude-specific agent teams, workflows, tool discovery, messaging, and wakeups. Use only on Claude when native multi-agent mechanics or capability probing are required."
---

# harness — Claude-only, not emitted for other harnesses

`RECONCILIATION.md`, Canonical sources, records the decision: this skill stays Claude-only by design and
is never compiled for a Codex or Pi target. Its entire content is platform mechanics for
ONE harness's own multi-agent primitives — Agent Teams membership rules, the Dynamic
Workflow fan-out vehicle, `ToolSearch` deferred-tool resolution scope, and native tool
presence/absence semantics for that platform specifically. None of it is a fact about any
other harness, and abstracting it into harness-neutral prose would manufacture a claim no
evidence supports (`skills/harness/SKILL.md` §Agent Teams, §Workflow tool, §ToolSearch).

Each other harness's OWN fan-out/dispatch mechanics belong in that harness's own
implementation, never here — a future Codex dispatch adapter's `spawn_agent` flow
and hard descendant cap, and Pi's session-per-role subprocess model with a strict-replacing
`--tools` allowlist, are genuinely different constructs, not translations of this one
(discovery report §Core vs adapter split, part (c): "native-model incompatibilities" —
concurrency ceiling, model-pin granularity, and the fan-out vehicle itself are named
explicitly as real port hazards, not cosmetic differences to paper over).

What DOES port from this skill's substance is already captured elsewhere in `content/`:
the abstract `capabilities`/`dispatch` vocabulary (`RECONCILIATION.md` §Capability
vocabulary) and the write-boundary/dispatch-scope predicates (`content/predicates/`) state
the harness-neutral FACTS this skill's Claude-specific mechanics exist to enforce on one
platform. A later-wave adapter for a given harness authors that harness's own fan-out
mechanics against those neutral facts, not against this file.
