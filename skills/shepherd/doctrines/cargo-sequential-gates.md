---
title: cargo sequential gates
description: |
  Cargo invocations on the same workspace MUST run sequentially. Parallel
  cargo deadlocks on the shared target/ lock and never speeds up wall-clock
  time. Applies to conductor WAVE-GATE runs and any @worker build verification.
introduced: v5.0.9
field_origin: shepherd v5.0.8 conductor feedback (axiom v0.3.2-dev.0) §5
---

# Doctrine — Cargo Sequential Gates

## The rule

Cargo holds an exclusive advisory lock on `target/`. Parallel invocations
block each other (and can deadlock under load). Each cargo process already
parallelizes internally via `-j $(nproc)` / Rayon — the parallelism budget is
consumed within one invocation.

**Chain with `&&`, never with `&`:**

```bash
# CORRECT
{gates.format} && {gates.check} && {gates.lint}

# WRONG — deadlock-prone; total time ≥ sequential
{gates.check} & {gates.lint} & wait
```

Where a gate tool supports `--message-format=json --keep-going`, prefer that
form so all errors surface in one pass (per `pipeline.md §XIII-bis`), but
still run gates sequentially.

## Scope

- **Conductor** WAVE-GATE inline runs — see `SKILL.md §2 BODY`.
- **`@worker`** dispatches that perform build verification — workers also
  chain with `&&`.
- **`@coder`** is already prohibited from invoking cargo at all
  (`agents/coder.md` Hard Prohibitions). This doctrine doesn't add a new
  rule for coders; it codifies the conductor's analog.

## Exception: distinct `--target-dir`

Two cargo invocations with explicitly different `CARGO_TARGET_DIR` paths
do not share the lock and CAN run in parallel:

```bash
CARGO_TARGET_DIR=/tmp/a cargo check &
CARGO_TARGET_DIR=/tmp/b cargo test  &
wait
```

The shepherd default uses a shared workspace `target/` — this exception
only applies when target dirs are explicitly partitioned.

## See also

- `pipeline.md §XV-bis` — worktree `target/` sharing policy
- `pipeline.md §XIII-bis` — structured gate output for one-pass error capture
- `agents/coder.md` Hard Prohibitions — coders never run cargo
- `hooks/scripts/bash_guard.sh` — PreToolUse warn on backgrounded cargo
