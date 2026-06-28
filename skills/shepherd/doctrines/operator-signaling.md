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

## Seed is recommended, not required — a seedless single-sprint run plants inline

A seed is the best drift anchor, but a missing one no longer dead-ends a run. The
FIRST node of a single `--scope sprint` walk is `SEED-AUTHOR` (`pipeline.md` §IV):

1. **Seed present** → no-op pass-through; the walk proceeds exactly as today.
2. **Seed absent** → emit ONE turn-ending confirm: *"No seed for `<slug>`. Plant
   inline now, or state the objective / run `/shepherd:plant` for the full
   treatment?"* This is an enumerated structural pause, not a mid-run "let me
   check" — it REPLACES the old "go run `/shepherd:plant` and come back" report
   with a one-tap continuation (same single stop, no session hop, action-bias
   intact). On the operator's reply, the session loads the planter inner frame
   (`agents/planter.md §Plant mode`, two-meta-loading), authors the seed from that
   reply + the planter mesh, and the seed must pass `shctx seed verify` (the
   `SEED-GATE`) before the walk falls through to `INTRO-COMBO-WAVE`. The committed
   seed is the durable intent capture — no objective lives only in chat.
3. **Multi-sprint** (`--scope patch | minor | version`, `--parallel`) is unchanged:
   a missing seed still routes to `/shepherd:plant` (`spawn.md` Check 6) — those are
   deliberate multi-seed planning sessions, not a quick spawn.

This does NOT re-admit `AskUserQuestion` to execution sessions — **v6.1.7 holds**.
The inline sub-phase gathers intent the way execution sessions always reach the
operator: a turn-ending report answered in chat. The structured, batched
`AskUserQuestion` front-loading remains the dedicated `/shepherd:plant` session's
advantage; an operator who wants it plants first (or loads the planter frame
in-session via two-meta-loading). Between `SEED-GATE` and close the run invents no
new stops — the inline confirm is the one structural pause, and it fires only when
there is genuinely no seed. The seed remains the happy path: a planted seed
front-loads the questions so even `SEED-AUTHOR` is a pass-through.
