---
name: agent-auditor-reference
slug: agent-auditor-reference
description: "On-demand reference catalog for @auditor, loaded at startup via Skill. Holds the per-concern emphasis catalog, per-finding contract template, Bayesian weighting, grade rubric, and report examples."
metadata:
  triggers:
    - "agent-auditor-reference"
---

# @auditor — Reference catalog

This file holds the verbose reference material extracted from `agents/auditor.md`. The agent loads this via `Skill(skill="shepherd:agent-auditor-reference")` once per dispatch, so the long catalogs do not bloat every system-prompt turn.

Use this reference to answer: *what is my exact emphasis for the concern I was assigned?*, *what does a well-formed finding look like?*, *how do I weight finding classes by prior?*, *what does each grade letter mean in prose?*.

## Per-finding contract — full template (hypothesis-driven shape)

Every finding (regardless of severity) MUST carry the Hypothesis + Falsification + Confidence triple. Below is the canonical block; copy verbatim and fill each slot.

```markdown
### Finding A-3 (HIGH) — {title}

**Location:** {path}:{lines}
**Pattern:** {what's wrong, observed}

**Hypothesis:** {one-sentence prediction of the failure mode — future or conditional tense for forward-looking findings; declarative for current failures}

**Falsification attempt:**
- Ran: `{command, grep, query, or trace}`
- Result: {what came back}
- Inference: {whether result is consistent with hypothesis or disproves it}

**Confidence:** HIGH | MEDIUM | LOW
**Confidence rationale:** {one-line justification per the matrix in doctrines/auditor-hypothesis-driven.md}

**Why it matters:** {impact — money path, regression risk, deferred cost}

**Recommendation:** {what should happen}

**Suggested hot-fix lane:** [FILE-SCOPE] ...; [ACCEPTANCE] ...

**GH:** #NNN (filed) | n/a (LOW — surfaced inline only)
```

**Findings without the hypothesis + falsification + confidence triple ARE NOT findings.** They are conjecture. Drop them or surface under `## Open questions`.

**LOW-confidence findings are NOT findings.** Do not file them in the report's `## Findings` section. Surface them under `## Open questions` instead, so the engineer/conductor can investigate without the GH-triage cost. This matches `doctrines/auditor-hypothesis-driven.md` — LOW falls below the finding threshold; it's an open question dressed up as a finding otherwise.

### Confidence calibration matrix

| Level | Definition |
|---|---|
| HIGH | Hypothesis is structurally verifiable + falsification ran + falsification produced evidence consistent with hypothesis + no plausible alternative explanation |
| MEDIUM | Hypothesis is plausible + falsification ran but partial + alternative explanations possible |
| LOW | Hypothesis is suggestive + falsification didn't fully address it — belongs in `## Open questions`, not findings |

## Falsification disproved → `## Verifications`

When you formed a hypothesis but the falsification DISPROVED it (the grep returned 0, the test passed, the trace was clean), surface the disproof in `## Verifications (positive findings worth noting)`:

```markdown
## Verifications

- Hypothesized DriftCircuit::tick double-borrow at line 142;
  `cargo check ...` returned 0 hits → hypothesis disproved; not a finding.
- Hypothesized wrapper-must-earn violation on new `MoneyAmount` type;
  `rg "pub struct MoneyAmount" → 1 hit with invariant comment` → justified;
  not a finding.
```

This is the audit-trail equivalent: future readers see what failure modes the auditor considered and disproved. Zero GH overhead.

## Bayesian finding-class weighting (sprint-patterns integration)

Read `<ns>/sprint-patterns.md` at dispatch time (per `doctrines/adaptation-loop.md`). The registry records per-class real-vs-false rates from prior sprints. Use it to calibrate effort:

- **High-real-rate classes** (≥ 70% verified historically): falsify with lower bar; surface with HIGH confidence on weaker evidence.
- **Low-real-rate classes** (< 30% verified): demand strong falsification before filing HIGH; default to MEDIUM or `## Open questions`.

If the registry is empty (new project), use framework priors per `doctrines/auditor-hypothesis-driven.md` §Bayesian:

- WORKTREE-DRIFT: 90%
- BASE-DRIFT: 90%
- STAGE-GRAPH-VIOLATION: 80%
- DUPLICATION RISK: 75%
- wrapper-must-earn: 60%
- SUBTRACT violation: 70%
- chronic carry-forward: 70%

## Per-concern emphasis — full catalog

### `code-quality` (close mode)

Hypothesis-first: ask "what idiom violations would THIS sprint's change pattern produce?" Then grep specifically. A sprint introducing async code generates different idiom risks than a sprint refactoring error handling.

Procedure:
- Run language-skill detection greps (e.g., wrapper-grep from `doctrines/wrapper-must-earn.md`)
- Check naming conventions per `code-style:<language>.md`
- Search `TODO|FIXME|XXX|HACK` in lane-modified files — grade-cap if hits
- Verify the language-mastery skill's idiom set against the diff

### `data-flow` (close mode)

Hypothesis-first: ask "which money-path / business-critical path was MOST changed in this sprint?" Trace that one end-to-end first; trace others only after the most-changed one is clean.

Procedure:
- Trace business-critical paths end-to-end (input → side-effect → state)
- Check fail-closed semantics (default deny; gate-pass=true requires explicit reason)
- Verify diagnostic-key population on every gate-fail / early-return
- Confirm signal correctness (every observable derived from the right source)

### `dependency-topology` (close mode)

Hypothesis-first: ask "what new types or aliases were introduced this sprint?" Run wrapper-grep on those specifically — much faster than full-tree.

Procedure:
- Run wrapper-grep gate (per `doctrines/wrapper-must-earn.md`)
- Check build-manifest changes — adds vs removes; every add must justify itself
- Verify feature flag discipline (per language skill)
- Confirm package-boundary integrity (no leaked private types across crate / package lines)

### `datastore-state` (close mode)

Hypothesis-first: ask "what schema changes did this sprint introduce?" Advisor checks AFTER those changes are the high-signal surface.

Procedure:
- Run datastore-MCP advisor checks (`mcp__plugin_supabase_supabase__get_advisors` or equivalent)
- Verify migrations applied if seed claimed they would be
- Spot-check row counts on key tables for anomalies
- Verify RLS / row-level-security policies still gate access correctly
- Confirm indexes exist where the new query paths require them

### `completeness` (close mode)

Hypothesis-first: ask "what did the seed PROMISE that the plan delivered (or not)?" Real-work test is the highest-signal check; everything else is downstream.

Procedure (long-form — see body for cache-extension steps):
- Verify Phase 0 mesh ran AND included ledger sweep (`doctrines/issue-ledger-awareness.md`)
- Verify drift-risk items from Phase 0 had a disposition
- Verify carry-forward refresh ran (`doctrines/carry-forward-refresh.md`)
- Apply chronic label to items crossing `[ledger.chronic_threshold_patches]`
- Run SUBTRACT-DON'T-ADD verification (`doctrines/subtract-dont-add.md`)
- Verify real-work test passed: did the seed's deliverables actually ship? (Per `doctrines/sprint-as-patch.md`, "ship" means patch-grade ship — operator-visible improvement at sprint close.)
- **Engineer skill-load discipline.** Verify the plan opens with seed citation; verify the brainstorming + writing-plans skills were invoked.
- **`[CODE-STYLE]` block presence.** For every coder lane brief whose `[FILE-SCOPE]` includes source files, verify the conductor injected a `[CODE-STYLE]` block.
- **`[DB-CONTEXT]` block presence** when applicable.
- **`[DISCOVERY-CONTEXT]` / `[INTRO-AUDIT-CONTEXT]` consumption (v5.1.1+).** When an INTRO-COMBO-WAVE fired, verify the engineer's plan addressed the HIGH findings surfaced — silent absorption is a process violation, grade-cap C+.
- **Sprint pattern journal write.** Per `doctrines/adaptation-loop.md §II`, after all other verifications:
  1. Read CLOSE-SWARM reports from every concern to collect finding counts.
  2. Collect halt codes from the walk trace.
  3. Check carry-forward ledger for MUST-LAND items that did not land.
  4. Append one sprint entry to `{paths.ctx}/sprint-patterns.md`. If file absent, create it with the header block first.
  5. Note "sprint-pattern entry written" in the AUDITOR REPORT output.
- **Brief-order verification (v5.1.3+ — per `doctrines/brief-cache-discipline.md`).** Read the conductor's dispatch run-log entries for this sprint (typically under `.artifacts/runs/` or wherever the `agent_invocation_tagger.sh` hook writes). For each captured brief, verify the bracketed-section ordering matches the doctrine: the stable framing block (`[ROLE]` → `[SKILLS]` → `[DOCTRINES]` → `[PROTOCOL-REMINDERS]`) appears before the variable content block (`[FILE-SCOPE]` → `[CONTEXT-INVENTORY]` → `[DO-NOT-DUPLICATE]` → `[ACCEPTANCE]` → `[NON-GOALS]` → `[WORKTREE]` → `[BASE-COMMIT-EXPECTED]`). File LOW per dispatch on violation; aggregate as MEDIUM if > 30% of captured dispatches violate.
- **Cache telemetry table (v5.1.3+ — per `doctrines/cache-telemetry.md`).** Run `shctx query cache-usage --sprint={sprint_branch} --md` and embed the table verbatim under `## Cache telemetry` in the report. If the `v_cache_usage` view is absent (telemetry not yet collected), write "telemetry view absent — establishing baseline" and skip. Threshold guidance: aggregate hit-rate < 40% across the sprint is a MEDIUM finding flag for investigation; do NOT grade-cap on this alone in the first three sprints (exploratory baseline period per `doctrines/cache-telemetry.md`).

### `regression` (intro mode — v5.1.1)

Hypothesis-first: ask "what acceptance from the PRIOR sprint is most likely to have drifted at HEAD?" Run those acceptances first.

Procedure:
1. Read the prior sprint's plan (`{paths.plans}/<prior-sprint>.plan.md`) and close report (`{paths.reports}/*-{prior-sprint}-close.md`).
2. For every coder lane in the prior plan, extract the `[ACCEPTANCE]` block.
3. Re-run each runnable acceptance grep / structural assertion at the current HEAD.
4. File findings on mismatches (HIGH for 0-hit-where-N-expected, MEDIUM for off-by-one, LOW for structural-only drift).

No grade emitted. Findings list only.

### `carry-forward-disposition` (intro mode — v5.1.1)

Hypothesis-first: ask "which carry-forward entries are most likely to be stale or mislabeled?" Recent entries with target sprint = current sprint are highest priority.

Procedure:
1. Read carry-forward ledger (per `[ledger].carry_forward_file`).
2. For each entry, verify:
   - Referenced GH issue still open?
   - Entry's target sprint matches current sprint, future, or past (stale)?
   - Entry has the right label per `[ledger].non_issue_labels` / `[ledger.chronic_threshold_patches]`?
3. File findings on drift.

No grade emitted. Findings list only.

## Grade rubric — full prose (close mode)

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

**Sprint-as-patch calibration (v5.1.1):** per `doctrines/sprint-as-patch.md`, each sprint is patch-equivalent in scope. Grade anchors to patch-grade output, not sprint-grade input. A sprint that "made reasonable incremental progress on a patch" grades C+ if the seed promised patch-delivery and patch-delivery did not happen.

### Column meanings (for body-side reference)

- **Grade letter** — the discrete bucket the sprint lands in. No fractional grades; pick the lowest letter the sprint qualifies for.
- **Meaning** — the test the sprint must pass to qualify for that letter. Failing any disqualifying condition (real-work test fail, SUBTRACT violation, drift-risk silence) caps at C+ regardless of other strengths.

## Report-section examples

### Findings summary table — populated example

```markdown
## Findings summary
| Severity | Count | Filed as GH issue? |
|---|---|---|
| CRITICAL | 0 | n/a |
| HIGH     | 2 | yes — #142, #143 |
| MEDIUM   | 3 | yes — #144, #145, #146 |
| LOW      | 1 | no (inline only) |
```

### Pattern delta — populated example (completeness concern only)

```markdown
## Pattern delta
| Concern | This sprint | Prior sprint | 3-sprint trend |
|---|---|---|---|
| code-quality | C=0 H=0 M=1 | C=0 H=1 M=2 | ↓ |
| data-flow | C=0 H=1 M=0 | C=0 H=0 M=1 | ↑ |
| dependency-topology | C=0 H=0 M=0 | C=0 H=0 M=1 | → |
| datastore-state | C=0 H=0 M=1 | C=0 H=0 M=0 | ↑ |
| completeness | C=0 H=1 M=1 | C=0 H=2 M=1 | ↓ |

Systemic risks (3+ HIGH/CRITICAL in same concern across 3+ sprints): none
Sprint-pattern entry written: yes
```

### Cache telemetry table — populated example (close mode, v5.1.3+)

```markdown
## Cache telemetry
| sprint | role | dispatches | avg_hit_rate | total_input | total_cache_read | total_cache_creation |
|---|---|---|---|---|---|---|
| v5.1.3-dev.1 | coder    | 5 | 0.62 | 12300 | 7600 | 4700 |
| v5.1.3-dev.1 | auditor  | 4 | 0.71 | 18400 | 13100 | 5300 |
| v5.1.3-dev.1 | critic   | 1 | 0.45 |  3200 |  1440 | 1760 |
| v5.1.3-dev.1 | engineer | 1 | 0.30 |  4100 |  1230 | 2870 |

Aggregate hit-rate: 0.58 — above the 0.40 MEDIUM-flag threshold; no finding filed.
```

If the view is absent: write `telemetry view absent — establishing baseline` and move on.

## See also

- `doctrines/auditor-hypothesis-driven.md` — the source discipline
- `doctrines/auditor-readonly.md` — read-only contract
- `doctrines/agent-excellence.md` — strive-higher framing
- `doctrines/brief-cache-discipline.md` — brief ordering rule (forward reference; landed in v5.1.3 Lane B)
- `doctrines/cache-telemetry.md` — telemetry capture + thresholds (forward reference; landed in v5.1.3 Lane C)
- `doctrines/adaptation-loop.md` — sprint-patterns registry
- `doctrines/sprint-as-patch.md` — patch-grade calibration
- `superpowers:systematic-debugging` — skill loaded at dispatch
