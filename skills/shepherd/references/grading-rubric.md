---
title: grading-rubric
description: Deterministic formula synthesizing per-concern auditor grades (A-F) into one sprint-level grade, replacing ad hoc blending. Use when a conductor computes or cites a sprint-level grade.
---

# Sprint-Level Grading Rubric

The sole owner of the sprint-level grade table and synthesis formula. Per-concern letter definitions: `agents/auditor.md` Grade rubric.

## The grades

| Grade | Meaning |
|---|---|
| A | Excellent — exceeds all gates; SUBTRACT win; zero CRITICAL/HIGH; real-work delivered fully |
| A- | Strong — minor MEDIUM findings; SUBTRACT met; real-work delivered |
| B+ | Solid — some MEDIUM findings; SUBTRACT met; real-work delivered substantially |
| B | Acceptable — MEDIUM findings actionable; SUBTRACT met; real-work delivered |
| B- | Marginal — MEDIUM/HIGH findings; SUBTRACT borderline; real-work mostly delivered |
| C+ | **Capped** — failed real-work test OR SUBTRACT violation OR drift-risk silence — none of the above can grade higher |
| C | Poor — multiple HIGH findings; substantive scope drift; SUBTRACT violation |
| D | Failing — CRITICAL findings unaddressed; theme not delivered |
| F | Sprint-fail — gates broken at HEAD; theme abandoned; operator escalation |

## Concern weights

Default weights (MUST sum to 1.00; override via `shepherd.toml [gates.audit_weights]`):

| Concern | Weight | Why |
|---|---|---|
| `completeness` | 0.35 | Did the seed deliver? — the most load-bearing question |
| `code-quality` | 0.20 | In-code discipline, observable in the diff |
| `dependency-topology` | 0.20 | Build hygiene + wrapper discipline, propagates downstream |
| `data-flow` | 0.15 | Money-path correctness, high-impact when violated |
| `datastore-state` | 0.10 | Schema/RLS discipline, high-impact but narrowly visible |

## Synthesis formula

The conductor computes the sprint-level grade in three steps:

1. **Map to numeric**: A=4.0, A-=3.7, B+=3.3, B=3.0, B-=2.7, C+=2.3, C=2.0, D=1.0, F=0.0.
2. **Weighted average** across concern grades, re-normalizing weights when a concern wasn't run.
3. **Map back to letter, applying caps** (each overrides the average):
   - Any concern = **F** → sprint grade **F** (one CRITICAL gate break overrides the average).
   - Any concern = **D** → sprint grade capped at **C+**.
   - Any concern flags **SUBTRACT-VIOLATION** without operator pre-auth (`skills/shepherd/SKILL.md §Principles`) → capped at **C+**.
   - Any **MISSING-`[CODE-STYLE]`** or **MISSING-`[DB-CONTEXT]`** finding → first occurrence caps **C+**, repeat occurrence → **F**.
   - Any unresolved **OUTCOME-REGRESSION** (a seeded acceptance predicate from seed §6 promised true, now false at close) caps the **completeness** concern specifically — **no A/A- while a seeded outcome is false**. This propagates through the 0.35 weight and anchors the synthesized headline down even when every other concern is strong. The close auditor re-runs every predicate before grading (`references/pipeline.md §Gates`); a regressed predicate is filed HIGH.
4. **Otherwise**, round the weighted numeric average to the nearest letter.

## Close-report template (required shape)

```markdown
## Sprint-level grade: <letter>

Per-concern grades:
- completeness          <grade>  (weight 0.35)
- code-quality          <grade>  (weight 0.20)
- dependency-topology   <grade>  (weight 0.20)
- data-flow             <grade>  (weight 0.15)
- datastore-state       <grade>  (weight 0.10)

Weighted numeric: <n> → <letter>
Caps applied: <none | list>

## Grade rationale
<one paragraph citing which concern anchored the headline and why>
```

When a concern isn't run, drop its row and re-normalize the remaining weights to sum to 1.00 before computing the weighted numeric.

## When the formula disagrees with judgment

If the conductor's read of the sprint disagrees with the formula by more than half a letter grade, the close report MUST cite the deviation:

```markdown
## Sprint-level grade: B (formula computed B+; downgraded due to <reason>)
```

Common reasons: a mid-sprint operator amendment not fully absorbed; an audit finding-set scoped too narrowly to be representative; a real-work test that technically passed but produced unusable output (a "moral C"). Defaulting to the formula keeps grades calibrated across sprints; the escape hatch keeps them honest.

## See also

- `agents/auditor.md` — per-concern letter definitions, Grade rubric section
- `skills/shepherd/SKILL.md §Principles` — SUBTRACT-VIOLATION trigger condition
- `references/pipeline.md §Gates` — OUTCOME-REGRESSION seam + predicate re-run
- `references/pipeline.md §CLOSE` — drift-risk silence / ledger discipline cap
