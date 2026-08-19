# l5-vocabulary — sandbox.sh falsification, verbatim transcripts

Produced by the successor conductor against
`.shepherd/runs/v651/lanes/l5-vocabulary/sandbox.sh` (446 lines) at base
`b0ad8aa`, with the pre-fix binary preserved from that same base.

The falsification standard: after the fix, `--mode expect-abort` must fail
loudly and exit 1. It does. The assertions that still hold in that run are
exactly the mode-independent negative controls, which is what distinguishes a
relaxation from a disabled check.

| run | binary | mode | exit | result |
|---|---|---|---|---|
| 1 | pre-fix `b0ad8aa` | `expect-abort` | 0 | 28 assertions held, 0 failed |
| 2 | fixed | `expect-fixed` | 0 | 29 assertions held, 0 failed |
| 3 | fixed | `expect-abort` | 1 | 10 failed, 18 held — **the falsification** |
| 4 | n/a | `--mode bogus` | 2 | usage error, refuses to run |

NOTE ON A COLLISION. A coder dispatched by the previous conductor
(`l5-sandbox`) landed a different 755-line `sandbox.sh` over this one at
05:22:07 after failing to answer two status checks and one stand-down. That
version reported a correctly fixed binary as unfixed: its `control2` asserted
that the run id appears in `seed verify` output, which the CLI never prints
(`crates/cli/src/cmd/wave_b2_seed.rs` names the unresolved PATH and the phrase
`run closed`, not the run id), so `--mode expect-fixed` exited 1 against a
good binary. A gate that returns the wrong verdict is the exact defect class
this sprint exists to remove, so it was rejected and this verified version
restored. The rejected file is retained outside the repository at
`scratchpad/sandbox-l5sandbox-rejected.sh` for reference.

---

## Run 1 — pre-fix binary, `--mode expect-abort` (exit 0)

```

sandbox.sh — l5-vocabulary falsification (#324, #319)
  mode:    expect-abort
  binary:  /private/tmp/claude-501/-Users-jo3-src-pzzld-shepherd/30803988-ff6d-40ea-b140-8cbfbb98ce7b/scratchpad/shepherd-prefix-b0ad8aa
  repo:    /Users/jo3/src/pzzld/shepherd/.worktrees/v651-l5-vocabulary
  scratch: /var/folders/98/hw9cxq3d29sdw5nb5gv0b9wh0000gn/T/tmp.u2v0FzpzUx

#324 — models resolve accepts the role by the name every other surface uses
  PASS  canonical: models resolve root --harness claude (exit 0)
  PASS  DEFECT #324 reproduces: resolve shepherd is refused (exit 2)
  PASS  DEFECT #324 reproduces: names shepherd as an unknown role
  PASS  NC8: an unknown role is still refused (both modes) (exit 2)
  PASS  NC8: the refusal still names the offending role

#319 — the seed gate against the real corpus
  PASS  this sprint's own seed passes (both modes) (exit 0)
  PASS  DEFECT #319 reproduces: v646 HARD-fails (exit 1)
  PASS  DEFECT #319 reproduces: the 200-line cap on a 393-line seed
  PASS  DEFECT #319 reproduces: HARD on a path v6.4.6 itself deleted
  PASS  NC7: v645 (historical, no close.md) still HARD-fails (both modes) (exit 1)
  PASS  NC7: v645 keeps its first HARD file_scope failure
  PASS  NC7: v645 keeps its second HARD file_scope failure

#319 — negative controls
  PASS  NC3: run-shaped path, NO close.md -> HARD (both modes) (exit 1)
  PASS  NC3: the HARD message is today's, unchanged
  PASS  DEFECT #319 reproduces: a sibling close.md changes nothing (exit 1)
  PASS  DEFECT #319 reproduces: still HARD with close.md present
  PASS  NC1: close.md beside a NON run-shaped path relaxes nothing (both modes) (exit 1)
  PASS  NC1: the HARD failure survives the stray close.md
  PASS  NC2: the hook's own mktemp copy is immune to a $TMPDIR close.md (both modes) (exit 1)
  PASS  NC2: SEED-GATE still blocks (exit 1 is what the hook denies on)
  PASS  NC4: a closed run's TODO: marker still HARD-fails (both modes) (exit 1)
  PASS  NC4: the relaxation did not leak past the file_scope site
  PASS  NC5: a 401-line sprint-seed is HARD over the 400 ceiling (both modes) (exit 1)
  PASS  NC5: the ceiling names itself
  PASS  NC6: a 401-line patch-seed cannot relabel past the ceiling (both modes) (exit 1)
  PASS  NC6: before the fix, the declared kind sets the hard cap
  PASS  DEFECT #319 reproduces: a 250-line patch-seed HARD-fails (exit 1)
  PASS  DEFECT #319 reproduces: the declared kind sets a hard cap

OK: mode=expect-abort — 28 assertion(s) held, 0 failed.
```

## Run 2 — fixed binary, `--mode expect-fixed` (exit 0)

```

sandbox.sh — l5-vocabulary falsification (#324, #319)
  mode:    expect-fixed
  binary:  /Users/jo3/src/pzzld/shepherd/.worktrees/v651-l5-vocabulary/target/debug/shepherd
  repo:    /Users/jo3/src/pzzld/shepherd/.worktrees/v651-l5-vocabulary
  scratch: /var/folders/98/hw9cxq3d29sdw5nb5gv0b9wh0000gn/T/tmp.eI4AdTPPIU

#324 — models resolve accepts the role by the name every other surface uses
  PASS  canonical: models resolve root --harness claude (exit 0)
  PASS  FIXED #324: resolve shepherd is accepted (exit 0)
  PASS  FIXED #324: resolve shepherd is byte-identical to resolve root
  PASS  NC8: an unknown role is still refused (both modes) (exit 2)
  PASS  NC8: the refusal still names the offending role

#319 — the seed gate against the real corpus
  PASS  this sprint's own seed passes (both modes) (exit 0)
  PASS  FIXED #319: v646 passes (exit 0)
  PASS  FIXED #319: no HARD finding remains on v646
  PASS  FIXED #319: the footprint mislabel is still reported, as a warn
  PASS  FIXED #319: the unresolved path is still reported, as a warn
  PASS  NC7: v645 (historical, no close.md) still HARD-fails (both modes) (exit 1)
  PASS  NC7: v645 keeps its first HARD file_scope failure
  PASS  NC7: v645 keeps its second HARD file_scope failure

#319 — negative controls
  PASS  NC3: run-shaped path, NO close.md -> HARD (both modes) (exit 1)
  PASS  NC3: the HARD message is today's, unchanged
  PASS  FIXED #319: run-shaped path + close.md -> warn, exit 0 (exit 0)
  PASS  FIXED #319: the warn names the unresolved path and why
  PASS  NC1: close.md beside a NON run-shaped path relaxes nothing (both modes) (exit 1)
  PASS  NC1: the HARD failure survives the stray close.md
  PASS  NC2: the hook's own mktemp copy is immune to a $TMPDIR close.md (both modes) (exit 1)
  PASS  NC2: SEED-GATE still blocks (exit 1 is what the hook denies on)
  PASS  NC4: a closed run's TODO: marker still HARD-fails (both modes) (exit 1)
  PASS  NC4: the relaxation did not leak past the file_scope site
  PASS  NC5: a 401-line sprint-seed is HARD over the 400 ceiling (both modes) (exit 1)
  PASS  NC5: the ceiling names itself
  PASS  NC6: a 401-line patch-seed cannot relabel past the ceiling (both modes) (exit 1)
  PASS  NC6: after the fix, the ceiling is 400 regardless of declared kind
  PASS  FIXED #319: a 250-line patch-seed warns rather than blocks (exit 0)
  PASS  FIXED #319: the warn names the mislabel rather than hiding it

OK: mode=expect-fixed — 29 assertion(s) held, 0 failed.
```

## Run 3 — fixed binary, `--mode expect-abort` (exit 1, the falsification)

```

sandbox.sh — l5-vocabulary falsification (#324, #319)
  mode:    expect-abort
  binary:  /Users/jo3/src/pzzld/shepherd/.worktrees/v651-l5-vocabulary/target/debug/shepherd
  repo:    /Users/jo3/src/pzzld/shepherd/.worktrees/v651-l5-vocabulary
  scratch: /var/folders/98/hw9cxq3d29sdw5nb5gv0b9wh0000gn/T/tmp.0c3MG4grJV

#324 — models resolve accepts the role by the name every other surface uses
  PASS  canonical: models resolve root --harness claude (exit 0)
  FAIL  DEFECT #324 reproduces: resolve shepherd is refused
        expected exit 2, got 0; output: opus[1m]
  FAIL  DEFECT #324 reproduces: names shepherd as an unknown role
        expected output to contain: unknown role: shepherd
        actual output: opus[1m]
  PASS  NC8: an unknown role is still refused (both modes) (exit 2)
  PASS  NC8: the refusal still names the offending role

#319 — the seed gate against the real corpus
  PASS  this sprint's own seed passes (both modes) (exit 0)
  FAIL  DEFECT #319 reproduces: v646 HARD-fails
        expected exit 1, got 0; output:   warn  footprint 393 lines > patch cap 200 (kind=patch-seed) — sprint-shaped; relabel or move evidence to mesh.md
  warn  file_scope path does not resolve: bin (run closed — close.md present; a closed run's seed is a record, not a proposal)
OK: 0 hard failures, 2 warning(s)
  FAIL  DEFECT #319 reproduces: the 200-line cap on a 393-line seed
        expected output to contain: HARD  footprint 393 lines > cap 200 (kind=patch-seed)
        actual output:   warn  footprint 393 lines > patch cap 200 (kind=patch-seed) — sprint-shaped; relabel or move evidence to mesh.md
  warn  file_scope path does not resolve: bin (run closed — close.md present; a closed run's seed is a record, not a proposal)
OK: 0 hard failures, 2 warning(s)
  FAIL  DEFECT #319 reproduces: HARD on a path v6.4.6 itself deleted
        expected output to contain: HARD  file_scope path does not resolve and is not marked (NEW): bin
        actual output:   warn  footprint 393 lines > patch cap 200 (kind=patch-seed) — sprint-shaped; relabel or move evidence to mesh.md
  warn  file_scope path does not resolve: bin (run closed — close.md present; a closed run's seed is a record, not a proposal)
OK: 0 hard failures, 2 warning(s)
  PASS  NC7: v645 (historical, no close.md) still HARD-fails (both modes) (exit 1)
  PASS  NC7: v645 keeps its first HARD file_scope failure
  PASS  NC7: v645 keeps its second HARD file_scope failure

#319 — negative controls
  PASS  NC3: run-shaped path, NO close.md -> HARD (both modes) (exit 1)
  PASS  NC3: the HARD message is today's, unchanged
  FAIL  DEFECT #319 reproduces: a sibling close.md changes nothing
        expected exit 1, got 0; output:   warn  file_scope path does not resolve: /var/folders/98/hw9cxq3d29sdw5nb5gv0b9wh0000gn/T/tmp.0c3MG4grJV/repo/bin (run closed — close.md present; a closed run's seed is a record, not a proposal)
OK: 0 hard failures, 1 warning(s)
  FAIL  DEFECT #319 reproduces: still HARD with close.md present
        expected output to contain: HARD  file_scope path does not resolve and is not marked (NEW): /var/folders/98/hw9cxq3d29sdw5nb5gv0b9wh0000gn/T/tmp.0c3MG4grJV/repo/bin
        actual output:   warn  file_scope path does not resolve: /var/folders/98/hw9cxq3d29sdw5nb5gv0b9wh0000gn/T/tmp.0c3MG4grJV/repo/bin (run closed — close.md present; a closed run's seed is a record, not a proposal)
OK: 0 hard failures, 1 warning(s)
  PASS  NC1: close.md beside a NON run-shaped path relaxes nothing (both modes) (exit 1)
  PASS  NC1: the HARD failure survives the stray close.md
  PASS  NC2: the hook's own mktemp copy is immune to a $TMPDIR close.md (both modes) (exit 1)
  PASS  NC2: SEED-GATE still blocks (exit 1 is what the hook denies on)
  PASS  NC4: a closed run's TODO: marker still HARD-fails (both modes) (exit 1)
  PASS  NC4: the relaxation did not leak past the file_scope site
  PASS  NC5: a 401-line sprint-seed is HARD over the 400 ceiling (both modes) (exit 1)
  PASS  NC5: the ceiling names itself
  PASS  NC6: a 401-line patch-seed cannot relabel past the ceiling (both modes) (exit 1)
  FAIL  NC6: before the fix, the declared kind sets the hard cap
        expected output to contain: HARD  footprint 401 lines > cap 200 (kind=patch-seed)
        actual output:   HARD  footprint 401 lines > cap 400 (kind=patch-seed)
FAIL: 1 hard failure(s), 0 warning(s)
  FAIL  DEFECT #319 reproduces: a 250-line patch-seed HARD-fails
        expected exit 1, got 0; output:   warn  footprint 250 lines > patch cap 200 (kind=patch-seed) — sprint-shaped; relabel or move evidence to mesh.md
OK: 0 hard failures, 1 warning(s)
  FAIL  DEFECT #319 reproduces: the declared kind sets a hard cap
        expected output to contain: HARD  footprint 250 lines > cap 200 (kind=patch-seed)
        actual output:   warn  footprint 250 lines > patch cap 200 (kind=patch-seed) — sprint-shaped; relabel or move evidence to mesh.md
OK: 0 hard failures, 1 warning(s)

FAIL: mode=expect-abort — 10 assertion(s) failed, 18 held.
If the fix has landed, this is the expected result: the defects no longer reproduce.
```

## Run 4 — usage guard, `--mode bogus` (exit 2)

```
error: --mode must be expect-abort or expect-fixed (got: bogus)
```
