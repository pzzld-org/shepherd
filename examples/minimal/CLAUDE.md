<!-- BEGIN shepherd:operating-doctrine (managed block — re-sync with `shctx config claude-md --force`) -->
# How to work

This block is maintained by the **shepherd** plugin. Edit freely OUTSIDE the
markers; everything INSIDE is overwritten on `shctx config claude-md --force`.
It is the portable how-to-work doctrine; the framework binding lives in
`skills/shepherd/doctrines/operating-philosophy.md`.

## Do the whole thing

The marginal cost of completeness is near zero with AI. Ship the finished product —
with tests and docs in the same diff — not a plan to build it. Before you call
anything DONE, you must be able to explain why it is correct and exactly where it
would break: passing tests is not the same as understanding.

## The two machine spaces — pick the right one

Every task is **latent** (LLM judgment, ambiguous inputs, prose) or
**deterministic** (code: same input → same answer). If the same question asked
twice would by definition give the same correct answer — arithmetic, date/timezone
math, counts, file lookups, CSV/JSON transforms, regex, hashing, progress/rate/ETA —
write the script, do not compute it in a reply. The model writes the script once;
the script then constrains the model forever after, and the old failure path
becomes unreachable. If a task is both, split it: script + test for the
deterministic half, prompt + eval for the latent half.

## Tie every change to a measurable outcome

"It works" is not an outcome. Name the metric, workflow step, or user-visible
behavior that changes before you build, and leave a **runnable acceptance check**
behind — a predicate you can execute, not a sentence of prose.

## Tests and evals, same commit

Every feature and every fix ships its test — and, where an LLM call is involved,
its eval — in the same diff, never "later." Two lanes: **gate tests** are
deterministic, local, free, under ~2s, and never flaky; **periodic evals** are
paid, slower, allowed to be non-deterministic, and carry a pass threshold.

## Search before building; vanilla by default; subtract

Reuse before creating; read before writing. Prefer the simplest standard tool over
the framework of the month. A new dependency, abstraction, or wrapper must justify
itself in one sentence or it does not belong. Lean toward the smaller diff.

## Skillify repeated success

The second time you run a manual flow by hand, the third time is a command. A sequence
that keeps working is a reusable procedure — promote it to a script, skill, or workflow
rather than re-deriving it. One-off prompts do not compound; reusable flows do.

## The context window is the lever

It is the one surface you control: load the spec, the contract, the relevant files, and
concrete examples; leave the noise out. When a task goes sideways, the first question is
"what was in the window," not "was the model dumb." Debug the window before the model.

## Completion status — the return contract

End every task in exactly one state: **DONE** · **DONE_WITH_CONCERNS** (list each
with severity + a follow-up) · **BLOCKED** (the blocker + what you tried) ·
**NEEDS_CONTEXT** (exactly what is missing). "Partially done" is not a status.

## Commit, push, then say what to restart

After a task, commit and push (never bypass pre-commit hooks, never commit
secrets). Then state exactly which service or program must restart for the change
to take effect — or say plainly that nothing needs restarting.

## Confusion protocol

On high-stakes ambiguity — two viable architectures, a destructive operation of
unclear scope, or missing context that would change the approach — stop, name the
ambiguity in one sentence, present 2-3 options with real trade-offs, and ask.
Routine, obvious changes do not need this.
<!-- END shepherd:operating-doctrine -->
