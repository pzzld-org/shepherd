# W0-GATE — reproduction before any fix (lane `identity`, run v646)

- Date: 2026-08-17
- Repo commit: aa6dc98165026dda7235d9e95aecf764132c6c78
- Branch: v6.4.6
- Binary: `/Users/jo3/src/fl03/shepherd/target/debug/shepherd` — `shepherd-cli 6.4.6`
- Fixture: throwaway git repo under $TMPDIR (never inside the repo): `/var/folders/98/hw9cxq3d29sdw5nb5gv0b9wh0000gn/T/v646-w0-repro`
- Operator: conductor, lane `identity`. Bash only, no repo mutation.

## 1. Fixture is a clean git repository
```
$ git init -q . && git status --short && git rev-parse --is-inside-work-tree
true
```

## 2. `shepherd init --confirm`
```
$ shepherd init --confirm
initialized layout-v5 namespace: /private/var/folders/98/hw9cxq3d29sdw5nb5gv0b9wh0000gn/T/v646-w0-repro/.shepherd
registry: /private/var/folders/98/hw9cxq3d29sdw5nb5gv0b9wh0000gn/T/v646-w0-repro/.shepherd/shepherd.db
exit=0
```

## 3. The complete artifact set init actually produced
```
$ find .shepherd -maxdepth 3 | sort
.shepherd
.shepherd/ctx
.shepherd/docs
.shepherd/runs
.shepherd/shepherd.db
.shepherd/shepherd.db-shm
.shepherd/shepherd.db-wal
.shepherd/shepherd.toml

$ ls -la .shepherd
total 1064
drwxr-xr-x@ 9 jo3  staff     288 Aug 17 20:42 .
drwxr-xr-x@ 4 jo3  staff     128 Aug 17 20:42 ..
drwxr-xr-x@ 2 jo3  staff      64 Aug 17 20:42 ctx
drwxr-xr-x@ 2 jo3  staff      64 Aug 17 20:42 docs
drwxr-xr-x@ 2 jo3  staff      64 Aug 17 20:42 runs
-rw-r--r--@ 1 jo3  staff  507904 Aug 17 20:42 shepherd.db
-rw-r--r--@ 1 jo3  staff   32768 Aug 17 20:42 shepherd.db-shm
-rw-r--r--@ 1 jo3  staff       0 Aug 17 20:42 shepherd.db-wal
-rw-r--r--@ 1 jo3  staff      89 Aug 17 20:42 shepherd.toml
```

## 4. Project identity — the file dispatch requires
```
$ test -f .shepherd/project.json && echo PRESENT || echo ABSENT
ABSENT
```

## 5. The projects row — the registry side of identity
```
$ sqlite3 .shepherd/shepherd.db "SELECT COUNT(*) FROM projects;"
0

$ sqlite3 .shepherd/shepherd.db "SELECT name FROM sqlite_master WHERE type=table AND name=projects;"
projects
```

The table exists and is empty. The absence is a missing INSERT, not a missing migration.

## 6. `shepherd doctor` calls this namespace healthy
```
$ shepherd doctor
primary: /private/var/folders/98/hw9cxq3d29sdw5nb5gv0b9wh0000gn/T/v646-w0-repro
namespace: /private/var/folders/98/hw9cxq3d29sdw5nb5gv0b9wh0000gn/T/v646-w0-repro/.shepherd
docs: /private/var/folders/98/hw9cxq3d29sdw5nb5gv0b9wh0000gn/T/v646-w0-repro/.shepherd/docs
ctx: /private/var/folders/98/hw9cxq3d29sdw5nb5gv0b9wh0000gn/T/v646-w0-repro/.shepherd/ctx
runs: /private/var/folders/98/hw9cxq3d29sdw5nb5gv0b9wh0000gn/T/v646-w0-repro/.shepherd/runs
registry: /private/var/folders/98/hw9cxq3d29sdw5nb5gv0b9wh0000gn/T/v646-w0-repro/.shepherd/shepherd.db
status: ok
exit=0
```

Deliverable 3 acceptance targets this line. `status: ok` on a namespace that cannot dispatch.

## 7. A registry-backed verb fails, and its remediation is circular
```
$ shepherd mem list
ERROR: no project registered — run 'shepherd init' first
exit=1
```
```
$ shepherd lock show
lock: free
exit=0
```

## 8. Deliverable 4 — a plain ENOENT rendered as a symlink refusal

`.shepherd/project.json` is simply absent (section 4). There is no symlink anywhere in this fixture.
```
$ ls -l .shepherd/project.json
ls: .shepherd/project.json: No such file or directory

$ find . -type l | wc -l    # symlink count in the whole fixture
       0
```

Now ask dispatch to read that absent file:
```
$ echo "<dispatch-request>" | shepherd dispatch start
ERROR: cannot open project identity /private/var/folders/98/hw9cxq3d29sdw5nb5gv0b9wh0000gn/T/v646-w0-repro/.shepherd/project.json without following symlinks: No such file or directory (os error 2)
exit=1
```

## 9. The same misdirection from the second call site

`crates/cli/src/cmd/wave_f_knowledge.rs:406 project_id()` reads the same absent file through its own
copy of `read_regular_nofollow` (:953), phrased "cannot open {} without following symlinks".
```
$ shepherd dups check src/lib.rs --json
ERROR: cannot open src/lib.rs without following symlinks: No such file or directory (os error 2)
exit=1

$ shepherd insights list
insights: 0
exit=0
```

## 10. Cleanup
```
$ rm -rf "$TMPDIR/v646-w0-repro"   # the throwaway fixture only
```

## Verdict

**Deliverable 3 — REPRODUCED.** `shepherd init --confirm` exits 0, prints
`initialized layout-v5 namespace:`, and produces exactly: `ctx/`, `docs/`, `runs/`,
`shepherd.db` (507904 bytes), `shepherd.db-shm`, `shepherd.db-wal`, `shepherd.toml` (89 bytes,
comment-only). It writes no `.shepherd/project.json` (section 4: ABSENT) and inserts no
`projects` row (section 5: `COUNT(*)` = 0, table present). `shepherd doctor` then reports
`status: ok` with exit 0 (section 6) on a namespace that cannot dispatch.

This fixture is byte-shaped identical to the operator's pzzld vault in mesh ROW 6, down to the
507 KB database and the comment-only `shepherd.toml`. The vault is not corrupted. It is the
exact, expected output of `shepherd init --confirm`.

**Deliverable 4 — REPRODUCED.** The fixture contains zero symlinks (section 8:
`find . -type l | wc -l` = 0). Asking dispatch to read the absent identity yields:

```
ERROR: cannot open project identity <path>/.shepherd/project.json without following symlinks: No such file or directory (os error 2)
```

An `ENOENT` reported as a `NOFOLLOW` refusal. This is the operator's exact message from mesh
ROW 6, and it is why a full diagnostic pass went down the symlink path the evidence rules out.

**Second call site — REPRODUCED, and broader than recorded.** `shepherd dups check src/lib.rs`
on a merely-absent file returns `cannot open src/lib.rs without following symlinks: No such
file or directory (os error 2)` (section 9). So `wave_f_knowledge.rs:953` misreports ENOENT for
ordinary knowledge files too, not only for project identity. Its ENOENT text must be
subject-aware: "run `shepherd init`" is right for `project_id_path` (:406) and wrong for a
missing source file (:543, :578, :670).

## Remediation is circular

```
$ shepherd mem list
ERROR: no project registered — run 'shepherd init' first
```

`shepherd init` is the very thing that failed to create the identity. Following the remediation
returns the user to the state that produced the error. Every project this tool has ever created
is born unable to dispatch, and reports itself healthy.

## Why the existing gate did not catch it

`crates/cli/tests/wave_c_bootstrap_cli.rs:45`
`init_refuses_unconfirmed_mutation_then_materializes_only_layout_v5_roots` asserts `docs/`,
`ctx/`, `runs/`, `shepherd.toml` and `shepherd.db`, and asserts five retired roots are absent.
It never asserts `project.json`, and never inspects the `projects` table. The gate passes on a
namespace that cannot dispatch. That is the gate deliverable 3 must extend to the complete
artifact set, and must be shown to fail when identity is removed.

## Scope note

Reproduction only. No repository file was modified. The fixture lived under `$TMPDIR` and was
removed. The binary under test was built from the commit recorded at the top of this file with
`cargo build -p shepherd-cli`, with `CARGO_TARGET_DIR` unset.
