# Hot-fix dispatch cardinality ladder — binding doctrine

> Added v6.0.8 (#135). The shepherd was observed spinning up a hot-fix
> *teammate* for a single-coder dispatch — paying full Agent-Teams setup,
> liveness, and mailbox cost for one bounded edit. This doctrine fixes the
> default: a hot-fix's dispatch vehicle is chosen by **how many independent
> hot-fixes there are**, and a dynamic workflow (Claude Code's native `Workflow`
> tool — always present, never a `ToolSearch` target; `references/glossary.md`) is
> always reached for before a dedicated teammate.

## The principle

> A hot-fix is unplanned, unseeded remediation work surfaced by a gate failure
> (`WAVE-GATE on-fail`) or an audit finding (`WAVE-AUDIT` / `CLOSE-SWARM`
> `on-finding`). The number of **file-disjoint independent hot-fixes** — call it
> `H` — selects the dispatch vehicle. Reach for a **dynamic workflow** (a
> compiled out-of-context agent fanout, `doctrines/dispatch-cascade.md §IV-bis`)
> **before** a dedicated teammate. A teammate is the heaviest vehicle and is
> justified only when the batch is large enough to need its own conductor and
> loop to drive to completion.

Three corollaries:

1. **Vehicle ≠ concurrency.** The ladder picks the *vehicle* (single subagent
   vs root-dispatched batch vs dedicated lane). It does NOT change the existing
   **≤3 concurrent coders per HOTFIX batch** concurrency cap (`pipeline.md §VII`,
   `agents/conductor.md` HOTFIX subgraph). Those compose: a 5-HF batch still
   dispatches ≤3 coders concurrently, chunking the remainder.
2. **Speed, precision, cost — in that order — favor the workflow.** A dynamic
   workflow runs the fanout out-of-context (no held-open teammate session, no
   liveness polling), is precise (one brief per file-disjoint cluster), and is
   cheaper than a teammate. A teammate is reached for only at the top of the
   ladder.
3. **Be certain you cannot batch before you spawn anything.** A single hot-fix
   that is merely *awaiting another agent's result* is not yet a hot-fix to
   dispatch — it is a dependency edge. Do not spin a vehicle for it until the
   blocking result lands and you know whether it batches with siblings.

## The ladder

Let `H` = the count of file-disjoint independent hot-fixes ready to dispatch.
Domain notation in the band column: `(a, b]` excludes `a`, includes `b`.

| Band | `H` | Vehicle | Dispatcher | Why |
|------|-----|---------|-----------|-----|
| **Single** | `H = 1` | ONE single subagent — a dynamic-workflow `agent()` step (one `@coder`). **NEVER a teammate.** | Root shepherd (spawn) or conductor (solo) | A teammate's setup/liveness/mailbox cost is pure waste for one bounded edit. |
| **Batch** | `(1, 5]` → `H ∈ {2,3,4,5}` | ONE batched dynamic workflow — clusters fanned out as a single compiled segment. | **Directly by the root shepherd** (spawn) / conductor inline (solo) | A handful of disjoint fixes is a fanout, not a sprint. The root drives it without delegating to a teammate. |
| **Lane** | `H ≥ 6` | A **dedicated HOT-FIX lane**: one teammate-conductor instance with its own Stage-Graph loop to drive the full batch to completion. | Root shepherd spawns the lane (spawn-mode only) | At ≥6 independent fixes the batch needs its own conductor + iteration loop to gate-rerun and converge; a one-shot workflow under-serves it. |

The `H = 6` boundary is **hard**: the fifth HF still rides the root-dispatched
batch; the sixth automatically promotes the whole batch to a dedicated lane.

```
                    H hot-fixes ready (file-disjoint)
                                │
          ┌─────────────────────┼─────────────────────────┐
        H = 1                (1, 5]                      H ≥ 6
          │                     │                           │
  ONE single subagent   ONE batched dynamic        DEDICATED HOT-FIX lane
  (dynamic-workflow      workflow, dispatched       (teammate-conductor +
   agent() step)         DIRECTLY by root           own Stage-Graph loop)
  NEVER a teammate       shepherd                   drives batch to done
```

## Counting `H` — what is one hot-fix

`H` counts **file-disjoint clusters**, not raw findings. Two findings in the
same file are ONE cluster (one coder owns the file). The clustering is the same
file-disjoint partition `HOTFIX-DYNAMIC` already performs on gate errors
(`pipeline.md §II`, §XIII-bis):

1. Collect the findings/errors (auditor `Suggested hot-fix lane` blocks, or the
   structured gate-error parse).
2. Partition by file-disjoint scope — each cluster is one coder's `[FILE-SCOPE]`.
3. `H` = the number of clusters. Apply the ladder to `H`.

A single 12-error cluster confined to one file is `H = 1` — one subagent, not a
teammate, regardless of error count.

## The single-HF rule (the bug this doctrine fixes)

When `H = 1`:

- Dispatch **exactly one `@coder`** as a dynamic-workflow `agent()` step (the
  one-agent compiled segment of `doctrines/dispatch-cascade.md §IV-bis`; in
  solo mode, a single in-context `@coder` dispatch).
- **Do NOT** spawn a teammate-conductor, do NOT open a
  HOT-FIX lane. A teammate for one fix is the `WRONG-VEHICLE` anti-pattern.
- **Certainty gate before dispatch.** Confirm both:
  - You genuinely have only one fix — you are not about to surface a sibling
    finding from the same wave that would batch with it.
  - The fix is not merely *awaiting another agent's result*. If it is, hold:
    once the result lands you may discover `H ≥ 2` and a batch is correct.

  If either is uncertain, prefer to wait one tick and re-count `H` rather than
  commit a vehicle.

## The batch rule — `(1, 5]` (the **HOTFIX-BATCH** composite)

This band is the **HOTFIX-BATCH** named composite registered in
`doctrines/workflow-patterns.md` — a Pattern-2 (Fanout-And-Synthesize) fanout,
not a new Stage-Graph node type (the underlying node stays `HOTFIX-DYNAMIC`).

When `H ∈ {2,3,4,5}`:

- The **root shepherd dispatches the batch directly** (spawn-mode) — it does NOT
  delegate the batch to a teammate-conductor. In solo `/shepherd:start`, the
  conductor dispatches it inline.
- Cluster by file-disjoint scope; emit ONE compiled dynamic-workflow segment
  with one `agent()` step per cluster (the `HOTFIX-DYNAMIC` compile path).
- The ≤3-concurrent-coders cap still binds: a 4- or 5-cluster batch runs in
  ≤3-wide chunks (`Promise.all` chunked per `dispatch-cascade.md §IV-bis`).
- After all clusters return, re-run the gate ONCE (`pipeline.md §II`). Iterate
  to the 3-iteration `HOTFIX-DYNAMIC` cap before `HARD-STOP`.

## The lane rule — `H ≥ 6`

When `H ≥ 6` independent file-disjoint hot-fixes are ready:

- The root shepherd **auto-creates a dedicated HOT-FIX lane** — one
  teammate-conductor instance (spawn-mode; native teammate-spawn per `commands/spawn.md`),
  with its own Stage-Graph loop, dispatched to drive the whole batch to
  completion (impl → gate-rerun → converge).
- The lane is **not** seeded/planned work — it is an injected remediation lane.
  It loops (gate-rerun per cluster wave) until the batch is green or the
  iteration cap is hit, then closes back to the root.
- This is the only band where a teammate is the correct vehicle. Below it, a
  dynamic workflow is mandatory.
- Solo `/shepherd:start` has no teammates: a solo run that reaches `H ≥ 6`
  surfaces a `HARD-STOP` recommendation to the operator (the volume warrants a
  spawn-mode dedicated lane) rather than silently degrading to a wide in-context
  batch.

## How this composes with existing HOTFIX nodes

| Existing surface | What it owns | What this doctrine adds |
|---|---|---|
| `HOTFIX` (`pipeline.md §VII`) | Pre-declared count, ≤3 concurrent, ≤S scope, 3-iteration cap, paste auditor's `Suggested hot-fix lane` block | The **vehicle** for that count is chosen by the ladder, not improvised |
| `HOTFIX-DYNAMIC` (`pipeline.md §II`, §XIII-bis) | Runtime file-disjoint cluster count from gate errors | `H` = cluster count feeds the ladder; the dynamic workflow IS the `(1,5]` vehicle |
| `HOTFIX-CLOSE` (`agents/shepherd.md`) | Close-swarm CRITICAL/HIGH remediation | Default is a dynamic workflow, not a re-spawned teammate; teammate only at `H ≥ 6` |

The ladder is orthogonal to the **≤3 concurrent coders** cap and to the
**3 HOTFIX iterations** cap — both still bind inside whatever vehicle the ladder
selects.

## Anti-patterns

1. **Teammate for a single HF.** `H = 1` → ONE subagent. Spawning a
   teammate-conductor (or any teammate) for one fix is `WRONG-VEHICLE`.
2. **Premature dispatch while awaiting a result.** Spinning any vehicle for a
   fix that is only waiting on another agent's output. Re-count `H` after the
   result lands.
3. **Delegating the `(1,5]` batch to a teammate.** The root dispatches the batch
   directly; handing it to a teammate-conductor adds a coordination hop for no
   gain below `H = 6`.
4. **Skipping the lane at `H ≥ 6`.** Cramming six-plus independent fixes into a
   one-shot batch under-serves the convergence loop — promote to a dedicated
   HOT-FIX lane.
5. **Counting raw findings instead of file-disjoint clusters.** Two findings in
   one file are `H = 1`, not `H = 2`. Cluster first, then apply the ladder.

## See also

- `pipeline.md §II` — `HOTFIX-DYNAMIC` cardinality (runtime file-disjoint cluster count)
- `pipeline.md §VII` — the HOTFIX subgraph (≤3 concurrent, ≤S scope, 3-iteration cap)
- `pipeline.md §XIII-bis` — structured gate output → file-disjoint cluster → parallel HF dispatch
- `doctrines/dispatch-cascade.md §IV-bis` — fanout segments run as Dynamic Workflows (the `(1,5]` vehicle; one-agent segment = the `H=1` vehicle)
- `doctrines/workflow-compile-down.md §VII` — compiler authors the segment; read-only allowlist binds under acceptEdits
- `doctrines/workflow-patterns.md` — Pattern 2 (Fanout-And-Synthesize) circuit-breakers apply to the batch band
- `doctrines/dispatch-tier-separation.md §IV-bis` — `@coder` dispatch shape; root-vs-teammate vehicle rules
- `agents/conductor.md` — HOTFIX / HOTFIX-DYNAMIC walk-tick rules the ladder governs
- `agents/shepherd.md` — root HOTFIX-CLOSE dispatch decision
- `#61` (match tier to work) — single-file/bounded work becomes a one-agent step, not a heavier allocation (`workflow-compile-down.md §VIII`)
