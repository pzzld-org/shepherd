# INTRO-COMBO-WAVE — sprint-start parallel orientation

> Origin: v5.1.1 (2026-05-15). Operator request: dispatch auditors AND
> discoveries in parallel at sprint open to absorb the prior-state-ingestion
> load and surface regressions BEFORE the engineer's MESH.

## What it is

A graph-node type that fires between `SEED-VERIFY` and `MESH`. Dispatches
N discoveries + M intro-mode auditors as ONE parallel fan-out. Both
streams produce reports the engineer consumes as Phase-0 mesh input
(`[DISCOVERY-CONTEXT]` + `[INTRO-AUDIT-CONTEXT]` in the engineer's brief).

**Dispatch mechanism (v6.0.x).** INTRO-COMBO-WAVE is a gate-free,
parallel-safe agent-fanout node, so it **compiles to a Dynamic Workflow** via
`shctx graph compile` — the primary execution path, identical to how
WAVE-IMPL / WAVE-AUDIT / CLOSE-SWARM compile (see
`doctrines/workflow-compile-down.md §V`, φ map). The compiler emits all N
discovery + M intro-auditor lanes as one bounded `Promise.all([...])` batch
(≤ `[stage_graph.intro_wave].parallel_max`) returning a mesh-input bundle in a
script variable; the conductor reads it and injects the
`[DISCOVERY-CONTEXT]` + `[INTRO-AUDIT-CONTEXT]` blocks into the MESH brief. The
wave satisfies the §IV faithfulness contract because every lane is independent
(scope-partitioned discoveries, concern-split intro auditors) and all spawns are
read-only by allowlist (§VII). Lane 0 (patch-branch-advancement check, below) is
a §VI seam: it runs at the conductor *before* the batch is launched, never inside
the workflow. Hand-rolled in-context Agent dispatch is the fallback only when the
workflow runtime is unavailable.

```
SEED-VERIFY ──on-green──► INTRO-COMBO-WAVE ──on-intro-wave-complete──► MESH ──► PLAN-GATE ──► ...
                              │  (compiled Promise.all batch; runtime-fallback: one Agent batch)
                              ├─ @discovery: prior-close-audit-summary
                              ├─ @discovery: canonical-types-freshness
                              ├─ @discovery: gh-state-inventory
                              ├─ @auditor (regression): verify prior plan's [ACCEPTANCE] still holds
                              └─ @auditor (carry-forward-disposition): verify carry-forward ledger truth
```

Discoveries answer **"what is the state right now"**. Intro auditors answer
**"did the prior sprint actually deliver what it promised and is anything
regressing now"**. Both feed MESH.

## Why combine

- **Parallel-safety.** Both are read-only. Maximum concurrent batch size
  without contention — the structural reason the wave compiles to a single
  `Promise.all` rather than a sequence (`workflow-compile-down.md §V`).
- **Information density.** Discoveries surface neutral facts; intro audits
  surface graded findings on the same surface. Engineer reads both as
  complementary inputs.
- **Conductor + engineer context preservation.** Without this wave, the
  engineer's Phase-0 mesh redoes every read and every regression check
  inline. With this wave, the engineer reads pre-digested syntheses.

## Default composition

Plan-time defaults (configurable per project via shepherd.toml):

| Lane | Role | Brief template |
|---|---|---|
| 0 | conductor-inline | `patch-branch-advancement-check` — **mandatory** (v5.1.9+, GH #60). Runs BEFORE dispatching the combo batch. Verifies patch branch contains all prior sprint commits. If stale: ff-merge the gap before continuing. See procedure below. |
| 1 | @discovery | `prior-close-audit-summary` — reads prior sprint's audit reports, lists outstanding findings |
| 2 | @discovery | `canonical-types-freshness` — reports last refresh date + drift since last canonical-types refresh |
| 3 | @discovery | `gh-state-inventory` — enumerates open issues with classification bucket counts |
| 4 | @auditor (mode: regression) | verifies prior plan's `[ACCEPTANCE]` blocks still hold at HEAD; files findings on regressions |
| 5 | @auditor (mode: carry-forward-disposition) | reads carry-forward ledger; verifies each entry's status (open / closed / drifted) |

### Lane 0 — patch-branch advancement check (conductor-inline, mandatory)

Fires before the parallel Agent batch. NOT an agent dispatch — the conductor
runs this inline in < 30 seconds:

```bash
git fetch origin {patch_branch}
PATCH_HEAD=$(git rev-parse origin/{patch_branch})
SPRINT_BASE=$(git merge-base HEAD origin/{patch_branch})
if [ "$PATCH_HEAD" != "$SPRINT_BASE" ]; then
  echo "PATCH-BRANCH-STALE: origin/{patch_branch} is at $PATCH_HEAD but sprint base is $SPRINT_BASE"
  echo "Prior sprint commits may not have been merged. FF-merge required."
fi
```

If stale: conductor ff-merges the gap (`git checkout {patch_branch} && git merge --ff-only <prior_sprint_branch> && git push origin {patch_branch} && git checkout {sprint_branch} && git rebase {patch_branch}`) BEFORE dispatching the combo wave. This prevents a downstream sprint incident (30 commits dangling 6 hours because dev.7 close didn't rebase).

**Severity: P0.** A stale patch branch means every sprint operates on
code that doesn't include the prior sprint's work. The cost compounds
across sprints — the longer it goes undetected, the harder the merge.

Plan may add or remove lanes; the engineer's plan emits the actual `agents:`
block in the Stage Graph YAML.

## Configuration

`shepherd.toml`:

```toml
[stage_graph.intro_wave]
enabled                  = true       # default true; false skips the wave entirely
default_discoveries      = ["prior-close-audit-summary", "canonical-types-freshness", "gh-state-inventory"]
default_intro_auditors   = ["regression", "carry-forward-disposition"]
disable_for_tshirt       = ["XS"]     # skip intro wave for tiny sprints (typical XS doesn't justify the dispatch overhead)
parallel_max             = 5          # cap on concurrent lanes in this wave
```

If `enabled = false`, the graph proceeds `SEED-VERIFY ──► MESH` directly,
matching the v5.x.x topology.

## Intro-auditor mode — `regression` and `carry-forward-disposition`

Intro-mode auditors are NOT close-time auditors. They run at sprint OPEN
(before MESH) and verify CONTINUITY rather than grade NEW work. Two canonical
intro concerns:

### `regression` mode

**Question:** does the prior sprint's claimed work still hold?

**Procedure:**
1. Read the prior sprint's plan (`{paths.plans}/<prior-sprint>.plan.md`)
   and close report (`{paths.reports}/*-{prior-sprint}-close.md`).
2. For every coder lane in the prior plan, find the `[ACCEPTANCE]` block.
3. Re-run each runnable grep / structural assertion in `[ACCEPTANCE]` at
   the current HEAD (which is one rebase-merge past the prior sprint's close).
4. File a finding for any acceptance that no longer holds.

**Severity calibration:**
- HIGH — runnable acceptance grep returns 0 hits where N expected
- MEDIUM — runnable acceptance grep returns N±1 where N expected
- LOW — structural assertion drift (file moved, name aliased)

**Report path:** `{paths.reports}/<date>-intro-audit-regression.md`
**Grade:** none — intro-mode auditors don't grade. They surface findings.

### `carry-forward-disposition` mode

**Question:** does the carry-forward ledger reflect reality?

**Procedure:**
1. Read carry-forward ledger (per `[ledger].carry_forward_file`, default
   `.artifacts/ctx/carry-forward.md` or `.shepherd/ctx/carry-forward.md`).
2. For each entry, verify:
   - Is the referenced GH issue still open?
   - Does the entry's "next-sprint" target match the current sprint, a
     future sprint, or a past sprint (= stale)?
   - Does the entry have the right label per `[ledger].non_issue_labels` /
     `chronic_threshold_patches`?
3. File findings on drift.

**Severity calibration:**
- HIGH — entry references closed GH issue but ledger says open
- HIGH — entry past-due (target sprint < current) without chronic label
- MEDIUM — entry's chronic label not applied per threshold rule
- LOW — entry's wording out of sync with GH issue title

**Report path:** `{paths.reports}/<date>-intro-audit-carry-forward.md`

### Distinction from close-time auditing

Close auditors grade the WORK that landed. Intro auditors grade the STATE
that's been carried forward. Different surfaces, different questions, but
both use auditor's discipline (hypothesis-driven, falsify-before-confirm,
evidence-citing) per `doctrines/auditor-hypothesis-driven.md`.

## How the engineer consumes the wave output

The conductor's MESH brief auto-injects two blocks:

```
[DISCOVERY-CONTEXT]
## Source: <path to prior-close-audit-summary report>
<Findings section quoted>
## Source: <path to canonical-types-freshness report>
<Findings section quoted>
## Source: <path to gh-state-inventory report>
<Findings section quoted>
[/DISCOVERY-CONTEXT]

[INTRO-AUDIT-CONTEXT]
## Source: <path to regression report>
<Findings list quoted>
## Source: <path to carry-forward-disposition report>
<Findings list quoted>
[/INTRO-AUDIT-CONTEXT]
```

The engineer treats both as authoritative for Phase-0 mesh rows they cover.
Engineer is NOT required to redo the reads — that defeats the purpose. The
engineer IS required to ACT on the findings (e.g., a HIGH regression finding
must be addressed as a Wave 1 hotfix lane in the plan).

## Certifiable current context under `/shepherd:spawn` (always-on)

Under `/shepherd:spawn`, the INTRO-COMBO-WAVE is the sprint's **certifiable
current context**: discovery gathers ground-truth facts; intro-auditors certify
regression/carry-forward/freshness. It is **always-on under spawn** regardless
of T-shirt size (the `disable_for_tshirt` XS exemption applies to solo
`/shepherd:start` only — see table below). The wave MUST fire **fresh per
sprint**:

- Each sprint in a `--scope patch`/`--auto` run certifies its OWN current context
  before proceeding to MESH. Never carry over the prior sprint's wave output as a
  substitute.
- Each `--parallel <N>` sibling sprint certifies its OWN current context
  independently — sibling sprints share a repo snapshot, not a wave result.
- The "certifiable" framing means the engineer's Phase-0 mesh acts on verified,
  not assumed, ground truth. Skipping the wave (under spawn) means MESH is
  operating on potentially stale prior-sprint context — treat it as a process
  violation equivalent to skipping PLAN-GATE.

Under `/shepherd:start` (solo), the existing T-shirt defaults apply unchanged.

**Self-contained engineer — the wave is relocated, not skipped (v6.2.6).** When
root spawns a **self-contained `@engineer` teammate** (`doctrines/engineer-self-contained-plan.md`),
the INTRO-COMBO-WAVE is **run by the engineer, in its own session**, instead of by
root — the engineer dispatches the `@discovery` + intro-`@auditor` batch as its
read-only sub-flock. The wave still fires (the always-on certification is
preserved and its reports still land); only the **dispatcher and the context
window** move. Root running its own wave AND spawning a self-contained engineer
would double the work — root skips its wave precisely because the engineer runs
it. This is the "same workflow, compartmentalized" migration: it takes the
majority of discovery + critic context out of root's window.

## When the wave fires vs. when it doesn't

| Sprint scope | `/shepherd:start` (solo) | `/shepherd:spawn` |
|---|---|---|
| XS | skip (low ROI on dispatch overhead) | **fire** (always-on; certifiable ground truth required) |
| S | optional — depends on `disable_for_tshirt` | **fire** |
| M | fire (3 discoveries + 2 auditors default) | **fire** |
| L | fire (3 discoveries + 2 auditors default; engineer plan may scale up) | **fire** |
| XL | fire with potential lane expansion | **fire** |

A sprint that catches HIGH/CRITICAL findings in the intro wave should NOT
proceed straight to MESH — the engineer's plan must address the findings as
Wave 1 hotfix lanes. The intro wave is the early-warning surface.

## Anti-patterns

1. **Engineer ignoring `[INTRO-AUDIT-CONTEXT]`.** Auto-injected blocks are
   not decorative. Engineer that doesn't address a HIGH intro finding in
   the plan → process violation, completeness auditor flags at close.
2. **Auditor in intro mode grading.** Intro audits surface findings; no
   grade. Auditor that emits A/B/C/D/F in intro mode → process violation,
   reject report.
3. **Discovery in intro mode proposing code.** Discovery is read-only +
   neutral. Surfacing facts is OK; "recommend rewriting X" is not.
4. **PRE-MESH-DISCOVERY duplicate to intro wave.** Pick one. If intro wave
   is enabled, the discoveries fire as part of it; don't also schedule a
   separate PRE-MESH-DISCOVERY node.

## See also

- `pipeline.md` §II stage taxonomy — INTRO-COMBO-WAVE node type
- `pipeline.md` §IV canonical sprint graph — wave placement
- `doctrines/workflow-compile-down.md §V` — INTRO-COMBO-WAVE is a φ-map compile target (gate-free fan-out → `Promise.all`)
- `doctrines/discovery-combo-wave.md` — body-phase equivalent (BODY phase; allows `@worker` lanes)
- `doctrines/discovery-readonly.md` — discovery contract
- `doctrines/auditor-hypothesis-driven.md` — auditor discipline applies to intro mode
- `doctrines/sprint-as-patch.md` — why intro-wave findings matter (patch-grade scope)
- `agents/auditor.md` — regression + carry-forward-disposition concerns documented
- `commands/spawn.md` — `/shepherd:spawn` always-on + fresh-per-sprint requirement
