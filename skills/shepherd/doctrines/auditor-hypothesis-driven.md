# Auditors are hypothesis-driven — falsify before you confirm

> Origin: v5.1.1 (2026-05-15). Operator request: "update the auditor agent
> to be better; like /superpowers:systematic-debugging".

Auditors today (≤ v5.x) walked a concern checklist and filed findings. That
produces correct outputs on average but admits false alarms when the auditor
"sees a pattern" without verifying it. v5.1.1 reframes auditor methodology
around hypothesis-driven discipline — same systematic-debugging principle the
flock applies to bugs in code.

## The shift

**Old auditor mental model:**
> "Walk the checklist. For each item, look for the pattern. Found it? File
> the finding."

**v5.1.1 auditor mental model:**
> "Form a hypothesis about what would fail given the change pattern. Predict
> the failure. Attempt to falsify the prediction by running a check. If the
> check returns evidence consistent with the hypothesis, the finding lands.
> If the check disproves the hypothesis, drop the finding silently and move
> on. Never file a finding without a falsification attempt."

This raises the cost of each finding but eliminates the "I think this is bad"
class of low-quality reports that the operator has to manually triage.

## Per-finding evidence contract

Every finding (CRITICAL / HIGH / MEDIUM / LOW) in the audit report MUST
carry these three new fields, in addition to the existing location +
pattern + recommendation:

```markdown
### Finding A-3 (HIGH) — DriftCircuit::tick double-borrows state

**Location:** crates/circuits/src/drift.rs:142
**Pattern:** `&mut state` borrowed at line 142 then re-borrowed at line 168.

**Hypothesis:** under the Wave-2 extension proposed by Lane 2, line 168's
borrow scope will extend past line 142's use, producing a compile error.

**Falsification attempt:**
- Ran: `cargo check --workspace --features full 2>&1 | grep "drift.rs"`
- Result: 0 hits at HEAD (current state)
- Inference: hypothesis is FORWARD-LOOKING — the failure manifests only
  after Lane 2 lands. The pre-emptive finding stands because Lane 2's
  acceptance grep `rg "&mut state" crates/circuits/src/drift.rs → 2`
  would push the scope past the safety threshold.

**Confidence:** HIGH — the structural pattern is verifiable today; the
failure mode is a known Rust borrow-checker behavior.

**Why it matters:** Lane 2 will fail compile on first attempt. Auditor
files now so the engineer can adjust Lane 2's scope or split into two lanes.

**Recommendation:** refactor to extract `let snapshot = state.clone()` at
line 142 before Lane 2 extends.

**Suggested hot-fix lane:** [FILE-SCOPE] crates/circuits/src/drift.rs only;
[ACCEPTANCE] `rg -n 'state.borrow_mut' crates/circuits/src/drift.rs → 1`

**GH:** #NNN (filed)
```

### Required fields

- **Hypothesis** — one-sentence prediction of the failure mode. Written in
  the future or conditional tense (if it's a current failure, hypothesis IS
  the diagnosis).
- **Falsification attempt** — the SPECIFIC command, grep, query, or trace
  the auditor ran that would have DISPROVED the hypothesis. Includes the
  result and the inference drawn from it.
- **Confidence** — HIGH / MEDIUM / LOW. Calibrated per the matrix below.

### Confidence calibration

| Level | Definition |
|---|---|
| HIGH | Hypothesis is structurally verifiable + falsification ran + falsification produced evidence consistent with hypothesis + no plausible alternative explanation |
| MEDIUM | Hypothesis is plausible + falsification ran but partial + alternative explanations possible |
| LOW | Hypothesis is suggestive + falsification didn't fully address it + this is essentially an open question dressed as a finding |

LOW-confidence findings SHOULD NOT be filed as findings — they belong in the
report's `## Open questions` section or as `// AUDITOR NOTE` items the
engineer reviews without the GH-issue overhead.

## Hypothesis-first per concern

The auditor's per-concern playbook (in `agents/auditor.md` §Per-concern
emphasis) gains a hypothesis-first opening:

### `code-quality`

Before greping for `TODO|FIXME|XXX|HACK`, ask: **what idiom violations would
THIS sprint's change pattern produce?** Then grep specifically for those.
A sprint introducing async code generates different idiom risks than a
sprint refactoring error handling.

### `data-flow`

Before tracing every path, ask: **which money-path / business-critical path
was MOST changed in this sprint?** Trace that one end-to-end. Trace the others
only after the most-changed one is clean.

### `dependency-topology`

Before the wrapper-grep gate, ask: **what new types or aliases were
introduced this sprint?** Run wrapper-grep on those specifically — much
faster than full-tree.

### `datastore-state`

Before running advisor checks, ask: **what schema changes did this sprint
introduce?** Advisor checks AFTER those changes are the high-signal surface.

### `completeness`

Before listing carry-forwards, ask: **what did the seed PROMISE that the
plan delivered (or not)?** Real-work test is the highest-signal check;
everything else is downstream.

## Bayesian finding-class weighting (sprint-patterns integration)

The auditor reads `<ns>/sprint-patterns.md` at dispatch time to inform
finding-class priors. The pattern registry tracks (per finding class):
- How many times this class was filed across the last K sprints
- How many were verified as real by hot-fix landing
- How many were withdrawn / closed as won't-fix / closed as duplicate

The auditor weights effort accordingly:
- **High-real-rate classes** (≥ 70% verified) — spend deeper falsification
  effort; the prior says this class is signal-not-noise.
- **Low-real-rate classes** (< 30% verified) — surface only if falsification
  is overwhelming; otherwise mark as `## Open questions` instead of finding.

Example: `WORKTREE-DRIFT` historically real ~90% — auditor surfaces with
HIGH confidence on weak evidence. `wrapper-must-earn` historically ~60% real
— auditor demands strong falsification before filing HIGH.

If the registry is empty (new project), auditor uses framework priors:
- WORKTREE-DRIFT: 90%
- BASE-DRIFT: 90%
- STAGE-GRAPH-VIOLATION: 80%
- DUPLICATION RISK: 75%
- wrapper-must-earn: 60%
- SUBTRACT violation: 70%
- chronic carry-forward: 70%

## When the hypothesis disproves

If the falsification attempt DISPROVES the hypothesis (the grep returns 0,
the test passes, the trace is clean), the auditor does NOT file the finding.
Instead, the auditor adds a one-line entry to the report's `## Verifications`
section:

```markdown
## Verifications (positive findings worth noting)

- Hypothesized DriftCircuit::tick double-borrow at line 142;
  `cargo check ...` returned 0 hits → hypothesis disproved; not a finding.
```

This is the audit-trail equivalent: someone reading the report later can
see the auditor considered the failure mode and disproved it. No GH issue
opened; no operator triage cost.

## What about findings on existing code (pre-existing bugs)?

Same contract: hypothesis-driven, falsification-required. The hypothesis
just shifts from "Wave 2 will cause X" to "Wave N's change pattern revealed
that X exists today and has always existed".

For pre-existing findings:
- File with HIGH if the bug is reachable on the money path
- File with MEDIUM if the bug is reachable in tested code paths
- File with LOW (= don't file, surface in `## Open questions`) if the bug
  exists in untested or vestigial code

## Loading the skill

The auditor's system prompt opens with a Skill invocation:

```
Step 1 — Load systematic-debugging discipline.
Invoke: Skill(skill="superpowers:systematic-debugging")
```

This loads the falsify-don't-confirm methodology before the auditor reads
the brief. Every finding is filtered through that discipline.

## Audit report frontmatter additions

Existing audit reports get one new frontmatter field:

```yaml
---
title: Audit — {concern} — {sprint_branch}
date: <YYYY-MM-DD>
auditor: @auditor (agent-id-<id>)
sprint: {sprint_branch}
concern: {concern}
mode: close | regression | carry-forward-disposition   # NEW v5.1.1
methodology: hypothesis-driven                          # NEW v5.1.1
prior_class_priors: <inline summary of weights used>    # NEW v5.1.1 (optional)
---
```

`mode` distinguishes close-time audits from intro-wave audits (see
`doctrines/intro-combo-wave.md`).

## Anti-patterns this doctrine catches

1. **"I see a pattern; therefore it's a finding."** Pattern recognition
   without falsification = conjecture.
2. **"It's obviously wrong."** Obvious to whom? Falsify.
3. **"I'll file it as LOW just to be safe."** LOW findings clog the
   GH-issue surface and dilute the high-signal ones. Filter at the source.
4. **Auditor reads no historical signal.** Auditing without sprint-patterns
   priors = re-deriving every weight from scratch. The registry exists;
   read it.
5. **Auditor in intro mode grading.** Intro mode (regression /
   carry-forward-disposition) surfaces findings, NEVER grade. Grade in
   close mode only.

## See also

- `agents/auditor.md` — system prompt body (v5.1.1+)
- `doctrines/adaptation-loop.md` — sprint-patterns registry (the Bayesian prior source)
- `doctrines/intro-combo-wave.md` — regression + carry-forward-disposition concerns
- `superpowers:systematic-debugging` — the skill auditors load on dispatch
