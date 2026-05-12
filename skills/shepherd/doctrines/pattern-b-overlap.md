# Pattern B overlap — auditors and Wave 2 coders run concurrently

When Wave 1 lands and the gates pass, dispatch the auditors ON Wave 1's output **in the same message batch as the Wave 2 coders**. Do NOT wait for all coder waves to complete.

## Pattern A vs Pattern B

**Pattern A (sequential — wrong for L/XL sprints):**
```
Wave 1 coders → gates → Wave 2 coders → gates → Wave 3 coders → gates → @auditor swarm
```
The auditors only run at the end. They review everything at once, after the sprint is closed-from-the-conductor's-perspective. Findings come too late to be hot-fixed cheaply.

**Pattern B (overlap — correct for L/XL sprints):**
```
Wave 1 coders → gates ┐
                       ├→ same Agent batch: { @auditor on Wave 1 output, Wave 2 coders }
                       └→ gates → same batch: { @auditor on Wave 2, Wave 3 coders }
                                              ⋮
                                              @auditor swarm (final, full sprint scope)
```
Auditors review each wave's output AS the next wave is being built. Findings land while the sprint is still open and hot-fixable.

## Why

- **Earlier surface** — a CRITICAL finding on Wave 1 should not wait for Waves 2/3 to also land before being addressed. Hot-fix cost rises with elapsed time + downstream-dependency depth.
- **Parallel cycles** — auditors are read-only. Their work doesn't block coder progress. Sequential dispatch wastes the cycles.
- **Better grade** — sprints where Pattern B catches wave-level issues consistently grade B+/A-; sprints that defer audits to close consistently grade B/B+ with hot-fix-coder thrash.

## How to dispatch

Every Wave N completion gate triggers ONE Agent batch with two-or-more elements:

```
Agent({ description: "@auditor: Wave 1 / code-quality concern", model: "sonnet", prompt: "..." })
Agent({ description: "@auditor: Wave 1 / data-flow concern",     model: "sonnet", prompt: "..." })
Agent({ description: "@coder: Wave 2 / lane A", model: "sonnet", prompt: "..." })
Agent({ description: "@coder: Wave 2 / lane B", model: "sonnet", prompt: "..." })
```

All four (or more) go in a single message. The conductor processes results as they return — auditors typically finish before coders, hot-fixes get filed in time.

## When NOT to use

- **XS or S sprint** — single wave, no overlap to apply.
- **Wave 1 was a single coder** with trivial scope — wait for the close-time auditor swarm; overlap is overhead.
- **Wave 1 broke the gates** — fix-forward IS the next dispatch, not Wave 2. Auditor on broken-gate output is wasted.

## Final auditor swarm at close

The wave-level auditors don't replace the close-time auditor swarm. The close swarm:

- Reviews the FULL sprint scope (all waves combined)
- Splits by concern, not by wave
- Carries the issue-ledger discipline (see `{patch_branch}` close checklist)
- Carries the SUBTRACT-DON'T-ADD verification

Wave-level auditors catch finds early; close auditors verify the full sprint shape.

## Anti-patterns

- "I'll dispatch the auditors at close so I can give them the complete scope" — too late. Close auditors review the complete scope; wave auditors catch issues in time to hot-fix.
- "I'll wait for Wave 2 gates before auditing Wave 1" — gates aren't audits. Gates check `cargo` (or equivalent) compiled / linted / formatted. Audits check correctness, completeness, design quality.
- "I'll dispatch the auditor sequentially after Wave 2 coders are dispatched" — process violation; this skips the overlap and waste a parallel cycle.

## See also

- `subtract-dont-add.md` — auditor-completeness verifies SUBTRACT at close
- `chain-repair.md` — when an auditor finding contradicts the seed
