# shepherd-registry

The SQLite registry: schema, migration runner, and query surface.

## Why this is a crate and not a module

**The registry schema is the cross-harness contract, not CLI stdout.** All 32 guard scripts open `shepherd.db` directly and none of them shell out to a binary, so row shapes are the compatibility surface every implementation must honor.

Isolating that surface here means a consumer can link the schema without linking the command-line interface, and means `shepherd-core` never acquires an I/O backend. The `engine-boundary` CI job forbids `rusqlite` in the engine for exactly this reason.

## The contract this crate owes

- The 20 migration files port **verbatim**. Migration SQL is the portable artifact; only the runner is rewritten.
- `rusqlite_migration` is rejected: it tracks state in `user_version`, while this schema uses a `schema_versions` table that both existing runners already read.
- FTS5 external-content tables keep the `unicode61 remove_diacritics 2` tokenizer and all 6 sync triggers.
- `json_valid()` CHECK constraints are asserted by **behavior**, never by probing `PRAGMA compile_options` for `ENABLE_JSON1`. That flag is absent on SQLite 3.53.2 and `json_valid` still works, because JSON went core in 3.38.

Acceptance for the port is an order-normalized `sqlite_master` dump that is byte-identical between the Python and Rust implementations.

## SQLite backends

`rusqlite` 0.40 picks its backend by **target cfg**, not by feature: `libsqlite3-sys` is a hard dependency everywhere except `cfg(all(target_family = "wasm", target_os = "unknown"))`, where it becomes optional and `sqlite-wasm-rs` takes over.

| Target | Feature | Backend |
|---|---|---|
| native | `bundled` *(default)* | `libsqlite3-sys`, SQLite compiled from C |
| `wasm32-unknown-unknown` | `wasm` → `sqlite-wasm` | `sqlite-wasm-rs`; `bundled` must stay **off** |
| `wasm32-wasip1` | `wasi` → `bundled` + `wasi-vfs` | `libsqlite3-sys` plus the WASI VFS shim |

Verified against 0.40 on `wasm32-unknown-unknown`: a 2.07 MB module with FTS5, `json_valid` and the unicode61 tokenizer compiled in. Apple's system clang has no wasm backend; use Homebrew's LLVM.

## Gate tests

`tests/default.rs` re-runs the capability probe that justified locked decision 4 — FTS5 present, the contract tokenizer accepted, `json_valid` enforcing. A probe that ran once proves nothing about the next dependency bump, so it runs on every commit instead of living in a spec document.
