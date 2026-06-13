# Reference — Sprint-Level Grading Rubric

> Project-agnostic principle: an audit swarm's per-concern grades aren't a
> sprint-level grade. The conductor synthesizes them into one. v5.0.4 makes
> the synthesis formula explicit so close reports cite a traceable
> calculation instead of a vibe-blend.
>
> Field origin: shepherd v5.0.3 conductor feedback (downstream Rust service),
> §9 — Wave-2 audits returned B+ / A- / B- / B+ across four concerns;
> the sprint-level grade was a manual blend hard to articulate precisely.

## The grades

Each per-concern auditor returns a grade from the agent prompt's rubric:

| Grade | Meaning |
|---|---|
| A    | Excellent — exceeds all gates; SUBTRACT win; zero CRITICAL/HIGH; real-work delivered fully |
| A-   | Strong — minor MEDIUM findings; SUBTRACT met; real-work delivered |
| B+   | Solid — some MEDIUM findings; SUBTRACT met; real-work delivered substantially |
| B    | Acceptable — MEDIUM findings actionable; SUBTRACT met; real-work delivered |
| B-   | Marginal — MEDIUM/HIGH findings; SUBTRACT borderline; real-work mostly delivered |
| C+   | Capped — failed real-work test OR SUBTRACT violation OR drift-risk silence — none of the above can grade higher |
| C    | Poor — multiple HIGH findings; substantive scope drift; SUBTRACT violation |
| D    | Failing — CRITICAL findings unaddressed; theme not delivered |
| F    | Sprint-fail — gates broken at HEAD; theme abandoned; operator escalation |

## Concern weights

The conductor blends per-concern grades with these default weights:

| Concern | Weight | Why |
|---|---|---|
| `completeness` | 0.35 | Did the seed deliver? — the most-load-bearing question |
| `code-quality` | 0.20 | In-code discipline — observable in the diff |
| `dependency-topology` | 0.20 | Build hygiene + wrapper discipline — propagates downstream |
| `data-flow` | 0.15 | Money-path correctness — high-impact when violated |
| `datastore-state` | 0.10 | Schema/RLS discipline — high-impact but narrowly visible |

> Projects with a different concern set redistribute these weights in
> `shepherd.toml` `[gates.audit_weights]`. The default sums to 1.00.

## Synthesis formula

The conductor computes the sprint-level grade in three steps:

1. **Map grades to numeric** (A=4.0, A-=3.7, B+=3.3, B=3.0, B-=2.7, C+=2.3,
   C=2.0, D=1.0, F=0.0).
2. **Weighted average** across concern grades using the weights above.
3. **Map back** to letter, applying caps:
   - Any concern returning **F** → sprint grade **F** (one CRITICAL gate
     break overrides the average).
   - Any concern returning **D** → sprint grade ≤ **C+** (cap, never
     better than capped).
   - Any concern flagging **SUBTRACT-VIOLATION** without operator
     pre-auth → sprint grade ≤ **C+** (cap).
   - Any **MISSING-`[CODE-STYLE]`** or **MISSING-`[DB-CONTEXT]`**
     auditor finding → first occurrence cap **C+**, repeat **F**.
   - Any unresolved **OUTCOME-REGRESSION** — a seeded acceptance
     predicate (`seed §6`) that was promised true and now returns
     false at close — caps the **completeness** concern grade: no
     A/A- while a seeded outcome is false. The cap is on completeness
     (weight 0.35), so it anchors the synthesized headline downward
     even when other concerns are strong. Per `doctrines/outcome-enforcement.md §Seam 3`,
     the close auditor re-runs the predicates before grading; a
     promised-true predicate that regressed is a HIGH finding.
4. **Otherwise**, round the numeric average to the nearest letter grade.

## Worked example (a downstream Rust service)

| Concern | Grade | Numeric | Weight | Contribution |
|---|---|---|---|---|
| code-quality | B+ | 3.3 | 0.20 | 0.66 |
| dependency-topology | A- | 3.7 | 0.20 | 0.74 |
| completeness | B- | 2.7 | 0.35 | 0.945 |
| ledger-integrity ¹ | B+ | 3.3 | 0.15 | 0.495 |
| (data-flow not run this sprint) | — | — | — | — |
| **Weighted total** | | | **0.90 (re-normalized)** | **3.16** |

¹ ledger-integrity here substitutes for `data-flow` per a downstream Rust
service's non-default concern split.

Re-normalized total numeric ≈ 3.51 → **B+/A-** range. Conductor picks
**B+** (rounded down) because completeness (highest weight) returned
B-, anchoring the headline. Cite this calculation in the close report's
**## Grade rationale** section.

## Conductor close-report template

```markdown
## Sprint-level grade: B+

Per-concern grades:
- completeness          B-  (weight 0.35)
- code-quality          B+  (weight 0.20)
- dependency-topology   A-  (weight 0.20)
- ledger-integrity      B+  (weight 0.15)
- data-flow             —   (concern not run)

Weighted numeric: 3.16 → B+
Caps applied: none (no F/D/SUBTRACT-VIOLATION/MISSING-block findings).
Rationale: completeness B- anchored the headline; dep-topology A- and
code-quality B+ supported a B+ sprint synthesis. No CRITICAL findings
unaddressed; carry-forward refresh complete.
```

## When the formula disagrees with judgment

If the conductor's read of the sprint disagrees with the formula by more
than half a letter grade, the close report must explicitly cite the
deviation reason:

```markdown
## Sprint-level grade: B (formula computed B+; downgraded due to <reason>)
```

Common deviation reasons:
- Mid-sprint operator amendment that wasn't fully absorbed.
- A passing audit whose finding-set looked light because the concern
  was scoped too narrowly.
- A real-work test that technically passed but produced unusable
  output (a "moral C").

Defaulting to the formula keeps grades calibrated across sprints; the
escape hatch keeps them honest.

## See also

- `agents/auditor.md` Grade rubric — per-concern letter definitions.
- `doctrines/subtract-dont-add.md` — SUBTRACT-VIOLATION cap logic.
- `doctrines/issue-ledger-awareness.md` — drift-risk silence cap logic.
