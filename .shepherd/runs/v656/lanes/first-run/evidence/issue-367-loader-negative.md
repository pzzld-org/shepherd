# Historical pre-rebase reproduction

This file preserves the original `6837e109...` reproduction only. It is not
final-state evidence. Current base, implementation, projection, and gate results
are recorded in `status-and-diff.md`, `implementation-verification.md`, and
`issue-369-authored-spawn.md`.

HEAD: 6837e109ab618e3d22cb34c637de8ed7b7da7c69
COMMAND: cargo test -p shepherd-core --features full --test loader layout_v5_migration_loader_rejects_malformed_or_unknown_legacy_keys -- --exact --nocapture
EXIT_CODE: 0
--- STDOUT BEGIN ---

running 1 test
test layout_v5_migration_loader_rejects_malformed_or_unknown_legacy_keys ... ok

test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 25 filtered out; finished in 0.00s

--- STDOUT END ---
--- STDERR BEGIN ---
[1m[92m    Finished[0m `test` profile [optimized + debuginfo] target(s) in 0.03s
[1m[92m     Running[0m tests/loader.rs (target/debug/deps/loader-8bfbc3f9453f4e0b)
--- STDERR END ---
