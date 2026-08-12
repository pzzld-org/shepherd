# shepherd-core

The harness-agnostic shepherd engine. Domain types, configuration schema, run state, and the artifact contract.

## The boundary

**This crate does not know it is a CLI.** That is not a style preference, it is the reason the crate exists.

Shepherd has been rewritten once already, Python to Rust, and the reason was reach: the Python implementation could not become a fast static binary and could not embed in-process in a host that needed it. A third rewrite happens the same way, when some future host needs the engine without the command-line interface wrapped around it.

So this crate holds the logic and none of the delivery. `shepherd-cli` is one consumer. A Node binding, a WebAssembly module, or any future harness adapter is another, and none of them should have to strip out an argument parser to get at the run state.

## What may never appear here

| Forbidden | Why |
|---|---|
| `clap`, or any argument parser | Arguments are a delivery concern. A wasm host has none. |
| `std::process`, exit codes, `std::env::args` | Process semantics are the binary's, not the engine's. |
| `anyhow` | Contextual error strings are an application concern. This crate returns typed errors. |
| `tracing-subscriber`, any log sink | A library configures no global subscriber. `tracing` alone is fine. |
| Direct filesystem path assumptions | Callers supply paths. The engine does not go looking. |
| Anything named for a harness | No `claude`, `codex`, or `pi` behavior. `Harness` is a value, never a branch in the engine. |

## How the boundary is enforced

Not by this document. CI compiles this crate to `wasm32-unknown-unknown` on every push. Any dependency that cannot reach that target fails the build and names itself. An architecture rule that only lives in prose drifts; one that breaks a build does not.

```bash
cargo check -p shepherd-core --target wasm32-unknown-unknown
```

Apple's system clang has no WebAssembly backend. CI installs LLVM; locally, use Homebrew's.

## Features

`std` is on by default and is what a native or wasm32 build wants. The `alloc` and `std` split exists so the dependency surface can be narrowed later; the crate itself still uses `std::path::PathBuf`, so `#![no_std]` is not yet declared. Note that `wasm32-unknown-unknown` supports `std`, so the wasm target does not depend on that work landing.
