# Rust — project code style

This file is project-local at `.artifacts/styles/rust.md`. The conductor injects its content into every coder brief whose `[FILE-SCOPE]` includes Rust files. Edit freely; lives next to the project, not the user.

## Error handling
- Library crates use `thiserror` for explicit error enums; binaries use `anyhow` for ergonomic propagation.
- Public APIs return `Result<T, MyError>`; never `Result<T, Box<dyn Error>>`.
- `.unwrap()` and `.expect()` are forbidden in `src/lib.rs` and any module exposed to consumers. They are tolerated in tests and `examples/`.
- Prefer `?` over `match e { Ok(v) => v, Err(e) => return Err(e) }`. Convert with `From`/`#[from]`.

## Ownership & cloning
- `.clone()` requires a comment explaining why a borrow won't work. Reviewer rejects unjustified clones.
- Prefer `&str` over `String` in function signatures unless ownership is needed.
- Use `Cow<'a, str>` when borrow-or-own is genuinely conditional.

## Module layout
- `lib.rs` is re-exports only — no logic. Public surface is a hand-curated `pub use` block.
- Files > 200 LOC are split. One primary type per file when the type exceeds ~50 LOC of methods.
- `mod tests` lives at the bottom of the file under test (small) or in `tests/` (integration).

## Async
- `tokio` features are explicit in `Cargo.toml` — never `features = ["full"]` in libraries; binaries may use `full` only with justification.
- `async fn` in traits uses `#[async_trait]` until the language stabilizes the feature; revisit per Rust release notes.
- `.await` boundaries respect cancellation safety; document non-cancel-safe futures in doc comments.

## Collections
- `HashMap` requires a specified hasher (`ahash::HashMap` or `std::collections::HashMap<K, V, BuildHasherDefault<Hasher>>`) when used in hot paths or for security-sensitive keys.
- `BTreeMap` when key ordering is observable to consumers.
- `Vec::with_capacity` when the size is known.

## Tooling
- `cargo fmt` config: `max_width = 100`, `use_small_heuristics = "Default"`.
- `cargo clippy --all-targets --all-features -- -D warnings` MUST pass before commit.
- `#[allow(...)]` requires a comment with a tracking issue number.

## Documentation
- Every `pub` item has a `///` doc comment with at minimum a one-line summary.
- `pub` types include a `# Examples` block when non-trivial.
- `# Errors`, `# Panics`, `# Safety` sections follow rustdoc conventions where applicable.

## Common patterns to AVOID (operator-flagged)
- Wrapping types just to add one method — extension traits or inherent `impl` first; new types only when invariant is meaningful.
- Returning `&Vec<T>` from getters — return `&[T]`.
- `Arc<Mutex<T>>` in single-threaded contexts.
- `let _ = ...` to silence warnings — use `drop(...)` or fix the underlying.
- Recreating `Regex` in a hot loop — use `once_cell::sync::Lazy` or `OnceLock`.
- `unsafe` without a `// SAFETY:` comment explaining the invariant being upheld.
