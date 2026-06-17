# Operator signaling — the planter asks; execution sessions run (session → operator)

> Two postures, deliberately different — and now mechanically separated:
> - The **planter** plans WITH the operator. It is the framework's **sole interactive
>   asker** and the only profile that carries the `AskUserQuestion` tool.
> - **Execution sessions** (`/shepherd:start` SOLO, `/shepherd:spawn` root) are biased to
>   **ACTION**. As of v6.1.7 they **do not carry `AskUserQuestion` at all** — they cannot
>   pop a structured question. Their only operator touchpoints are the enumerated
>   turn-ending pauses (reports the operator replies to in chat), never a mid-run "let me check".
>
> This is the inverse of `mid-flight-operator-amendment.md` (operator → session).

## Planter — the sole interactive asker (planning is interactive)

The planter (`/shepherd:plant`) is the planning session, just detached. During its
read-everything phase it RESOLVES ambiguity WITH the operator instead of inventing
answers: unclear objective / scope / acceptance, competing approaches, which work items
belong in this arc, version-tier intent. Ask liberally, structured, batched.
**This is the right place for questions** — answered here, execution doesn't have to stop.

**Mechanical rule (binding):** the planter surfaces every operator question via the
**`AskUserQuestion` tool** — NEVER as prose typed into the chat / terminal. A question
written as terminal prose is the `INLINE-QUESTION-MISUSE` anti-pattern (`agents/planter.md
§Anti-patterns`): it throws away the structured, batchable, resumable interaction the tool
provides, and it is the exact habit this contract exists to kill. If you find yourself
typing "Question 1: … / Question 2: …" into the chat, stop and call `AskUserQuestion`.

## Execution sessions — bias to action; no structured questions

`/shepherd:start` (SOLO) and `/shepherd:spawn` (root) **do not carry `AskUserQuestion`**
(removed from their toolset, v6.1.7). Their default posture is **proceed**. They reach the
operator ONLY through the framework's enumerated **turn-ending** pauses, each of which emits
a concrete report or decision prompt the operator answers in chat:

- pre-spawn approval gate, `--scope` gates, the sprint-close PAUSE, dispute adjudication,
  `HARD-STOP`, and an explicit operator interrupt (`doctrines/coordinate-active-drive.md §II`).

These are structural boundaries, not interactive questioning. Everything between them is
action. Specifically, an execution session does NOT:

- ❌ ask for confirmation / approval — "should I proceed?", "does this look right?";
- ❌ ask for reassurance, status check-ins, or narrate a decision it is equipped to make;
- ❌ stop on anything with an obvious default — pick it, note it in the report, move on;
- ❌ invent NEW stop points. A decision worth recording goes in the close report, not a
  mid-sprint interrupt. A runner that stops every time it wants reassurance has failed.

If an execution session feels it needs to ask the operator a free-form question, that is a
signal the work should have been **planted** first (`/shepherd:plant`) — route it there;
do not grow a question habit in the runner.

**Teammate-conductors NEVER contact the operator** — they escalate to root via `SendMessage`
(`doctrines/dispatch-tier-separation.md`); root decides whether anything reaches the operator,
and surfaces it as a turn-ending report (root has no `AskUserQuestion` either).

## Seed is recommended, not required

A seed is the best drift anchor, but `/shepherd:spawn` and `/shepherd:start` run WITHOUT one —
never hard-refuse for a missing seed:

1. If the objective is **derivable** from the handoff / issue ledger / branch / repo state,
   RUN on best-effort defaults. Record the assumed objective + scope + done-criteria and the
   elevated drift risk in the plan header and the close report.
2. If the objective is **not derivable at all**, do NOT guess a sprint into existence and do
   NOT pop a question (the tool is gone). Emit a one-block turn-ending report recommending the
   operator either state the objective in chat or run `/shepherd:plant` first — then stop.
3. Seedless trades drift-resistance for speed, with eyes open. Keep the EXISTING pause/gate
   discipline; do NOT add new interrupts to compensate.

The seed remains the happy path: a planted seed front-loads the questions (planter ↔ operator,
via `AskUserQuestion`) so execution runs uninterrupted.
