---
name: shepherd
slug: shepherd
version: 6.0.2
description: "Sprint-by-sprint version-cycle conductor. Six-agent flock (engineer, critic, coder, auditor, worker, discovery) on an INTRO/BODY/CLOSE pipeline with planter/conductor/shepherd meta tiers."
metadata:
  triggers:
    - "/shepherd"
    - "/shepherd:plant"
    - "/shepherd:start"
    - "/shepherd:spawn"
---

# /shepherd — Conductor Quick Reference

This file is a **quick-reference index**. Operational detail lives in the sibling files and agent profile files (see §XI). When this file points at one, load it.

**Sprint-runner behavior is canonical in `agents/conductor.md`.** This file provides orientation and cross-references; for the binding dispatch procedure, pipeline steps, and halt codes, see `agents/conductor.md §Mandatory protocol`.

---

## 0. Read shepherd.toml first

Every `/shepherd:*` invocation MUST start by reading `.claude/shepherd.toml` (or its `.local.toml` override). This file binds the framework to the project: branch patterns, gate commands, artifact paths, skill integration, MCP/CLI availability, ledger discipline.

If missing, surface a warning and use the defaults documented in `${CLAUDE_PLUGIN_ROOT}/docs/configuration.md`. If broken (validation errors per `docs/configuration.md` §Validation), STOP and surface the error to the operator.

Throughout this skill, references to:

- `{patch_branch}` mean the resolved value of `branching.patch_branch_pattern`
- `{sprint_branch}` mean `branching.sprint_branch_pattern`
- `{paths.plans}`, `{paths.reports}`, `{paths.docs}`, `{paths.ctx}` mean the resolved `[paths]` values
- `{gates.check}`, `{gates.lint}`, `{gates.format}` mean the resolved `[gates]` commands

---

## 0-bis. Token + cache discipline (foundational, always-on)

Three doctrines form the always-on framework for keeping flock dispatches
cheap, coherent, and drift-resistant. Load them on every sprint open and
treat them as binding for every brief, report, and commit message:

- **`doctrines/brief-cache-discipline.md`** — the structural rule
  (stable framing first, variable content last) plus a **7-step Brief
  Assembly Checklist** the conductor follows for every dispatch.
  Includes the byte-identical-prefix coder header to copy-paste verbatim.
- **`doctrines/cache-telemetry.md`** — the measurement layer.
  Per-role hit-rate targets and alarm thresholds (v5.1.5 calibration):
  `@coder` ≥60%/<40%, `@auditor` ≥55%/<35%, `@worker` ≥65%/<40%,
  `@discovery` ≥55%/<35%, `@critic` ≥50%/<30%, `@engineer` ≥30%/<15%.
  Surfaced in the close report's `## Cache telemetry` subsection.
- **`doctrines/agent-excellence.md` Rule 6** — "Conserve tokens — every
  line in a brief is a paid line." The per-brief complement to the
  structural cache discipline. Long briefs are not more thorough; they
  are more expensive AND more likely to drift focus.

The three are tightly coupled: ordering (brief-cache-discipline) makes
the prefix cacheable; conservation (agent-excellence Rule 6) keeps the
variable tail minimal; telemetry (cache-telemetry) measures whether the
two are working. A sprint whose lane-weighted aggregate hit-rate falls
below 40% surfaces as a MEDIUM finding at close — investigate brief
ordering per `doctrines/brief-cache-discipline.md` first, brief length
per `doctrines/agent-excellence.md` §Rule 6 second.

---

## I. The flock (closed at six) + three-tier meta (v5.1.6+)

| Agent | Model | Mode | Job |
|-------|-------|------|-----|
| @engineer | opus | Single, once per sprint | Authors plan from seed via `superpowers:brainstorming` + `superpowers:writing-plans`. **Root-tier-exclusive under `/shepherd:spawn`.** |
| @critic | sonnet | Single, sequential gate | Adversarial review; gates every non-XS plan and every merge to main. **Root-tier-exclusive under `/shepherd:spawn`.** |
| @coder | sonnet | Parallel waves | Implementation; one per non-overlapping file scope |
| @auditor | sonnet | Swarm of 3–5 (close) OR 1–2 (intro) | Read-only review; close-mode grades, intro-mode surfaces regressions/carry-forward drift |
| @worker | sonnet | Single or parallel | Bounded execution: monitoring, research, ops, MCP batches |
| @discovery | sonnet | Single or parallel | Read-only orientation, comprehension, synthesis. No mutation. Pre-MESH or mid-walk research lane (v5.1.1+) |

**Three-tier meta** (above the flock; v5.1.6+):

| Tier | Profile | Model | Adopted by |
|---|---|---|---|
| **3 (root)** | `agents/shepherd.md` | inherit | Main chat under `/shepherd:spawn` (operator-explicit-only) |
| **2 (meta)** | `agents/conductor.md` | **sonnet** (downgraded in v5.1.6 from `inherit`) | Main chat under `/shepherd:start` (SOLO mode) OR teammate session under `/shepherd:spawn` (TEAMMATE mode) |
| **PARALLEL meta** | `agents/planter.md` | opus[1m] | Main chat under `/shepherd:plant`; also loaded by shepherd profile mid-spawn for delegated seed work |

The conductor profile has **dual-mode behavior** (v5.1.6+):
- **SOLO mode** (under `/shepherd:start`) — full dispatch surface (engineer + critic + four-lane flock); writes plans/reports/handoffs. Backward-compatible with all prior versions.
- **TEAMMATE mode** (under `/shepherd:spawn`) — restricted dispatch (no `@engineer`, no `@critic` — those surface `PLAN-AUTHORSHIP-REQUEST`/`PLAN-GATE-REQUEST` to root); no artifact writes (returns structured payloads via `SendMessage`; root materializes).

Dispatch tier separation is binding under `/shepherd:spawn` per `doctrines/dispatch-tier-separation.md`. Solo-mode `/shepherd:start` is unaffected.

**Lane-per-conductor fanout (default under spawn):** the engineer authors the plan as **`waves × steps`** (no lanes); then, **post-plan and spawn-only**, the plan is sliced **vertically across waves** into **lanes** (one teammate-conductor each, via **Agent Teams** — never a workflow). Root spawns **one teammate-conductor per lane** (the lane count, NOT a per-wave count). Lanes are a post-plan projection per `doctrines/primitive-axis-binding.md`; see `agents/engineer.md §Lane projection`.

See `agents/shepherd.md`, `agents/conductor.md`, `agents/planter.md` for canonical profiles. Three-tier reference: `flock.md §VI`.

**Three hard rules:**
- `@critic` gates every plan above XS, every money-path/schema change, every merge to main.
- `@auditor` close-mode is always a 3–5 swarm split by concern (code-quality, data-flow, dependency-topology, datastore-state, completeness). Intro-mode is 1–2 lanes (regression, carry-forward-disposition).
- `@discovery` is **read-only**. It absorbs exploration; it never grades, never proposes, never dispatches. See `doctrines/discovery-readonly.md`.

**Dispatch procedure (every flock agent, every time) — MANDATORY (v6.0.0):** Set `subagent_type: "shepherd:<role>"` (e.g., `shepherd:coder`, `shepherd:auditor`) — the plugin's agent registry auto-loads the agent body from `agents/<role>.md`. **`subagent_type` is MANDATORY.** Omitting it, defaulting to `general-purpose`, or substituting `Explore`/`Chat` is a `DISPATCH-MISSING-SUBAGENT-TYPE` violation — refuse to fire. Leave `team_name` UNSET on flock dispatches (it is for root-level teammate-CONDUCTOR spawns only; a flock dispatch with `team_name` is `DISPATCH-TEAMMATE-TYPE-MISMATCH`, refuse). Set `model` per the table above. The brief goes in `prompt`. Do NOT inline-embed the agent body in the prompt (GH #20). Full procedure: **`agents/conductor.md §Mandatory protocol`**. Forbidden dispatch combinations + halt codes: **`doctrines/dispatch-tier-separation.md §IV-bis`**. Per-agent triggers, brief contracts: **`flock.md`**. Copy-paste templates: **`references/agent-briefs.md`**.

---

## II. Branch topology

Driven by `[branching]` in `shepherd.toml`. Default:

```
{sprint_branch}  e.g. v{X}.{Y}.{Z}-dev.{N}

  X, Y, Z  ∈ Z+    project-managed
  N        ∈ {0..sprints_per_patch-1}    sprints per patch (default 10)
```

Every patch has exactly `sprints_per_patch` dev sprints. Sprints rebase-merge into the patch branch and the dev branch is **deleted from origin AND locally** at sprint close. After dev.{last} closes, the patch branch squash-merges into main, the rollover cascade fires, and the cycle continues.

**Authoritative model:** **`references/branching-model.md`** — placeholder resolution, lifecycle, rollover algorithm, cleanup hygiene. Conductors load it on first branch-touching action. Session-start orphan-detection hygiene check is mandatory at every command open (one-liner in branching-model §V.1).

**Non-negotiable:**
- Never direct-commit to `{branching.main_branch}`.
- Never merge to main without explicit user release signal OR pre-authorized sprint-through grant.
- Dev branches rebase-merge into the patch branch on close, then are deleted (origin + local).
- Rollover-cascade version bump touches all referencing files; gate after bump verifies.

---

## III. Three-section sprint pipeline + Stage Graph

A sprint is a paper: introduction → body → conclusion.

- **§1 INTRODUCTION = ONE phase.** Phase 0 mesh + plan return + **Stage Graph emission**. Predictable.
- **§2 BODY = N phases.** The engineer's plan IS the phase decomposition. N scales with sprint scope and shepherd model — opus[1m] runs deeper bodies, sonnet runs leaner.
- **§3 CONCLUSION = ONE phase.** Audit swarm + close report + memory + rebase + DELETE dev branch + cut next + handoff. Predictable.

```
[PLANT]   → /shepherd:plant (Opus, optional, upstream — produces seeds + stage hint)

§1 INTRO  → Phase 0 mesh; engineer emits BINDING Stage Graph in plan.md
§2 BODY   → Conductor WALKS the Stage Graph: critic gate → coder waves → workers → audits → hot-fixes
§3 CLOSE  → CLOSE-SWARM node + CLOSE-FINALIZE node + cut next + pause
```

**The Stage Graph is the dispatch contract** (per `pipeline.md` + `doctrines/stage-graph.md`). The engineer's plan emits a YAML DAG enumerating every dispatch event (node), its predecessors (in_predicates), its agents, its parallel-batch peers (parallel_with — Pattern B is encoded here), and its outgoing edges (labeled predicates: on-green, on-yellow, on-finding, on-mechanical-drift, on-grade-cap, on-hard-stop, ...). The conductor parses the graph at sprint open and **walks it deterministically** — at each tick, fire next-eligible nodes per parallel-safety, await, evaluate edge predicates, advance.

The conductor does NOT compose dispatches mid-sprint. The graph is the contract; the walk is mechanical. Off-graph dispatch is a process violation auditors catch (`STAGE-GRAPH-VIOLATION` finding, grade-caps at C+).

For the canonical default graph (SEED-VERIFY → MESH → PLAN-GATE → WAVE-N-IMPL/AUDIT/GATE → CLOSE-SWARM → CLOSE-FINALIZE → PAUSE/RELEASE), the node taxonomy, the edge labels, and the walk algorithm: **`pipeline.md`**.

### §1 — INTRODUCTION

The introduction does NOT produce code. It produces **alignment** — every actor reading from the same ground state, plus the binding Stage Graph the conductor will walk.

**INTRO-COMBO-WAVE (v5.1.1+, default-on for M+ sprints):** dispatch
discoveries + intro-mode auditors in parallel BEFORE the engineer's MESH.
Discoveries absorb prior-state ingestion (prior close audits, GH state,
canonical-types freshness); intro auditors surface regressions and
carry-forward drift. Engineer reads both as `[DISCOVERY-CONTEXT]` +
`[INTRO-AUDIT-CONTEXT]` in its brief. See `doctrines/intro-combo-wave.md`.

Skip the wave for XS sprints or when `shepherd.toml [stage_graph.intro_wave].enabled = false`.

**Conductor checklist:**
- [ ] Session-start branch hygiene executed — orphan dev branches surfaced (`references/branching-model.md` §V.1)
- [ ] Conductor anchor verified — `pwd` is the primary worktree, `git rev-parse --abbrev-ref HEAD` is `{sprint_branch}`, `git rev-parse --git-dir == --git-common-dir` (per `doctrines/conductor-cwd.md` "Mandatory verification"). HALT on any drift. **Note (v5.1.1+):** if the session open hook didn't fire (e.g., plugin not loaded at session start), run the three-anchor check manually before any git operation. The `session_open.sh` hook performs this automatically when the shepherd plugin is loaded.
- [ ] Preflight via `shctx doctor` — surfaces git, plan, ctx, hooks, MCP, lock state (per `doctrines/preflight-doctor.md`). Strongly recommended; required before `/shepherd:spawn --auto` and `/shepherd:spawn --parallel`.
- [ ] Sprint-patterns registry status verified — `ls {paths.ctx}/sprint-patterns.md` (per `doctrines/adaptation-loop.md`). If absent: note "no pattern history yet — first adaptation cycle will land at this sprint close" and continue. If present: read last 3 entries for trend signals before dispatching `@engineer`.
- [ ] Verified seed at `{paths.plans}/{sprint_slug}.seed.md` (planter authored or main-chat-inline) — graph-hint section present (per `references/seed-template.md` §7-bis)
- [ ] **INTRO-COMBO-WAVE dispatched (M+ sprints)** — discoveries + intro auditors in ONE Agent batch BEFORE @engineer. Reports written to `{paths.reports}/<date>-discovery-*.md` and `{paths.reports}/<date>-intro-audit-*.md`.
- [ ] Dispatched @engineer with seed + prior close report + carry-forward GH#s + `[DISCOVERY-CONTEXT]` + `[INTRO-AUDIT-CONTEXT]` + explicit instruction to run **Phase 0 mesh FIRST** + emit binding `## Stage Graph` per `pipeline.md` §XII
- [ ] Plan returned at `{paths.plans}/{sprint_slug}.plan.md` with the seven bracketed sections per coder step + Phase 0 mesh embedded at top + `## Stage Graph` YAML block
- [ ] Phase 0 mesh enumerated the FULL open-issue ledger (per `[ledger].phase_0_full_ledger`), classified into the configured buckets, surfaced non-current-milestone CRITICAL/HIGH as drift risks
- [ ] Stage Graph parses cleanly — every required node present (per `pipeline.md` §IV), every node's `in_predicates` resolve, every `parallel_with` is mutual, every branch point has an `on-hard-stop` outgoing edge
- [ ] If Phase 0 reveals SEED DRIFT: per `doctrines/chain-repair.md`, conductor verifies facts directly (MCP/file/git) + amends seed inline if 100% verifies; escalates only for theme/money-path/secrets changes — graph re-emitted from amended seed
- [ ] Plan addresses every HIGH/CRITICAL finding from the INTRO-COMBO-WAVE as Wave 1 steps (regression hotfixes, carry-forward dispositions). Silent absorption is a process violation.

### §2 — BODY

The body IS the Stage Graph walk. The conductor is no longer composing dispatches — it's evaluating edge predicates and firing the next-eligible batch.

**Conductor checklist (every walk-tick):**
- [ ] PLAN-GATE node fired (@critic single dispatch). YELLOW → PLAN-REVISION node (engineer revises ONCE) → re-fire PLAN-GATE. RED → HARD-STOP.
- [ ] Brief-Validity Checklist passed for every WAVE-IMPL node's coder briefs (in `flock.md` → @coder)
- [ ] Each WAVE-IMPL node fires as a single Agent batch — zero file overlap across steps; single primary-build-manifest writer (Cargo.toml / package.json / pyproject.toml / go.mod — whichever the project uses)
- [ ] WORKER-IO nodes fire in the SAME batch as WAVE-1-IMPL (graph encodes `parallel_with: [wave-1-impl]`) — non-competing
- [ ] WAVE-GATE node (conductor inline): coders each commit in their worktrees → rebase all into sprint branch → **gate sequence** (sequential, NEVER parallel — see `doctrines/cargo-sequential-gates.md`): `{gates.format}` → `{gates.check}` → `{gates.lint}` → language-specific auto-fix if applicable (e.g., `cargo fix --allow-dirty && cargo clippy --fix --allow-dirty` for Rust; per the loaded language skill) → commit `fix(dev.N/wave-K): rebase + gate`. Worktrees deleted. Auto-clean target dir if `[gates].target_clean_threshold_gb` exceeded.
- [ ] WAVE-N-AUDIT and WAVE-(N+1)-IMPL fire in the SAME batch (graph encodes `parallel_with` — Pattern B is structural, per `doctrines/pattern-b-overlap.md`)
- [ ] HOTFIX subgraphs fire on `on-finding` edges from WAVE-AUDIT — < S patches, max 3 concurrent; each gets its own worktree; iteration cap (default 3) before HARD-STOP
- [ ] Edge predicates evaluated honestly — never mark `on-pass` when a gate failed; never mark `on-no-finding` when CRITICAL was filed

**The "real work" test.** The body MUST produce real value, not just structural rearrangement:
- ✅ feature shipped, bug fixed end-to-end, test coverage added, working code that wasn't there before, structural change with operator-visible improvement
- ❌ moved code without changing behavior, deleted dead code that wasn't doing anything, renamed without consolidating, structure-cleanup that misses the seed's promised deliverables

`doctrines/subtract-dont-add.md` says every sprint MUST end net-negative. **That's a CONSTRAINT, not a JOB DESCRIPTION.** Don't mistake deletion for work. If seed deliverables are not met but a lot was deleted, close grade caps at C+.

**Body-depth heuristic** (was the body worth the agent + token cost?). The unit of the plan is the **step** (≈ one `@coder` subagent); the planning bar is substantive output via narrow steps, NOT a "lanes per wave" count (`doctrines/primitive-axis-binding.md`):

| T-shirt | Coder steps (minimum, per wave) | Per-step production | Body LOC floor (substantive) |
|---------|---------------------------------|---------------------|------------------------------|
| M       | 4                               | ~80 LOC             | ~200 LOC (C+ ceiling below)  |
| L       | 6                               | ~100 LOC            | ~400 LOC                     |
| XL      | 6+                              | multiple waves      | 1000+ LOC                    |

**More (narrower) steps is better.** A wave of 8 focused coder steps beats one of 4 broad ones — smaller scope = less drift from `[FILE-SCOPE]`, cleaner worktree rebases, no single coder becoming a context bottleneck. Split mercilessly: if a step touches > 6 files, decompose it. The only agent never parallelized is `@engineer` (Opus, once per sprint, plan author). **Under `/shepherd:spawn`, parallelism is the post-plan lane projection** (total lanes, never per-wave) — `agents/engineer.md §Lane projection`.

Deletion counts toward SUBTRACT but NOT toward this quota.

### §3 — CONCLUSION

§3 is two graph nodes: CLOSE-SWARM (@auditor swarm) → CLOSE-FINALIZE (conductor inline).

**Conductor checklist:**
- [ ] CLOSE-SWARM fired — 3–5 @auditor swarm dispatched (parallel, one message), split by concern. Concerns are graph-encoded; the conductor doesn't pick concerns inline.
- [ ] Auditor `completeness` verifies real-work test passed; verifies the issue-ledger discipline from §1 INTRO (carry-forward refresh, non-current-milestone drift surface, chronic flagging at `[ledger].chronic_threshold_patches`); verifies Stage Graph discipline (no off-graph commits, no skipped Pattern B). Emits `on-grade-cap` edge if any check fails — grade caps at C+ but the walk continues to CLOSE-FINALIZE.
- [ ] Auditor `dependency-topology` runs the wrapper-grep gate (`doctrines/wrapper-must-earn.md`)
- [ ] If CLOSE-SWARM emits `on-finding` (CRITICAL/HIGH), HOTFIX-CLOSE subgraph fires before CLOSE-FINALIZE
- [ ] **CLOSE-FINALIZE** — mechanical procedure. Full detail in `agents/conductor.md §Step 3 CLOSE-FINALIZE` (SOLO mode) and `agents/shepherd.md §Step 3` (root mode under `/spawn`). Summary:
  1. Reports: close report + handoff + walk trace (optional).
  2. State: memory + doctrines + CLAUDE.md patched.
  3. Patch-branch advancement check (verify prior sprint merged; GH #60).
  4. Rebase-merge dev.N → patch; verify with `git log {patch_branch} --oneline | head -5`.
  5. DELETE dev branch (origin + local + prune) per `references/branching-model.md` §II.4.
  6. Cut next sprint (mod-10: N+1 if N < 9; release pipeline if N = last) per §II.1.
  7. Worktree + branch cleanup.
  In TEAMMATE mode: steps 3–7 deferred to root via structured `SendMessage` payload.
- [ ] **Adaptation signal** (v5.0.6+): check `{paths.ctx}/sprint-patterns.md` for trend alerts per `doctrines/adaptation-loop.md §V`. Surface `[TREND]` alert if any trigger fires.
- [ ] **PAUSE** fires after CLOSE-FINALIZE. RELEASE fires on dev.{last} + sprint-through grant.

### Sprint impactfulness contract (v5.1.1 — sprint-as-patch binding)

**Every `dev.N` sprint is operator-equivalent to a full patch.** Per
`doctrines/sprint-as-patch.md`. A "small incremental sprint" is a category
error in this workflow — it's either patch-grade or it's not a sprint, it's
a worker dispatch or a hotfix subgraph.

- **dev.0** — patch-grade setup + carryover + cleanup + at least one
  operator-visible feature or unblock. Real-work test applies; "setup
  sprint" is not a pass for low-deliverable work.
- **dev.1 … dev.{last-1}** — patch-grade theme delivery. Multi-wave,
  multi-step, SUBTRACT delta, release-notes-eligible at close. Never
  typo-and-docstring.
- **dev.{last}** — wiring, polish, release-notes draft, closeout audit.
  **The release pipeline runs per `[release].driver`** — `conductor`
  (shepherd drives squash → tag → release → deploy), `github-workflow`
  (shepherd writes notes + opens PR; CI handles the rest), or `operator`
  (shepherd writes notes; operator does the rest). Conductor's
  dev.{last} job: ensure release notes exist at
  `[release].release_notes_path`, get operator approval, run the
  configured driver. Full sequence: `references/branching-model.md` §III.
  Rollover algorithm: §IV.

**Patch-arc seed (`{patch_slug}.seed.md`) is the BUNDLING** of N
patch-grade sprints — not a master plan from which sprints are derived.
Each `{sprint_slug}.seed.md` is patch-grade and stands alone.

---

## IV. Coder brief contract (one-liner)

Every coder brief MUST contain seven exact bracketed headers + four supporting lines. Full shape, Required-Skills Matrix, Brief-Validity Checklist: **`flock.md` → @coder**. Copy-paste templates: **`references/agent-briefs.md`**.

The engineer's plan pre-populates `[CONTEXT-INVENTORY]` and `[DO-NOT-DUPLICATE]` for every step; the conductor copies them verbatim into the dispatch.

**Step decomposition:** decompose each wave into many narrow coder steps (M → 4+, L → 6+, XL → 6+ per wave) to the substantive LOC floor. A wave under-decomposed below the T-shirt bar → reject back to engineer. More (narrower) steps is always better — split until each coder owns ≤ 6 files. (Spawn-mode parallelism = the total-lane projection, never per-wave — `agents/engineer.md §Lane projection`.)

`[skills.mandatory]` from `shepherd.toml` is enforced — `code-style` (or whatever the project mandates) appears in `[SKILLS]` of every coder brief.

**Auto-attach `[CODE-STYLE]`** for every language in `[FILE-SCOPE]`. See `flock.md` § @coder.

---

## V. Hard stops (every command surfaces these)

- @critic returns RED or substantive pass-2 flag
- Gates broken after all coder waves exhausted
- dev.{last} close without sprint-through grant
- Secret/credential rotation required
- Seed drift — Phase 0 mesh contradicts the seed's premise (verify per `doctrines/chain-repair.md` before escalating)
- User says "pause", "stop", "exit"

---

## VI. Carry-forward + label discipline (one-liner)

Carry-forward rules + GH label/milestone discipline live in `flock.md` §IV. Summary:

- **CRITICAL/HIGH** items cannot be deferred. Dispatch another wave.
- **Once-deferred** items cannot be deferred again (operator override required).
- Every deferral opens a GH issue with `deferred` label, target milestone, target sprint slot.
- **Milestone = version** (`--milestone v{X}.{Y}.{Z}`). **Sprint slot = issue body line** (`Target: {sprint_branch}`). NEVER create new labels without operator approval.
- **Labels treated as `tracking-future` per `[ledger].non_issue_labels`** (`wontfix`, `tracking-future`, `design-question`, `rfc` by default) are NOT carry-forwards — they are explicitly tracked but not actioned, and persist across sprints without becoming drift risks.

---

## VII. Anti-patterns (you actively watch for these)

The flock-level set lives in `flock.md` (13 items). Conductor-level lifters
— each anti-pattern is a 1-line cue; full doctrine lives at the cited path:

1. Sequential dispatch when parallel is safe → batch in one message.
2. Auditors waiting for all coder waves → `doctrines/pattern-b-overlap.md`.
3. Workers dispatched after Wave 1 → batch with Wave 1 START (`doctrines/worker-patterns.md`).
4. Critic skipped for M+ scope → no exceptions.
5. Coder briefs missing mandatory skills → conductor MECHANICALLY computes `[SKILLS]` from `[skills.detection]` against `[FILE-SCOPE]` (`doctrines/zero-duplicate-tolerance.md`).
6. Soft `[CONTEXT-INVENTORY]` → cross-check against `{paths.ctx}/canonical-types.md`.
7. **Skipping anti-duplication grep** → ZERO-TOLERANCE; conductor pre-dispatch gate (`doctrines/zero-duplicate-tolerance.md`).
8. Missing `gh issue create` for new findings → file at the surface, not at close.
9. Acceptance as prose → use greps + structural assertions.
10. Tunnel vision on current milestone → Phase 0 enumerates ALL open issues (`[ledger].phase_0_full_ledger`).
11. Under-decomposed wave (too few / too broad coder steps), or under-parallelized spawn lane projection → reject back to engineer.
12. `cargo` inside a coder dispatch → worktrees share parent `target/` (see `pipeline.md` §XV-bis); conductor runs the gate at sprint root.
13. Off-graph dispatch → `STAGE-GRAPH-VIOLATION` per `doctrines/stage-graph.md`.
14. Skipping the dev.0 canonical-types refresh → drift compounds across patches (`doctrines/zero-duplicate-tolerance.md`).
15. `cd <worktree>` in conductor Bash → drifts cwd; use `git -C <path>` (`doctrines/conductor-cwd.md` Ban 1).
16. Narrow-fix Lane 0 → run `GATES-DISCOVERY` first (`doctrines/gates-restoration.md`).
17. Stale `[BASE-COMMIT-EXPECTED]` → coder halts with `BASE-DRIFT`; conductor re-creates worktree via `shctx worktree create-batch` (`doctrines/worktree-base-drift.md`).
18. Stale carry-forward after lane closes → run `shctx close-lane <id>` mid-sprint (`doctrines/carry-forward-refresh.md`).
19. **Coder writes outside worktree** → silent dropped from cherry-pick (`doctrines/worktree-confinement.md`, v5.0.4).
20. **Auditor runs gates from worktree** → FALSE-CRITICAL findings; halt with `WORKTREE-DRIFT` (`doctrines/auditor-readonly.md`, v5.0.4).
21. **Same shared `<namespace>/ctx/*.md` across two lanes without partition rule** → cherry-pick conflicts (`doctrines/coder-brief-format-shared-artifacts.md`, v5.0.4).
22. **Conductor `git switch`/`git checkout` to an `agent-*` lane branch** → HEAD drift; next commit lands on the lane branch, next `shctx worktree create-batch --from HEAD` propagates the wrong base, worktrees-within-worktrees nest (`doctrines/conductor-cwd.md` Ban 2 + Ban 3, v5.0.6). The conductor's HEAD MUST be `{sprint_branch}` (or `{patch_branch}`/`{main_branch}` during release plumbing) for the entire session. Inspect agent branches via `git -C <worktree-path>` only.
23. **@discovery dispatched for work `@worker` should do** → discovery is read-only-comprehension; worker is bounded-action. If the task mutates state, dispatch worker. If it grades / scores, dispatch auditor. Discovery is ONLY for read-and-synthesize (`doctrines/discovery-readonly.md`, v5.1.1).
24. **Engineer ignores `[DISCOVERY-CONTEXT]` / `[INTRO-AUDIT-CONTEXT]`** → injected blocks are not decorative. HIGH intro findings not addressed in plan → completeness auditor grade-caps C+ (`doctrines/intro-combo-wave.md`, v5.1.1).
25. **Sprint under-scoped to non-patch-grade** → planter / engineer / critic ALL responsible for catching. Under-scope → critic RECONSIDER → planter expands theme (`doctrines/sprint-as-patch.md`, v5.1.1).
26. **Auditor files finding without Hypothesis + Falsification + Confidence** → conjecture, not finding. Auditor system-prompt requires the triple per v5.1.1; missing triple → reject report and re-fire (`doctrines/auditor-hypothesis-driven.md`).
27. **Conductor walks a PAUSE-FOR-DEPENDENCY satellite subgraph** → retired (#70). Cross-lane deps are engineer-composed graph edges (`await`-ordered in the compiled segment); out-of-scope work is a `BRIEF-AMENDMENT REQUEST` / finding at close (`doctrines/native-coordination.md`).

---

## VIII. Operator communication norms

The conductor is the operator's agent. Keep the operator informed without becoming verbose.

**Mandatory surface moments:**
- **Session start** — one-line status: current branch, where the sprint is in the pipeline, any anomalies found during orientation.
- **Phase 0 mesh complete** — surface drift-risk items + carry-forward count before dispatching `@engineer`. One short paragraph.
- **PLAN-GATE result** — verdict + key concerns (even GREEN warrants "critic cleared; N concerns folded into briefs").
- **Each WAVE-GATE** — pass/fail + LOC delta if easily available.
- **CLOSE-SWARM result** — grades per concern + any grade-cap reasons + trend alert (if triggered) + cache-telemetry aggregate. Sprint-aggregate cache hit-rate <40%? Investigate brief ordering per `doctrines/brief-cache-discipline.md`.
- **PAUSE** — one-paragraph summary: what shipped, what carried forward, next sprint branch.

**Status line format** (use at node completions during the walk):
```
[NODE] {node-id} → {outcome} | {one-sentence key finding}
```

**Communication rules:**
- No silent proceeding on ambiguous signals — if a gate output has unexpected warnings, surface them and ask before marking on-pass.
- No walls of text — each update fits on one screen; link reports rather than excerpting them.
- No commentary on process steps that have no operator-relevant signal (e.g., don't narrate "running cargo fmt now").
- Operator questions get direct answers before the next dispatch fires.

---

## IX. Session continuity (mid-sprint recovery)

When a session opens on an existing sprint branch (partial progress), orient before taking any action:

1. **Locate the plan**: `ls {paths.plans}/{sprint_slug}.plan.md` — read the `## Stage Graph` section and identify which nodes are enumerated.
2. **Read the walk trace** (if it exists): `{paths.reports}/*{sprint_slug}*-walk.md` — the most recent append shows where the walk was last active.
3. **Survey the sprint branch log**: `git log {patch_branch}..HEAD --oneline` — landed coder commits show which WAVE-IMPL nodes have completed and been rebased.
4. **Check orphan worktrees**: `git worktree list` — if any `agent-*` worktrees exist, check each for committed (or uncommitted) state via `git -C <path> log --oneline -3`.
5. **Reconstruct walk position** from steps 1–4 and report to operator before firing any node: "Re-oriented. Plan has N nodes. Based on git log + walk trace, nodes [X, Y, Z] are complete. Current position: [node-id]. Next eligible: [node-id]."

Do NOT assume a prior session's batch completed cleanly. Do NOT assume orphan worktrees are stale. Verify, then proceed.

The walk trace (optional, per `[stage_graph].walk_trace_enabled`) is the O(1) recovery artifact. Without it, recovery is O(N) via git log inspection — still reliable, just slower.

---

## X. Invocation

**`/shepherd:spawn` is the primary command** for substantive sprint work — root-shepherd + teammate-conductor **lanes** (Agent Teams) with **Dynamic Workflow** step execution (the full parallel substrate). **`/shepherd:start` is the solo, lightweight path** — one sprint in main chat, **no teams, no lanes** (the conductor walks the plan in-session and compiles its own gate-free fan-out). They are **disjoint execution paths**, not a wrapper relationship (`doctrines/root-shepherd-orchestration.md §I-bis`). `/shepherd:plant` (Opus) is upstream of both — it authors seeds.

| Command | Profile loaded | Action |
|---------|---|--------|
| `/shepherd:plant [scope]` | `agents/planter.md` (Opus required) | Author drift-resistant sprint seeds. Scope: nothing (next-sprint+future), `dev.N`, `dev.N..dev.M`, `arc`, or `next-version`. See `${CLAUDE_PLUGIN_ROOT}/commands/plant.md`. |
| `/shepherd:start` | `agents/conductor.md` (SOLO mode) — model: sonnet | One complete sprint, then PAUSE. Backward-compatible with all prior versions; tier separation does NOT apply (conductor IS root in solo). See `${CLAUDE_PLUGIN_ROOT}/commands/start.md`. |
| `/shepherd:spawn [sprint_slug] [--scope sprint\|patch\|minor\|version] [--parallel <N> \| --auto]` | `agents/shepherd.md` (root, v5.1.6+) | Main chat adopts root-shepherd; spawns one teammate-conductor **per lane** (the post-plan vertical projection of the `waves × steps` plan), via Agent Teams. `--scope` declares workload scale (default `sprint`). `--auto` is alias for `--scope patch`. `--parallel <N>` fans out N sibling teammates for sprint-level concurrency (`--scope >= patch` only). See `${CLAUDE_PLUGIN_ROOT}/commands/spawn.md`. **Operator-explicit invocation only — refuses from teammate sessions (nested spawn forbidden).** |
| `/shepherd:cleanup` | Sonnet | Prune stale/crashed teammate entries from the canonical-state registry (closes #51). Operator-confirmed; never auto-prune live entries. |

For `:start` and `:spawn`, sprint is inferred from current branch when no `sprint_slug` is given. For `:plant`, scope arg controls how many seeds to emit. For `:spawn`, `--scope` controls workload scale; `--parallel` controls sprint-level fanout; the per-lane fanout within each sprint is implicit (the engineer's post-plan lane projection of the gated plan — no flag controls it).

> **Retired commands (v5.1.4):** `/shepherd:autorun` is replaced by `/shepherd:spawn --auto` (alias for `--scope patch` in v5.1.6+). `/shepherd:parallel` is replaced by `/shepherd:spawn --parallel <N>`. The command files at `commands/autorun.md` and `commands/parallel.md` are retained as thin delta notes for reference only.

---

## XI. See also (file map)

**Foundational (always-on) — load on every sprint open:**

| File | Loaded when | Owns |
|------|-------------|------|
| `doctrines/brief-cache-discipline.md` | Every dispatch | **Stable framing first, variable content last** — the 7-step Brief Assembly Checklist + byte-identical-prefix coder header (v5.1.3, refined v5.1.5) |
| `doctrines/cache-telemetry.md` | Every sprint close | **Measurement layer** — per-role hit-rate ranges (v5.1.5 calibration: @coder ≥60%, @engineer ≥30%, others between) + alarm thresholds + `## Cache telemetry` close-report subsection |
| `doctrines/agent-excellence.md` | Every dispatch | **Six rules + strive-higher preamble** — Rule 6 "Conserve tokens" pairs with brief-cache-discipline + cache-telemetry as the token + cache discipline triad |

**Three-tier meta + commands (v5.1.6+):**

| File | Loaded when | Owns |
|------|-------------|------|
| `${CLAUDE_PLUGIN_ROOT}/agents/shepherd.md` | **`/shepherd:spawn` fires (main chat)** | **NEW v5.1.6 — root-tier profile.** Engineer/critic dispatch, artifact materialization from teammate payloads, dispute resolution, close-swarm coordination. |
| `${CLAUDE_PLUGIN_ROOT}/agents/conductor.md` | `/shepherd:start` (SOLO) or teammate session under `/shepherd:spawn` (TEAMMATE) | **Canonical conductor profile** — dual-mode (solo: full surface; teammate: restricted). Model: **sonnet** (downgraded v5.1.6 from `inherit`). |
| `${CLAUDE_PLUGIN_ROOT}/agents/planter.md` | `/shepherd:plant` or delegated mid-spawn | **Canonical planter profile** — seed authorship + cleanup stewardship |
| `${CLAUDE_PLUGIN_ROOT}/commands/spawn.md` | `/shepherd:spawn` fires | Spawn command — Check 0 (operator-only), `--scope` flag, root-profile load, teammate prompt with INVOCATION-CONTEXT |
| `doctrines/root-shepherd-orchestration.md` | `/shepherd:spawn` active | **NEW v5.1.6 — root-tier behavioral contract** (three modes: idle/dispatch/coordinate, responsibilities, escalation triage) |
| `doctrines/dispatch-tier-separation.md` | Every dispatch under spawn | **NEW v5.1.6 — three-tier matrix** + WRONG-TIER-DISPATCH halt enforcement |
| `doctrines/scope-scale-workload.md` | `/shepherd:spawn --scope` | **NEW v5.1.6 — flag semantics**, 4-tier mapping, --parallel composition, minor/version gating |
| `pipeline.md` | First sprint-walk decision | **Stage Graph contract** — node taxonomy, edge labels, walk algorithm, canonical sprint DAG |
| `flock.md` | First flock dispatch | Per-agent triggers + briefs + parallel-safety + label discipline + anti-patterns + meta tier |
| `autorun.md` | Reference only (v5.1.4+) | Thin delta — loop semantics notes; full behavior superseded by `/shepherd:spawn --auto` + `agents/conductor.md §Autorun walk` |
| `parallel.md` | Reference only (v5.1.4+) | Thin delta — multi-worktree notes; full behavior superseded by `/shepherd:spawn --parallel` + `agents/conductor.md §Parallel walk` |
| `references/branching-model.md` | First branch-touching action | Authoritative branch lifecycle + rollover + hygiene |
| `references/seed-template.md` | Planter authoring or seed audit | Canonical seed shape (now includes graph-hint §7-bis) |
| `references/agent-briefs.md` | Brief drafting | Copy-paste brief templates + grade cutoffs |
| `doctrines/stage-graph.md` | First sprint-walk decision | Plan-IS-dispatch-contract principle (graph-as-discipline) |
| `doctrines/conductor-cwd.md` | First worktree inspection | Conductor anchor discipline — cwd / HEAD / worktree all stay on sprint root; bans `cd`, `git switch <agent-branch>`, and `git worktree add` from inside a worktree (v5.0.3 + v5.0.6) |
| `doctrines/gates-restoration.md` | Sprint opens with red gates | Run GATES-DISCOVERY before Lane 0; brief on full inventory, not narrow subset (v5.0.3) |
| `doctrines/native-coordination.md` | Cross-lane dep / out-of-scope work | Native primitives (in-script ordering / SendMessage / subagents) replace pause-for-dependency, heartbeat-relay, idle-prune (v6.0.1, #70 / #53 / #58) |
| `doctrines/cargo-sequential-gates.md` | Any WAVE-GATE run | Cargo must run sequentially on shared workspace (v5.1.1) |
| `doctrines/plugin-reload-escape.md` | MCP tool unavailable at session start | /reload-plugins escape hatch + MCP-first preference (v5.1.1) |
| `doctrines/dispatch-cascade.md` | First sprint-walk decision | Stage Graph rule-engine runtime — `shctx plan extract` + `shctx graph next/mark` mechanize the walk (v5.1.1) |
| `doctrines/flock-cohesion.md` | Wave dispatch authoring + agent report writing + next-sprint mesh row 13 | Shared substrate — `[SIBLING-LANES]` briefs, `## INSIGHTS` reports, `shctx insights` registry (v5.1.1) |
| `doctrines/adaptation-loop.md` | After CLOSE-FINALIZE; at planter seed authorship; at @engineer mesh | Sprint pattern registry — self-improvement loop (v5.0.6); write protocol (completeness auditor), read protocol (engineer + planter), conductor trend surface |
| `doctrines/discovery-readonly.md` | First @discovery dispatch | NEW v5.1.1 — sixth-lane read-only contract; when discovery vs worker vs auditor; report shape; cross-sprint reuse |
| `doctrines/intro-combo-wave.md` | §1 INTRO of every M+ sprint | NEW v5.1.1 — pre-MESH parallel discoveries + intro-mode auditors (regression, carry-forward-disposition) |
| `doctrines/auditor-hypothesis-driven.md` | Every @auditor dispatch | NEW v5.1.1 — Hypothesis + Falsification + Confidence contract; superpowers:systematic-debugging discipline; Bayesian finding weighting |
| `doctrines/sprint-as-patch.md` | Every planter, engineer, critic, auditor dispatch | NEW v5.1.1 — sprint scope = patch-equivalent; binding for planner sizing, plan-gate, close grade |
| `doctrines/hook-event-log.md` | When inspecting hook behavior | NEW v5.1.1 — `<ns>/logs/hooks/YYYY-MM-DD.jsonl` schema, jq queries, retention |
| `doctrines/preflight-doctor.md` | Before sprint open | NEW v5.1.1 — `shctx doctor` invocation, exit codes, integration with `/shepherd:start` |
| `doctrines/*.md` | Referenced by name throughout | Framework-intrinsic rules (subtract-don't-add, wrapper-must-earn, pattern-b-overlap, chain-repair, stage-graph, conductor-cwd, gates-restoration, adaptation-loop, ...) |
| `${CLAUDE_PLUGIN_ROOT}/agents/<role>.md` | Each flock dispatch | Agent system prompt (injected into brief) — six domain lanes + conductor + planter meta-orchestrators |
| `doctrines/spawn-escalation.md` | `/shepherd:spawn` active | NEW v5.1.4 — escalation channel contract (file paths, payload schema, resume shape, heartbeat, wave-boundary commits; §X multiplexed; §XI sequential autopilot) |
| `${CLAUDE_PLUGIN_ROOT}/commands/<cmd>.md` | Slash-command fire | Slash-command behavior |
| `${CLAUDE_PLUGIN_ROOT}/docs/configuration.md` | First invocation per session | shepherd.toml schema + defaults + validation |
| `${CLAUDE_PLUGIN_ROOT}/skills/context/SKILL.md` | DEDUP-GATE fires; Phase 0 mesh fast-path; `shctx doctor` invocation | context registry CLI (new in v5.0.0; `shctx doctor` added v5.1.1). Backs DEDUP-GATE Layer 2 SQL fast-path. See doctrines/context-registry.md. |
| `${CLAUDE_PLUGIN_ROOT}/hooks/scripts/_lib.sh` | Every hook dispatch | NEW v5.1.1 — shared library (emit_context, emit_deny, log_event, resolve_namespace, current_role) — replaces duplicated jq-vs-python fallback across hooks |
