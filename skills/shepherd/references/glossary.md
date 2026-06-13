# Glossary — disambiguating "workflow" (and other collision-prone terms)

> **Why this file exists.** "workflow" names THREE different things in and around shepherd.
> A v0.3.5 sprint stalled because teammates heard "dynamic workflow", assumed it was a tool
> to find, ran `ToolSearch`, got nothing, and gave up. It is **not** a searchable tool. The
> model has no training prior for the native Workflow tool (research-preview, 2026-05); these
> doctrines are its only teacher (`doctrines/primitive-axis-binding.md`). Be unambiguous.

## "workflow" — three distinct senses

### 1. The native Claude Code `Workflow` tool  (a.k.a. "dynamic workflow")
- **What:** a top-level Claude Code tool that runs a JavaScript orchestration script
  (`agent()`, `parallel()`, `pipeline()`, `phase()`) to fan out many subagents in the
  background and return one consolidated result. Intermediate results live in script
  variables, not the conversation context.
- **Availability:** **ALWAYS PRESENT as a top-level tool** on a Claude Code build that
  supports it. It is **NOT** a deferred or MCP tool.
- **❌ NEVER `ToolSearch` for it.** `ToolSearch("workflow")` / `ToolSearch("dynamic workflow")`
  returns nothing — *by design*, because the tool is not deferred. A nothing-result does
  **not** mean "unavailable"; it means you looked in the wrong place.
- **✅ How to tell if it's available:** is `Workflow` in your visible tool list? If yes, call
  it directly. If **no**, you are on a Claude Code build below the Dynamic Workflows floor —
  fall back to in-context `Agent(...)` fan-out (the documented degraded path). Do not
  ToolSearch; do not conclude "the feature is broken."
- **In shepherd:** shepherd COMPILES gate-free Stage-Graph fan-out segments into a Workflow
  script via `shctx graph compile` and runs it out-of-context. Doctrine:
  `doctrines/workflow-compile-down.md`; axis binding (which primitive for which job):
  `doctrines/primitive-axis-binding.md`.
- **Docs:** `https://code.claude.com/docs/en/workflows`.

### 2. Shepherd's six "workflow patterns"  (a coordination abstraction)
- **What:** the six canonical coordination structures the engineer composes into a Stage
  Graph at plan time — Classify-And-Act, Fanout-And-Synthesize, Adversarial Verification,
  Generate-And-Filter, Tournament, Loop-Until-Done.
- **Where:** `doctrines/workflow-patterns.md`; Stage Graph shapes in
  `references/workflow-templates.md`.
- **Not a tool.** A pattern is a design choice about HOW agents coordinate; it may be
  *executed* via the native `Workflow` tool (sense 1), via Agent Teams, or inline.

### 3. GitHub Actions workflows  (`.github/workflows/*.yml`)
- **What:** CI/CD automation. `release.yml` runs the patch→main release cascade.
- **Unrelated** to senses 1 and 2 beyond the shared English word.

## Quick disambiguation

| You see / hear… | Sense | Do |
|---|---|---|
| "compile to a Dynamic Workflow", "run the workflow out-of-context", `agent()`/`pipeline()` | 1 — native tool | call the `Workflow` tool directly; **never ToolSearch it** |
| "Pattern 2 / Fanout-And-Synthesize", "the six workflow patterns" | 2 — abstraction | author it in the Stage Graph per `workflow-patterns.md` |
| `.github/workflows`, "release.yml fires", "the GHA workflow" | 3 — CI | it's GitHub Actions |

## Other collision-prone terms

- **`ToolSearch` is for DEFERRED tools only** — specialist agents and MCP tools surfaced on
  demand (`doctrines/specialist-dispatch.md`). **Top-level tools** (`Agent`, `Task`,
  `Workflow`, `Bash`, `Edit`, …) are always present and are **never** ToolSearch targets.
  Rule of thumb: if a capability is a core verb of the harness, it's top-level; if it's a
  third-party/plugin/specialist capability, it's deferred and discoverable via `ToolSearch`.
- **`/loop` vs Loop-Until-Done vs a loop template:** `/loop` is the native Claude Code
  interval command; **Loop-Until-Done** (Pattern 6) is shepherd's convergent-iteration
  pattern; the loop **templates** (`references/loop-templates.md`) are per-role
  specializations. Entry point: `SKILL.md §0-ter`.
- **Agent Teams vs a workflow:** Agent Teams (teammates via `TeamCreate`/`SendMessage`) is
  the primitive for *long-lived, gated, communicating* lanes; a Dynamic Workflow is the
  primitive for *gate-free, fire-and-collect* fan-out. One primitive per axis — never invert
  (`doctrines/primitive-axis-binding.md`).
