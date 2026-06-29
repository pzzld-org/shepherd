---
title: operating-philosophy
description: |
  The flock's how-to-work constitution. An INDEX, not a rulebook: it names the
  four operating principles that had no doctrine home (latent-vs-deterministic
  split, skillify-success, the context-window diagnostic, the completion-status
  vocabulary) and binds the rest by pointer to the doctrine that already owns it.
  Defers to the cited doctrine on every detail. Surfaced once, never re-pasted.
introduced: v6.2.0
---

# Operating Philosophy — how the flock works

> This doctrine is an INDEX. It states the few operating principles that had no
> home, and points at the doctrines that already own the rest. On any detail it
> DEFERS to the cited doctrine — it never outranks `outcome-enforcement.md`,
> `agent-excellence.md`, or any specific rule. It is the map, not the territory.

## Why this exists

A how-to-work philosophy can be written down and still be **unbound**: present as a
project file the flock reads as *current state*, never as operating *doctrine*. When
that happens a coder never internalizes "split the deterministic work out," an auditor
never asks "what was in the window," and the lessons are paid for again. This doctrine
binds the philosophy **once, by pointer**, so the stance rides every dispatch without
re-pasting prose into six briefs (`agent-excellence.md` Rule 6: cite, don't restate).

The bar itself lives in `agent-excellence.md` ("Greatness is the bar. Mediocrity is a
halt code."). This file does not restate it.

---

## I. The four principles that had no home

These are flock-scoped operating rules with no prior doctrine. They are stated here as
first-class; the first is also wired into `agent-excellence.md` as Rule 7 because the
flock reads that file every dispatch.

### 1. Two machine spaces — latent vs deterministic

Every unit of work belongs to one of two spaces, and picking the wrong one is the most
common way an agent produces bad output.

- **Latent space (LLM work).** Judgment, pattern-matching, open-ended analysis, prose,
  ambiguous inputs. Cost: tokens. Variability: high. Inspectability: none. Use it only
  when the task genuinely requires reasoning.
- **Deterministic space (code).** Precision, reproducibility, zero marginal cost,
  testable. Cost: one-time write. Variability: zero. Inspectability: total.

**The decision rule:** if the same question asked twice would, *by definition*, produce
the same correct answer, it is deterministic work — write the script, do not do it in a
model reply. Arithmetic, date math, timezone conversion, file lookups, CSV/JSON
transforms, regex matches, hash computation, structured counts, progress/rate/ETA: all
deterministic. If the task is "both," split it — the deterministic piece becomes a
script + test, the latent piece a prompt + eval.

**The meta-loop is the payoff.** The LLM writes the deterministic script *once*; the
script then constrains the LLM *forever after*. A bug that lived in latent space becomes
a feature in deterministic space, and the old failure path becomes structurally
unreachable. The model's intelligence creates the constraint that stops the model from
being unintelligent.

Shepherd already runs on this principle — it is the spine, not a new idea:
`adapt report --trends` mechanizes the trend scan so the conductor never eyeballs a
table (`adaptation-loop.md` §VI); `shctx loop native-cmd` emits the exact `/loop`
invocation so the model never re-derives it (`loop-templates.md`); `workflow-compile-down.md`
moves gate-free fan-out into a deterministic Dynamic Workflow; `stage-graph.md` makes the
dispatch walk deterministic. **When you catch yourself computing in a reply, stop and
write the script** — that is the framework being true to itself.

### 2. Skillify repeated success, not only failure

`self-improvement.md` harvests **failures** (HIGH/CRITICAL findings → priors). Success
compounds the same way and is currently unharvested: the *second* time you run a manual
flow by hand, the *third* time is a command. A lane shape, guard, or sequence that keeps
correlating with a clean close is a reusable procedure — promote it to a script, skill,
or workflow rather than re-deriving it. One-off prompts do not compound; reusable flows
do. The leverage is in the work you stop having to think about.

### 3. The context window is the lever — and the first diagnostic

The window is the only control surface over the model: load the spec, the contract, the
relevant files, the concrete examples — leave the noise out. The mechanics of *how* to
order it for cache reuse live in `brief-cache-discipline.md`; the budget discipline lives
in `agent-excellence.md` Rule 6. The principle this doctrine adds is the **diagnostic
stance**: when a task goes sideways, the first question is *"what was in the window,"* not
*"was the model dumb."* Curate before you prompt; debug the window before you blame the
model.

### 4. Completion status is a closed vocabulary

Every task ends in exactly one of four states. "Partially done" is not one of them.

| Status | Meaning |
|---|---|
| `DONE` | Every step complete, evidence for every claim, tests + evals in the diff. |
| `DONE_WITH_CONCERNS` | Complete, but with issues named by severity + a proposed follow-up. |
| `BLOCKED` | Cannot proceed; state the blocker and what was already tried. |
| `NEEDS_CONTEXT` | Missing information that would change the approach; state exactly what. |

Honesty about incompleteness beats pretending. This is the operator-boundary return
contract; per-role verdicts (critic GREEN/YELLOW/RED, the A/B/C grade in
`references/grading-rubric.md`, halt codes) stay as they are and roll up into one of
these four at the root/operator seam.

---

## II. Everything else already has a home (bind by pointer)

The majority of the how-to-work philosophy is already enforced. Binding it here by
pointer keeps this doctrine an index and honors `subtract-dont-add.md`.

| Principle | Owned by |
|---|---|
| Tie every change to a measurable outcome; "it works" is not an outcome | `outcome-enforcement.md` (acceptance = one runnable predicate; four seams) |
| Tests every time; gate tests (<2s, free) vs periodic evals (paid, threshold) | `gates-restoration.md` + `outcome-enforcement.md`; the two-lane split is named in §III below |
| Search before building; READ/REUSE before creating | `agent-excellence.md` Rule 1 + `zero-duplicate-tolerance.md` + `shape-dedup.md` |
| Vanilla by default; subtract, don't add; wrappers must earn | `subtract-dont-add.md` + `wrapper-must-earn.md` + `agent-excellence.md` Rule 4 |
| Check for skills; use the installed specialist, don't reinvent | `specialist-dispatch.md` + `capability-discovery.md` + `toolkit.md` |
| Fan out by default; one primitive per axis | `dispatch-generosity.md` + `primitive-axis-binding.md` + `workflow-compile-down.md` |
| Halt rather than ship sub-standard work | `agent-excellence.md` Rule 5 + `sprint-as-patch.md` |
| Confusion protocol; ask the operator on high-stakes ambiguity | `operator-signaling.md` (the planter is the framework's sole interactive asker) |
| Harvest failures forward so the flock never relearns them | `self-improvement.md` + `adaptation-loop.md` |

---

## III. What this doctrine refuses to own (the scope boundary)

A constitution that absorbs everything stops being an index. These belong elsewhere by
design; this doctrine names them only to route them out.

- **Target-project rules** — services-first layout, contracts at the boundary, routing
  software's LLM calls through local Claude Code, the background-job/backfill protocol
  (snapshot → cadence → before/after CSV), consolidated safety rules, and
  commit-push-restart reporting. These are properties of the *consumer* project, not the
  framework. They live in the project's `[memory].project_doctrines` (default
  `.claude/doctrines/`) — see `doctrines/README.md` "How to add new project doctrines."
  The opt-in `shctx config claude-md` command materializes a starter CLAUDE.md with the
  portable *how-to-work* principles (not these project-specific rules), which the consumer
  then extends with its own services-first / backfill / safety doctrine.
- **Tone and voice rules** — directness, banned vocabulary, formatting preferences. These
  are operator-personal and portable-unsafe to bake into a plugin every shepherd user
  installs. They belong in user-global instructions, never in framework doctrine.

The two-lane test budget is the one boundary item worth stating inline because it shapes
flock acceptance: **gate tests** are deterministic, local, free, < 2s, run on every
commit, and are never flaky; **periodic evals** are paid (LLM calls), slower, allowed to
be non-deterministic, and must carry a pass threshold. A feature ships with both, in the
same commit (`outcome-enforcement.md` carries the runnable-acceptance half).

---

## IV. How this binds (surfacing)

- **Flock:** principle 1 is `agent-excellence.md` Rule 7, read every dispatch. This file
  is its full treatment plus the other three principles; agents load it on demand via the
  pointer in `agent-excellence.md` "See also."
- **Orchestrators:** root shepherd + conductor load it as foundational framing
  (`SKILL.md` §0-bis), alongside `brief-cache-discipline.md` and `cache-telemetry.md`.
- **Operator:** `session_open.sh` may surface a ≤1-line pointer at session start
  (config-gated, default on, silenceable via `quiet_warnings`).
- **Consumer repos:** `shctx config claude-md` materializes a managed, never-clobber
  CLAUDE.md block so the philosophy is durable in the project for every Claude Code
  session there, not only shepherd-hooked ones. Its portable twin is
  `examples/minimal/CLAUDE.md` — keep the two aligned when this §I changes.

## See also

- `agent-excellence.md` — the bar + the seven rules incl. Rule 7 (latent/deterministic); read every dispatch
- `outcome-enforcement.md` — measurable-outcome, the strongest single home; this index defers to it
- `self-improvement.md` + `adaptation-loop.md` — failure-harvest; principle 2 is the success complement
- `brief-cache-discipline.md` — the context-window mechanics behind principle 3
- `subtract-dont-add.md` — why this doctrine is an index and not a re-paste
- `README.md` "How to add new project doctrines" — where the §III target-project rules live
