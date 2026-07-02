---
title: engineer-self-contained-plan
status: binding
introduced: v6.2.5
revised: v6.2.6
description: |
  The engineer is a flock LEADER: seed + current context in, one executable
  multi-phase plan out. Spawned as a self-contained TEAMMATE, it runs — in
  its own context — the read-only waves root used to run for it: the
  INTRO-COMBO-WAVE (@discovery + intro-mode @auditor) and its own @critic
  gate. Its sub-flock is discovery/auditor/critic ONLY; it touches no code
  and dispatches no coder/worker/engineer. It returns the plan + reports + a
  hash-tied critic-proof. Root does not re-run discovery or @critic: it runs
  a thin acceptance gate (shctx seed verify + plan verify + lane sanity) and
  proceeds to LANE-INTEGRATE. Same workflow, moved into the engineer's window.
---

# Engineer self-contained plan — a read-only flock leader carrying its own proof (#169, clarified #172)

## Why the engineer exists

Plan construction is the highest-leverage act in a sprint: a complete,
decomposed, drift-resistant plan is the difference between N parallel coders
converging and diverging. The engineer takes the **seed + current context**
and produces **one actionable, executable, multi-phase plan**:

- Each **phase** holds N granular tasks/stages (`steps`), ≈ one subagent's unit of work.
- Stages are **conditionally linked** via a `## Stage Graph` whose `on-*`
  edges make execution near-automatic (`doctrines/stage-graph.md`).
- The finished, critic-gated plan slices **vertically into independent
  lanes**, file-disjoint from siblings (`doctrines/primitive-axis-binding.md §II`).
- Root maps **each lane to a team led by a conductor**, which dispatches
  **coder/worker waves** with **auditor self-review** (`doctrines/flock-output-review.md`).

Everything downstream inherits the plan's quality — why this role runs the
most expensive model, gated before a single coder fires.

## The engineer IS a flock leader — with a read-only sub-flock

Every flock leader guarantees its output's quality with an adversarial agent
before handing up: root gates the plan with `@critic`; the conductor gates
each wave's coder output with an `@auditor` (`doctrines/flock-output-review.md`).
The engineer does the same, on its own output, in its own context.

The engineer's sub-flock is the **three read-only/adversarial roles**, only:

| Sub-flock role | Wave it runs | What it was, before |
|---|---|---|
| `@discovery` | discovery half of INTRO-COMBO-WAVE | root ran it, injected `[DISCOVERY-CONTEXT]` |
| `@auditor` (intro mode) | intro-audit half (regression + carry-forward, **no grade**) | root ran it, injected `[INTRO-AUDIT-CONTEXT]` |
| `@critic` | adversarial plan gate | root dispatched it after the plan |

**No code is touched during this phase.** All three roles are read-only
(`hooks/tests/lint_agent_capabilities.sh` pins them mutation-free). The
engineer NEVER dispatches `@coder`/`@worker` and NEVER dispatches
`@engineer` (no nested/phantom engineer). The only artifacts generated are
the plan + its reports (discovery reports, intro-audit findings, the critic-proof).

## Two dispatch topologies

The plan body is **mode-agnostic** (`waves × steps`, never lanes —
`doctrines/primitive-axis-binding.md`). What differs is who runs the
read-only waves and where that context lands:

- **Classic (root-tier subagent, or `/shepherd:start` solo).** Root runs the
  INTRO-COMBO-WAVE (`doctrines/intro-combo-wave.md`) *before* the engineer and
  dispatches a distinct `@critic` *after*. The engineer **consumes**
  `[DISCOVERY-CONTEXT]`+`[INTRO-AUDIT-CONTEXT]`, dispatching nothing; all wave
  context lives in root's window. Dispatched as an ordinary Agent/Task subagent.
- **Self-contained (teammate).** Root spawns the engineer as its OWN named
  teammate. It runs the INTRO-COMBO-WAVE **and** its own `@critic` gate
  in-session, returning a finished plan + critic-proof. Root runs neither —
  that context stays in the engineer's window.

Both modes produce the identical plan artifact; only the dispatch topology
and where wave context accrues differ.

## What self-contained mode runs in-session

1. **INTRO-COMBO-WAVE — run it, don't consume it.** Dispatch the discovery +
   intro-audit wave itself (`doctrines/intro-combo-wave.md`), the same shape
   the planter uses for its own orientation wave (`agents/planter.md §Step
   2-bis`): a bounded, scope-partitioned, single-batch fan-out —
   `@discovery`×N + intro-mode `@auditor`×M, scaled to the T-shirt (M/L
   default 3+2; XS/S fewer), never fixed. Each lane declares a
   non-overlapping domain (`doctrines/discovery-combo-wave.md §Scope-partition
   rules`). Reports land at `{paths.reports}/`.
2. **Author the plan** against the seed + wave findings (a HIGH intro-audit
   finding becomes a Wave 1 hot-fix step, same as classic mode).
3. **Adversarial critic gate — dispatch a real `@critic`.** Capture the
   pre-critic plan hash, dispatch `@critic` (Agent tool, `subagent_type:
   shepherd:critic`) against its OWN plan, revise at least once against the
   findings — a genuine independent pass, not an in-context self-review. To
   pass `dispatch_guard.sh` (blocks a teammate dispatching `@critic`), tag
   the brief `[INVOCATION-CONTEXT].dispatcher: engineer-self-contained`.
   *(Fallback: if the platform blocks the dispatch, apply the `@critic`
   rubric — `agents/critic.md` — as an embedded pass, still revise + record
   the proof; the dispatched critic is primary.)*
4. **Emit the critic-proof.** After the revision, record the proof (below).

The engineer still NEVER writes source, NEVER commits, and dispatches ONLY
the read-only sub-flock — never `@coder`/`@worker`/`@engineer`/a nested
teammate (structurally impossible + `doctrines/dispatch-tier-separation.md`).

## Mode determination — a hard signal, default classic

The engineer self-activates self-contained mode **only** when ALL THREE hold:

1. `[INVOCATION-CONTEXT].mode: self-contained` is present in its brief, AND
2. `[INVOCATION-CONTEXT].dispatcher: root-shepherd` — only ROOT spawns the
   engineer teammate; a teammate-conductor doing so is still `WRONG-TIER-DISPATCH`, AND
3. it is genuinely running as a **teammate** (native teammate-spawn), not an Agent/Task subagent.

If ANY is absent or ambiguous, the engineer runs **classic**: consume root's
context blocks, submit to root's `@critic`, dispatch nothing. **Ambiguity
NEVER activates self-contained** — the fix for the v6.2.5 failure where a
bare-subagent engineer self-activated a discovery fan-out it was never
spawned to lead.

## Spawn topology — self-contained is a NAMED teammate, never a subagent

A self-contained engineer is spawned by root via the native teammate-spawn
(Agent Teams) — a long-lived named peer session — never via Agent/Task as a
subagent. Classic dispatch (root → Agent/Task subagent) stays valid and is
the default. The two are mutually exclusive per dispatch; root picks one and the brief's `mode:` reflects it.

Mechanical enforcement (`hooks/scripts/dispatch_guard.sh`):

- **`ENGINEER-TOPOLOGY-MISMATCH`.** An Agent/Task dispatch of
  `shepherd:engineer` whose brief carries `mode: self-contained` is DENIED —
  it must be a teammate-spawn. (The native teammate-spawn doesn't go through
  the Agent/Task hook, so the legitimate spawn is unaffected.) Fixes the
  "unnamed subagent engineer" failure.
- **`WRONG-TIER-DISPATCH` (tightened).** A teammate dispatching `@engineer`
  is DENIED unconditionally. A teammate dispatching `@critic` is DENIED
  unless marked `dispatcher: engineer-self-contained` — the engineer
  teammate may gate its own plan, but a conductor lane still can't re-gate a fixed one.

## The critic-proof — irrefutable, not trust

The critic-proof is a hash-tied artifact written alongside the plan
(`<plan-slug>.critic-proof.json`), so root can accept the plan mechanically instead of re-reading it:

```
pre_critic_hash   sha256 of the plan BEFORE the critic pass
post_critic_hash  sha256 of the plan AFTER the revision
edited            post != pre   (proves ≥1 edit happened)
critic.verdict    the critic verdict (not a hard FAIL)
critic.iterations ≥1
```

- Engineer writes it: `shctx plan record-critique --plan <p> --pre <hash> --verdict <v> --iterations <n>`
  (capture `--pre` via `shctx plan hash <p>` BEFORE the critic dispatch).
- Root verifies it: `shctx plan verify --plan <p>` — re-hashes the CURRENT
  plan bytes, requires `post_critic_hash` to match, so a stale or
  hand-forged proof cannot pass.

The hash-proof + verifier make "critiqued AND edited at least once"
**provable**, not asserted (the latent→deterministic split, CLAUDE.md).

## Root's thin acceptance gate — no re-critique, no re-discovery

On receiving a self-contained engineer teammate's plan, root runs ONLY:

1. `shctx seed verify <seed>` (the existing v6.2.1 seed gate), and
2. `shctx plan verify --plan <plan>` (the critic-proof gate), and
3. a lane-count sanity check (≥1 lane; within the T-shirt band, `agents/engineer.md §Lane-count guidance`).

All green → root proceeds to `LANE-INTEGRATE` (`doctrines/teammate-integration-authority.md`).
Root does NOT run its own INTRO-COMBO-WAVE and does NOT re-run `@critic` — the
engineer already did both. A failed gate returns the named code
(`CRITIC-PROOF-MISSING`/`PLAN-UNEDITED`/`CRITIC-PROOF-STALE`/`PLAN-UNCRITIQUED`)
to the engineer teammate for a fresh pass — root never repairs the plan itself.

## Why this saves context

In classic mode, root pays for the whole discovery wave, the whole
intro-audit wave, and the `@critic` findings — all before the plan is even
accepted. On an ultra-parallel spawn, root is the coordination bottleneck,
and that wave context is the majority of what fills it. Moving the waves
into the engineer's teammate session leaves root with a thin, mechanical
gate over a finished artifact — same workflow, same certification, a
fraction of root's context: lean wiring, token/cache-efficient.

## Mechanical teeth

- `shctx plan verify` is deterministic and exit-coded; root's gate is a
  mechanical call, not a judgment. `post_critic_hash` is checked against the
  live plan bytes, so the gate can't be satisfied by an unedited plan or a
  proof describing an older one.
- `dispatch_guard.sh` Checks 4/4b (above) plus Check 4c
  `ENGINEER-SUBFLOCK-VIOLATION` (blocks a marked dispatch outside the
  read-only trio) give "no code is touched" mechanical teeth, not prose. The
  engineer tags EVERY sub-flock dispatch with the marker so 4c is total.
- The engineer's `Agent` grant is pinned to `shepherd:discovery`/`auditor`/`critic`
  by `hooks/tests/lint_agent_capabilities.sh`; never a `@coder`/`@worker` dispatch.
- Coverage row: `doctrines/invariant-enforcement-matrix.md`.

## Anti-patterns

- **Fixed-count discovery fan-out.** Hard-coded "always 5" `@discovery` batch
  instead of T-shirt-scaled, scope-partitioned — the v6.2.5 failure that "ate
  our discovery dynamic workflow." Scale N/M to scope.
- **Self-activating on ambiguity.** Missing one of the three mode signals — default classic.
- **Engineer as a bare subagent in self-contained mode.** Blocked by `ENGINEER-TOPOLOGY-MISMATCH`.
- **Nested / phantom engineer.** Dispatching `@engineer` — blocked
  unconditionally; a leader does not spawn another leader.
- **Touching code.** Sub-flock is read-only; the engineer writes only
  `.md`/reports/plan. `@coder`/`@worker` under the leader marker is blocked
  (`ENGINEER-SUBFLOCK-VIOLATION`); file a plan step for the conductor instead.
- **Root re-critiquing / re-discovering.** Re-running `@critic` or the
  INTRO-COMBO-WAVE on a plan already carrying a valid critic-proof.
- **Recording a critic-proof with `edited=false`** — `shctx plan verify` fails it (`PLAN-UNEDITED`).

## See also

- `doctrines/intro-combo-wave.md` — the discovery + intro-audit wave the engineer runs (self-contained) or consumes (classic).
- `doctrines/primitive-axis-binding.md` — waves × steps; lanes as a post-plan projection; §V run-vs-consume by mode.
- `doctrines/dispatch-tier-separation.md` — why a teammate cannot dispatch @engineer; the tightened @critic allowance.
- `doctrines/stage-graph.md` — the binding dispatch contract + conditional edges.
- `doctrines/flock-output-review.md` — the adversarial-agent-per-leader pattern the engineer mirrors.
- `doctrines/teammate-integration-authority.md` — LANE-INTEGRATE.
- `doctrines/model-map.md` — the model each sub-flock role dispatches with.
- `agents/critic.md` — the adversarial rubric the dispatched `@critic` applies.
- `agents/planter.md §Step 2-bis` — the leader-runs-its-own-read-only-wave template.
