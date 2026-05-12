# Carry-forward refresh at sprint close

Every sprint close runs a GH-issue delta against the carry-forward ledger BEFORE the close handoff is written. Items that have crossed `[ledger.chronic_threshold_patches]` patch boundaries without landing get the `chronic` label.

## The problem this prevents

Without a structural refresh, carry-forward items roll forward indefinitely. Each sprint close says "carry these to next sprint" and the next sprint's seed faithfully copies them in. After 4–5 patches, half the seed is stale carries — and nobody flags that those carries have been deferred N times.

The canary that surfaced this in Axiom: GH #582 was deferred across 3 separate patches without anyone noticing. The fix was the chronic label + the close-time refresh.

## What the refresh does

At sprint close, the auditor-completeness concern:

1. **Diff the ledger** — read `[ledger.carry_forward_file]` (a markdown table of carry-forward items) and the current open-issue list.
   - Items in ledger but no longer open in GH → mark as RESOLVED, remove from ledger
   - Items in ledger and still open → increment their `patches_crossed` counter
   - Items NOT in ledger but newly opened with carry-forward-ish patterns → review for inclusion

2. **Apply chronic label** — any item whose `patches_crossed` ≥ `[ledger.chronic_threshold_patches]` (default 2) gets the `chronic` label applied via GH MCP. The chronic label is a structural signal: "this has been deferred N times; surface to the operator at next planter session for an explicit dispose-or-prioritize decision".

3. **Update the ledger** — write the refreshed ledger back to `[ledger.carry_forward_file]`. The ledger is structured as:

```markdown
# Carry-forward ledger for v{X}.{Y}.{Z}

Last refreshed: {date} at sprint {sprint_branch} close

| GH# | Title | Severity | First seen sprint | Patches crossed | Disposition this sprint |
|---|---|---|---|---|---|
| #674 | Settlement chain dark | CRITICAL | v0.2.7-dev.5 | 4 | CHRONIC — surfaced for planter |
| #834 | r2 IEEE 754 boundary | LOW | v0.2.9-dev.0 | 1 | CARRY |
| #840 | bet_usd schema-change | HIGH | v0.2.9-dev.1 | 1 | CARRY → dev.5 |
| ... | ... | ... | ... | ... | ... |
```

4. **Surface to handoff** — the close handoff doc lists every chronic item with a one-line summary so the next-sprint planter sees them at session open.

## Engineer-time use

When the engineer reads the carry-forward ledger at Phase 0 (which is part of `[ledger.carry_forward_file]` resolution), it MUST read the chronic items first and surface them as candidates for inclusion in the upcoming sprint. The chronic label converts "still deferred" into a structural escalation.

## Planter-time use

When the planter authors a new seed (especially `dev.0` of a new patch), it walks the chronic-labeled items as the FIRST input. The planter's job at chronic-finding is to:

- Either push for inclusion in the upcoming patch
- Or formally drop with operator-marked won't-fix entry
- Or escalate the severity (chronic + CRITICAL = drop everything else)

Chronic items can NEVER silently roll forward to a fourth patch. Either land or formally drop.

## Anti-patterns

- **"This is the third sprint we've carried this; let's just defer again"** — wrong; chronic label triggers + planter-time decision.
- **"I'll edit the ledger by hand at close"** — wrong; auditor automation runs first; manual edits ride on top.
- **"Chronic label is for big-deal items only"** — wrong; the threshold is mechanical (`[ledger.chronic_threshold_patches]`), not severity-weighted. Any item that crosses N patch boundaries gets the label regardless of perceived size.

## See also

- `issue-ledger-awareness.md` — the broader Phase 0 mesh discipline
- `subtract-dont-add.md` — landing a chronic item is a SUBTRACT win
- `chain-repair.md` — when the ledger refresh contradicts the seed
