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

## Consumers link `shepherd`, not this crate

Nothing outside the workspace should name `shepherd-core` in a manifest. The `shepherd` umbrella re-exports everything here, which is what makes splitting a new member out of the engine an internal refactor rather than a breaking change for every adapter.

## Features

Every dependency past `thiserror` and `strum` is optional, and every module that needs one is gated on it. The point is not minimalism for its own sake: it is that an embedder can take the run-state machine without linking a JSON codec, a schema generator, a clock, or an entropy source.

| Feature | Enables |
|---|---|
| `std` *(default)* | `settings`, and the `std` surface of every enabled dependency |
| `alloc` | the `no_std` floor; `error` and `types` are available here |
| `json` | `serde` + `serde_json`, for the canonical artifact codec |
| `parse` | `nom`, for the run-id and branch grammars |
| `schema` | `schemars`, for the config key universe |
| `chrono`, `uuid`, `tracing` | the named dependency, nothing more |
| `full` | everything above; `native` is its alias |
| `wasm`, `wasi` | the target-appropriate set |

The crate is genuinely `#![no_std]` below `std`. `settings` is gated on `std` because it is the only module that names a filesystem path; under `alloc` alone you still get the error and domain types, and you do not get a type that presumes a filesystem.

`wasm` and `wasi` deliberately exclude `uuid` and `chrono`. UUIDv7 needs an entropy source and chrono's `clock` needs a system timezone, and neither exists on `wasm32-unknown-unknown` without a JS shim; an embedder supplies both.

Every leaf dependency flag pulls in `alloc`, because there is no configuration of this crate that builds below the allocating floor — `Error` carries owned strings. A flag that lets you select an unbuildable combination is a flag that hands you a compile error and blames your feature list.

Run `scripts/check-features.sh` to check each combination in isolation. CI runs it on every push.
