---
name: plant
description: "Equip the root session with the planter profile to author a drift-resistant sprint seed before spawn turns it into a plan."
---

# plant — the root session becomes the planter

```
root --[plant]--> planter --[report]--> spawn
```

Plant is role adoption, not dispatch: it equips the running session, root, with the planter
profile. `spawn` picks up where planting left off, same session or not.

`shepherd models resolve planter` reports the advisory tier: advisory only, never a gate;
planting proceeds regardless.

## Preconditions

Each is a command, not a judgement; a failure stops planting before any artifact exists.

- `shepherd doctor` reports a dispatchable namespace, exiting 3 and naming the absent
  artifact on an unscaffolded project.
- `shepherd init --confirm` mints a missing namespace, gated because it mutates; root
  surfaces the command and halts rather than run it.

## Step 1 — open the run first

`shepherd run init <run>` creates the run directory before `seed.md` or `mesh.md` exist.
`<run>` is the sprint or patch slug, sanitized to `[a-z0-9-]`. The run lands `planted`
already; no separate `run set --status planted` follows.

## Step 2 — sweep, author, verify

Sweep every open signal (issues, PRs, prior close reports, carry-forward, project doctrine)
into one mesh report before authoring anything. Write `mesh.md` first, run-scoped under
`<paths.runs>/<run>/` (default `.shepherd/runs/<run>/`), then author `seed.md` from it in
the same directory. Every deliverable anchors to a tracked signal or carry-forward; sizing
is a recommendation only, sequencing belongs to the plan author. `shepherd seed verify
.shepherd/runs/<run>/seed.md` must exit 0 before commit; hard failures block, warnings do
not.

## Step 3 — record the pointer

`shepherd run set <run> --seed .shepherd/runs/<run>/seed.md` records the seed path; `run
init` leaves `seed` empty otherwise.

## The session ends at the report

Planting ends at the planter report. It never dispatches an implementer or a gating role,
nor begins the sprint pipeline; `spawn` is the next operator action, not this session's
continuation.

## What plant is not

Not a dispatch: no persistent agent spawns into a planter role; root adopts the profile
directly. Not the plan author: it names deliverables and recommends sizing, never
sequencing. Not the start of execution: no implementer runs until `spawn`, then `start`.
