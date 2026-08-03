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

## Closes

#51 — /shepherd:cleanup command to prune stale/crashed teammate entries
