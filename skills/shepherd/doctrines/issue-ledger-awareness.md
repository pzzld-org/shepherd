# Issue-ledger awareness — combat tunnel vision

The default failure mode of a sprint conductor is tunnel vision: it sees the seed's deliverables and the current-milestone issue list, and ignores the rest of the open-issue ledger. Critical items not on the current milestone fester invisibly across patches.

This doctrine forces the engineer (Phase 0) and the auditor-completeness (close) to enumerate the FULL open-issue space, classify it, and surface drift risks.

## What "tunnel vision" looks like

Real-world example from the Axiom project, sprint v0.2.9-dev.2 open:

- Current milestone (v0.2.9): 88 issues
- Other milestones (v0.2.8 still open): 75 issues
- Unmilestoned issues: ~30
- Total open: 197

The conductor was running sprints that addressed 5–10 milestone-tagged items per sprint and ignoring the other 187. Some of those 187 carried CRITICAL severity for production correctness (paper-positions stuck since 2026-04-23, settlement chain dark, OOM at 18:35Z confirmed). They had NO milestone tag and no one was looking at them.

The fix was structural: every Phase 0 mesh now enumerates the full ledger and classifies into operator-defined buckets.

## Phase 0 mandate (engineer-time)

The engineer's Phase 0 mesh table includes a row that enumerates the full open-issue space:

```markdown
| N | Issues | Open-issue ledger sweep — `gh issue list --state open --limit 500 --json number,title,milestone,labels` | Engineer classifies every result into [ledger.classify_into] buckets and surfaces non-current-milestone CRITICAL/HIGH items as drift risks in the plan |
```

The classifications are operator-configured via `[ledger.classify_into]` in `shepherd.toml`. Default:

- **blocking-this-sprint** — already on the seed; included in `[CONTEXT-INVENTORY]` for affected lanes
- **labeled-non-issue** — carries a label from `[ledger.non_issue_labels]` (`wontfix`, `tracking-future`, `design-question`, `rfc`); explicitly tracked but not actioned
- **tracking-future** — milestoned to a future patch; verify the milestone is correct
- **drift-risk** — open, unmilestoned (or milestoned to a CLOSED milestone), CRITICAL/HIGH severity → surface to operator as a NON-SEEDED finding

The plan's Phase 0 section embeds the classification as a table:

```markdown
## Phase 0 — open-issue ledger ({total_open} issues)

| Bucket | Count | Examples (top 5 by priority) |
|---|---|---|
| blocking-this-sprint | 7 | #840, #841, #842, ... |
| labeled-non-issue | 24 | #553 (rfc), #129 (wontfix), ... |
| tracking-future | 92 | #29 → v0.3.0, ... |
| drift-risk | 4 | #674 (CRITICAL, no milestone — settlement chain), ... |
```

Drift-risk items are surfaced to the operator with one-line summaries. The sprint plan does not silently grow to absorb them — that's scope creep — but the operator decides whether to (a) milestone them out of drift status, (b) add them to the current sprint, or (c) accept the drift risk and move on.

## Auditor-completeness mandate (close-time)

The close-time auditor (`completeness` concern) verifies:

1. **Phase 0 ledger sweep was performed** — there's a `## Phase 0 — open-issue ledger` table in the plan.
2. **Drift-risk items had a disposition** — every drift-risk item from Phase 0 has either (a) been actioned this sprint, (b) been milestoned out of drift status, or (c) carries an operator-marked acceptance line in the close report.
3. **Carry-forward refresh ran** — the carry-forward ledger at `[ledger.carry_forward_file]` is up to date.
4. **Chronic flagging** — items that have crossed `[ledger.chronic_threshold_patches]` patch boundaries without being landed get the `chronic` label applied via GH MCP.

If any of these fail, the close report includes a `LEDGER-DISCIPLINE-VIOLATION` finding and the grade caps at C+.

## Configuration

```toml
[ledger]
phase_0_full_ledger      = true
classify_into            = ["blocking-this-sprint", "labeled-non-issue", "tracking-future", "drift-risk"]
non_issue_labels         = ["wontfix", "tracking-future", "design-question", "rfc"]
carry_forward_file       = "{paths.plans}/v{X}.{Y}.{Z}-carry-forwards.md"
chronic_threshold_patches = 2
```

A project that genuinely doesn't need this discipline (e.g., a 5-issue toy repo) can set `phase_0_full_ledger = false`. Most projects with > 50 open issues should leave it on.

## Why this matters

The original failure mode was: the conductor reads CLAUDE.md, sees the current sprint's seed, dispatches the engineer, runs the flock, closes. At no point did anyone enumerate the broader open-issue space. CRITICAL items not on the seed never got anyone's eyes.

This doctrine makes the broader space a structural input, not an afterthought. The engineer is now FORCED to look at every open issue at every sprint open. The auditor verifies the look happened. The chronic label flags items that cross multiple patches without landing.

## Anti-patterns

- **"The seed says we're working on X, so I won't look at Y" (Y is unrelated to X)** — wrong; the engineer's job at Phase 0 is to surface Y as a drift risk so the operator decides.
- **"Issue Z is CRITICAL but it's not on my milestone, so it's not my problem"** — wrong; the auditor flags Z as drift-risk and the operator decides.
- **"I'll do the ledger sweep at sprint close instead of Phase 0"** — wrong; close is too late to absorb a drift-risk item into this sprint's scope. Surface at Phase 0; act in the body if the operator approves.
- **"The ledger has 200 items, I'll just spot-check 20"** — wrong; the sweep is `gh issue list --limit 500`. Process every item programmatically.

## See also

- `subtract-dont-add.md` — issue closures count toward SUBTRACT
- `chain-repair.md` — when the ledger sweep contradicts the seed
- `pattern-b-overlap.md` — auditors run during Wave 2, can surface mid-sprint drift
