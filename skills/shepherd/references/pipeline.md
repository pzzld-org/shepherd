---
title: pipeline
description: |
  Sprint Stage Graph and gates: stage taxonomy, lane law, combo waves,
  PLAN/DEDUP/WAVE gates, hotfix ladder, REDO, CLOSE-FINALIZE git ops. Use when
  walking or authoring a sprint Stage Graph.
---

# Pipeline — the Stage Graph and its gates

The engineer's plan emits ONE **Stage Graph**; the conductor **walks** it. Per-role dispatch: `skills/shepherd/references/flock.md`.

## Stage Graph

Every dispatch is a named node, every transition a labeled edge. The conductor NEVER invents, skips, or re-orders a node; an unanticipated need halts → amend the plan (re-run PLAN-GATE) → resume.

Node types by shape (walk batches by shape). **Conductor-inline:** `SEED-AUTHOR`/`SEED-VERIFY` (missing seed → planter inline-plants), `CHAIN-REPAIR`, `DEDUP-GATE`, `GATES-DISCOVERY`, `WAVE-GATE`, `LANE-CLOSE` (`shctx close-lane <lane-id>` per lane — auto-resolves carry-forward + dedup ledger), `LANE-INTEGRATE`, `CLOSE-FINALIZE`/`RELEASE`/`HARD-STOP`/`PAUSE`. **Single agent:** `MESH` (`@engineer`), `PLAN-GATE`/`PLAN-REVISION` (`@critic`). **Parallel batch:** `WAVE-IMPL` (N `@coder`/step + `@worker` IO, SAME message), `WAVE-AUDIT`/`CLOSE-SWARM` (`@auditor`, concern-split), `HOTFIX`/`HOTFIX-DYNAMIC`, `DISCOVERY` (gate-free `@discovery` outside a combo wave; plant-mode 1–3 lanes; edge `on-research-complete`), `INTRO-COMBO-WAVE`/`DISCOVERY-COMBO-WAVE`, `CANONICAL-TYPES-REFRESH` (`@worker`, every dev.0).

Each node carries `in_predicates` (predecessor + edge-label pairs, ALL hold — AND-join), `parallel_with` (node-ids in one Agent batch), `agents`, `out_edges`. Multiple `out_edges` = a branch point, exactly ONE fires; OR-joins are separate nodes. Edge-label vocabulary (the grammar every plan parses against — plans MUST use these, not invent synonyms): `unconditional`, `on-green`/`on-yellow`/`on-red`, `on-pass`/`on-fail`, `on-finding`/`on-no-finding`, `on-coder-complete`, `on-intro-wave-complete`/`on-intro-audit-complete`, `on-research-complete`, `on-rebase-clean`, `on-amend`, `on-no-drift`/`on-mechanical-drift`/`on-substantive-drift`, `on-dedup-clear`/`on-dedup-block`, `on-grade-cap`, `on-budget-exceeded`, `on-hard-stop`. Routing: `on-red`/`on-substantive-drift`→HARD-STOP, `on-mechanical-drift`→CHAIN-REPAIR, `on-grade-cap` caps grade without failing the sprint.

Walk: `ready_set` = nodes whose `in_predicates` hold; group by `parallel_with` cliques; a HARD-STOP batch fires and EXITs; agent batches dispatch IN ONE MESSAGE; await; evaluate out-edges; recompute (`shctx plan extract`/`graph next`/`graph mark`). At a `WAVE-GATE` in spawn mode, root releases the next wave via `TaskUpdate(status: completed)` on the `wave-{N}-gate-{sprint_slug}` marker; wave-(N+1) tasks carry `addBlockedBy`, unclaimable until release. **The registry is authoritative** (§Wave gate): the release is recorded in the registry (`shctx graph mark <wave-gate-node> --state=done`); the `TaskUpdate`/`addBlockedBy` pair is a best-effort MIRROR for teammate-visible claiming. A `Task*` call that errors or is unavailable NEVER stalls the wave — root advances on the registry gate and logs the downgrade. Wave progression MUST NOT depend on the harness task list. **Boundary-merge ledger (#242) — mechanical, never eyeballed:** root records each accepted `WAVE-COMPLETE` with `shepherd run wave accept <run> <lane> --commit <sha>`, records the lane's merge with `shepherd run wave merged <run> <lane>`, and MUST hold `shepherd run wave pending <run>` EMPTY (exit 0) before declaring any wave gate green — a non-empty pending set (exit 6: accepted-but-unmerged lanes remain) is a mechanical stop. **Pattern B**: `WAVE-N-AUDIT.parallel_with = [WAVE-(N+1)-IMPL]`, `WORKER-IO.parallel_with = [WAVE-1-IMPL]` — firing a `parallel_with` clique sequentially walks the graph wrong.

`completeness` auditor `STAGE-GRAPH-VIOLATION` (grade-caps C+): off-graph dispatch; sequential Pattern B; branch point missing `on-hard-stop`; `CLOSE-SWARM` without grade-cap edge; `WORKER-IO` not parallel-with `WAVE-1-IMPL`; `CHAIN-REPAIR` without amend-and-loop edge; HOTFIX loop past 3 without operator surface; `WAVE-IMPL` with no preceding `DEDUP-GATE`; dev.0 plan with no `CANONICAL-TYPES-REFRESH`; teammate lane merged without `LANE-INTEGRATE`.

## Lane law

Waves × steps is the **plan** (engineer authority, no primitive). A **lane** = a vertical slice across waves, one teammate-conductor, spawn-time only — never in the plan, never nested in a wave. **Count LANES, not teammate-instances** — never "lanes per wave." Root MAY refresh an idle lane's teammate at a wave boundary (lane durable, instance recyclable).

Decomposition floors (binding): per-step ~80–100 LOC, ≤5 files, 2–5 min; wave LOC floor S ~100 / M ~400 / L ~700 / XL 1500+; steps file-disjoint across a wave. Lane projection (spawn only): fat vertical slices, L 3–5, XL 4–6 **total** (never per-wave), file-disjoint, one conductor per lane. Under-decomposition or an under-sized projection → `RECONSIDER` to `@engineer`.

One primitive per axis, never inverted — the fan-out axis is **SUBSTRATE-CONDITIONAL, never DRIVER-CONDITIONAL** (the tier reading we shipped and #263 corrects) **and never unconditional** (mandating a compiled Workflow regardless of substrate over-corrects past the same platform fact) (`skills/harness/SKILL.md §Workflow tool`, #263, CC 2.1.212): lanes = **Agent Teams**; one step = one **subagent**; a wave's gate-free step fan-out = a compiled **Dynamic Workflow** on a LIVE **Agent-Teams teammate** substrate — root, a teammate-`@conductor`, or a self-contained `@engineer` running as a genuine native teammate-spawn. `Workflow` ships in the `tools:` frontmatter of `@conductor` and `@engineer` (#233) and the grant is LIVE on that substrate. The platform message `"Workflow is not available inside subagents"` (#220, CC 2.1.212) is TRUE and STAYS TRUE — it is a fact about an **Agent-tool subagent** substrate; the plugin's error was generalizing it to "any spawned role," which silently folded the teammate branch into the subagent branch, and #263 undoes only that generalization, not the fact itself. On an Agent-tool subagent substrate — `Agent(...)` dispatch, INCLUDING a "teammate" spawned when the Agent-Teams substrate was absent at spawn and is silently just a subagent — `Workflow` IS genuinely denied, and hand-rolled in-context `Agent()` fan-out is CORRECT there, and the ONLY option; not a downgrade to apologize for. CRITICAL NUANCE that survives the correction untouched: a team lead hand-driving its OWN lane fan-out is CORRECT and never flaggable — who drives the fan-out never changed on either substrate. What changed is only which vehicle that lead drives: a compiled Dynamic Workflow on a live teammate substrate, a hand-rolled batch of `Agent()` calls on a subagent substrate (`skills/shepherd/references/wave-routine.md §Per-wave compile`). In-context `Agent()` fan-out is the DOWNGRADE path ONLY on a live teammate substrate — legitimate there only after a `WORKFLOW-VEHICLE-PROBE` (`skills/shepherd/references/wave-routine.md`) finds `Workflow` genuinely absent from the visible tool list, and recorded with a `fanout_downgrade_reason`; a SILENT downgrade on a teammate substrate is a wave-review finding (`FANOUT-VEHICLE-DOWNGRADE`), never a certified-correct outcome. On a subagent substrate the identical `Agent()` fan-out needs neither probe nor downgrade reason — it is the substrate's only primitive, never a fallback from one. Every passage below that authorizes a teammate-substrate lead to compile a Workflow is bound by `skills/shepherd/SKILL.md §Fan-out counterweight` (#256): file-disjointness authorizes concurrent WRITES, not concurrent BUILDS — fan out fixes, verify once centrally; the `[coder].max_parallel_lanes` cap and the platform's ~16 concurrent-agent cap both still bind inside a Workflow. Two constructions are hook-refused:

> Halt: `PRIMITIVE-INVERSION — workflow-spawns-teammates`. Refuse the workflow-spawn. (Root tier only.)

> Halt: `PRIMITIVE-INVERSION — handrolled-fanout` (#263). A gate-free step fan-out compiles to a Dynamic Workflow on a LIVE Agent-Teams teammate substrate — root, teammate-conductor, or self-contained engineer running as a genuine teammate; hand-rolling that fan-out in-context via individual `Agent()` calls IS this violation ON THAT SUBSTRATE, unless a `WORKFLOW-VEHICLE-PROBE` found `Workflow` genuinely absent from the visible tool list and the dispatcher recorded a `fanout_downgrade_reason` — that recorded downgrade is not this violation, it is the required fallback. On an Agent-tool subagent substrate the identical hand-rolled `Agent()` fan-out is NOT this violation at all — it is correct, and the only option the substrate offers, no probe and no downgrade reason required. A team lead hand-driving its OWN lane fan-out is still CORRECT and never flaggable, on either substrate; only the vehicle it drives changes with the substrate under it.

A session per step crosses axes — `PRIMITIVE-INVERSION`. A step stood up as a teammate is `DISPATCH-TEAMMATE-TYPE-MISMATCH` (`skills/shepherd/SKILL.md §Dispatch law`).

**Lane-task ownership** (spawn, shared team task list): every teammate `TaskCreate` title MUST be prefixed `"{lane_id}: "`, then `TaskUpdate(owner: <teammate-name>)`. Claim/complete ONLY tasks whose prefix matches your `lane_id`; root-owned terminal tasks carry NO prefix. Violation → `TASK-LANE-MISMATCH`: re-title, set owner, release the sibling.

## Combo waves

A combo wave dispatches mixed read-only lanes as ONE parallel fan-out — a compiled Dynamic Workflow (`skills/harness/SKILL.md §Workflow tool`) on a LIVE Agent-Teams teammate substrate, one vehicle regardless of WHICH teammate dispatches it: root, or a teammate (e.g. the self-contained engineer's own discovery wave, §INTRO below) — `Workflow` ships in `@conductor`'s and `@engineer`'s `tools:` frontmatter and the grant is LIVE on that substrate, so the split-by-dispatcher reading collapses; the axis was never the dispatcher's tier, it is the substrate under it (#263). On an Agent-tool subagent substrate, in-context `Agent()` dispatch is simply correct — no probe, no downgrade reason; on a live teammate substrate it is the DOWNGRADE path only, taken on a confirmed `WORKFLOW-VEHICLE-PROBE` absence and recorded with a `fanout_downgrade_reason` (`skills/shepherd/references/wave-routine.md`); a teammate newly compiling a combo-wave Workflow is bound by `skills/shepherd/SKILL.md §Fan-out counterweight` (#256). Variants:

| | INTRO-COMBO-WAVE | DISCOVERY-COMBO-WAVE |
|---|---|---|
| Phase | INTRODUCTION (before MESH) | BODY (during execution) |
| Purpose | prior-state ingestion; feeds Phase-0 mesh | audit + research; feeds next wave |
| Workers | No | Yes (Z = 0–2) |
| Feeds | `[DISCOVERY-CONTEXT]` + `[INTRO-AUDIT-CONTEXT]` | `BODY-AGGREGATE` → next wave / PLAN-GATE |
| Trigger | always-on under `/shepherd:spawn` (incl. XS) | engineer declares in the plan |

INTRO fires a conductor-inline Lane 0 (`patch-branch-advancement-check`, mandatory P0 — ff-merge any stale patch-branch gap **before** the batch), then `@discovery`×N + intro-mode `@auditor`×M (`regression` re-runs prior `[ACCEPTANCE]` at HEAD; `carry-forward-disposition` verifies ledger truth; both **no grade**). Always-on under `/shepherd:spawn` — `[stage_graph.intro_wave].disable_for_tshirt = ["XS"]` is solo-only; each `--scope patch`/`--auto`/`--parallel` sibling certifies its OWN context fresh. Skipping it under spawn = skipping PLAN-GATE. Scaling (auditors/discoveries/workers): XS 1/1/0, S 1–2/1–2/0–1, M 2–3/2–3/0–1, L 3–4/3–4/1–2, XL 4–5/4–5/2; total lanes ≤ `[coder].max_parallel_lanes` (default 8), else `DISPATCH-OVERFLOW`. Each auditor lane = a UNIQUE concern, each discovery lane a NON-OVERLAPPING read-only domain; workers never synthesize. `BODY-AGGREGATE` is conductor-inline; a CRITICAL/HIGH with `HALT-FOR-REVIEW`/`HOTFIX-REQUIRED` blocks the next wave.

## INTRO

INTRODUCTION is ONE phase: INTRO-COMBO-WAVE → MESH (`@engineer`, Opus, once per sprint) → PLAN-GATE → operator approval. Plan body is mode-agnostic (waves × steps); modes differ in where the read-only waves run.

- **Classic** (root-tier subagent, fallback only): root runs INTRO-COMBO-WAVE before and a distinct `@critic` after; the engineer consumes context, dispatches nothing.
- **Self-contained** (named teammate — the DEFAULT under `/shepherd:spawn`): the engineer is a team lead. Root spawns `@engineer` via native teammate-spawn with `[INVOCATION-CONTEXT].mode: self-contained` + `dispatcher: root-shepherd`, then dispatches NO discovery or orientation wave of its own — the intro wave belongs to the engineer's sub-flock; a root-run discovery/intro wave alongside a self-contained engineer is `ROOT-INTRO-USURPED` (duplicate context spend + drift risk). The engineer's fixed workflow: (1) dispatch his discovery wave — MINIMUM 5 subagents: 2 `@discovery` + 3 intro-`@auditor`, scaled upward at the engineer's sole discretion; (2) generate the draft plan; (3) dispatch adversarial `@critic` review; (4) update the plan; (5) repeat 3–4 until GREEN; (6) produce the ONE finalized plan + hash-tied critic-proof; (7) alert root via `SendMessage`; (8) rest. Sub-flock is **read-only** (`@discovery`, intro-`@auditor`, `@critic` ONLY — no code, no `@coder`/`@worker`/`@engineer`); `@discovery` lanes take external sources (documentation, web research, release notes) while intro-`@auditor` lanes walk the codebase; root runs neither wave. It tags EVERY sub-flock dispatch `[INVOCATION-CONTEXT].dispatcher: engineer-self-contained` — the marker `dispatch_guard.sh` requires to pass a teammate→`@critic` dispatch (Check 4) and to scope `ENGINEER-SUBFLOCK-VIOLATION` (Check 4c) to marked dispatches outside the trio. Acceptance is THIN: `shctx seed verify` + `shctx plan verify --plan <p>` (re-hashes live bytes; a stale/`edited=false` proof FAILS → `CRITIC-PROOF-MISSING`/`PLAN-UNEDITED`/`CRITIC-PROOF-STALE`/`PLAN-UNCRITIQUED`) + lane-count sanity, then `LANE-INTEGRATE`.

Self-contained activates ONLY with ALL THREE: `mode: self-contained` + `dispatcher: root-shepherd` + a genuine native teammate-spawn; ambiguity NEVER activates it (guards a bare-subagent engineer self-launching an un-spawned fan-out). A subagent dispatch carrying `mode: self-contained` → `ENGINEER-TOPOLOGY-MISMATCH`; a marked sub-flock dispatch outside the trio → `ENGINEER-SUBFLOCK-VIOLATION` (`skills/shepherd/references/flock.md §@engineer`).

## PLAN-GATE

`@critic` (single, sequential) gates every plan above XS, every money-path/schema change, every merge to main. GREEN → DEDUP-GATE; YELLOW → PLAN-REVISION once → pass-2 GREEN or ESCALATED; RED → HARD-STOP. Pass-2 flags classify `dispatcher-patch` (applied inline) vs `substantive` (escalate) with explicit reasoning — silent acceptance forbidden. The critic confirms every Loop-Until-Done node carries `max_iterations` (`PLAN-MISSING-LOOP-CAP`) and every deliverable a runnable acceptance predicate (§Gates, Seam 2).

## DEDUP-GATE

Conductor-inline, BEFORE the `WAVE-IMPL` batch, runs each lane's `[DO-NOT-DUPLICATE]` grep and BLOCKS dispatch on any whose hit count != expected. `shctx query dedup-check` pre-filters, but a registry miss does NOT skip the grep. On a block: emit a `DEDUP-GATE BLOCK` message (wire-to-existing / replace / extend / operator-justified divergence — default NO), amend the brief, re-run; the batch fires only on `on-dedup-clear`. At close the auditor re-runs every grep; a violation grade-caps at C+ (`DUPLICATION-DRIFT`). The field-shape leg (`SHAPE-DEDUP`) catches same-shape/different-name types via `shctx dups` (PreToolUse `dups_write_guard.sh`; `shctx dups scan --fail-on foundation-blocking` at CLOSE; persisted to `index_struct_shapes`). Detection, CLI, registry: `skills/context/SKILL.md §Dedup`.

## Wave review + REDO

Before emitting `WAVE-COMPLETE`, the conductor MUST hold `review_verdict: PASS` from an adversarial wave-review `@auditor` — a coder's self-gate-green claim is NOT the review. Pattern B timing. Checklist per diff: (1) satisfies the linked issue's INTENT, not just compiles; (2) no workspace-wide flag/feature for one call site; (3) no canonical helper re-created under a new name (behavioral dedup); (4) no passes-local-breaks-CI. `PASS` → `WAVE-COMPLETE`; `REDO` → each finding carries a `Suggested redo` block (exact author, scope, required change) the conductor pastes verbatim.

The **REDO loop** forces the ONE named author to redo the ONE named scope (never blanket-re-run a wave). The REDO brief = the original coder brief + a `[REDO]` block (`[PRIOR-DISPATCH]` verbatim finding + `[REDO-CONSTRAINT]`: fix only the named items, identical `[FILE-SCOPE]`, no adjacent refactor). Vehicle = §Hotfix ladder. Termination: ≤3 REDO iterations on the same scope; the third unresolved raises `REDO-CAP-EXCEEDED` → HARD-STOP.

Root NEVER repairs the source: a `REDO` at `LANE-INTEGRATE` (§CLOSE-FINALIZE) → a `REDO-DIRECTIVE` via `SendMessage` to the owning teammate-conductor. A `WAVE-COMPLETE` missing `review_verdict: PASS` + `reviewer` is a `DISPATCH-CONTRACT-VIOLATION` — root refuses the wave; solo, the close `completeness` auditor caps the grade for any wave missing PASS.

## Hotfix ladder

A hot-fix is unseeded remediation from a gate `on-fail` or audit `on-finding`. `H` = count of **file-disjoint clusters** (two findings in one file are `H=1`, cluster first). Vehicle by `H` (dynamic workflow before a teammate):

| `H` | Vehicle |
|---|---|
| `H = 1` | ONE single subagent — a dynamic-workflow `agent()` step (one `@coder`). NEVER a teammate. |
| `(1, 5]` | ONE batched dynamic workflow, dispatched by whichever lead owns the finding — root, OR the teammate-conductor for its own lane (conductor inline in solo) (#263). |
| `H ≥ 6` | a dedicated HOT-FIX lane: one teammate-conductor with its own Stage-Graph loop. |

The `(1, 5]` band is the **HOTFIX-BATCH** composite (Pattern-2 fan-out; node stays `HOTFIX-DYNAMIC`). Vehicle ≠ concurrency — the ≤3-concurrent-coders and 3-HOTFIX-iteration caps still bind. A teammate-conductor compiling its own HOTFIX-BATCH Workflow is bound by `skills/shepherd/SKILL.md §Fan-out counterweight` (#256) exactly as root is. A teammate for one fix is `WRONG-VEHICLE`; solo at `H ≥ 6`, recommend HARD-STOP. Clusters from structured gate output: run the gate with JSON `--keep-going`, cluster file-disjoint, dispatch ONE `@coder` per cluster, re-run ONCE. The conductor NEVER composes a hot-fix brief from scratch — it pastes the auditor's `Suggested hot-fix lane: [FILE-SCOPE] ... [ACCEPTANCE] ...` block (`skills/shepherd/references/flock.md §@auditor`) verbatim.

## Gates

Every `WAVE-GATE` runs the configured gates **sequentially** (`{gates.format}` → `{gates.check}` → `{gates.lint}`) — chain with `&&`, NEVER `&`. Cargo holds an exclusive `target/` lock; parallel invocations deadlock — backgrounding a gate is `CARGO-GATE-BACKGROUNDED`. Exception: distinct `CARGO_TARGET_DIR` invocations don't share the lock, CAN run in parallel. Prefer `--message-format=json --keep-going`, still sequential (Execution pattern).

**Disk discipline (#214).** A wave that fills the disk hard-freezes the session — even the tool harness cannot write its task files. Four rules, carried verbatim in every wave brief (`skills/shepherd/references/wave-routine.md §Hard-rule preamble`): (1) every cargo invocation is preceded by `${CLAUDE_PLUGIN_ROOT}/scripts/df-guard.sh --min=12` (coder and auditor alike); (2) the wave's coder and its review `@auditor` SHARE one lane `CARGO_TARGET_DIR` (warm cache, no duplicate tree); (3) that lane target dir is DELETED on the wave's final PASS to reclaim disk; (4) the root/workspace gate NEVER runs concurrently with a lane cargo build.

**Deterministic LOC (#216).** A wave's production-LOC budget is asserted by `${CLAUDE_PLUGIN_ROOT}/scripts/loc-count.py <base_ref>` — added-minus-removed `.rs` lines OUTSIDE brace-matched `#[cfg(test)]`/`#[cfg(all(test, …))]` spans, `tests/` dirs skipped — never counted in latent space. It is the wave-gate LOC oracle and the body-depth-floor check (§Lane law); the coder's ONE-LOC rule (`agents/coder.md`) is the same contract at authoring time.

**Wave-return signal (#213).** A wave compiled to a Dynamic Workflow reports completion by polling the run's `journal.jsonl` with `${CLAUDE_PLUGIN_ROOT}/scripts/journal-status.sh` (steps spawned / returned / PASS-REDO verdicts), NEVER by trusting the harness task registry (which has gone blind mid-run). The dispatcher records the `runId` + absolute journal path in the plan frontmatter at dispatch time so the handle survives `/compact`; the background until-loop watchdog on the journal is the canonical wave-return signal, task notifications best-effort.

**GATES-DISCOVERY** (conductor-inline, before any restore-gates wave): run every gate verbosely, parse the FULL latent-error inventory, brief the wave with ALL errors (`[ACCEPTANCE]` = "all gates pass after this lane lands," not the engineer's subset). **Does NOT apply to:** single-error gates (one compile error, fully diagnosed) — go ahead with the narrow fix; the doctrine targets cascades, not single bugs. Logic bugs discovered by tests that pass — those are not "gates" failures; treat as normal hot-fix dispatches. Auditor findings post-merge — those route through HOTFIX nodes per the Stage Graph, which is already its own broad-sweep mechanism.

**Workspace isolation gate.** When workspace topology is in scope, the acceptance gate MUST include per-member isolated builds, not only the unified build (which masks transitively-resolved features and hoisted deps). Per touched member, run the equivalent:

| Ecosystem | Workspace-unified | Per-member isolated |
|---|---|---|
| cargo | `cargo check --workspace --features full` | `cargo check -p <member> --features <composite> --frozen` |
| pnpm | `pnpm -r build` | `cd <member> && pnpm build --filter=. --no-deps` |
| npm workspaces | `npm run -ws build` | `cd <member> && npm run build --workspaces=false` |
| turborepo | `turbo build` | `turbo build --filter=<member> --no-cache` |
| go work | `go build ./...` from root | `cd <member> && go build ./...` (clean module cache) |
| bazel | `bazel build //...` | `bazel build //path/to:member` from a fresh server |

Declared per project in `[gates].extra`; the intro-mode regression auditor runs it (`skills/shepherd/references/flock.md §@auditor`).

**Outcome enforcement** binds the seeded outcome to four seams. An acceptance predicate is a runnable check with a known expected result (grep+count, LOC floor, probe); prose is not a predicate. **Falsifiability is mandatory (#10):** a predicate that cannot return false is not a gate — a branch hard-coded to succeed regardless of what ran (e.g. a stub that always `exit 0`s, a check whose assertion never executes) defeats Seam 3's re-verification mandate by construction, since "now-false" can never occur. Zero cases run is a failure, not a pass; author and reviewer alike MUST be able to point at the specific input that would flip the predicate to false before it is accepted as a gate. `@critic` (Seam 2) rejects a predicate shown to be unfalsifiable under `PLAN-MISSING-OUTCOME-VERIFICATION`, and a wave-review REDO applies the same check to any predicate a coder introduces mid-wave. **Seam 1 (SEED):** the planter writes each deliverable's outcome as a runnable predicate (`skills/shepherd/references/seed-template.md §Verification`). **Seam 2 (PLAN-GATE):** a plan with prose-only `[ACCEPTANCE]` or a dropped seeded predicate fails with `PLAN-MISSING-OUTCOME-VERIFICATION`. **Seam 3 (CLOSE):** before the completeness grade is synthesized, the auditor MUST re-run EVERY seeded acceptance predicate against current HEAD/live state and compare each to its promised truth. A predicate promised true that now returns false is an `OUTCOME-REGRESSION` — filed HIGH, capping the completeness grade (no A/A- while a seeded outcome is false, `skills/shepherd/references/grading-rubric.md`). **Seam 4 (SOAK, optional):** re-verify predicates post-close on wall-clock time, detection-only — `skills/motivation/SKILL.md §SOAK`.

If `[mcp]` tools are not visible at session open, surface it and request operator `/reload-plugins`; NEVER silently degrade to shell — degrade to CLI only after reload fails, with an annotation.

## CLOSE

CONCLUSION is ONE phase: CLOSE-SWARM (3–5 `@auditor`, concern-split, FULL sprint scope) → HOTFIX-CLOSE on any CRITICAL/HIGH → CLOSE-FINALIZE. Issue ledger: the Phase-0 mesh enumerates the FULL open-issue space (`gh issue list --state open --limit 500`), classifies into `[ledger.classify_into]` buckets, surfaces non-current-milestone CRITICAL/HIGH as drift risks. At close, `completeness` verifies the sweep ran, drift-risk items have a disposition, the carry-forward ledger is refreshed, and items crossing `[ledger.chronic_threshold_patches]` (default 2) patch boundaries get the `chronic` label via GH MCP. Any failure → `LEDGER-DISCIPLINE-VIOLATION`, grade caps at C+. A chronic item can NEVER silently roll to a fourth patch — land it or formally drop it.

## CLOSE-FINALIZE

Root executes these git operations directly and NEVER delegates them (root: dev.N→patch; `release.yml`: patch→main):

**RF-1. Patch-branch advancement check:** `git fetch origin {patch_branch} && git log origin/{patch_branch} --oneline | head -3` before rebase. Behind the prior sprint's HEAD → ff-merge the gap FIRST.

**RF-2. Close mode, then rebase-merge sprint → patch.** On `{sprint_branch}`, read the verdict (`shctx release --dry-run`). Assert the #242 ledger drained: `shepherd run wave pending {run}` MUST exit 0 (no accepted-but-unmerged lanes) before the rebase-merge — exit 6 is a mechanical stop. Then:
```bash
git checkout {patch_branch}
git pull --ff-only origin {patch_branch}
git merge --ff-only {sprint_branch}
git push origin {patch_branch}
```
Verify: `git log {patch_branch} --oneline | head -5`. Skip ONLY if `--scope > sprint` AND more sprints remain AND the next rebases from the same patch-branch HEAD.

**RF-3. DELETE dev branch** (non-negotiable):
```bash
git push origin --delete {sprint_branch}
git branch -d {sprint_branch}
git fetch --prune origin
```

**RF-4. Cut next sprint branch (mid-patch ONLY).** Mechanical gate — run it, don't eyeball. N = the dev.N just closed, K = `[branching].sprints_per_patch` (default 10):
```bash
N={N}
K="$(grep -E '^[[:space:]]*sprints_per_patch[[:space:]]*=' .claude/shepherd.toml 2>/dev/null | grep -oE '[0-9]+' | tail -1)"; K="${K:-10}"
if [ "$N" -lt "$((K - 1))" ]; then
  git checkout -b {next_sprint_branch} {patch_branch}
  git push -u origin {next_sprint_branch}
else
  echo "dev.last (N=$N, K=$K): NO next dev branch — open the release PR."
fi
```
dev.{last}: `release.yml` handles tag + release + next patch + dev.0 + orphan sweep + milestone roll. Never cut `dev.{sprints_per_patch}` — `release_trigger_guard` blocks it.

**RF-5. Cleanup stewardship.** Remove each closed lane's worktree individually (`git worktree remove .worktrees/{sprint_slug}-{lane_id}`); a blanket teardown while ANY teammate is live kills sibling sessions, so run the blanket `git worktree` sweep ONLY after `v_teammates_live` (in `<ns>/shepherd.db`) is zero — sibling-awareness rules in `skills/motivation/SKILL.md §Drive contract`. Release `shepherd.lock` if held. Prune orphan `agent-*` local branches.

**LANE-INTEGRATE** is root-exclusive — a teammate-conductor has NO integration authority. In-worktree `git add`/`git commit` are permitted; `git merge`/`rebase`/`push`/`cherry-pick` onto a shared branch are root-only — a teammate reaching for any → STOP, `SendMessage(to: lead, halt_code: TEAMMATE-GIT-WRITE, blocking: true)` (`teammate_git_guard.sh`). Root integrates diffs < 200 lines inline, larger via `@auditor` diff-review — never compiled or delegated. `CLOSE-FINALIZE INCOMPLETE` blocks PAUSE (`close_finalize_check.sh`).

## Phase-0 amendment

On a Phase-0 mesh `SEED DRIFT`, the conductor does NOT escalate first — it VERIFIES the contradiction against ground truth (MCP query, file read, git log), AMENDS the seed inline, CONTINUEs. The amendment IS provenance — never silent. Add a top-of-file section:

```markdown
## Phase 0 amendment ({date})

The engineer's Phase 0 mesh surfaced these drifts:

| Drift | Seed claimed | Mesh found | Resolution |
|---|---|---|---|
| ... | ... | ... | ... |

Lanes affected: {lane numbers + revised scope}.
```

Commit `seed: amend dev.{N} per Phase 0 mesh`, re-dispatch. Even a verified-correct amendment still escalates when: the amended scope shrinks the seeded T-shirt size; the amendment adds a new unseeded lane (scope creep — operator decides); or the drift implicates the sprint theme, a money path, secrets/credentials, or an architecture-changing decision.

## Dispatch patterns

Every Stage Graph traces to the six canonical patterns (defined in `skills/shepherd/references/flock.md §Dispatch`); a graph that can't be explained as a composition needs revision; else direct single-agent dispatch (XS/atomic leaf only).

**Composition grammar — legal nestings (outer ⊃ inner) ONLY:** Classify-And-Act ⊃ any (each `on-class-X` branch roots an inner graph); Fanout-And-Synthesize ⊃ Adversarial Verification; Generate-And-Filter ⊃ Fanout; Tournament ⊃ Fanout; Loop-Until-Done ⊃ Fanout; Loop-Until-Done ⊃ Adversarial Verification; Classify-And-Act ⊃ Tournament. **Forbidden:** Generate-And-Filter inside Tournament (competing selection — pick one); Loop-Until-Done inside a Fanout iteration body (needs multi-level `max_iterations`); Adversarial Verification as classifier in Classify-And-Act (verifiers don't route — use `@discovery`); Tournament with N = 2 (use Adversarial Verification with `@critic`).

Circuit breakers (graph-enforced): pattern declared in the seed (`PLAN-MISSING-PATTERN`); Fanout non-overlapping scope (`FANOUT-SCOPE-OVERLAP`) + all-or-nothing synthesis + cap `[coder].max_parallel_lanes` (`DISPATCH-OVERFLOW`); Generate-And-Filter rubric-before-dispatch (`CIRCULAR-RUBRIC`) + identical briefs; Tournament bracket declared in the seed (`TOURNAMENT-NO-BRACKET`) + match isolation (`TOURNAMENT-CONTAMINATION`) + N ≥ 4; Loop-Until-Done `max_iterations` mandatory (`PLAN-MISSING-LOOP-CAP`), structured `new_findings: true|false` (`LOOP-REPORT-INVALID`), cap-exceeded halts (`LOOP-CAP`), default ceiling 5 (> 5 needs engineer justification, > 10 needs critic sign-off). Wrong agent for a role → `DISPATCH-WRONG-ROLE`; nesting past three levels → `COMPOSITION-TOO-DEEP`. Pattern-6 loop composites `FOCUS-LOOP`/`CONVERGENCE-LOOP`/`WATCH-LOOP`: `skills/motivation/SKILL.md §Loop discipline`.

Rigor add-ons (L/XL): every `on-fail`/`on-all-fail` edge routes to a declared escalation level, not a bare HALT (L1 Fanout-unit fail → HOTFIX that unit; L2 judge tie → operator tiebreak; L3 all fail → structured HALT; L4 loop cap → `LOOP-CAP`); L/XL compositions add `Checkpoint` nodes (`shctx sprint record --checkpoint=N`, `## Checkpoint: <node-id>`) for `shctx doctor` resume.
