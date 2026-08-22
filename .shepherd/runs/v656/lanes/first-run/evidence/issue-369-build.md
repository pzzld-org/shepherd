# Historical pre-rebase reproduction

This file preserves the original `6837e109...` reproduction only. It is not
final-state evidence. Current base, implementation, projection, and gate results
are recorded in `status-and-diff.md`, `implementation-verification.md`, and
`issue-369-authored-spawn.md`.

HEAD: 6837e109ab618e3d22cb34c637de8ed7b7da7c69
COMMAND: cargo build -p shepherd-cli
EXIT_CODE: 0
BINARY: target/debug/shepherd
-rwxr-xr-x@ 1 jo3  staff  14881384 Aug 22 10:59 target/debug/shepherd
--- STDOUT BEGIN ---
--- STDOUT END ---
--- STDERR BEGIN ---
[1m[92m   Compiling[0m libc v0.2.189
[1m[92m   Compiling[0m typenum v1.20.1
[1m[92m   Compiling[0m serde v1.0.229
[1m[92m   Compiling[0m serde_json v1.0.151
[1m[92m   Compiling[0m find-msvc-tools v0.1.11
[1m[92m   Compiling[0m syn v3.0.3
[1m[92m   Compiling[0m shlex v2.0.1
[1m[92m   Compiling[0m num-traits v0.2.19
[1m[92m   Compiling[0m smallvec v1.15.2
[1m[92m   Compiling[0m vcpkg v0.2.15
[1m[92m   Compiling[0m pkg-config v0.3.34
[1m[92m   Compiling[0m log v0.4.33
[1m[92m   Compiling[0m cc v1.4.3
[1m[92m   Compiling[0m anstyle v1.0.14
[1m[92m   Compiling[0m tracing v0.1.44
[1m[92m   Compiling[0m shepherd-core v6.5.6 (/Users/jo3/src/pzzld/shepherd/.worktrees/v656-first-run/crates/core)
[1m[92m   Compiling[0m foldhash v0.2.0
[1m[92m   Compiling[0m cpufeatures v0.3.0
[1m[92m   Compiling[0m hybrid-array v0.4.14
[1m[92m   Compiling[0m serde_derive v1.0.229
[1m[92m   Compiling[0m ref-cast-impl v1.0.26
[1m[92m   Compiling[0m serde_derive_internals v0.30.0
[1m[92m   Compiling[0m thiserror-impl v2.0.20
[1m[92m   Compiling[0m libsqlite3-sys v0.38.2
[1m[92m   Compiling[0m crypto-common v0.2.2
[1m[92m   Compiling[0m block-buffer v0.12.1
[1m[92m   Compiling[0m schemars_derive v1.2.2
[1m[92m   Compiling[0m digest v0.11.3
[1m[92m   Compiling[0m sha2 v0.11.0
[1m[92m   Compiling[0m hashbrown v0.17.1
[1m[92m   Compiling[0m ref-cast v1.0.26
[1m[92m   Compiling[0m encoding_rs v0.8.35
[1m[92m   Compiling[0m unicode-width v0.2.2
[1m[92m   Compiling[0m arraydeque v0.5.1
[1m[92m   Compiling[0m bitflags v2.13.1
[1m[92m   Compiling[0m granit-parser v1.1.0
[1m[92m   Compiling[0m annotate-snippets v0.12.16
[1m[92m   Compiling[0m hashlink v0.12.1
[1m[92m   Compiling[0m shepherd-render v6.5.6 (/Users/jo3/src/pzzld/shepherd/.worktrees/v656-first-run/crates/render)
[1m[92m   Compiling[0m shepherd-compiler v6.5.6 (/Users/jo3/src/pzzld/shepherd/.worktrees/v656-first-run/crates/compiler)
[1m[92m   Compiling[0m fallible-streaming-iterator v0.1.9
[1m[92m   Compiling[0m encoding_rs_io v0.1.8
[1m[92m   Compiling[0m memo-map v0.3.3
[1m[92m   Compiling[0m fallible-iterator v0.3.0
[1m[92m   Compiling[0m shepherd-registry v6.5.6 (/Users/jo3/src/pzzld/shepherd/.worktrees/v656-first-run/crates/registry)
[1m[92m   Compiling[0m regex-syntax v0.8.11
[1m[92m   Compiling[0m serde-saphyr v1.1.0
[1m[92m   Compiling[0m thiserror v2.0.20
[1m[92m   Compiling[0m regex-automata v0.4.18
[1m[92m   Compiling[0m clap_lex v1.1.0
[1m[92m   Compiling[0m lazy_static v1.5.0
[1m[92m   Compiling[0m unicode-segmentation v1.13.3
[1m[92m   Compiling[0m rustix v1.1.4
[1m[92m   Compiling[0m shepherd-sdk v6.5.6 (/Users/jo3/src/pzzld/shepherd/.worktrees/v656-first-run/crates/sdk)
[1m[92m   Compiling[0m anyhow v1.0.104
[1m[92m   Compiling[0m matchers v0.2.0
[1m[92m   Compiling[0m sharded-slab v0.1.7
[1m[92m   Compiling[0m clap_builder v4.6.6
[1m[92m   Compiling[0m getrandom v0.4.3
[1m[92m   Compiling[0m clap_derive v4.6.4
[1m[92m   Compiling[0m errno v0.3.14
[1m[92m   Compiling[0m thread_local v1.1.10
[1m[92m   Compiling[0m uuid v1.24.1
[1m[92m   Compiling[0m chrono v0.4.45
[1m[92m   Compiling[0m tracing-subscriber v0.3.23
[1m[92m   Compiling[0m glob v0.3.4
[1m[92m   Compiling[0m rusqlite v0.40.2
[1m[92m   Compiling[0m clap v4.6.6
[1m[92m   Compiling[0m schemars v1.2.2
[1m[92m   Compiling[0m minijinja v2.24.0
[1m[92m   Compiling[0m shepherd-cli v6.5.6 (/Users/jo3/src/pzzld/shepherd/.worktrees/v656-first-run/crates/cli)
[1m[92m    Finished[0m `dev` profile [optimized + debuginfo] target(s) in 22.63s
--- STDERR END ---
