---
title: engineer-self-contained-plan
status: binding
introduced: v6.2.5
revised: v6.2.6
description: |
  The engineer is a flock LEADER. Its whole job is to turn the seed + current
  context into an executable, multi-phase, vertically-lane-sliced plan. When root
  spawns it as a self-contained TEAMMATE, it runs — in its OWN context — the exact
  read-only waves root used to run on its behalf: the INTRO-COMBO-WAVE (@discovery
  + intro-mode @auditor) AND its own @critic gate. Its sub-flock is the three
  read-only / adversarial roles ONLY — discovery, auditor, critic. It touches no
  code and dispatches no coder/worker/engineer. It returns the plan + reports +
  a hash-tied critic-proof. Root does NOT re-run discovery or re-dispatch @critic:
  it runs a thin, mechanical acceptance gate (shctx seed verify + shctx plan verify
  + lane sanity) and proceeds to LANE-INTEGRATE. Same workflow as before, moved
  into the engineer's window — sparing the majority of context root used to incur.
---

# Engineer self-contained plan — a read-only flock leader carrying its own proof (#169, clarified #172)

## Why the engineer exists

Plan construction is the single highest-leverage act in a sprint. A plan that is
complete, decomposed, and drift-resistant is the difference between 4-5 parallel
coders converging and diverging. The engineer's entire reason to exist is to take
the **seed + current context** and produce **one actionable, executable,
multi-phase plan**:

- Each **phase** holds N granular tasks/stages (`steps`), each ≈ one subagent's
  unit of work.
- Stages are **conditionally linked** — the plan emits a `## Stage Graph` whose
  edges (`on-*` predicates) make execution near-automatic (`doctrines/stage-graph.md`).
- The finished, critic-gated plan is then sliced **vertically into independent
  lanes** — a lane is a vertical slice across phases, file-disjoint from its
  siblings (`doctrines/primitive-axis-binding.md §II`).
- Root maps **each lane to a team led by a conductor**, who runs dynamic
  workflows dispatching **coder/worker waves** with **auditor self-review**
  (`doctrines/flock-output-review.md`).

Everything downstream inherits the plan's quality. That is why this role runs on
the most expensive model and why its output is gated before a single coder fires.

## The engineer IS a flock leader — with a read-only sub-flock

Every flock leader guarantees the quality of its output with an **adversarial
agent** before handing it up: root gates the plan with `@critic`; the conductor
gates each wave's coder output with an `@auditor` review (`doctrines/flock-output-review.md`).
The engineer, as the plan's author-leader, does the same — **on its own output,
in its own context**.

The engineer's sub-flock is the **three read-only / adversarial roles**, and
**only** those three:

| Sub-flock role | Wave it runs | What it was, before |
|---|---|---|
| `@discovery` | the discovery half of the INTRO-COMBO-WAVE | root ran it, injected `[DISCOVERY-CONTEXT]` |
| `@auditor` (intro mode) | the intro-audit half of the INTRO-COMBO-WAVE (regression + carry-forward, **no grade**) | root ran it, injected `[INTRO-AUDIT-CONTEXT]` |
| `@critic` | the adversarial plan gate | root dispatched it after the plan |

**No code is touched during this phase.** All three sub-flock roles are read-only
(`hooks/tests/lint_agent_capabilities.sh` pins them mutation-free). The engineer
NEVER dispatches `@coder` or `@worker` (those write; this phase writes nothing but
the plan and its reports) and NEVER dispatches `@engineer` (no nested/phantom
engineer — a self-contained leader does not spawn another one). The **only**
artifacts this phase generates are **the plan itself + its reports** (discovery
reports, intro-audit findings, the critic-proof).

## Two dispatch topologies

The plan body is **mode-agnostic** (`waves × steps`, never lanes —
`doctrines/primitive-axis-binding.md`). What differs is **who runs the read-only
waves and where that context lands**:

- **Classic (root-tier subagent, or `/shepherd:start` solo).** Root runs the
  INTRO-COMBO-WAVE (`doctrines/intro-combo-wave.md`) *before* the engineer and
  dispatches the **distinct `@critic`** *after*. The engineer **consumes**
  `[DISCOVERY-CONTEXT]` + `[INTRO-AUDIT-CONTEXT]`; it dispatches nothing. All that
  wave context lives in **root's** window. Highest independence. Dispatched as an
  ordinary Agent/Task **subagent**.
- **Self-contained (teammate).** Root spawns the engineer as its OWN **named
  teammate**. The engineer runs the INTRO-COMBO-WAVE **and** its own `@critic`
  gate in-session, and returns a finished plan + critic-proof. Root runs **no**
  discovery wave and **no** `@critic` — that entire context stays in the
  **engineer's** window. This is the same workflow, **compartmentalized**: it
  eliminates the majority of context root used to incur running discovery + critic
  on the engineer's behalf.

Both modes produce the identical plan artifact. Mode changes only the dispatch
topology and where the read-only-wave context accrues.

## What self-contained mode runs in-session

1. **INTRO-COMBO-WAVE — run it, don't consume it.** The engineer dispatches the
   discovery + intro-audit wave itself (`doctrines/intro-combo-wave.md`), exactly
   the shape the planter uses for its own orientation wave
   (`agents/planter.md §Step 2-bis`): a **bounded, scope-partitioned, single-batch**
   fan-out — `@discovery` × N + intro-mode `@auditor` × M, N/M **scaled to the
   T-shirt** (M/L default 3 discovery + 2 auditor; XS/S fewer), **never** a fixed
   hard-coded count. Each lane declares a **non-overlapping** domain
   (`doctrines/discovery-combo-wave.md §Scope-partition rules`). Reports land at
   `{paths.reports}/`. This IS the always-on certifiable wave — relocated into the
   engineer's session, not skipped (`doctrines/intro-combo-wave.md §Certifiable
   current context`).
2. **Author the plan** against the seed + the wave's findings (a HIGH intro-audit
   finding becomes a Wave 1 hot-fix step, same as classic mode).
3. **Adversarial critic gate — dispatch a real `@critic`.** The engineer captures
   the pre-critic plan hash, dispatches `@critic` (Agent tool, `subagent_type:
   shepherd:critic`) against its OWN plan, and **revises at least once** against
   the findings. This is a genuine independent critic agent — not an in-context
   self-review. To pass `hooks/scripts/dispatch_guard.sh` (which otherwise blocks
   a teammate from dispatching `@critic`, so conductor lanes cannot re-gate a fixed
   plan), the engineer tags the critic brief `[INVOCATION-CONTEXT].dispatcher:
   engineer-self-contained`. *(Fallback: if the platform blocks the `@critic`
   dispatch in some context, apply the `@critic` rubric — `agents/critic.md` — as
   an embedded pass and still revise + record the proof. The dispatched critic is
   the primary path.)*
4. **Emit the critic-proof.** After the revision, record the proof (below).

The engineer still NEVER writes source, NEVER commits, and dispatches ONLY the
read-only sub-flock — `@discovery`, intro-mode `@auditor`, `@critic` — never
`@coder`/`@worker`/`@engineer`, and never a nested teammate (structurally
impossible + `doctrines/dispatch-tier-separation.md`).

## Mode determination — a hard signal, default classic

The engineer self-activates self-contained mode **only** when ALL THREE hold:

1. `[INVOCATION-CONTEXT].mode: self-contained` is present in its brief, AND
2. `[INVOCATION-CONTEXT].dispatcher: root-shepherd` (only ROOT spawns the
   engineer teammate — a teammate-conductor dispatching the engineer is still
   `WRONG-TIER-DISPATCH`), AND
3. it is genuinely running as a **teammate** (spawned via the native teammate-spawn),
   not as an Agent/Task subagent.

If ANY of the three is absent or ambiguous, the engineer runs **classic**:
consume root's `[DISCOVERY-CONTEXT]`/`[INTRO-AUDIT-CONTEXT]`, submit to root's
`@critic`, dispatch nothing. **Ambiguity NEVER activates self-contained.** This
is the fix for the v6.2.5 failure where an engineer dispatched as a bare subagent
read its own "self-contained" prose and self-activated a discovery fan-out it was
never spawned to lead.

## Spawn topology — self-contained is a NAMED teammate, never a subagent

A self-contained engineer is spawned by root via the **native teammate-spawn**
(Agent Teams) — a long-lived named peer session — **never** via the Agent/Task
tool as a subagent. Classic engineer dispatch (root → Agent/Task subagent) stays
valid and is the default. The two are mutually exclusive per dispatch; root picks
exactly one and the brief's `mode:` reflects it.

Mechanical enforcement (`hooks/scripts/dispatch_guard.sh`):

- **`ENGINEER-TOPOLOGY-MISMATCH` (new).** An Agent/Task dispatch of
  `shepherd:engineer` whose brief carries `mode: self-contained` is DENIED — a
  self-contained engineer must be a teammate-spawn, not a subagent. (The native
  teammate-spawn does not go through the Agent/Task hook, so the legitimate spawn
  is unaffected; only the mistaken subagent-dispatch is caught.) This is the
  mechanical fix for the "unnamed subagent engineer" failure.
- **`WRONG-TIER-DISPATCH` (tightened).** A teammate dispatching `@engineer` is
  DENIED **unconditionally** (no nested/phantom engineer). A teammate dispatching
  `@critic` is DENIED **unless** the brief carries `dispatcher:
  engineer-self-contained` — so the engineer teammate may gate its own plan, but a
  conductor lane still cannot re-gate a fixed one.

## The critic-proof — irrefutable, not trust

The critic-proof is a hash-tied artifact written ALONGSIDE the plan
(`<plan-slug>.critic-proof.json`), so root can accept the plan mechanically
instead of re-reading it:

```
pre_critic_hash   sha256 of the plan BEFORE the critic pass
post_critic_hash  sha256 of the plan AFTER the revision
edited            post != pre   (proves ≥1 edit happened)
critic.verdict    the critic verdict (not a hard FAIL)
critic.iterations ≥1
```

- Engineer writes it: `shctx plan record-critique --plan <p> --pre <hash> --verdict <v> --iterations <n>`
  (capture `--pre` with `shctx plan hash <p>` BEFORE the critic dispatch).
- Root verifies it: `shctx plan verify --plan <p>` (mirrors the v6.2.1
  `shctx seed verify` gate). It re-hashes the CURRENT plan bytes and requires
  `post_critic_hash` to match — so a stale or hand-forged proof cannot pass.

The critic agent produces findings; the deterministic hash-proof + verifier make
"the plan was critiqued AND edited at least once" **provable**, not asserted
(the latent→deterministic split, CLAUDE.md).

## Root's thin acceptance gate — no re-critique, no re-discovery

On receiving a self-contained engineer teammate's plan, root runs ONLY:

1. `shctx seed verify <seed>` (the existing v6.2.1 seed gate), and
2. `shctx plan verify --plan <plan>` (the critic-proof gate), and
3. a lane-count sanity check (≥1 lane; count within the T-shirt band,
   `agents/engineer.md §Lane-count guidance`).

All green → root proceeds to `LANE-INTEGRATE`
(`doctrines/teammate-integration-authority.md`). Root does **not** run its own
INTRO-COMBO-WAVE and does **not** re-run `@critic` — the engineer already did both,
in its own window. A failed gate returns the named code
(`CRITIC-PROOF-MISSING` / `PLAN-UNEDITED` / `CRITIC-PROOF-STALE` /
`PLAN-UNCRITIQUED`) to the engineer teammate for a fresh pass — root never repairs
the plan itself.

## Why this saves context (the point of the migration)

In classic mode, root pays for the whole discovery wave, the whole intro-audit
wave, and the `@critic` findings — all of it lands in root's window before the
plan is even accepted. On an ultra-parallel spawn, root is the coordination
bottleneck, and that wave context is the majority of what fills it. Moving the
waves into the engineer's teammate session leaves root with a thin, mechanical
gate over a finished artifact. Same workflow, same certification, a fraction of
root's context. This is the shepherd north-star: lean wiring, token/cache-efficient.

## Mechanical teeth

- `shctx plan verify` is deterministic and exit-coded; root's thin gate is a
  mechanical call, not a judgment.
- The proof's `post_critic_hash` is checked against the live plan bytes, so the
  gate cannot be satisfied by an unedited plan or a proof describing an older one.
- `dispatch_guard.sh` enforces the topology + scope mechanically: Check 4b
  `ENGINEER-TOPOLOGY-MISMATCH` blocks a self-contained engineer dispatched as a
  subagent; Check 4 `WRONG-TIER-DISPATCH` blocks a nested `@engineer`
  (unconditional) and a conductor-lane `@critic` re-gate; Check 4c
  `ENGINEER-SUBFLOCK-VIOLATION` blocks a marked (`dispatcher: engineer-self-contained`)
  dispatch to anything outside the read-only trio — so "no code is touched" has
  mechanical teeth, not prose. The engineer tags EVERY sub-flock dispatch with the
  marker so Check 4c is total over its dispatches.
- The engineer's `Agent` grant is pinned to the read-only sub-flock
  (`shepherd:discovery` / `shepherd:auditor` / `shepherd:critic`) by
  `hooks/tests/lint_agent_capabilities.sh`; it may never carry a write-role
  dispatch (`@coder`/`@worker`).
- Coverage row: `doctrines/invariant-enforcement-matrix.md`.

## Anti-patterns

- **Fixed-count discovery fan-out.** Dispatching a hard-coded "always 5"
  `@discovery` batch instead of the T-shirt-scaled, scope-partitioned wave — the
  v6.2.5 failure that "ate our discovery dynamic workflow." Scale N/M to scope.
- **Self-activating on ambiguity.** Running self-contained without all three mode
  signals — default classic when unsure.
- **Engineer as a bare subagent in self-contained mode.** Blocked by
  `ENGINEER-TOPOLOGY-MISMATCH`; self-contained is a named teammate.
- **Nested / phantom engineer.** The engineer dispatching `@engineer` — blocked
  unconditionally; a leader does not spawn another leader.
- **Touching code.** The engineer or its sub-flock writing source — the sub-flock
  is read-only; the engineer writes only `.md`/reports/plan. Dispatching `@coder`/
  `@worker` (or any non-trio role) under the leader marker is blocked mechanically
  (`ENGINEER-SUBFLOCK-VIOLATION`); file a plan step for the conductor's coder wave
  instead.
- **Root re-critiquing / re-discovering.** Running `@critic` or the INTRO-COMBO-WAVE
  on a plan that already carries a valid critic-proof — the context bloat this
  doctrine exists to remove.
- **Recording a critic-proof with `edited=false`** — `shctx plan verify` fails it
  (`PLAN-UNEDITED`).

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
