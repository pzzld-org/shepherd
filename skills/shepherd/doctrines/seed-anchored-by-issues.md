# Seed lanes are anchored by GH issues

Every MUST-LAND lane in a sprint seed cites a GH issue (existing `#NNN` or `file at Phase 0 — title: "..."` placeholder). Detailed change-spec, full file scope, hypothesis evidence, and detailed acceptance criteria live in the GH issue body — NOT duplicated in the seed.

This is what keeps seeds dense (150–300 lines per sprint) instead of ballooning into 800-line manifestos.

## The pattern

Lane block in the seed (≤ 10 lines):

```markdown
### Lane 2 — Sharpe extraction to per_bot.rs

**GH:** #840 (existing) — "feat(attribution): per-bot sharpe primitive"
**Priority:** HIGH (release-gate criterion #1)
**Size:** S (1 file new, ~120 LOC)
**Files:** `crates/attribution/src/per_bot.rs` (new), `crates/engine/src/allocator.rs` (extend)
**Acceptance:** see issue body

**Why this sprint:** Lane 0 unlocked allocator wiring; this lane is the
canonical primitive everything else builds on.
```

The GH issue body carries:

- Full change-spec (signatures, semantics, edge cases)
- File-by-file scope with byte-accurate ranges
- Hypothesis evidence (why this fix solves the problem)
- Acceptance criteria (runnable greps + structural assertions)
- Cross-references to memory anchors / prior reports
- Test fixtures
- Known limitations

## Why

- **Single source of truth.** If the change-spec lives in two places (seed + issue), they drift. The issue is the contract; the seed cites it.
- **Dense seeds.** Seeds that include full lane bodies bloat to 600–1000 lines. Seeds that cite issue bodies stay at 200–300.
- **Discoverable from the GH side.** Operators reviewing `#840` see the full context inline. They don't have to walk to `.artifacts/plans/v0.2.9-dev.5.seed.md` to understand it.
- **Cross-sprint reuse.** A lane that doesn't land this sprint just gets a new sprint pointer in its issue body. The body doesn't have to be re-authored.

## Process lane exception

Closeout / retrospective / release-pipeline / audit-swarm lanes don't need backing GH issues — they're mechanical and local to the sprint. They keep priority + size + acceptance inline:

```markdown
### Lane 5 — Sprint close

**Priority:** MECHANICAL
**Size:** XS (handoff doc + memory updates + rebase)
**Acceptance:**
- Close report at .artifacts/reports/<date>-{sprint}-close.md
- Handoff at .artifacts/docs/<date>-dev{N}-close-handoff.md
- All cargo gates green at HEAD
- Dev branch deleted from origin and local
```

## "File at Phase 0" placeholder

Sometimes the engineer surfaces a finding at Phase 0 that should become a lane but doesn't have a GH issue yet. The seed marks it:

```markdown
### Lane 4 — Stale book auto-clear

**GH:** *file at Phase 0 — title: "fix(quad): stale_book auto-clear on hot-upsert"*
**Priority:** MEDIUM
**Size:** S
**Files:** quad_tick.rs:283-287
**Acceptance:** rg -n 'stale_book' should return 0 hits in production logs after deploy
```

When the engineer's Phase 0 mesh runs, it files the issue (via GH MCP), captures the issue number, and the conductor inlines that number into the seed before dispatching coders.

## Anti-patterns

- **"I'll just put the full lane body in the seed; it's cleaner than splitting"** — wrong; seeds bloat, GH issues stay empty, coders read the seed and miss issue-body detail.
- **"This is a process lane, but I'll file an issue for it anyway"** — wrong; needless GH ledger noise. Process lanes are inline.
- **"I'll cite an issue that doesn't exist yet, and we'll create it later"** — wrong; the planter VERIFIES every cited issue at seed-commit time. Use the `file at Phase 0` placeholder instead.
- **"The lane block is 30 lines, that's fine"** — wrong; ≤ 10 lines per lane block. Detail goes in the issue body.

## Verification (planter pre-commit)

The planter's pre-commit checklist verifies:

- [ ] Every MUST-LAND lane has a `**GH:**` line
- [ ] Every existing `#NNN` resolves via `mcp__plugin_github_github__issue_read`
- [ ] Every `file at Phase 0` placeholder has a matching mesh row
- [ ] Lane blocks stay under 10 lines

A seed that fails any check is fixed before commit.

## See also

- `issue-ledger-awareness.md` — Phase 0 enumerates the full ledger
- `carry-forward-refresh.md` — chronic items get the chronic label
- `subtract-dont-add.md` — issue closures count toward SUBTRACT
