# shepherd-compiler

Pure, deterministic compilation of canonical Shepherd role and skill content.

## Boundary

This crate accepts already-parsed `CompileInput` plus an explicit
`HarnessProfile`, then returns an in-memory `EmittedTree`. It has no filesystem,
environment, process, clock, or harness dependency. The CLI owns parsing source
files and safely materializing a returned tree; adapters own installation.

That split is the portability contract. The exact same input and profile emit
the same sorted paths, bytes, source hashes, content hashes, measurements, and
whole-tree SHA-256 digest on native and WASM targets.

## What it validates

- non-empty, unique canonical role and skill identifiers;
- bounded one-line descriptions and frontmatter;
- per-file role, skill, and command budgets;
- the compiled skill-set aggregate budget;
- harness capability mappings only where the selected profile declares them.

Measurements use `shepherd-prompt-v1-uax29`: physical lines, Unicode Standard
Annex 29 words, UTF-8 bytes, and a documented model-neutral token estimate.
The version is emitted with every tree so a release never compares budgets from
different algorithms as if they were equal.

## Features

| Feature | Meaning |
|---|---|
| `alloc` | Allocation-only pure compiler floor. |
| `std` | Host error integration, enabled by default. |
| `wasm` | Allocation-only target capability for WASM embeddings. |
| `full` | Release and docs target, currently equivalent to `std`. |

```toml
[dependencies]
shepherd = { package = "shepherd-sdk", version = "6.5.3", default-features = false, features = ["compiler", "alloc"] }
```

Consumers normally import the crate through `shepherd::compiler`; direct use is
reserved for internal release tooling.

## Release gates

```bash
cargo test -p shepherd-compiler --locked
cargo check -p shepherd-compiler --no-default-features --features alloc --locked
cargo check -p shepherd-compiler --no-default-features --features wasm --locked
scripts/check-features.sh --targets
```

The compiler is not a filesystem writer. A passing tree is only a candidate
release surface until the CLI materializer proves its path, ownership, and
atomic-write guarantees.
