---
name: agent-coder-reference
slug: agent-coder-reference
description: "On-demand reference catalog for @coder, loaded at startup via Skill. Holds the INSIGHTS section template, the BASE-DRIFT halt narrative, and project-doctrine layering guidance."
metadata:
  triggers:
    - "agent-coder-reference"
---

# @coder reference

Loaded once per session. The agent body in `agents/coder.md` cites this file
for the longer-form material — the INSIGHTS template, BASE-DRIFT narrative,
and project-doctrine layering — that does not need to be re-read on every
turn of reasoning.

> **Senior-engineering standard (v6.1.6, always-on — `doctrines/senior-engineering.md`).**
> Write like a senior who has to live with this code: reconstruct the **intent** of
> code you touch before changing it (§I); take the **root** fix or say why it is out
> of scope (§II); prefer the **reversible, narrow** change, flag irreversible ones for
> gate (§III); when a step admits >1 approach, **name the rejected alternative and why**
> in your report (§IV); resolve style **top-down by precedence** — project doctrines >
> `[CODE-STYLE]` ledger > `code-style` skill > adaptation priors > the neighbors >
> defaults (§V); stay **bounded** — the most senior move is often the smaller diff (§VII).

## Cross-lane dependencies (pause-for-dependency retired — #70)

> Superseded by `doctrines/native-coordination.md`. The pause-for-dependency
> satellite mechanism — halt code, satellite brief, resume-condition dance, and
> the `<ns>/pauses/` registry — is deleted in v6.0.1.

If your `[ACCEPTANCE]` cannot be met without a symbol that (a) does not exist in
the workspace, (b) lives outside your `[FILE-SCOPE]`, and (c) is not owned by a
wave-sibling, that dependency should have been a **graph edge** the engineer
composed — the conductor's compiled segment `await`-orders it. You do **not**
pause. Pre-check first (same discipline as before):

```bash
rg -n "pub fn <needed_fn>|pub struct <needed_struct>" --type <lang>   # already exists?
# re-read [CONTEXT-INVENTORY] — maybe it's there under a different name
# re-read the wave's lane list — a sibling may own it (re-sequence, don't block)
```

- If it belongs to this sprint but wasn't sequenced → commit any WIP, then file a
  `BRIEF-AMENDMENT REQUEST` so the conductor re-meshes the graph edge.
- If it is genuinely **out of this sprint's scope** → finish your assigned scope
  and surface it as a **finding / GH issue at close**. Never expand scope silently.

## BASE-DRIFT halt narrative

> Field origin: shepherd v5.0.1 conductor feedback §2.3 — Lane 2 worktree
> was branched from `main` (v0.2.9 era) instead of the active sprint branch,
> causing a cherry-pick conflict storm at rebase time. v5.0.3 codifies the
> prevention as a coder-side halt.

The verification (Step 0.5 in the body) runs BEFORE any code is touched.
If the SHAs do not match, HALT with:

```
BASE-DRIFT — worktree HEAD <actual_sha> does not match [BASE-COMMIT-EXPECTED] <expected_sha>.
The worktree was branched from the wrong base — likely `main` or a stale patch branch.
Halting before Step 1. Conductor must re-create the worktree from {sprint_branch} HEAD.
```

This is a **first-class halt code** alongside `BRIEF INVALID`,
`CONTEXT-INVENTORY STALE`, `DUPLICATION RISK`. Do not proceed and "hope for
the best" — the cherry-pick will conflict, the conductor will burn cycles,
and the work may be lost when the worktree is later cleaned up.

If the brief omits `[BASE-COMMIT-EXPECTED]` entirely (legacy pre-v5.0.3
brief), HALT with `BRIEF INVALID — missing [BASE-COMMIT-EXPECTED]`. The
conductor amends and re-fires.

## Optional: ## INSIGHTS (cross-lane observations)

Per `doctrines/flock-cohesion.md`, you MAY append a `## INSIGHTS` section
with cross-lane observations the engineer should weigh in the NEXT sprint's
planning. Entries are optional; quality > quantity. Skip entirely if you
have nothing structural to flag. The `agent_insight_capture.sh` hook
auto-records each entry to `<ns>/insights/<sprint>/<id>.json`.

```
## INSIGHTS

- kind: relocation | extension | duplication | consolidation | gap | nit
  subject: <symbol or file path you observed>
  observation: <one sentence — what you saw>
  rationale: <one sentence — why it matters>
```

Do NOT use INSIGHTS to:

- Request scope changes for THIS sprint (use `BRIEF-AMENDMENT REQUEST`).
- Flag missing symbols you need (file a `BRIEF-AMENDMENT REQUEST`).
- Vent about taste or code style (those aren't insights — they're nits
  at best; one per report max, none preferred).

### Insight kinds (canonical)

| Kind | When to use |
|---|---|
| `relocation` | A symbol or file lives in the "wrong" package/module |
| `extension` | A type/trait/function needs a small extension for a real use case |
| `duplication` | Two or more places implement the same logic |
| `consolidation` | Multiple small artifacts could merge into one (SUBTRACT candidate) |
| `gap` | A capability the workspace should have but does not |
| `nit` | Style / naming observation; aggregate sparingly |

## Project-doctrine layer

Some projects ship `.claude/doctrines/*.md` (per `docs/customization.md`).
The conductor injects these into your brief preamble. Treat them as
authoritative for THIS PROJECT — they are the operator's structural rules
that the framework cannot generalize. Examples:

- "Geo-block law — node region pinned to yyz forever"
- "All API endpoints require X-Request-Id header"
- "Database writes go through WriteOnlyClient wrapper"

If a project doctrine conflicts with framework guidance, the project
doctrine wins (the operator owns the project; the framework is a tool).

## Anti-pattern dispatch examples (what NOT to do)

The Step-3 grep and the Step-2 canonical-types read are mandatory. The most
common ways coders try to skip them:

- "The brief listed `Foo` in `[CONTEXT-INVENTORY]`; I trust it." — No: the
  brief may be stale. Verify with a Read or `rg` before writing.
- "The dedup grep showed 1 hit, but I assumed it was the wrong one." — Read
  the existing one. If it does the job, REUSE. If not, JUSTIFY-NEW in your
  report with a one-sentence reason that names the missing invariant.
- "I added a TODO comment because the satellite would be too much overhead."
  — No. TODO is a process violation. File a `BRIEF-AMENDMENT REQUEST` (or
  surface the gap as a finding at close).

## See also

- `skills/shepherd/doctrines/agent-excellence.md` — strive-higher framing
- `skills/shepherd/doctrines/zero-duplicate-tolerance.md` — DEDUP-GATE mechanics
- `skills/shepherd/doctrines/native-coordination.md` — cross-lane deps + out-of-scope handling (pause-for-dependency retired, #70)
- `skills/shepherd/doctrines/worktree-confinement.md` — `[WORKTREE]` write rules
- `skills/shepherd/doctrines/flock-cohesion.md` — INSIGHTS rationale
- `hooks/scripts/dedup_write_guard.sh` — runtime duplicate-symbol blocker
