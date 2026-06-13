# CLAUDE.md snippet for shepherd integration

Add this section to your project's `CLAUDE.md` so any Claude Code session knows shepherd is wired in.

```markdown
## Sprint orchestration — shepherd plugin

This project runs sprint cycles via the [shepherd](https://github.com/FL03/shepherd) plugin (v5.0.6).

Configuration: `.claude/shepherd.toml`. Project doctrines: `.claude/doctrines/`.

**Commands:**
- `/shepherd:plant`   — Opus session, authors sprint seeds upstream of execution
- `/shepherd:start`              — Sonnet session, runs one sprint then pauses
- `/shepherd:spawn --auto`       — Sonnet session, runs sprints back-to-back (fresh context window per sprint)
- `/shepherd:spawn --parallel N` — Sonnet session, fans out N disjoint sprints across worktrees

**Branch topology:** `v{X}.{Y}.{Z}-dev.{0..9}` — 10 sprints per patch, rebase-merge into patch on close, squash patch into main on dev.9 + automated release pipeline (`.github/workflows/release.yml`).

**Closed flock:** engineer (Opus, plans), critic (Sonnet, gates), coder (Sonnet, parallel waves), auditor (Sonnet, swarm of 3–5), worker (Sonnet, bounded execution). NO outside agents.

**Operator-pre-authorized doctrines** (loaded into every flock dispatch):
- `subtract-don't-add` — every sprint must end net-negative on (deps, abstractions, LOC)
- `wrapper-must-earn-its-existence` — hollow wrappers fail the wrapper-grep gate
- `pattern-b-overlap` — auditors run concurrently with Wave 2 coders
- `chain-repair` — Phase 0 seed drift triggers VERIFY → AMEND → CONTINUE, not blanket escalate
- `issue-ledger-awareness` — Phase 0 enumerates ALL open issues, not just current milestone

**Project doctrines** (project-specific, loaded from `.claude/doctrines/`):
- `geo-block-law.md` — node process group pinned to a single region for a regulatory requirement
- `three-role-topology.md` — node + worker + gateway, no fold
- `extend-existing-structs.md` — find the closest-existing struct + extend in same crate, don't define parallel
- (others as the project accumulates them)
```

Customize the doctrine list for your project's actual `.claude/doctrines/` content.
