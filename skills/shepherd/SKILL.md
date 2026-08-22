---
name: shepherd
description: "Execute a Shepherd sprint through the nine-role flock, native dispatch, gates, artifacts, and resume. Use for planning, coordinating, gating, resuming, or closing multi-lane project work."
---

# shepherd — the sprint-execution contract

Bind role dispatch, gates, artifacts, and resume into one harness-neutral sprint.

## Preconditions

A failing precondition stops dispatch and is reported verbatim.

- `shepherd doctor` reports a dispatchable namespace. On an unscaffolded project it exits 3
  and names the absent artifact.
- The project is scaffolded. `shepherd init --confirm` mints project state. Root never
  runs it for the operator; surface the command and halt.

## The flock is closed

The flock is exactly `shepherd`, `planter`, `engineer`, `conductor`, `critic`, `coder`,
`auditor`, `discovery`, and `worker`. Never invent or silently substitute a tenth role.

## Dispatch law

Every dispatch binds identity, role, capabilities, lane, scope, acceptance, and result.
Set generic subagent `model` to the exact output of
`shepherd models resolve ROLE --harness HARNESS`; Pi suffixes carry effort. Reference the
brief. Conductors escalate plan-author and gate roles. Escalate one bounded ordinary task
only after its agent returns concrete inability evidence.

## Root contract

**Introduction** performs fresh orientation, authors the plan, and gates it before spawn.
**Body** assigns one conductor per lane and requires a clean independent review at each
wave. **Close** aggregates lane evidence, runs concern-split review, remediates blockers,
and performs integration under root custody. Root never writes source or leaves a finding
only in a transcript.

## Principles

**Durable artifact** — every top-tier dispatch ends in one canonical artifact or registry
record. Transcript-only reasoning has no effect.

**Subtract** — prefer replacement over parallel authority. Inline single callers, collapse
hollow wrappers, retire superseded shims in the same slice, and justify net-new surface.

**External writes** — use a connected managed API by its deadline. Otherwise use only the
sanctioned fallback and record why.

**Capability discovery** — trust measured startup facts, not provider names or environment
guesses. Missing required capability fails closed; supported extras remain adapter-local.
