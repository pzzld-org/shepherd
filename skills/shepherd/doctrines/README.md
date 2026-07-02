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
       └─→  domain skills           (finance, payments, supabase, claude-api, ...)
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

- "Geo-block law — node process group pinned to yyz forever" (downstream-project-specific, not a framework rule)
- "BMS sigma-floor calibration — 7d window minimum" (downstream-project-specific)
- "ONNX models compile to WASI-NN, not native ort" (downstream-project-specific)

These get loaded by the conductor at session-open per `[hooks].on_every_dispatch`. They are NOT shepherd doctrines and don't belong in this directory.

## Doctrine index

| Doctrine | Principle |
|---|---|
| `adaptation-loop.md` | (v6.0.4 SQLite-canonical, #94) Sprint metrics registry — `shctx adapt roll` writes a `sprint_metrics` row at close; engineer/planter/spawn read measured averages via `shctx adapt priors`; now shapes dispatch *sizing* mechanically (Check 8) |
| `self-improvement.md` | (v6.0.4 #95) Harvest→inject contract — HIGH/CRITICAL `audit_findings` become `mem_entries(kind='prior')` lessons, injected into the next `/shepherd:plant` + engineer Phase-0 brief; bounded, graceful-empty, citation-measured |
| `auditor-hypothesis-driven.md` | (v5.1.1+) Auditors load `superpowers:systematic-debugging`; every finding carries Hypothesis + Falsification + Confidence; Bayesian finding-class weighting from the adaptation registry |
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
| `workflow-tool-self-check.md` | (v6.1.6) The operational front-end for the native `Workflow` tool — ONE first-action self-check (visible-tool-list test, NEVER `ToolSearch`), recorded as `workflow_tool: present\|absent`, then branch: present → compile gate-free fan-out out-of-context (the conductor's OWN benefit); absent → degrade to in-context `Agent(...)`. Consolidates the detection-and-benefit seam that kept getting skipped (`WORKFLOW-SELFCHECK-TOOLSEARCH` / `PRIMITIVE-INVERSION`) |
| `native-coordination.md` | (v6.0.1) Native primitives (workflow in-script ordering, Agent Teams SendMessage, subagents) replace pause-for-dependency / heartbeat-relay / idle-pruning; the proven replacement Lane F deletes against |
| `subtract-dont-add.md` | Every sprint ends net-negative; deletion is a constraint, not the job |
| `use-mcp-not-cli.md` | Writes to shared systems use MCP; CLI for read-only enumeration |
| `work-bound-to-tracking.md` | Every intentional gap in production code cites a GH issue; language-specific stub primitives enumerated |
| `worker-patterns.md` | Bounded workers dispatched at Wave 1 START; main chat never idles on Monitor streams |
| `worktree-base-drift.md` | Worktrees pre-created from sprint HEAD; coder halts on BASE-DRIFT; canonical no-isolation workaround codified |
| `worktree-confinement.md` | All coder writes inside the worktree path |
| `wrapper-must-earn.md` | Wrapper types justify with invariant / lifetime / shared-allocation / substantive-trait |
| `zero-duplicate-tolerance.md` | DEDUP-GATE runs every grep before dispatch; coder-side halt is the fallback |
| `lane-task-ownership.md` | Team task list is shared; every teammate task is lane-prefixed + owner-set; root routes by title prefix (`TASK-LANE-MISMATCH`) |
| `dispatch-tier-separation.md` | (v5.1.6+, v6.2.6) Three-tier dispatch hierarchy — root owns engineer/critic dispatch + artifact materialization in **classic** mode (in **self-contained** mode the engineer teammate runs its own discovery + critic in its window, #172); teammate-conductors own coder/auditor/worker/discovery; forbidden-dispatch halt codes (`TEAMMATE-GIT-WRITE`, `DISPATCH-TEAMMATE-TYPE-MISMATCH`, `WRONG-TIER-DISPATCH`, `ENGINEER-TOPOLOGY-MISMATCH`, `ENGINEER-SUBFLOCK-VIOLATION`) |
| `flock-output-review.md` | (v6.2.4 #167) A conductor holds a wave-review `@auditor` `PASS` before `WAVE-COMPLETE`; a `REDO` verdict re-dispatches the named author on the named scope via the hot-fix ladder (≤3, `REDO-CAP-EXCEEDED`); root delegates the verdict at `LANE-INTEGRATE`, never repairs teammate source |
| `engineer-self-contained-plan.md` | (v6.2.5 #169, clarified v6.2.6 #172) The engineer is a flock leader; a self-contained **teammate** runs its read-only sub-flock — the INTRO-COMBO-WAVE (`@discovery` + intro-`@auditor`) + its own dispatched `@critic` gate + ≥1 revision — in its own window and returns a hash-tied **critic-proof** (`shctx plan record-critique`/`verify`); root runs neither wave itself and accepts via a thin gate, no re-critique. No code touched. Named-teammate topology + marker-scoped `@critic` enforced by `dispatch_guard.sh` (`ENGINEER-TOPOLOGY-MISMATCH`) |
| `model-map.md` | (v6.2.5 #170) One `[models]` block maps each role to its model; `shctx models resolve <role>` (config → built-in default) is injected as the Agent `model:` pin by every dispatching tier; root is advisory; resolution chain leaves slots for future profile/mode presets |
| `workdir-prune.md` | (v6.2.5 #171) `shctx prune` reclaims non-current ∧ terminal ∧ aged workdir/registry state; `--dry-run` default, `--confirm` moves to /tmp (reversible), every DB DELETE table-guarded; on-disk sweeps execute now, DB-row sweeps preview-only |
| `root-shepherd-orchestration.md` | (v5.1.6+) Root-tier responsibilities under `/shepherd:spawn` — wave-gate enforcement, escalation triage, artifact materialization from teammate payloads, dispute resolution, close-swarm coordination |
| `primitive-axis-binding.md` | (v6.0.2) One primitive per axis: Agent Teams = lanes, Dynamic Workflows = step fan-out, subagents = steps; `PRIMITIVE-INVERSION` flag when axes are crossed |
| `dispatch-cascade.md` | Stage Graph is the rule engine; conductor walks `shctx graph next`/`mark` mechanically — no fresh sequencing decisions; halts and hot-fixes extend the topology, never bypass it |
| `spawn-escalation.md` | Canonical return-and-resume contract for spawned teammate-conductors — channels, payload schema, heartbeat, wave-boundary commit discipline, and escalation triage |
| `coordinate-active-drive.md` | (v6.0.5, #113/#98/#112) The dispatch→coordinate transition is active, never a passive wait — root runs wake→act→probe→yield-to-events after spawning the teammates and ends its turn only at enumerated operator-pauses; teammates begin on boot; mechanically backstopped by the `coordinate_drive_guard.sh` Stop hook |
| `scope-scale-workload.md` | (v5.1.6+) `/shepherd:spawn --scope` declares workload scale (sprint/patch/minor/version); scope is NEVER a quality bar; `--auto` is a preserved alias for `--scope patch` |
| `sqlite-canonical-state.md` | (v5.1.7) `.artifacts/root.db` is canonical for operational state; filesystem is canonical only for human-authored durable artifacts; markdown reports are generated views over DB rows |
| `claude-code-platform-alignment.md` | (v5.1.8) Binding map between shepherd's teammate-coordination stack and Claude Code's Agent Teams primitive — ownership split, migration trajectory, task-list adoption for wave-gate enforcement (v6.0.3) |
| `specialist-dispatch.md` | (v5.1.1+) Flock-first dispatch; specialist third-party agents permitted only for self-contained tasks the flock cannot serve; canonical DISPATCH DECISION TREE (Q1–Q4); `SPECIALIST-UNCLEAR` / `SPECIALIST-UNAVAILABLE` halt codes |
| `invariant-enforcement-matrix.md` | (v6.0.2) Coverage map of every load-bearing shepherd invariant paired with its enforcement mechanism (hard-block / flag / lint / auditor) and live/deferred/gap status |
| `flock-cohesion.md` | (v5.0.9) Agents as a coordinated group — sibling-awareness in briefs, INSIGHTS channel, insight registry, sprint-pattern registry; closes the isolated-dispatch structural gap |
| `agent-excellence.md` | (v5.1.1+) Greatness is the bar; seven rules every flock agent reads — READ/REUSE first, refuse the lazy path, no scope overflow, no silent drift, Rule 7 deterministic-work-is-code; `SCOPE OVERFLOW` is a halt code |
| `operating-philosophy.md` | (v6.2.0) The how-to-work constitution — an INDEX that names the four homeless principles (latent-vs-deterministic split, skillify-success, the context-window diagnostic, the DONE/DONE_WITH_CONCERNS/BLOCKED/NEEDS_CONTEXT vocabulary) and binds the rest by pointer; defers to the cited doctrine; declares the target-project + tone scope boundary it refuses to own |
| `brief-cache-discipline.md` | (v5.1.3) Stable framing first, variable content last — brief ordering that maximizes prompt-cache prefix reuse; ordering sections between blocks invalidates the cache |
| `cache-telemetry.md` | (v5.1.3) Measurement layer for prompt-caching health — `SubagentStop` hook aggregates per-dispatch cache-read vs cache-creation token ratios; proves brief-cache-discipline is producing wins |
| `cargo-sequential-gates.md` | (v5.0.9) Cargo invocations on the same workspace MUST be sequential (`&&`); parallel cargo deadlocks on `target/` lock; applies to conductor WAVE-GATE runs and `@worker` build verification |
| `dir-watch.md` | (v5.1.1+) `shctx watch` tracks per-path content hashes (git tree-object or fs shasum) so agents can ask "has this changed?" without redundant reads when state is stable |
| `plugin-reload-escape.md` | (v5.0.9) When MCP tools declared in `shepherd.toml [mcp]` are unloadable, operator runs `/reload-plugins`; conductor flags unavailability explicitly rather than silently falling back to shell |
| `seed-naming.md` | (v5.1.1+) Branches keep dots; filenames collapse them — seed/plan files use slug form (`v512-dev3.seed.md`), never the dotted branch form (`v5.1.2-dev.3.seed.md`) |
| `version-scale-roadmap.md` | (v5.1.3) Binding scale factor: version → 1000 sprints, minor → 100, patch → 10, dev sprint → 1; scope is workload-scale NEVER a quality bar; "it's just a patch" is documented malpractice |
| `workspace-member-isolation-gate.md` | (v5.1.7) Acceptance gate for workspace-topology changes MUST include per-member isolated builds, not only the workspace-unified build; silently satisfied deps are a shipping hazard |
| `autonomous-sentinel.md` | (v6.1.5, #148) Authorized supervised self-heal — the supervised-remediation SUPERSET of SOAK-LOOP; PROBE → CLASSIFY → ACT (≤S `@coder` hotfix via the hotfix-dispatch ladder → gates-before-deploy → re-probe) → TERMINATE; NEVER by default — gated behind `[close].autonomous_sentinel` + a `close: autonomous-sentinel` seed declaration + a complete `sentinel_rails` block; hard rails (gates-before-deploy, ≤S/≤3/≤N caps, no destructive DB ops, auto-rollback, paper-only, operator-override-each-tick, full audit trail) |
| `capability-discovery.md` | (v6.1.5, #146; v6.1.7 corrected) Auto-discover environment plugins/skills/tools → EPHEMERAL roster (distinct from the curated `toolkit.json`), merged into the `[TOOLKIT]` surfaces labeled auto-discovered; guarded integrations degrade cleanly ("if `/remember` available → handoff/CLOSE-FINALIZE + resume, else native"); records an advisory note for the native `Workflow` tool — enabled across entrypoints (web/remote/cloud-container included), agent confirms via visible tool list, degrade to `Agent(...)` only on explicit-disable/below-floor; config `[discovery].auto_capabilities`; zero hot-path cost, fail-open |
| `dispatch-generosity.md` | (v6.1.7) Reach for the lane, the swarm, and the loop — only `@engineer` is count-capped; `@auditor`/`@worker`/`@discovery` are freely repeatable (close-swarm + intro waves are floors). The under-use is an incentive gap, not a cap; out-of-context compiled fan-out makes extra dispatch context-CHEAP. Worker-first for bounded ops; audit mid-body; re-discover before risky waves; loop when completion = "no new findings". Pull, not policing (no new halt code) |
| `staged-handoff.md` | (v6.1.7) Two-session overlap — `/shepherd:spawn --staged` orients/discovers while a separate `/shepherd:plant` authors the seed, then waits on a durable `seed-ready` signal over the existing SQLite `mailbox` before plan authorship; zero new schema/tooling (one spawn flag + one signal at plant close); opt-in; seed file stays source of truth |

## Doctrine promotion pipeline

Project-specific rules that prove general enough for framework inclusion go through `_candidates/`. See `_candidates/README.md` for the promotion checklist. When a candidate is promoted, its row moves here and `introduced: v{X}.{Y}.{Z}` frontmatter is added to the doctrine file.

## See also

- [`docs/integration.md`](../../../docs/integration.md) — how to wire your project's per-language skills
- [`docs/customization.md`](../../../docs/customization.md) — adding project-specific doctrines
- [`docs/configuration.md`](../../../docs/configuration.md) — `shepherd.toml [skills]` schema
- [`_candidates/README.md`](_candidates/README.md) — promotion pipeline from project memory to framework doctrine
