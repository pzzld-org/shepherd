# Operator signaling — the planner asks; execution sessions run (session → operator)

> Two postures, deliberately different:
> - The **planter** plans WITH the operator — asking is core to its job.
> - **Execution sessions** (`/shepherd:start`, `/shepherd:spawn` root) are biased to
>   **ACTION**. They carry `AskUserQuestion` only as a NARROW escape valve, not a habit.
>   They must NOT start stopping for confirmation or approval.
>
> This is the inverse of `mid-flight-operator-amendment.md` (operator → session).

## Planter — ask freely (planning is interactive)

The planter (`/shepherd:plant`) is the planning session, just detached. During its
read-everything phase it RESOLVES ambiguity WITH the operator via `AskUserQuestion`
instead of inventing answers: unclear objective / scope / acceptance, competing approaches,
which work items belong in this arc, version-tier intent. Liberal, structured, batched.
**This is the right place for questions** — answered here, execution doesn't have to stop.

## Execution sessions — bias to action; ask only when truly blocked

`/shepherd:start` (SOLO) and `/shepherd:spawn` (root) carry `AskUserQuestion`, but their
default posture is **proceed**. The bar to interrupt the operator is HIGH. Use it ONLY when:

- **No seed AND no derivable objective** — ONE batched kickoff question to set direction
  (objective + scope + done-criteria), then RUN. (See "Seed is recommended, not required".)
- A **destructive / irreversible outward action** with no safe default — force-push to a
  shared branch, release, data delete, publish.
- A **hard fork that blocks all forward progress** and has no sensible default.

Do NOT use it for:

- ❌ confirmation or approval — "should I proceed?", "does this look right?", "ok to continue?";
- ❌ reassurance, status check-ins, or narrating a decision you are equipped to make;
- ❌ anything with an obvious default — pick it, note it in the report, move on;
- ❌ **adding NEW stop points.** The framework already has defined boundaries (PLAN-GATE,
  the operator PAUSE at sprint close, `--scope` gates). Honor those; do not invent mid-run
  "let me check" stops. A decision worth recording goes in the close report, not a mid-sprint
  interrupt. An execution session that stops every time it wants reassurance has failed.

**Teammate-conductors NEVER ask the operator** — they escalate to root via `SendMessage`
(`doctrines/dispatch-tier-separation.md`); root decides whether anything reaches the operator.

## Seed is recommended, not required

A seed is the best drift anchor, but `/shepherd:spawn` and `/shepherd:start` run WITHOUT one —
never hard-refuse for a missing seed:

1. If there is no seed and the objective is not derivable from the repo / issue ledger, ask
   ONE batched kickoff `AskUserQuestion` (objective + scope + done-criteria), then run.
2. Seedless means less ground truth — keep the EXISTING pause/gate discipline; do NOT add new
   interrupts to compensate. Lean on sensible defaults and surface drift risk in the report.
3. Note the elevated drift risk in the plan header and the close report.

The seed remains the happy path: a planted seed front-loads the questions (planter ↔ operator)
so execution runs uninterrupted. Seedless trades drift-resistance for speed, with eyes open.
