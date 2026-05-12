---
title: autorun
description: Sequential autopilot — same pipeline as /shepherd:start but skips the PAUSE between sprints. One conductor, one flock, one sprint at a time, no inter-sprint pause until a hard stop or operator interrupt.
---

# shepherd/autorun — Sequential Autopilot

Activated by `/shepherd:autorun`. **One conductor session, one flock, one sprint at a time.** This mode does exactly one thing differently from `/shepherd:start`: it skips the PAUSE between sprints and immediately seeds dev.{N+1} after closing dev.{N}.

That is the entire feature. There is no parallel branching, no worktree fan-out, no multi-sprint interleaving. For the multi-sprint parallel-orchestration mode, see `parallel.md` (`/shepherd:parallel`).

---

## What changes vs `/shepherd:start`

| `/shepherd:start` | `/shepherd:autorun` |
|---|---|
| PAUSE after every sprint close | No PAUSE — seed dev.{N+1} immediately |
| User clears context manually between sprints | Conductor continues into next sprint |
| User explicitly re-invokes `/shepherd:start` | Loop continues until exit condition |
| dev.{last} close → STOP, wait for release signal | dev.{last} close → STOP unless sprint-through granted |

Everything else is **identical** to `/shepherd:start`:

- @engineer authors plan via `superpowers:brainstorming` + `superpowers:writing-plans`, gated by @critic
- Coder waves dispatched in parallel batches per the Brief-Validity Checklist
- Gates between every wave (one pass: `[gates.check]` + `[gates.lint]` + `[gates.format]` + `[gates.extra]`)
- @auditor swarm of 3–5 by concern at sprint close (Pattern B overlap during waves)
- Close finalizer: handoff doc + memory update + project CLAUDE.md patch
- Rebase-merge into patch branch → cut next sprint branch

---

## The autonomous loop (v4.2.0 — graph walk)

```
┌────────────────────────────────────────────────────────────────────┐
│ (1) Orient: handoff + CLAUDE.md + shepherd.toml + branch detect    │
│ (2) Verify seed for dev.{N}; ensure §"Stage decomposition hint" is  │
│     present (per references/seed-template.md §7-bis)                │
│ (3) Dispatch @engineer (Opus): Phase 0 mesh + binding Stage Graph   │
│     (per pipeline.md §XII)                                          │
│ (4) Parse plan's `## Stage Graph` YAML → build in-memory DAG        │
│ (5) WALK ALGORITHM (per pipeline.md §V):                            │
│       while ready_set is non-empty:                                 │
│         batch = group ready_set by parallel_with cliques            │
│         fire batch as ONE Agent message (or conductor inline)       │
│         await returns                                               │
│         evaluate each node's outgoing edge predicates               │
│         advance ready_set                                           │
│       (DEDUP-GATE blocks WAVE-IMPL until all greps return expected) │
│       (Pattern B is encoded as parallel_with — fires automatically) │
│       (HOTFIX subgraphs fire on on-finding edges)                   │
│ (6) CLOSE-FINALIZE: rebase + DELETE + cut dev.{N+1} + handoff       │
│ (7) Re-enter (1) with the new sprint                                │
└────────────────────────────────────────────────────────────────────┘
```

The conductor does NOT compose dispatches each iteration. The Stage Graph IS the dispatch contract; the loop walks the graph deterministically. This is the cognitive-load reduction over pre-4.2.0.

Conductor does NOT idle while the flock runs. It uses spare cycles to:

- Draft the next sprint's seed (if confidence is high)
- Triage one-shot health/error/deploy queries
- Read audit reports as they land
- Update memory with learnings

---

## What the user sees

- Periodic check-in summaries as waves close
- Commits landing with `fix(dev.N/<track>): <subject>`
- Build pipeline running automatically (CI-triggered on rebase) per project config
- A final summary on exit

---

## What the conductor still asks the user for

- Sign-off on merges to `main` (unless sprint-through granted)
- Secret / credential rotations
- Anything irrevocable outside the flock's scope
- When the conductor has lost thread and needs alignment

These all surface as `[ ]` entries in `questions.md` plus a direct stop with explanation.

---

## Hard stops (always halt the loop; surface to user)

1. **@critic returns RED** or substantive pass-2 flag → operator amendment needed
2. **Gates broken** after all coder waves exhausted → no wave can resolve it
3. **dev.{last} close without sprint-through** → release signal required
4. **Secret / credential rotation needed** → outside flock scope
5. **Seed drift** from Phase 0 mesh — verify per `doctrines/chain-repair.md` before escalating; if substantive, halt
6. **Operator interrupt** — "pause", "stop", "exit autorun"
7. **Coder rejected brief with `BRIEF INVALID`** → fix conductor's brief before re-dispatch (do not silently retry)

On exit: write final entry to `questions.md` with what landed, what's running, what's next, what needs the operator. Then stop.

---

## Sprint-through grant (dev.{last} release autonomy)

The default behavior on dev.{last} close is STOP and wait for the operator's release signal. To pre-authorize the full release pipeline, the operator says one of:

- "sprint through"
- "autonomous release at dev.{last}"
- "pipe through to v{next}"

OR a per-project memory entry tagged with the current version exists.

Sprint-through authorizes the dev.{last} release pipeline (squash → main → tag → release → bump → cut next patch + dev.0). Non-dev.{last} merges to main still require explicit approval.

---

## Per-sprint discipline (binding under autorun)

### Critic-pass-2 fast path

If @engineer revised once and @critic still flags:

- Flag labeled `dispatcher-patch` → conductor applies inline + informal pass-3 → ship on GREEN
- Flag labeled `substantive` → log to `questions.md`, STOP this sprint's coder dispatch, continue any non-blocking work

### Between waves (every wave)

```
{gates.check}
{gates.lint}
{gates.format}
# then [gates.extra] if any
```

Then health probes (one-shot deploy/error/datastore queries). Anything > 10 min → @worker.

### Sprint close checklist (automated)

- [ ] All gates green
- [ ] CI pipeline green
- [ ] Auditor swarm reports written
- [ ] Synthesized close report + grade
- [ ] dev.{N+1} seed written
- [ ] Memory / project doctrines updated
- [ ] `questions.md` updated
- [ ] Rebase-merge into patch branch
- [ ] dev.{N+1} branch cut + pushed

---

## Termination

Autorun exits when:

1. User says "pause", "stop", "exit autorun"
2. A hard stop (§hard stops above) is reached
3. dev.{last} closed and sprint-through NOT granted (waiting for release signal)

On exit, write the final `questions.md` entry and stop.

---

## What autorun is NOT

- Not parallel — for parallel worktree fan-out, use `/shepherd:parallel`
- Not unsupervised — operator is monitor; the conductor still STOPS on hard conditions
- Not a license to skip discipline — every flock rule from `SKILL.md`, `flock.md`, and `pipeline.md` applies unchanged
- Not a license to skip the DEDUP-GATE — the dedup pre-flight runs on EVERY wave, every sprint, regardless of how confident the plan looks
- Not a release blanket — main merges still need approval (sprint-through covers dev.{last} only)
