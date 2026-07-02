# INTRO-COMBO-WAVE — sprint-start parallel orientation

> Origin: v5.1.1 (2026-05-15). Operator request: dispatch auditors AND
> discoveries in parallel at sprint open to absorb the prior-state-ingestion
> load and surface regressions BEFORE the engineer's MESH.

## What it is

A graph-node type that fires between `SEED-VERIFY` and `MESH`. Dispatches N
discoveries + M intro-mode auditors as ONE parallel fan-out. Both streams
produce reports the engineer consumes as Phase-0 mesh input
(`[DISCOVERY-CONTEXT]` + `[INTRO-AUDIT-CONTEXT]`).

**Dispatch mechanism (v6.0.x).** INTRO-COMBO-WAVE is a gate-free,
parallel-safe agent-fanout node, so it **compiles to a Dynamic Workflow** via
`shctx graph compile` — the primary path, identical to WAVE-IMPL/WAVE-AUDIT/
CLOSE-SWARM (`doctrines/workflow-compile-down.md §V`, φ map). The compiler
emits all N discovery + M intro-auditor lanes as one bounded
`Promise.all([...])` batch (≤ `[stage_graph.intro_wave].parallel_max`)
returning a mesh-input bundle the conductor injects as
`[DISCOVERY-CONTEXT]`+`[INTRO-AUDIT-CONTEXT]` into the MESH brief. Every lane
is independent (scope-partitioned discoveries, concern-split intro auditors)
and read-only by allowlist, satisfying the §IV faithfulness contract. Lane 0
(patch-branch check, below) is a §VI seam: it runs at the conductor *before*
the batch launches, never inside the workflow. Hand-rolled in-context
dispatch is the fallback only when the workflow runtime is unavailable.

```
SEED-VERIFY ──on-green──► INTRO-COMBO-WAVE ──on-intro-wave-complete──► MESH ──► PLAN-GATE ──► ...
                              │  (compiled Promise.all batch; runtime-fallback: one Agent batch)
                              ├─ @discovery: prior-close-audit-summary
                              ├─ @discovery: canonical-types-freshness
                              ├─ @discovery: gh-state-inventory
                              ├─ @auditor (regression): verify prior plan's [ACCEPTANCE] still holds
                              └─ @auditor (carry-forward-disposition): verify carry-forward ledger truth
```

Discoveries answer "what is the state right now." Intro auditors answer "did
the prior sprint actually deliver what it promised and is anything
regressing now." Both feed MESH.

## Why combine

- **Parallel-safety.** Both are read-only, so the wave compiles to a single
  `Promise.all` rather than a sequence (`workflow-compile-down.md §V`).
- **Information density.** Discoveries surface neutral facts; intro audits
  grade findings on the same surface — complementary inputs.
- **Context preservation.** Without this wave, the engineer's Phase-0 mesh
  redoes every read and regression check inline; with it, the engineer reads pre-digested syntheses.

## Default composition

Plan-time defaults (configurable via shepherd.toml):

| Lane | Role | Brief template |
|---|---|---|
| 0 | conductor-inline | `patch-branch-advancement-check` — **mandatory** (v5.1.9+, GH #60). Runs BEFORE the combo batch; ff-merges any stale gap before continuing. |
| 1 | @discovery | `prior-close-audit-summary` — reads prior audit reports, lists outstanding findings |
| 2 | @discovery | `canonical-types-freshness` — last refresh date + drift since |
| 3 | @discovery | `gh-state-inventory` — enumerates open issues with classification bucket counts |
| 4 | @auditor (regression) | verifies prior plan's `[ACCEPTANCE]` blocks still hold at HEAD; files regression findings |
| 5 | @auditor (carry-forward-disposition) | reads carry-forward ledger; verifies each entry's status (open/closed/drifted) |

### Lane 0 — patch-branch advancement check (conductor-inline, mandatory)

Fires before the parallel batch, NOT an agent dispatch — conductor runs this
inline in under 30 seconds:

```bash
git fetch origin {patch_branch}
PATCH_HEAD=$(git rev-parse origin/{patch_branch})
SPRINT_BASE=$(git merge-base HEAD origin/{patch_branch})
if [ "$PATCH_HEAD" != "$SPRINT_BASE" ]; then
  echo "PATCH-BRANCH-STALE: origin/{patch_branch} is at $PATCH_HEAD but sprint base is $SPRINT_BASE"
fi
```

If stale: conductor ff-merges the gap (`git checkout {patch_branch} && git
merge --ff-only <prior_sprint_branch> && git push origin {patch_branch} &&
git checkout {sprint_branch} && git rebase {patch_branch}`) BEFORE
dispatching the combo wave — prevents a downstream incident (30 commits
dangling 6 hours because a close didn't rebase). **Severity: P0** — every
sprint otherwise operates on code missing the prior sprint's work, and the
cost compounds the longer it goes undetected.

Plan may add/remove lanes; the engineer's plan emits the actual `agents:` block in the Stage Graph YAML.

## Configuration

`shepherd.toml`:

```toml
[stage_graph.intro_wave]
enabled                  = true       # default true; false skips the wave entirely
default_discoveries      = ["prior-close-audit-summary", "canonical-types-freshness", "gh-state-inventory"]
default_intro_auditors   = ["regression", "carry-forward-disposition"]
disable_for_tshirt       = ["XS"]     # skip for tiny sprints (typical XS doesn't justify dispatch overhead)
parallel_max             = 5          # cap on concurrent lanes in this wave
```

If `enabled = false`, the graph proceeds `SEED-VERIFY ──► MESH` directly (v5.x.x topology).

## Intro-auditor mode — `regression` and `carry-forward-disposition`

Intro-mode auditors run at sprint OPEN (before MESH) and verify CONTINUITY
rather than grade new work.

### `regression` mode

**Question:** does the prior sprint's claimed work still hold? Read the
prior plan + close report, find each coder lane's `[ACCEPTANCE]` block,
re-run each runnable grep/assertion at current HEAD, file a finding for any
that no longer holds. **Severity:** HIGH — 0 hits where N expected. MEDIUM —
N±1. LOW — structural drift (file moved, name aliased). **Report:**
`{paths.reports}/<date>-intro-audit-regression.md`. **Grade:** none.

### `carry-forward-disposition` mode

**Question:** does the carry-forward ledger reflect reality? Read the ledger
(`[ledger].carry_forward_file`); for each entry verify the referenced GH
issue is still open, the "next-sprint" target isn't stale, and the label
matches `[ledger]` thresholds; file findings on drift. **Severity:** HIGH —
closed issue marked open, or past-due without chronic label. MEDIUM — chronic
label not applied per threshold. LOW — wording out of sync with GH title.
**Report:** `{paths.reports}/<date>-intro-audit-carry-forward.md`

### Distinction from close-time auditing

Close auditors grade the WORK that landed; intro auditors grade the STATE
carried forward. Different surfaces, same discipline (hypothesis-driven,
falsify-before-confirm, evidence-citing per `doctrines/auditor-hypothesis-driven.md`).

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

The engineer treats both as authoritative for the Phase-0 mesh rows they
cover — no re-reading — but is required to ACT on findings (a HIGH
regression finding must become a Wave 1 hotfix lane).

## Certifiable current context under `/shepherd:spawn` (always-on)

Under `/shepherd:spawn`, the INTRO-COMBO-WAVE is the sprint's **certifiable
current context**: discovery gathers ground-truth facts, intro-auditors
certify regression/carry-forward/freshness. It is **always-on under spawn**
regardless of T-shirt size (the `disable_for_tshirt` XS exemption applies to
solo `/shepherd:start` only). The wave MUST fire **fresh per sprint**: each
sprint in a `--scope patch`/`--auto` run, and each `--parallel <N>` sibling,
certifies its OWN current context independently — never carry over a prior
sprint's or sibling's wave output. Skipping the wave under spawn is a process
violation equivalent to skipping PLAN-GATE. Under `/shepherd:start` (solo),
the T-shirt defaults apply unchanged.

**Self-contained engineer — the wave is relocated, not skipped (v6.2.6).**
When root spawns a **self-contained `@engineer` teammate**
(`doctrines/engineer-self-contained-plan.md`), the INTRO-COMBO-WAVE is **run
by the engineer, in its own session** — it dispatches the
`@discovery`+intro-`@auditor` batch as its read-only sub-flock. The wave
still fires; only the dispatcher and context window move. Root skips its own
wave precisely because the engineer runs it — running both would double the work.

## When the wave fires vs. when it doesn't

| Sprint scope | `/shepherd:start` (solo) | `/shepherd:spawn` |
|---|---|---|
| XS | skip (low ROI on dispatch overhead) | **fire** (always-on) |
| S | optional — depends on `disable_for_tshirt` | **fire** |
| M | fire (3 discoveries + 2 auditors default) | **fire** |
| L | fire (default; engineer plan may scale up) | **fire** |
| XL | fire with potential lane expansion | **fire** |

A sprint catching HIGH/CRITICAL findings in the intro wave should NOT
proceed straight to MESH — the engineer's plan must address them as Wave 1 hotfix lanes.

## Anti-patterns

1. **Engineer ignoring `[INTRO-AUDIT-CONTEXT]`.** Not dispatching a HIGH
   intro finding as a plan lane → process violation, completeness auditor flags at close.
2. **Auditor in intro mode grading.** Intro audits surface findings, no
   grade — an A/B/C/D/F here is a process violation; reject the report.
3. **Discovery in intro mode proposing code.** Surfacing facts is OK;
   "recommend rewriting X" is not.
4. **PRE-MESH-DISCOVERY duplicate to intro wave.** Pick one — don't also schedule a separate PRE-MESH-DISCOVERY node.

## See also

- `pipeline.md` §II stage taxonomy — INTRO-COMBO-WAVE node type
- `pipeline.md` §IV canonical sprint graph — wave placement
- `doctrines/workflow-compile-down.md §V` — φ-map compile target (gate-free fan-out → `Promise.all`)
- `doctrines/discovery-combo-wave.md` — body-phase equivalent (allows `@worker` lanes)
- `doctrines/discovery-readonly.md` — discovery contract
- `doctrines/auditor-hypothesis-driven.md` — auditor discipline applies to intro mode
- `doctrines/sprint-as-patch.md` — why intro-wave findings matter (patch-grade scope)
- `agents/auditor.md` — regression + carry-forward-disposition concerns documented
- `commands/spawn.md` — `/shepherd:spawn` always-on + fresh-per-sprint requirement
