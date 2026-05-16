# Chain repair — VERIFY → AMEND → CONTINUE on Phase 0 mesh seed drift

When the engineer's Phase 0 mesh comes back with `SEED DRIFT` (some premise of the seed is contradicted by ground truth), the conductor's job is **not** to escalate to the operator immediately. The job is:

1. **VERIFY** — the conductor verifies the contradiction directly against ground truth (MCP queries, file reads, git log, deploy state).
2. **AMEND** — if the contradiction 100% verifies, the conductor amends the seed inline with a `## Phase 0 amendment ({date})` section that captures (a) what the seed claimed, (b) what mesh found, (c) the corrected scope/lanes.
3. **CONTINUE** — re-dispatch the engineer with the amended seed; sprint continues without operator round-trip.

**Escalate to operator ONLY if** the contradiction implicates:
- Sprint theme (the headline shifts entirely)
- Money path (ordering, sizing, risk gates, balance — anything that could lose dollars)
- Secrets / credentials (rotation, exposure)
- Architecture-changing decisions the operator would want to weigh in on

## Why

Default behavior is "ask the operator on any drift" — which is excessive. Most drifts are mechanical:
- An issue listed in carry-forwards was closed since the seed was authored
- A file path moved during a rename cascade
- A migration shipped between seed and mesh
- A type the seed cited got renamed

These cost the operator nothing to confirm — the conductor can verify and amend in 30 seconds. Escalating consumes the operator's attention for zero added safety.

The operator's attention should be spent on **judgment calls** the conductor can't make: theme shifts, money-path implications, security-relevant changes.

## VERIFY procedure

Drift-types and their verification commands:

| Drift type | Verify with |
|---|---|
| GH issue state | `mcp__plugin_github_github__issue_read` — does the issue still exist, what's its state, what milestone, what labels |
| File path | `Read` or `ls` the cited path |
| Type / function exists | `rg` the symbol; if absent, walk recent commits to find rename or deletion |
| Migration applied | Datastore MCP — query the schema (Supabase MCP or equivalent) |
| Deploy state | Deploy-platform MCP or CLI (Fly, k8s, whatever) |
| Memory entry exists | `Read` the memory file |

If the verification confirms the contradiction, AMEND. If verification fails (the seed was right), report back to the engineer with the verification evidence and re-dispatch.

## AMEND procedure

The conductor edits the seed file directly:

1. Open `{paths.plans}/{sprint_slug}.seed.md`
2. Add a top-of-file section:

```markdown
## Phase 0 amendment ({date})

The engineer's Phase 0 mesh surfaced these drifts:

| Drift | Seed claimed | Mesh found | Resolution |
|---|---|---|---|
| ... | ... | ... | ... |

Lanes affected: {lane numbers + revised scope}.
```

3. Update any lane sections that need scope adjustments
4. Commit `seed: amend dev.{N} per Phase 0 mesh`
5. Re-dispatch the engineer with the amended seed

## CONTINUE — when to escalate anyway

Even after a verified-correct amendment, escalate if:
- The amended scope makes the sprint much smaller (the seeded "L" is now an "S") — operator should know
- The amendment adds a new lane that wasn't seeded (scope creep — operator decides if it belongs in this sprint or a future one)
- The amendment touches a money-path / schema / secret — operator gates these regardless of how mechanical the drift looks

In those cases, surface the amendment to the operator with a one-line "I amended the seed for these mechanical drifts AND found these scope-affecting issues — ok to proceed with revised scope?" and wait.

## Anti-patterns

- **"Phase 0 found drift, escalate"** — wrong; verify first.
- **"I'll just plow ahead, the engineer can work around it"** — wrong; engineer's plan inherits the drift, the entire sprint is downstream-corrupted.
- **"I'll silently amend the seed without committing the amendment"** — wrong; the amendment IS provenance. Future audits need to see how the seed evolved.
- **"I verified, but it's a money path, so I can amend silently"** — wrong; money-path changes always escalate even if mechanical.

## See also

- `subtract-dont-add.md` — amendments don't excuse net-positive drift
- `pattern-b-overlap.md` — wave auditors can also surface drift mid-sprint
