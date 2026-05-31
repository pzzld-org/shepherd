---
title: adaptation-loop
description: |
  Self-improvement loop that accumulates sprint patterns across a patch cycle
  so the engineer, critic, and planter can make evidence-based adjustments to
  planning, review, and seeding over time. Requires no operator annotation —
  the completeness auditor writes entries; everything else reads them.
introduced: v5.0.6
---

# Adaptation Loop — Sprint Pattern Registry

## Why this exists

The shepherd flock has no cross-session memory by default. Each sprint starts from the seed and the prior handoff — which is one sprint old. Over a patch cycle, recurring finding types, persistent halt codes, and grade-cap patterns accumulate without a mechanism to surface them to planning.

The adaptation loop gives the system **sprint-level memory without requiring operator annotation**. The completeness auditor writes a compact pattern entry at sprint close; the engineer reads it at mesh time; the planter reads it at seed time; the conductor surfaces trends at PAUSE. No new infrastructure is required — just a markdown file at `{paths.ctx}/sprint-patterns.md`.

---

## I. The sprint pattern registry

**Location:** `{paths.ctx}/sprint-patterns.md`

Created on first write; append-only thereafter. Never hand-edit mid-sprint.

**File header (written once on creation):**

```markdown
# Sprint Pattern Registry — {project.name}

*Auto-maintained by the `completeness` auditor at each sprint close.*
*Read by: @engineer (Phase 0 mesh row 10), @planter (seed authorship), conductor (PAUSE trend surface).*
*Curator: add entries via the completeness auditor only — do not hand-edit.*

---
```

**Entry shape (one entry per sprint, appended at close):**

```markdown
## {sprint_branch} — {YYYY-MM-DD}

| Property | Value |
|---|---|
| Grade | {overall grade from CLOSE-SWARM, e.g. B+} |
| Sprint size | {XS/S/M/L/XL} |
| Lane count | {total coder lanes across all waves} |
| LOC delta | {+adds / -dels on subtract_paths} |

### Findings by concern
| Concern | CRITICAL | HIGH | MEDIUM |
|---|---|---|---|
| code-quality | N | N | N |
| data-flow | N | N | N |
| dependency-topology | N | N | N |
| datastore-state | N | N | N |
| completeness | N | N | N |

### Halt codes encountered
{comma-separated list of halt codes (BRIEF INVALID, BASE-DRIFT, DUPLICATION RISK, etc.) or "none"}

### Carry-forward items (unresolved from prior sprint)
{GH issue numbers that were MUST-LAND but did not land, or "none"}

### Adaptation notes
- {1–3 bullets: what went well, what triggered a grade-cap or hard-stop, what the planter/engineer should weight differently next sprint}
```

---

## II. Write protocol — completeness auditor at sprint close

The `completeness` auditor is responsible for appending a new entry at each sprint close. This is part of the `CLOSE-SWARM` phase, after all other verifications.

**Steps:**
1. Read the CLOSE-SWARM audit reports from every concern to collect finding counts.
2. Read the conductor's walk trace (if `[stage_graph].walk_trace_enabled = true`) or the coder CODER REPORTs for halt codes encountered.
3. Check the carry-forward ledger (`[ledger.carry_forward_file]`) for MUST-LAND items that did not land.
4. Write adaptation notes: what drove grade-caps (if any), what the planter should weight differently (if any), what went cleanly.
5. Append the entry to `{paths.ctx}/sprint-patterns.md`. If the file does not exist, create it with the file header first.

If the pattern file is inaccessible (path missing, permission error), note it in the audit report under "anomalies" and skip. Do NOT block CLOSE-FINALIZE for this.

**On first close** (file doesn't exist yet): create it with the file header, then append the entry. Surface to the conductor: "Sprint-patterns registry initialized — first adaptation cycle recorded."

---

## III. Read protocol — engineer at mesh time

**When:** Phase 0 mesh, after the standard mesh rows 1–9, as mesh row 10.

**How:**
```bash
# If shctx is available:
shctx query sprint-patterns --last=5 --md

# Fallback: read the file directly
cat {paths.ctx}/sprint-patterns.md | tail -200
```

**What to act on:**

| Pattern detected | Action |
|---|---|
| Same concern has **3+ HIGH/CRITICAL findings across 3+ sprints** | Classify as **systemic risk** in Phase 0 mesh summary. Add a dedicated coder lane or strengthened `[ACCEPTANCE]` criteria targeting that concern area. |
| Same GH issue appears as carry-forward in **3+ consecutive sprints** | Flag as **CHRONIC candidate** even if the ledger hasn't applied the label yet. Surface under "Drift-risk items not in this sprint's seed". |
| Same halt code (BASE-DRIFT, DUPLICATION RISK, etc.) in **2+ of last 3 sprints** | Flag to the conductor in the ENGINEER REPORT: "Recurring halt pattern — recommend conductor verify {halt code prevention step} before next dispatch." |
| A concern has been **CLEAN (0 CRITICAL/HIGH) for 5+ consecutive sprints** | Note in plan: reduced scrutiny weight for that concern; focus effort on active concern areas. |

**Mesh row format:**
```
| 10 | sprint-patterns | {paths.ctx}/sprint-patterns.md (last 5 entries) | Systemic risks: {list or none}. Recurring halts: {list or none}. Chronic candidates: {GH#s or none}. Clean streaks: {concern list or none}. |
```

---

## IV. Read protocol — planter at seed time

**When:** `/shepherd:plant`, reading context before writing any seed content.

**How:** read `{paths.ctx}/sprint-patterns.md` in full (or last 10 entries for a long-running project).

**What to act on:**

| Pattern detected | Seed action |
|---|---|
| Systemic risk concern (3+ HIGH/CRITICAL across 3+ sprints) | Include an explicit mitigation lane in the relevant sprint seed. Name the concern and the mitigation. |
| Chronic carry-forward (GH# unclosed across 3+ patches) | Include as MUST-LAND CRITICAL lane in the earliest available sprint slot. Do not defer a fourth time without operator signal. |
| Recurring grade-cap pattern (same reason across 3+ sprints) | Add an explicit non-goal or counter-measure in the seed's "Non-goals / guardrails" section. |
| Clean streak (concern 0 CRITICAL/HIGH for 5+ sprints) | Reduce seed emphasis on that area. Redirect planning depth toward weaker concerns. |

---

## V. Conductor trend surface at PAUSE

After `CLOSE-FINALIZE` and before `PAUSE`, the conductor checks the registry for any of these:

- Same concern has 3+ HIGH/CRITICAL findings in last 3 sprints
- Same halt code has occurred 3+ times in last 3 sprints
- Sprint grade has trended downward (e.g., A → B → C) for 3 consecutive sprints

If any trigger fires, surface a **TREND ALERT** to the operator before pausing:

```
[TREND] {concern/halt-code/grade-direction} has recurred for {N} consecutive sprints.
Recommendation: {1-sentence concrete suggestion}
```

Examples:
```
[TREND] data-flow concern has generated HIGH/CRITICAL findings for 3 consecutive sprints.
Recommendation: add a dedicated data-flow coder lane in the next seed to address the
recurring signal-correctness gap in the payment path.

[TREND] BASE-DRIFT halt code has fired 3 times in the last 3 sprints.
Recommendation: verify shctx worktree create-batch is called with --from $SPRINT_BRANCH
immediately before each WAVE-IMPL dispatch, not at session start.
```

Trend alerts are **informational** — they do not block PAUSE. The operator decides whether to act.

---

## V-bis. Node-level telemetry (dispatch-cascade integration, v5.0.9)

When the conductor uses `shctx plan extract` + `shctx graph mark` (per
`doctrines/dispatch-cascade.md`), the trace at `<ns>/graph/trace.jsonl`
gains a per-transition event log. The completeness auditor reads the
trace at CLOSE-SWARM and augments the sprint-pattern entry with
**node-level metrics**:

```markdown
### Node telemetry (this sprint)
| Node | Type | Duration | Exit edge | Halts |
|---|---|---|---|---|
| mesh | MESH | 4m12s | on-no-drift | — |
| wave-1-impl | WAVE-IMPL | 12m04s | on-coder-complete | 1× PAUSE-FOR-DEPENDENCY (retired v6.0.1; equivalent: await-edge dependency on target_path) |
| wave-1-gate | WAVE-GATE | 38s | on-fail → on-pass (re-run) | 1× HOTFIX |
```

This is the substrate for trend detection (`§V` trend alerts) at
sub-sprint granularity:

| Pattern detected | Action |
|---|---|
| Same node-type's avg duration trending up 50%+ across 3 sprints | Flag as "node-type bloat" — engineer reduces lane scope or decomposes |
| Specific node consistently exits via `on-fail` then `on-pass` | Auto-fixable failure pattern; suggest pre-emptive HOTFIX recipe in next plan |
| A cross-lane dependency expressed as a graph edge with await ordering fires on the same (source-lane, target-file) pair across 2+ sprints | Surface as a candidate for a dedicated Lane 0 in the next sprint |

If the trace is absent (legacy sprint or `shctx graph` not used), the
auditor falls back to sprint-level summary as before. Node telemetry is
additive, not mandatory.

---

## VI-bis. Feedback classification — project-specific vs framework-generic (v5.0.9)

> Field origin: shepherd v5.0.8 conductor feedback §10.

When the conductor saves a `feedback_*.md` memory entry mid-sprint (e.g., via
`shctx mem add`), classify it before writing:

| Classification | Criterion | Write location |
|---|---|---|
| Project-specific | Only applies to THIS project's stack, team, or codebase | `{paths.ctx}/feedback/<rule-name>.md` (project memory) |
| Framework-generic | Would benefit ANY shepherd project (e.g., cargo sequencing, file-scope caps) | `{paths.ctx}/feedback/<rule-name>.md` (project memory) AND note in close report: "Candidate for shepherd doctrine promotion" |

**Framework-generic feedback** is flagged in the close report so the operator
can promote it to the shepherd repo's doctrine library at their convenience.
The conductor does NOT push doctrine changes to the shepherd repo — it only
flags the candidate.

**Rule of thumb:** if the feedback starts "Every Rust/Python/Go shepherd
project will hit this…" — it's framework-generic.

---

## VI. What the adaptation loop does NOT do

- **Does not change dispatch rules.** The Stage Graph is still the contract; the adaptation loop informs its *content*, not its execution.
- **Does not override operator decisions.** Trend alerts are recommendations, not mandates.
- **Does not bloat the registry.** One entry per sprint; completeness auditor writes it at CLOSE-SWARM. No duplicates, no mid-sprint writes.
- **Does not require a running DB.** The markdown format works without `shctx`. DB-backed queries (`shctx query sprint-patterns`) are a fast-path for Phase 0 mesh.
- **Does not create new labels.** Chronic labeling still follows `doctrines/carry-forward-refresh.md`; the adaptation loop surfaces candidates, not labels.

---

## VII. Cross-doctrine references

- `doctrines/carry-forward-refresh.md` — chronic-label authority; adaptation loop surfaces candidates, carry-forward-refresh applies labels
- `doctrines/issue-ledger-awareness.md` — Phase 0 full-ledger sweep; adaptation loop complements it with historical pattern signal
- `doctrines/stage-graph.md` — graph is still the dispatch contract; adaptation loop informs what the engineer puts in the plan, not how the conductor walks it
- `doctrines/context-registry.md` — `shctx query sprint-patterns` is the fast-path; markdown file is the fallback
- `doctrines/subtract-dont-add.md` — SUBTRACT verification feeds into the adaptation entry's LOC delta field
