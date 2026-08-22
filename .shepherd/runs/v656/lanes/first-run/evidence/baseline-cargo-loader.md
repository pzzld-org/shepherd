HEAD: 6837e109ab618e3d22cb34c637de8ed7b7da7c69
COMMAND: cargo test -p shepherd-core --features full loader
EXIT_CODE: 0
--- STDOUT BEGIN ---

running 0 tests

test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 5 filtered out; finished in 0.00s


running 0 tests

test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 4 filtered out; finished in 0.00s


running 0 tests

test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 15 filtered out; finished in 0.00s


running 1 test
test explicit_content_loader_discovers_every_live_predicate ... ok

test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 68 filtered out; finished in 0.01s


running 2 tests
test layout_v5_migration_loader_rejects_malformed_or_unknown_legacy_keys ... ok
test layout_v5_migration_loader_accepts_only_the_typed_retired_subset ... ok

test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 24 filtered out; finished in 0.00s


running 0 tests

test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 7 filtered out; finished in 0.00s


running 0 tests

test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 6 filtered out; finished in 0.00s

--- STDOUT END ---
--- STDERR BEGIN ---
[1m[92m   Compiling[0m shepherd-core v6.5.6 (/Users/jo3/src/pzzld/shepherd/.worktrees/v656-first-run/crates/core)
[1m[92m    Finished[0m `test` profile [optimized + debuginfo] target(s) in 1.93s
[1m[92m     Running[0m unittests src/lib.rs (target/debug/deps/shepherd_core-4a9adad23e937ea9)
[1m[92m     Running[0m tests/default.rs (target/debug/deps/default-9632a692a79cec17)
[1m[92m     Running[0m tests/dispatch.rs (target/debug/deps/dispatch-9cd22356d2498ea7)
[1m[92m     Running[0m tests/guard.rs (target/debug/deps/guard-85ef6c5a8cef44f1)
[1m[92m     Running[0m tests/loader.rs (target/debug/deps/loader-8bfbc3f9453f4e0b)
[1m[92m     Running[0m tests/portable_dispatch.rs (target/debug/deps/portable_dispatch-d7da510e9aa16b5b)
[1m[92m     Running[0m tests/run_state.rs (target/debug/deps/run_state-6ebfcc52c40c44f8)
--- STDERR END ---
