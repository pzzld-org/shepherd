# l5-vocabulary — pre-fix reproduction, recorded by the conductor

worktree: .worktrees/v651-l5-vocabulary   base: b0ad8aa99abf1490e27ee8880dba9fe405ae165c
binary:   target/debug/shepherd, built from that base by `cargo build --locked -p shepherd-cli --bin shepherd`
date:     2026-08-19T09:57:31Z

## #324 — the root role answers to two different names
```
$ shepherd models resolve shepherd --harness claude
ERROR: unknown role: shepherd (valid: root planter engineer conductor critic discovery coder auditor worker)
exit=2
$ shepherd models resolve root --harness claude
opus[1m]
exit=0
$ shepherd models resolve nonsense --harness claude
ERROR: unknown role: nonsense (valid: root planter engineer conductor critic discovery coder auditor worker)
exit=2
```

## #319 — the seed gate hard-fails this project own seeds
```
$ shepherd seed verify .shepherd/runs/v646/seed.md
  HARD  footprint 393 lines > cap 200 (kind=patch-seed)
  HARD  file_scope path does not resolve and is not marked (NEW): bin
FAIL: 2 hard failure(s), 0 warning(s)
exit=1
$ shepherd seed verify .shepherd/runs/v651/seed.md
  warn  footprint 388 lines > smell threshold 300
OK: 0 hard failures, 1 warning(s)
exit=0
```
