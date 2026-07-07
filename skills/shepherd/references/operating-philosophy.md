---
title: operating-philosophy
description: |
  States the four operating principles with no other file, plus a pointer
  table for everything else. Use when a session needs the operating stance,
  not a specific rule.
---

# Operating Philosophy — how the flock works

This file is an INDEX: it states the principles with no other home and
points at the file owning everything else, deferring to it on conflict.

## I. The four principles with no other home

### 1. Two machine spaces — latent vs deterministic

Every unit of work is latent-space (LLM judgment, prose, ambiguous input;
tokens; high variability; zero inspectability) or deterministic-space (code;
one-time write; zero variability; total inspectability).

**Decision rule:** if the same question asked twice MUST, by definition,
produce the same correct answer, it is deterministic — write the script;
NEVER compute it in a model reply. Arithmetic, date math, timezone
conversion, file lookups, CSV/JSON transforms, regex, hashing,
progress/rate/ETA: all deterministic. A task that is both: split it — the
deterministic piece becomes a script + test, the latent piece a prompt +
eval. **Payoff:** the LLM writes the script once; the script constrains the
LLM forever after. Catch yourself computing inside a reply: stop, write the
script.

### 2. Skillify repeated success, not only failure

Failure harvest is owned by `skills/adaptation/SKILL.md §Loop contract`.
Success compounds the same way: the second manual run of a flow, the third
time is a command. A lane shape, guard, or sequence correlating with a clean
close MUST be promoted to a script, skill, or workflow, not re-derived.
One-off prompts do not compound; reusable flows do.

### 3. The context window is the lever — and the first diagnostic

The window is the only control surface over the model: load the spec, the
contract, the relevant files, the concrete examples; leave the noise out.
Cache-reuse ordering lives in `skills/shepherd/references/flock.md §Brief
assembly`; budget discipline in `skills/adaptation/SKILL.md §Excellence
bar`. The diagnostic stance: when a task goes sideways, the first question
is "what was in the window," NEVER "was the model dumb."

### 4. Completion status is a closed vocabulary

Every task ends in exactly one of four states — "partially done" is not one.

| Status | Meaning |
|---|---|
| `DONE` | Every step complete, evidence for every claim, tests + evals in the diff. |
| `DONE_WITH_CONCERNS` | Complete, but issues named by severity + a proposed follow-up. |
| `BLOCKED` | Cannot proceed; state the blocker and what was already tried. |
| `NEEDS_CONTEXT` | Missing information that would change the approach; state exactly what. |

Per-role verdicts (critic GREEN/YELLOW/RED, the grade in
`skills/shepherd/references/grading-rubric.md`, halt codes) roll up into one
of these four at the root/operator seam.

## II. Everything else has a home (bind by pointer)

| Principle | Owned by |
|---|---|
| Tie every change to a measurable outcome | `skills/shepherd/references/pipeline.md §Gates` (seams 1-3); `skills/motivation/SKILL.md §SOAK` (seam 4) |
| Gate tests (deterministic, <2s, free, every commit) vs periodic evals (paid, threshold) | `skills/shepherd/references/pipeline.md §Gates` |
| Search before building; reuse before creating | `skills/adaptation/SKILL.md §Excellence bar`; `skills/context/SKILL.md` |
| Subtract, don't add; wrappers must earn their place | `skills/shepherd/SKILL.md §Principles`; `skills/shepherd/references/flock.md §@auditor` |
| Check for the installed specialist before reinventing | `skills/shepherd/references/flock.md §Dispatch`; `skills/context/references/toolkit.md` |
| Fan out by default; one primitive per axis | `skills/shepherd/references/flock.md §Dispatch`; `skills/shepherd/references/pipeline.md §Lane law` |
| Halt rather than ship sub-standard work | `skills/adaptation/SKILL.md §Excellence bar`; `skills/shepherd/SKILL.md §Sprint contract` |
| Confusion protocol on high-stakes ambiguity | `skills/shepherd/SKILL.md §Operator surface` (the planter is the framework's sole interactive asker) |
| Harvest failures forward so the flock never relearns them | `skills/adaptation/SKILL.md §Loop contract` |

## III. What this file refuses to own

- **Target-project rules** (services-first layout, LLM-calls-through-local-
  Claude-Code, backfill protocol, safety rules) are consumer-project
  properties, not framework properties: `[memory].project_doctrines`
  (default `.claude/doctrines/`) — see `docs/customization.md`. `shctx
  config claude-md` materializes a starter CLAUDE.md with the principles
  above; the consumer extends it.
- **Tone and voice rules** (directness, banned vocabulary, formatting) are
  operator-personal, portable-unsafe, and belong in user-global
  instructions, NEVER in framework doctrine.

## How this binds

This file MUST exist at exactly this path and basename: `session_open.sh`
runtime-checks it with `-f`, and `test_shctx_locator.sh` greps the basename.
Flock agents load it on demand; root shepherd and conductor load it as
foundational framing; `session_open.sh` surfaces a one-line pointer at
session start (config-gated, `quiet_warnings` silences it). Consumer twin:
`examples/minimal/CLAUDE.md` — keep aligned with §I.
