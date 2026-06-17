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
- **Availability:** **ENABLED across Claude Code entrypoints — CLI, Claude-Code-on-the-web,
  AND remote / cloud-container sessions.** It is a **top-level** tool, **NOT** a deferred or
  MCP tool. Treat it as present by default; the only genuine absence is an explicit disable
  (`disableWorkflows` / `CLAUDE_CODE_DISABLE_WORKFLOWS`) or a Claude Code build below the
  Dynamic Workflows floor (v2.1.154) — **never** "web/remote omits it" (the retired #146 claim).
- **❌ NEVER `ToolSearch` for it.** `ToolSearch("workflow")` / `ToolSearch select:Workflow`
  returns nothing — *by design*, because the tool is **top-level**, not deferred (`ToolSearch`
  resolves deferred tools only). A nothing-result does **not** mean "unavailable"; it means you
  looked in the wrong place. This holds even under `/effort ultracode`: the instruction "use the
  Workflow tool on every substantive task" is satisfied by *checking your tool list*, NOT by
  searching for the tool — a v0.3.5 sprint AND this framework's own ultracode maintenance session
  (2026-06-15) both ToolSearched, got nothing, and wrongly declared it "confirmed absent."
  ToolSearching here is the `WORKFLOW-SELFCHECK-TOOLSEARCH` anti-pattern.
- **✅ How to tell if it's available:** is the token `Workflow` in your visible tool list? It is
  EXPECTED to be — call it directly. A **nothing-result from `ToolSearch` is not the test** and
  is not evidence of absence (see the forbidden-test note above). On the rare genuine absence
  (an explicit `disableWorkflows` / `CLAUDE_CODE_DISABLE_WORKFLOWS`, or a build below the v2.1.154
  floor) — and ONLY then — fall back to in-context `Agent(...)` fan-out (the documented degraded
  path). Web / remote / cloud-container is **not** such a case: Dynamic Workflows is enabled there.
  The full first-action protocol (detect → record → branch) is `doctrines/workflow-tool-self-check.md`.
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
  demand (`doctrines/specialist-dispatch.md`). **Top-level tools are never `ToolSearch`
  targets**, and the native orchestration primitives are all top-level: `Agent`, `Workflow`
  (Dynamic Workflows), `TaskCreate` / `TaskGet` / `TaskList` / `TaskUpdate`, `TeamCreate` /
  `TeamDelete`, `SendMessage`, plus `Bash` / `Edit` / `Read` / … . They are **enabled across
  entrypoints (web / remote / cloud-container included)** and called **directly**. A
  `ToolSearch` for any of them returns **nothing — by design** (you looked in the wrong index);
  that nothing is **never** evidence of absence. `ToolSearch select:TaskCreate` even *errors* —
  expected, because `TaskCreate` is native, not deferred. Rule of thumb: if a capability is a
  core verb of the harness, it's top-level (call it directly, never search); if it's a
  third-party / plugin / specialist capability, it's deferred and discoverable via `ToolSearch`.
- **`/loop` vs Loop-Until-Done vs a loop template:** `/loop` is the native Claude Code
  interval command; **Loop-Until-Done** (Pattern 6) is shepherd's convergent-iteration
  pattern; the loop **templates** (`references/loop-templates.md`) are per-role
  specializations. Entry point: `SKILL.md §0-ter`.
- **Agent Teams vs a workflow:** Agent Teams (teammates via `TeamCreate`/`SendMessage`) is
  the primitive for *long-lived, gated, communicating* lanes; a Dynamic Workflow is the
  primitive for *gate-free, fire-and-collect* fan-out. One primitive per axis — never invert
  (`doctrines/primitive-axis-binding.md`).
