---
title: cargo sequential gates
description: |
  Cargo invocations on the same workspace MUST run sequentially. Parallel cargo
  processes deadlock on the shared target/ lock and never speed up wall-clock
  time. This doctrine applies to conductor WAVE-GATE runs and coder dispatches.
introduced: v5.0.9
field_origin: shepherd v5.0.8 conductor feedback (axiom v0.3.2-dev.0) §5
---

# Doctrine — Cargo Sequential Gates

## The rule

**Cargo invocations on the same workspace MUST run sequentially.** Cargo holds
an exclusive advisory lock on `target/` (via `.cargo-lock` or the build
system's internal lock file). Parallel invocations do not speed up builds —
they block each other and, under load, deadlock the entire build until one
times out. Each `cargo` process already parallelizes internally via `-j
$(nproc)` / Rayon; the parallelism budget is already fully consumed inside a
single invocation.

## What this means at WAVE-GATE

The conductor's WAVE-GATE gate sequence is:

```bash
# CORRECT — all gates sequential in a single Bash call
{gates.format} \
  && {gates.check} \
  && {gates.lint}

# WRONG — these block each other; total time ≥ sequential, plus deadlock risk
bash -c "{gates.check}" &
bash -c "{gates.lint}"  &
wait
```

If any gate supports `--message-format=json --keep-going`, prefer that form
(per `pipeline.md §XIII-bis`) so all errors surface in one pass — but still
run sequentially:

```bash
{gates.lint} --message-format=json --keep-going \
  > .shepherd/runs/w{N}-gate.json 2>&1
```

## What this means for coder dispatches

Coders are prohibited from running `cargo` at all (per `agents/coder.md` Hard
Prohibitions). This doctrine applies to the **conductor** at WAVE-GATE and to
any `@worker` dispatched for build-verification tasks.

If a worker needs to run multiple cargo sub-commands, chain them with `&&`:

```bash
# CORRECT
cargo check && cargo test --lib

# WRONG — parallel cargo in same workspace
cargo check &
cargo test --lib &
wait
```

## Exception: different `--target-dir`

Two cargo invocations with explicitly different `--target-dir` paths (pointing
to distinct directories on distinct filesystems) do not share a lock and CAN
run in parallel. This is uncommon in shepherd projects but permitted when
the paths are provably disjoint.

```bash
# Permitted — distinct target dirs
cargo check --target-dir /tmp/check-target &
cargo test  --target-dir /tmp/test-target  &
wait
```

The default shepherd config uses a shared `target/` — the exception only
applies when `CARGO_TARGET_DIR` is explicitly overridden per crate.

## See also

- `pipeline.md §XV-bis` — worktree `target/` sharing policy (v5.0.4)
- `pipeline.md §XIII-bis` — structured gate output to capture all errors in one pass
- `agents/coder.md` Hard Prohibitions — coders never invoke cargo
