---
title: staged-handoff
status: binding
introduced: v6.1.7
description: |
  Canonical two-session overlap: a `/shepherd:spawn --staged` execution session
  gets its orientation / discovery wave done while a SEPARATE `/shepherd:plant`
  session is still authoring the seed. When the planter finishes it emits a
  durable `seed-ready` signal over the existing SQLite mailbox; the staged spawn
  session consumes it and unblocks plan authorship. Zero new schema, zero new
  tooling — only the existing `shctx mailbox` channel, a `--staged` spawn flag,
  and one signal at plant close. Opt-in; the default seed-first spawn flow is
  unchanged.
---

# Staged handoff — orient while the seed is still being planted

> **The shape.** Two operator sessions run concurrently:
> - **Session A** — `/shepherd:spawn <slug> --staged` (root-shepherd). Runs its
>   pre-seed orientation wave immediately, then **waits** for the seed before any
>   plan authorship.
> - **Session B** — `/shepherd:plant <slug>` (planter). Authors the seed
>   interactively, commits it, and **signals** Session A that it may begin.
>
> The win: the discovery / context cost is paid in parallel with planting instead
> of serially after it. The seam is a single durable mailbox message, so the two
> independent sessions never need to see each other's process.

## I. The signal — reuse the SQLite mailbox (no new schema)

The cross-session carrier is the existing `mailbox` table via `shctx mailbox`
(`skills/context/scripts/cmd_mailbox.sh`). Recipient names are free-form strings, so
both sessions agree on one derived from the sprint slug:

```
recipient = shepherd-spawn-<sprint_slug>
```

- **Planter emits at close** (Session B), as the last step before its PLANTER REPORT:
  ```bash
  printf '%s' '{"event":"seed-ready","sprint_slug":"<slug>","seed_path":"<path>"}' \
    | shctx mailbox send --to="shepherd-spawn-<slug>" --kind=seed-ready
  ```
  > **v6.1.8 fix:** the `mailbox.kind` CHECK was a closed enum through v6.1.7, so
  > `--kind=seed-ready` was rejected by the schema and this signal could never be
  > sent (the feature never worked end-to-end). `migrations/0016_mailbox_kind_relax.sql`
  > relaxes `kind` to non-empty, so any routing tag is accepted.
- **Staged spawn consumes** (Session A), at its seed-wait gate (`shctx mailbox recv`
  emits a JSON **array**, so iterate with `.[]`; each row carries its numeric `id`
  for the ack):
  ```bash
  shctx mailbox recv --as="shepherd-spawn-<slug>" --unread-only --mark-read \
    | jq -r '.[] | select(.kind=="seed-ready")'
  shctx mailbox ack <id>   # <id> = the row's .id; ack after it reads the committed seed
  ```

The message is **durable**: it survives even if Session A is not live at the moment
the planter finishes. There is no auto-wake across two independent operator sessions —
the operator bridges the wake with a light nudge ("continue") when they switch back to
Session A; the signal + the committed seed are what the session verifies, not a live event.

## II. Session A — the staged spawn flow (`--staged`)

`--staged` modifies `/shepherd:spawn` preflight so a *missing* seed is the EXPECTED
starting state rather than a seedless-run trigger:

1. **Orient first.** Run the pre-seed orientation wave immediately — a repo/ledger-
   general `@discovery` (and optional intro `@auditor`) pass, scope-partitioned, exactly
   like the planter's own optional discovery wave (`agents/planter.md §Step 2-bis`).
   This is orientation against the repo as-is, NOT a delta-check against a seed (there
   is none yet). Cache its findings for the engineer's later `[DISCOVERY-CONTEXT]`.
2. **Gate plan authorship on the seed.** Do NOT dispatch `@engineer` and do NOT spawn
   teammates until the seed exists. After orientation, check the seed-ready gate:
   - `seed-ready` mailbox message present AND `{paths.plans}/<slug>.seed.md` committed
     → proceed to the normal spawn flow (INTRO-COMBO-WAVE re-meshes against the seed as
     the usual delta-check, then engineer → critic → teammates).
   - neither present → emit a one-block turn-ending report: "Staged: orientation
     complete; awaiting `seed-ready` from the plant session for `<slug>`." Then yield.
     The operator nudges Session A once Session B has finished.
3. **No infinite spin, no guessing.** The staged session never busy-waits and never
   invents a seed. If the operator abandons planting, the seedless behavior applies
   (`doctrines/operator-signaling.md §"Seed is recommended, not required"`): orientation
   is already done, so the walk's `SEED-AUTHOR` node emits its one turn-ending confirm and
   either plants the seed inline (planter inner frame → `shctx seed verify`) or routes to
   `/shepherd:plant` on the operator's preference. No best-effort-defaults drift run.

The pre-seed orientation reconciles cleanly with the always-on `INTRO-COMBO-WAVE`
(`doctrines/intro-combo-wave.md`): the staged wave runs UPSTREAM of the seed and is
orientation-only; the intro wave still fires later as the seed-time delta-check. They are
not redundant — the intro wave re-meshes against a seed the staged wave ran before.

## III. Session B — the planter's emit step

In plant mode, after the seed passes pre-flight and is committed (the existing close
sequence in `agents/planter.md §Step 4–5`), and immediately before the PLANTER REPORT,
emit the `seed-ready` signal (§I). Record it in the PLANTER REPORT
(`seed-ready signal: sent → shepherd-spawn-<slug>`). The emit is **best-effort and
non-blocking** — if no staged spawn session is listening, the durable message simply
sits unread and harms nothing; the planter never waits on an ack.

## IV. Bounds

- **Opt-in.** Plain `/shepherd:spawn` with a pre-existing seed is unchanged. Staging
  is requested explicitly with `--staged` (and is only meaningful when a plant session
  is, or will be, running concurrently for the same slug).
- **Operator-explicit, two sessions.** This is not nested teams and not a single-session
  trick — it is two top-level operator sessions coordinating through one durable message.
- **No new schema / no new tooling.** Only the existing `mailbox` table + `shctx mailbox`
  verbs, one spawn flag, and one signal line at plant close.
- **The seed file remains the source of truth.** The `seed-ready` message is an
  optimization to overlap orientation; the staged session still verifies the committed
  seed before authoring against it. A signal without a committed seed is ignored.

## V. Cross-references

- `commands/spawn.md` — the `--staged` flag + the seed-wait gate.
- `commands/plant.md` / `agents/planter.md` — the close-time `seed-ready` emit.
- `doctrines/operator-signaling.md` — seedless ladder the staged gate falls back to.
- `doctrines/intro-combo-wave.md` / `agents/planter.md §Step 2-bis` — orientation-wave shape.
- `skills/context/scripts/cmd_mailbox.sh` — the mailbox verbs (`send` / `recv` / `ack`).
- `doctrines/claude-code-platform-alignment.md §V` — why there is no cross-session auto-wake.
