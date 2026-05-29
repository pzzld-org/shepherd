# Doctrines — language-agnostic by design

The doctrines in this directory are **framework-intrinsic** rules about HOW shepherd orchestrates work. They are language-agnostic on purpose. They describe principles ("wrapper structs must earn their existence", "auditors are read-only", "every sprint runs Phase 0 mesh") without mandating any particular language's syntax, build tools, or testing convention.

## The integration model

Per-language details — the actual grep patterns, idioms, build commands, code-review preferences — DO NOT live in shepherd. They live in the appropriate per-language skill, loaded into every flock dispatch via the `[skills]` machinery in `shepherd.toml`.

```
┌────────────────────────────────────────────────────────────────┐
│                     shepherd (this plugin)                      │
│  Doctrines  │  Flock dispatch   │  Phase 0 mesh   │  Pipeline   │
│  (language- │   (language-      │  (language-     │  (language- │
│   agnostic) │    agnostic)      │   agnostic)     │   agnostic) │
└──────┬─────────────────────────────────────────────────────────┘
       │
       │ shepherd.toml [skills.by_domain] + [skills.detection]
       │
       ├─→  rust skill              (cargo, clippy, no_std/std/alloc, lifetimes, ownership)
       ├─→  webassembly skill       (cargo-component, wit-bindgen, wasmtime)
       ├─→  python skill            (uv, ruff, black, type-hints)
       ├─→  typescript skill        (tsc, eslint, vitest, package.json)
       ├─→  code-style skill        (per-language ledger of personal style preferences)
       └─→  domain skills           (finance, polymarket, supabase, claude-api, ...)
```

When the conductor builds a coder brief, it walks `[skills.detection]` against the lane's file scope to pick which language + domain skills to inject into `[SKILLS]`. The doctrines speak in principles; the language skills supply the syntax.

## What the doctrines own

- WHEN to dispatch (Pattern B overlap, planter vs sprint pipeline, parallel-safety)
- WHAT to enforce (SUBTRACT-DON'T-ADD, wrapper-must-earn, auditor read-only, issue-ledger awareness)
- HOW the flock interacts with itself (engineer → critic → coder → auditor)
- HOW seeds compose into plans into briefs into commits
- HOW the system improves itself across a patch cycle (adaptation loop)

## What the doctrines DO NOT own

- Language syntax (`pub struct`, `fn`, `impl`, `class`, `def`) — language skills
- Build commands (`cargo check`, `npm test`, `pytest`) — `shepherd.toml [gates]`
- Style preferences (4-space indent, snake_case vs camelCase) — `code-style` skill
- Test framework choices (`cargo test`, `pytest`, `vitest`) — language skills
- Linter configuration (clippy lints, eslint rules, ruff rules) — language skills

## Wrapper-must-earn — language-agnostic example

The principle:

> A wrapper type that has no type-system-enforced invariant, no borrowed scope, no shared-allocation pattern, and no substantive trait/interface role IS A SMELL.

This applies to:
- Rust `pub struct Foo { params: P }` with single redirect method
- TS `class Foo { constructor(public params: P) {} doThing() { params.doThing(); } }`
- Python `class Foo:` with single attribute and pass-through methods
- Go `type Foo struct { params P }` with single delegating method
- Java `class Foo` with one field and pass-through

Each language has its own grep pattern to detect the smell. Each language has its own preferred refactor (method-on-params, lifetime-borrow, shared-pointer wrapper). The DOCTRINE expresses the principle; the language skill provides the per-language detection grep and refactor pattern. The doctrine cites the language skill, doesn't duplicate it.

## How to add new doctrines

If a new framework-intrinsic rule emerges, write it here as a `.md` file. The rules:

1. **Principle first.** State the rule abstractly. Don't lead with a code example.
2. **No language syntax in the rule statement.** "Wrapper structs must earn their existence" — yes. "`pub struct Foo { params: P }` is a smell" — no, that's an example, demote to §Examples.
3. **Cite per-language skills for implementation detail.** "See `rust` skill §wrappers for the per-language detection grep" beats inlining the grep.
4. **Cross-reference other doctrines.** Doctrines reinforce each other; explicit links keep the system coherent.
5. **Keep it under 200 lines.** If the rule needs 200+ lines to explain, it's probably two rules.

## How to add new project doctrines

Per-project doctrines that DRIFT beyond the framework's intrinsic rules live in `[memory].project_doctrines` (configured per-project, default `.claude/doctrines/`). Examples of project doctrines:

- "Geo-block law — node process group pinned to yyz forever" (Axiom-specific, not a framework rule)
- "BMS sigma-floor calibration — 7d window minimum" (Axiom-specific)
- "ONNX models compile to WASI-NN, not native ort" (Axiom-specific)

These get loaded by the conductor at session-open per `[hooks].on_every_dispatch`. They are NOT shepherd doctrines and don't belong in this directory.

## Doctrine index

| Doctrine | Principle |
|---|---|
| `adaptation-loop.md` | Self-improvement loop — sprint pattern registry written at close, read at mesh + seed time |
| `auditor-hypothesis-driven.md` | (v5.1.1+) Auditors load `superpowers:systematic-debugging`; every finding carries Hypothesis + Falsification + Confidence; Bayesian finding-class weighting from sprint-patterns |
| `auditor-readonly.md` | Auditors file findings; conductor dispatches fixes |
| `discovery-readonly.md` | (v5.1.1+) `@discovery` is the sixth lane — read-only orientation + research synthesis; never grades, never proposes, never dispatches |
| `intro-combo-wave.md` | (v5.1.1+) Sprint open dispatches discoveries + intro-mode auditors in parallel before MESH; engineer reads `[DISCOVERY-CONTEXT]` + `[INTRO-AUDIT-CONTEXT]` as authoritative |
| `hook-event-log.md` | (v5.1.1+) Every hook fire appends one line to `<ns>/logs/hooks/YYYY-MM-DD.jsonl`; structured operator-debuggable record |
| `mid-flight-operator-amendment.md` | Four amendment types (clarification, feature-add, regression, architectural); conductor response protocol + dispatcher-patch ledger |
| `carry-forward-refresh.md` | Chronic items labeled at sprint close; CRITICAL/HIGH cannot defer silently |
| `chain-repair.md` | Mechanical seed drift verified + amended inline; substantive drift escalates |
| `coder-brief-format-shared-artifacts.md` | Shared `.shepherd/ctx/*.md` files partitioned before dispatch to avoid cherry-pick conflicts |
| `conductor-cwd.md` | Conductor anchor stays on sprint root; `cd <worktree>` and `git switch <agent-branch>` banned |
| `context-registry.md` | SQLite registry backs DEDUP-GATE Layer 2; markdown fallback always available |
| `gates-restoration.md` | Run GATES-DISCOVERY before Lane 0 when sprint opens with red gates |
| `issue-ledger-awareness.md` | Phase 0 enumerates ALL open issues; tunnel vision is the documented failure |
| `pattern-b-overlap.md` | WAVE-N-AUDIT and WAVE-(N+1)-IMPL fire in the same batch |
| `preflight-doctor.md` | (v5.1.1+) `shctx doctor` runs a structured preflight (git, plan, ctx, hooks, MCP, lock); recommended before `/shepherd:start` |
| `seed-anchored-by-issues.md` | Every MUST-LAND lane cites a GH#; detail lives in the issue, not the seed |
| `sprint-as-patch.md` | (v5.1.1+) Every `dev.N` sprint is operator-equivalent to a full patch; planter and engineer size scope at patch-grade |
| `stage-graph.md` | The plan IS the dispatch contract; off-graph dispatch is a process violation |
| `workflow-compile-down.md` | (v6.0.1) Compile the Stage Graph's gate-free fanout segments to Claude Code Dynamic Workflows; the faithfulness invariant (soundness / completeness / determinism) gates every compiled segment |
| `subtract-dont-add.md` | Every sprint ends net-negative; deletion is a constraint, not the job |
| `use-mcp-not-cli.md` | Writes to shared systems use MCP; CLI for read-only enumeration |
| `work-bound-to-tracking.md` | Every intentional gap in production code cites a GH issue; language-specific stub primitives enumerated |
| `worker-patterns.md` | Bounded workers dispatched at Wave 1 START; main chat never idles on Monitor streams |
| `worktree-base-drift.md` | Worktrees pre-created from sprint HEAD; coder halts on BASE-DRIFT; canonical no-isolation workaround codified |
| `worktree-confinement.md` | All coder writes inside the worktree path |
| `wrapper-must-earn.md` | Wrapper types justify with invariant / lifetime / shared-allocation / substantive-trait |
| `zero-duplicate-tolerance.md` | DEDUP-GATE runs every grep before dispatch; coder-side halt is the fallback |

## Doctrine promotion pipeline

Project-specific rules that prove general enough for framework inclusion go through `_candidates/`. See `_candidates/README.md` for the promotion checklist. When a candidate is promoted, its row moves here and `introduced: v{X}.{Y}.{Z}` frontmatter is added to the doctrine file.

## See also

- [`docs/integration.md`](../../../docs/integration.md) — how to wire your project's per-language skills
- [`docs/customization.md`](../../../docs/customization.md) — adding project-specific doctrines
- [`docs/configuration.md`](../../../docs/configuration.md) — `shepherd.toml [skills]` schema
- [`_candidates/README.md`](_candidates/README.md) — promotion pipeline from project memory to framework doctrine
