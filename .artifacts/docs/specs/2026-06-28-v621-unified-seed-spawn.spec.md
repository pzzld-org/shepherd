# v6.2.1 Design Spec — Self-Sufficient Spawn, Seed Teeth, and Engineer Seam Refinements

- **Status:** DRAFT for operator review (pre-seed). Not yet a plan; not yet dispatched.
- **Author:** root design session (Opus 4.8 [1m]), 2026-06-28. Baseline gathered by a 9-agent map+critique workflow over the planter/engineer/spawn spine.
- **Branch:** `v6.2.1` (current; the only target). No future version is implied or proposed by this spec.
- **Namespace:** `.artifacts/` (honor `resolve_namespace` / `resolve_workdir`; never hardcode the literal).
- **Convertible to:** a `/shepherd:plant` seed once approved.
- **North-star:** refine the proven workflow, do not replace it. Less prose, more determinism. Every item is "keep X exactly as it is; sharpen only Y."

---

## 0. Orientation — what we keep, what we sharpen

The proven spine stays untouched: the planter, the engineer, the critic, the six-agent flock, lanes-as-teammate-conductors, the INTRO/BODY/CLOSE pipeline, and `/plant` as the deliberate seed-authoring door. **Nothing in this spec changes how a sprint executes once a gated seed exists.** It refines three seams and adds one gate.

Three load-bearing facts from the baseline map justify the work. If any is wrong, the dependent item is invalidated.

**Fact 1 — the framework's highest-precision artifact has zero deterministic enforcement.** The ~15-item seed pre-flight is prose the model is asked to honor. `seed-naming.md:110-119` admits it outright ("the planter sometimes hallucinates paths anyway... future sprints will add teeth"). The promised pre-commit hook was never built. The checklist also lives in two files that disagree (`planter.md:189-207` = ~15 items vs `seed-template.md:370-385` = ~11), the seed footprint is stated three ways (`planter.md:174` 150-300 / `:202` ≤400 / `:271` 400-smell), and the mesh row-count three ways (12 / 8+ / 15). A deterministic gate cannot enforce a threshold stated three ways.

**Fact 2 — the planter→execution boundary is the biggest discontinuity in the flow.** The planter writes the seed and stops (`plant.md:51`); the operator must then separately invoke `/spawn` or `/start`, re-deriving scope/branch at the hop. A missing seed produces three different behaviors by flag: hard-refuse (`spawn.md:1054-1063`), best-effort-degrade (`operator-signaling.md:55-71`), or staged-wait (`staged-handoff.md`). The machinery to close this already half-exists three times over: two-meta-loading (`shepherd.md:762-779`), the `--staged` seed-ready mailbox, and mid-spawn SEED-DRIFT escalation.

**Fact 3 — the engineer is load-bearing by TIMING, not by the #67 authority firewall.** Five engineer outputs cannot exist at seed time regardless of authority: per-step `[CONTEXT-INVENTORY]`/`[DO-NOT-DUPLICATE]` grounded in the live tree, **intra-wave file-disjointness between sibling steps** (the merge-safety guarantee for parallel coders — the seed's sprint-level `file_scope.exclusive` does not decompose to it), fine-grained step decomposition, the binding Stage Graph, and lane projection (`engineer.md:272-282`). The engineer stays. Only the bounded redundancy — a ~3-field transcription spine plus a double/triple ground-truth mesh that is theater when the seed is co-timed — gets cut.

---

## Pass 1 — Goals & Deliverables

"Done" stated in concrete, checkable terms per item. Each acceptance line is independently verifiable.

### Item A — Self-sufficient `/spawn`: inline planting on absent seed (single-sprint)

A seedless single-`--scope sprint` `/spawn` can no longer dead-end. It enters an inline planting sub-phase as the first node of the spawn Stage Graph, then falls through to the unchanged walk.

Deliverables:
1. **`SEED-AUTHOR` node** prepended to the spawn Stage Graph, before `SEED-VERIFY`, gated on `test -e {paths.plans}/{slug}.seed.md`.
   - **Seed present** → no-op pass-through. Today's happy path is byte-for-byte unchanged.
   - **Seed absent, single `--scope sprint`** → root emits exactly one turn-ending confirm (*"No seed for `{slug}`. Plant inline now?"*), replacing today's "go run `/shepherd:plant` then come back" report. On confirm, root loads `planter.md §Plant mode` as its inner frame (existing two-meta-loading), authors the seed in-session with AskUserQuestion, commits it, passes `SEED-GATE` (Item B), then continues. Same single operator stop as today; no session hop.
   - **Seed absent, multi-sprint / `--parallel`** → behavior unchanged (still routes to `/plant`; those are deliberate multi-seed planning sessions).
2. **Node-scoped AskUserQuestion.** The asker is live only while the active Stage-Graph head is `SEED-AUTHOR`; the inner frame collapses and the tool leaves the active posture at `SEED-GATE` green. The transition is recorded as an explicit marker so the remainder of the run is provably in execution posture. This converts today's tool-grant convention (planter is the only profile carrying the tool) into a node-boundary interlock.

Acceptance:
- A seedless single-sprint `/spawn` surfaces exactly one confirm; on confirm it authors and commits `{slug}.seed.md`, the seed passes `shctx seed verify`, and the run proceeds into `INTRO-COMBO-WAVE` with no second operator stop. Verified by a documented end-to-end trace fixture.
- After `SEED-GATE` green, the trace contains the mode-transition marker and zero subsequent `AskUserQuestion` calls (grep the trace).
- A seedless multi-sprint `/spawn` still routes to `/plant` (unchanged) — confirmed by the existing `spawn.md` Check 6 path and a regression note.

### Item B — Seed teeth: `shctx seed verify` + blocking hook + single-source checklist

The deterministic gate that makes a single uninterrupted run safe, and the single source of truth that ends the duplicated-checklist drift.

Deliverables:
1. **`shctx seed verify <path>`** (`skills/context/scripts/cmd_seed.sh`, registered in the `shctx` dispatcher allowlist, bash-3.2 clean — no `${,,}`, `mapfile`, `declare -A`). Deterministic checks only:
   - every §6 deliverable line carries a `GH:` reference; every `#NNN` resolves (ctx registry fast-path, else `gh issue view`);
   - every `file_scope` path resolves on the FS **or** carries the allow-marker;
   - mesh rows ≥ `MIN_MESH_ROWS`; footprint ≤ `SEED_FOOTPRINT_CAP`; no `TODO`/`FIXME`; no `Lane N` / sequencing / semver-judgment regex; ≥1 deliverable ranked CRITICAL/HIGH; milestone exists; frontmatter schema parses.
   - **Canonical numbers** `MIN_MESH_ROWS` and `SEED_FOOTPRINT_CAP` are defined once, in this script, and are the only authoritative values.
   - **Allow-syntax:** the single documented inline marker `(NEW)` exempts a not-yet-existing path (one that will exist at Phase 0) from FS resolution, per the verify-paths-in-seeds discipline. Without it the gate would block legitimate placeholder seeds.
2. **`hooks/scripts/seed_preflight_check.sh`** — guard on Write/Edit of `*.seed.md`, runs `shctx seed verify`, blocks on hard failure with a clear halt message naming the offending line. bash-3.2 clean; registered in the hooks config. Fires everywhere a seed is written, so standalone `/plant` gets the teeth too.
3. **Single-source cleanup:** delete the prose checklist copy at `seed-template.md:370-385`; rewrite `planter.md:189-207` to "run `shctx seed verify` — the gate is authoritative"; replace every conflicting seed-size and mesh-row number with the script's canonical constants.

Acceptance:
- `shctx seed verify` exits 0 on a clean fixture; exits non-zero naming the bad path on a hallucinated-path fixture; exits 0 on a fixture whose missing path carries the allow-marker. (tests in `skills/context/tests/`)
- Writing a `*.seed.md` containing `TODO` or a `Lane 2` line is blocked by the hook with a halt message. (test in `hooks/tests/`)
- `grep` confirms the seed checklist exists in exactly one place, and the footprint cap and mesh-row minimum each appear as a single canonical constant.
- A bash-3.2 portability grep over both new scripts finds none of the banned constructs.

### Item C — Engineer seam refinements (the three cuts)

The engineer stays; the bounded redundancy is excised. No change to the engineer's load-bearing outputs.

Deliverables:
1. **Cut 1 — conditional re-mesh.** `engineer.md` documents that when the seed is co-timed (its commit is HEAD, or authored in the current session via Item A), the engineer runs a targeted gap/delta-check instead of the full Phase-0 enumeration; the full re-mesh is retained for stale (patch-arc-ahead) seeds. Both modes stay first-class.
2. **Cut 2 — single-source acceptance.** Acceptance predicates are authored once in the GH issue body (already the shared anchor per `seed-anchored-by-issues.md`); `seed-template.md §6-bis` and the engineer's step `[ACCEPTANCE]` reference it rather than re-typing. Removes the silent divergence seam.
3. **Cut 3 — delete §7-bis.** Remove the non-binding "Stage decomposition hint" (`seed-template.md §7-bis`) and the planter authoring step that produces it. The engineer authors the binding Stage Graph from Phase-0 as it already does. The #67 firewall (planter does not prescribe structure) is preserved by removal, not weakened.

Acceptance:
- `engineer.md` states the co-timed conditional and the staleness boundary; a co-timed run's phase0 report records "delta-check (co-timed)" vs a stale run's "full mesh (stale)". (grep / trace)
- `grep` finds no acceptance-predicate block duplicated between `seed-template.md §6-bis` and the issue body; §6-bis references the issue.
- `grep` finds no `7-bis` / "Stage decomposition hint" in `seed-template.md` or `planter.md`; a sample engineer plan still emits a binding `## Stage Graph` (unchanged).

### Item D — Wording refinement (drift-class, behavior-neutral)

The "less is more" lane: purge duplicated normative text so intentions are delivered once, deterministically. No behavior changes.

Deliverables:
1. Fix `conductor.md:692` — delete the stale "SOLO carries AskUserQuestion" line to match `:101`/`:194` and the frontmatter (the tool was removed v6.1.7).
2. Demote the dead env vars (`$CLAUDE_AGENT_TEAMMATE_NAME`, `$CLAUDE_PROJECT_SESSION_TYPE`) in `dispatch-tier-separation.md §III` to "empty on live platform per #93 — do not rely"; remove or comment the dead read in `spawn.md:169-173`. Promote `INVOCATION-CONTEXT` + `.worktrees/` cwd to the primary signals (matching `conductor.md:65-77`).
3. Make `dispatch-tier-separation.md §IV-bis` the single canonical halt-code registry; reduce the `conductor.md` and `shepherd.md` tables to a pointer plus only the codes that file emits.
4. **doc-lint** (`hooks/scripts/` or a `shctx` check, bash-3.2 clean): grep-based, flags (a) any agent profile naming a tool absent from its own frontmatter, (b) any `halt_code` string not present in the registry.

Acceptance:
- `grep` confirms `conductor.md` no longer claims AskUserQuestion; the doc-lint passes (no profile references a tool absent from its frontmatter).
- `grep` confirms the dead env vars are not listed as PRIMARY detection signals anywhere; they appear once, marked dead.
- The doc-lint script exists, runs clean on the current tree, and is wired into the gate/pre-commit set.

---

## Non-goals (v6.2.1)

Explicitly out of scope. Named here so the seed and plan cannot drift into them.

- **No collapse of the engineer** into the planter (unsafe: bakes a stale tree-view into the merge-safety guarantee) or into the lane conductors (the documented v5.1.5 divergent-plan failure).
- **No collapse of the `shepherd.md` / `conductor.md`-SOLO duplication** (real, deepest drift source, but a large structural rewrite — a separate decision).
- **No folding of the planter babysitter half into root phases** (a clean consequence, but a bigger refactor; note only).
- **No SEED-CRITIC pass.** The deterministic gate plus the existing engineer→critic plan gate is sufficient.
- **No multi-sprint inline planting.** Single-sprint only; multi-sprint keeps routing to `/plant`.
- **No §7-bis-as-binding**, and therefore no change to the #67 firewall.
- **No new version target.** v6.2.1 only.

---

## Decisions resolved (operator, 2026-06-28)

1. **Seed timing:** both co-timed and patch-arc-ahead seeds stay first-class; the engineer re-mesh is conditional on staleness (Item C, Cut 1).
2. **Spawn no-seed:** inline planting with one confirm first (Item A).
3. **Seed teeth:** blocking gate with allow-syntax (Item B).
4. **Engineer scope:** keep it; cut the three transcription seams (Item C).

---

## Convertible to a seed

On approval, this spec becomes the input to `/shepherd:plant`, which grounds it (issue-anchoring for each deliverable, the Phase-0 mesh, file_scope verification) into the v6.2.1 seed at `{paths.plans}/v621.seed.md`. We dogfood the pipeline to refine the pipeline. The items are largely separable (A: spawn graph + node; B: `shctx`/hooks; C: engineer; D: doctrines + profiles), but note `seed-template.md` is edited by both B (delete the duplicate checklist) and C (§6-bis reference, delete §7-bis), so those edits are not file-disjoint and must be sequenced. Lane projection is the engineer's call, post-plan, not this spec's.
