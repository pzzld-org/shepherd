---
name: ctx
description: Manage the per-project shepherd context registry — issues, PRs, releases, code symbols, memories, profiles, locks. Backs DEDUP-GATE Layer 2 SQL fast-path.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Skill
---

# /shepherd:ctx — Context Registry CLI

Thin command shim. The full skill body lives at `${CLAUDE_PLUGIN_ROOT}/skills/context/SKILL.md`.

## Step 0 — Auto-orient

1. Load the `shepherd-context` skill via the Skill tool.
2. Read `.claude/shepherd.toml` `[context]` if present; otherwise use defaults from `${CLAUDE_PLUGIN_ROOT}/docs/configuration.md`.
3. Resolve the CLI path: `${CLAUDE_PLUGIN_ROOT}/bin/shepherd`.

## Step 1 — Run

Pass arguments through to `shctx`. Common invocations:

**Atomic:**
- `shctx init` — first-time scaffold of the per-project namespace.
- `shctx doctor` — diagnostic / pre-flight (binaries, schema, lock, refresh staleness).
- `shctx refresh --all` — rebuild every cache zone at sprint open.
- `shctx search "<text>"` — FTS5 fast-path over symbols + artifact content.
- `shctx inject coder [--scope=<glob>]` — emit a `[DB-CONTEXT]` block for a coder brief.
- `shctx query dedup-check --name=<symbol>` — Layer 2 SQL fast-path.
- `shctx worktree create-batch lane-1 lane-2 --from <sprint-branch>` — pre-create per-lane worktrees from sprint HEAD.

**Pipelines:**
- `shctx ready` — first-time bootstrap (`init` → `migrate` → `refresh --all` → `lint` → `doctor`).
- `shctx sync` — one-shot context refresh (`refresh` → `lint` → `status`).
- `shctx sprint open <branch>` — sprint kickoff (lock → refresh → lint → status).
- `shctx sprint wave <id>` — wave-gate refresh (github + artifacts + lint).
- `shctx sprint close <branch>` — sprint finale (close-lanes → handoff → worktree gc → lock release).
- `shctx audit` — read-only validation (lint → doctor → status).

For full subcommand documentation, read the skill body.
