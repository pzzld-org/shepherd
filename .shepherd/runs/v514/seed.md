---
title: v5.1.4 — teammate-aware /shepherd:parallel
branch: v5.1.4
base: v5.1.3 (next patch branch off v5.1.3 close)
date: 2026-05-19
author: main-chat (operator-confirmed scope)
scope_tier: patch  # per doctrines/version-scale-roadmap.md — governs ≤ 10 dev sprints
status: seed — Phase 0 must investigate teammate API state before design lands
---

# v5.1.4 seed — teammate-aware `/shepherd:parallel`

> Patch-scoped seed (per `doctrines/version-scale-roadmap.md`). Authorizes up to 10 dev sprints; realistic decomposition is 1–3 dev sprints depending on Phase 0 findings.

## North star

`/shepherd:parallel` becomes the multi-teammate fanout primitive: each Claude Code teammate runs an independent conductor + flock over their own sprint scope, coordinating via the existing shctx registry. No more one-Claude-session-juggles-N-flocks. The operator can step away; teammates merge in dev-order via a registry-mediated gate.

## Why now (operator framing — 2026-05-19)

- Operator has never invoked `/shepherd:parallel` because the single-session multi-worktree design saturates context fast and offers no real attention-offload benefit
- Claude Code's teammate feature is configured locally (`.claude/.env`) but not yet exercised in shepherd flows
- With teammates: every teammate becomes a conductor, each capable of managing their own flock with cross-teammate communication. That is the design `/shepherd:parallel` should have always had.
- v5.1.3 delivered prompt-caching telemetry — we now have measurement on per-role cache discipline. Teammate-parallel adds another dimension (per-teammate flock health) that should plug into the same telemetry surface.

## Phase 0 — Investigate teammate API surface (BLOCKING)

This is not optional. The seed cannot be turned into a plan until Phase 0 lands. Dispatch a `@discovery` agent at sprint open with this mission:

1. **What is the current Claude Code teammate primitive?** Names, semantics, lifecycle. Does it work via shared session, parallel sessions with shared session ID, file-system-mediated, or something else?
2. **What does `.claude/.env` actually enable?** Which env var(s)? What does each toggle?
3. **How do teammates communicate?** Shared filesystem? An API endpoint? A message queue surface? A shared transcript?
4. **Can a teammate dispatch into another teammate's session?** If yes, what is the dispatch shape (a tool call, a CLI command, a hook event)?
5. **What guarantees does the platform give about teammate identity?** Stable IDs? Roles? Permissions? Per-teammate config files?
6. **Where do logs/transcripts live per teammate?** Shared `.shepherd/` writers or per-teammate?
7. **What's the failure mode if a teammate's Claude session drops?** Does the work go orphan? Does another teammate pick it up?

Discovery output: `.artifacts/docs/handoffs/2026-05-NN-teammate-api-discovery.md`. The engineer's mesh CANNOT proceed until this report lands. If discovery reveals teammate APIs are too immature for what the seed proposes, the seed is amended (or escalated to RECONSIDER) — do NOT silently downgrade to "one-Claude-juggles-N-worktrees-but-with-better-bookkeeping".

## Scope items (conditional on Phase 0 findings)

### Item 1 — Per-teammate conductor ownership

- Each teammate runs `/shepherd:parallel join <sprint-slot>` to claim a sprint
- Conductor reads `shepherd.toml [parallel.assignments]` (or registry rows) to confirm slot identity
- Each teammate's conductor runs the full `/shepherd:start` pipeline against its assigned worktree
- The assigning operator/conductor (or the first teammate to start) authors the parallel-sprint manifest documenting which teammate owns which slot

### Item 2 — Shared coordination via shctx (extend registry, not invent new mechanism)

The context registry (`<ns>/root.db`) already holds project-wide state. Extend with:

- `parallel_assignments` table: `(sprint_id, sprint_slot, teammate_id, worktree_path, status, claimed_at, released_at)`
- `parallel_locks` table: build-manifest single-writer lock keyed on `(project_id, manifest_path, holding_teammate_id, acquired_at, released_at)`
- `parallel_ready` table: dev-order merge gate state `(sprint_id, slot_id, status, predecessors[], merged_at)`
- New `shctx parallel claim <slot>`, `shctx parallel ready`, `shctx parallel lock <manifest>` / `shctx parallel unlock <manifest>` subcommands

Existing `cmd_lock.sh` already locks the shepherd lifecycle per-project. Extend its semantics rather than invent a parallel lock mechanism. Existing `cmd_ready.sh` may already cover the dev-order ready bit — Phase 0 confirms.

### Item 3 — Dev-order merge gate (registry-mediated, not memory-mediated)

Replace the current "conductor pauses dev.5 merge until dev.3 lands" working-memory bookkeeping with:

- Each teammate at sprint close calls `shctx parallel ready --sprint=<slot>`
- The registry materializes a merge-readiness view: each sprint shows its predecessor status
- Teammates poll on close: if all predecessors merged, merge; else wait
- First teammate done with no predecessors merges immediately
- A hook on `Stop` (or `SubagentStop` of the close swarm) writes the `ready` row automatically so teammates don't have to remember to call it

### Item 4 — Build-manifest single-writer enforcement

- Cargo.toml / package.json / pyproject.toml / go.mod writes go through a registry lock
- Coder pre-write hook checks `shctx parallel lock` status; HALTs if a different teammate holds the lock for this file
- Operator/conductor releases the lock via `shctx parallel unlock <manifest>` after the writer's commit lands
- The existing `dedup_write_guard.sh` hook gains a parallel-aware codepath

### Item 5 — Cross-teammate visibility surface

- New `shctx parallel status` shows: assignments, locks, ready state, last-heartbeat per teammate
- The completeness auditor (per-teammate) reads the registry and surfaces sibling-teammate state in the close report's `## Parallel coordination` section
- Heartbeats: each teammate's session writes a heartbeat row every N minutes (or on every subagent dispatch); stale heartbeats are flagged

### Item 6 — `/shepherd:parallel` command rework

The command's UX changes from "conductor in one terminal fans worktrees" to "operator (or first teammate) declares the parallel manifest, teammates claim slots independently". Two roles:

- **`/shepherd:parallel propose`**: an operator (or any teammate) runs this to inventory existing seeds, identify parallel-safe subsets, and write the manifest to registry + `.artifacts/docs/plans/parallel-<date>-manifest.md`
- **`/shepherd:parallel join <slot>`**: any teammate (including the proposer) claims a slot, sets up the worktree, and starts `/shepherd:start` against it
- **`/shepherd:parallel status`** (read-only): any teammate sees the live cross-slot state

### Item 7 — Cache telemetry per-teammate aggregation (folds into v5.1.3 telemetry)

The v5.1.3 cache telemetry hook captures per-dispatch usage; v5.1.4 extends the view to:

- Aggregate per teammate AND per role
- Surface in `## Parallel coordination` close-report section
- Identify per-teammate hot/cold cache patterns (if teammate A has 80% hit-rate and teammate B has 20%, something is structurally different — investigate)

## Non-goals

- No replacement of `/shepherd:start`. Single-operator single-sprint workflow is unchanged.
- No replacement of `/shepherd:autorun`. Sequential single-operator workflow is unchanged.
- No new agent role. Coordination is via registry, not via new flock members.
- No replacement of git worktrees. Worktrees remain the per-sprint isolation primitive; teammates just own them individually.
- No new conductor model. Each teammate's conductor is the same Sonnet conductor from `/shepherd:start`.
- No live RPC between teammates. Async via registry is sufficient for v1. Live messaging is v5.2.x or later if at all.
- No teammate role / permission system. v1 assumes all teammates are peers with equal authority.

## Open questions for the engineer's plan

- If Phase 0 reveals teammate APIs don't yet exist as we hope, can the same registry-mediated coordination work for the existing single-operator multi-worktree mode (i.e., upgrade the current `/shepherd:parallel` even WITHOUT teammate support)? This may be the v5.1.4 fallback.
- Should we ship `parallel propose` + `parallel join` even before teammate support is mature, so operators can use the registry-mediated coordination today and adopt teammate-driven invocation when ready?
- Build-manifest single-writer lock: what's the acquire-timeout policy? Fail-fast or back-off?
- Heartbeat staleness threshold: what counts as "teammate dropped"? Auto-release the slot or HARD-STOP?
- How does the dev-order merge gate handle force-pushes or amended commits (which change SHAs)?

## Carry-forwards from v5.1.3

- Cache telemetry stack (Lane C) is foundational — teammate-aware per-teammate aggregation builds on it
- Brief-cache-discipline doctrine (Lane B) — extends to parallel-mode briefs, which may need an additional `[TEAMMATE]` bracketed section identifying which conductor owns which dispatch

## Phase decomposition (engineer expands this into the plan)

- **Phase 0** — Discovery investigation of Claude Code teammate API surface (BLOCKING, results gate the rest)
- **Phase 1** — Registry schema extension (parallel_assignments, parallel_locks, parallel_ready tables + views + queries)
- **Phase 2** — `shctx parallel *` subcommands implementing claim / ready / lock / unlock / status
- **Phase 3** — Command rework: `/shepherd:parallel propose` + `join` + `status` (replaces the existing single-monolithic command)
- **Phase 4** — Hook integration: dev-order merge gate via Stop hook, build-manifest lock via PreToolUse on Write/Edit
- **Phase 5** — Doctrine updates: `parallel-coordination.md` (new), `pause-for-dependency.md` extension (cross-teammate variant)
- **Phase 6** — Auditor completeness extension: `## Parallel coordination` close-report subsection
- **Phase 7** — Telemetry aggregation extension to per-teammate views
- **Phase 8** — Examples + docs: `examples/parallel/` showing a two-teammate invocation, README update

Engineer is free to merge or split phases based on Phase 0 findings — if teammate APIs turn out to be much simpler/richer than expected, scope tightens; if they're not yet usable, the whole sprint pivots to "registry-mediated single-operator parallel improvement" and teammate integration moves to a later patch once APIs mature.

## Sprint t-shirt (provisional)

L. The seed describes ~7 phases with material scope per phase. Engineer's mesh confirms or downgrades to M (drop telemetry aggregation to v5.1.5) or upgrades to XL (if teammate APIs need significant adapter work).

## Reference docs the engineer should consult

- `skills/shepherd/parallel.md` — existing design (to be replaced)
- `skills/shepherd/doctrines/context-registry.md` — registry-as-canonical pattern
- `skills/context/schema/0001_init.sql` — existing tables to extend, not duplicate
- `skills/context/scripts/cmd_lock.sh` — existing lock primitives
- `skills/context/scripts/cmd_ready.sh` — possibly pre-stubbed; verify
- `skills/shepherd/doctrines/pause-for-dependency.md` — coordination pattern to extend
- `.claude-plugin/hooks.json` — hook wiring for the new dev-order gate
- The (forthcoming) v5.1.3 discovery report on teammate APIs at `.artifacts/docs/handoffs/2026-05-NN-teammate-api-discovery.md`

## Proof of dispatch

- seed authored by: main-chat @ 2026-05-19
- supersedes: nothing
- operator confirmation: 2026-05-19 (scope = v5.1.4 standalone; teammate API state = configured but not exercised → Phase 0 mandatory)
- status: SEED — awaiting v5.1.3 close before sprint opens
