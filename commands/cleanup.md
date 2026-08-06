---
name: cleanup
description: Prune stale or crashed teammate entries from the team config + canonical state.
model: sonnet
allowed-tools:
  - Bash
  - Read
---

# /shepherd:cleanup

**Use when**: a spawned teammate has crashed silently (see #49 / #51) and
its team-config entry is polluting status displays, OR after a sprint to
prune retired teammate entries.

**Scope**: rows in the `teammates` table, via `bin/shepherd teammate prune`.
NOT the harness's `~/.claude/teams/` files — see Hard prohibitions 4 and 5.
If `/shepherd:spawn` Check 3 refused, this command is NOT the remedy: run
`${CLAUDE_PLUGIN_ROOT}/scripts/team-preflight.sh` and read `commands/spawn.md
§Check 3` (#267).

## Mandatory protocol

### Step 1: Show current teammate liveness

```bash
bin/shepherd teammate liveness --stale-mins=5
```

Identify rows with `verdict=presumed-crashed` or `status=retired`.

### Step 2: Confirm with operator

Surface the to-be-pruned list. If 0 rows, exit with "nothing to prune."

### Step 3: Prune

For each confirmed entry:

```bash
bin/shepherd teammate prune --confirm --name=<name>
```

OR bulk:

```bash
bin/shepherd teammate prune --confirm --crashed
```

### Step 4: Materialize cleanup report

```bash
bin/shepherd report teammates --stale-mins=5 \
  > .shepherd/cache/teammate-cleanup-<run>.md
```

`<run>` is the run slug (e.g. `v641-dev0`) — deterministic; a re-run for the
same run overwrites the same file. The cache file is gitignored; the canonical
state is in the `teammates` table.

### Step 5: PAUSE

Report to operator: number pruned, final liveness state.

## Hard prohibitions

1. NEVER prune without `--confirm`.
2. NEVER prune `status='active'` rows without operator override.
3. NEVER auto-respawn without operator confirmation.
4. **NEVER touch `~/.claude/teams/` — not a directory, not a `config.json`,
   not by `rm`, `mv`, or archive (#267).** This command prunes rows in the
   `teammates` TABLE. The harness's team files are not its business, and
   deleting the current session's own team file is unrecoverable by
   inspection: the next spawn dies with `team file for "session-XXXX" not
   found`, and the directory id has no string relationship to the session id,
   so nothing on disk tells you what to restore or what it was called.
5. **A lead-only team directory is NOT a husk.** A `config.json` whose
   `members[]` holds only `team-lead` is the harness's normal startup state
   for the CURRENT session. It looks abandoned — one member, no activity —
   and it is not. `${CLAUDE_PLUGIN_ROOT}/scripts/team-preflight.sh` is the
   only sanctioned way to judge whether a team is active; a recent mtime and
   a lone member are not evidence of anything.

## Closes

#51 — /shepherd:cleanup command to prune stale/crashed teammate entries
#267 — cleanup must never prune the session's own harness team file
