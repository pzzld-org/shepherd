---
title: Central verification audit — v645 W12 (closing wave)
date: 2026-08-13
auditor: central-verification
sprint: v6.4.5-dev.0
concern: regression + completeness (custom central-verify brief, 4-step closing wave)
mode: custom (PASS/REDO per step, no letter grade — brief-defined shape overrides close-mode default)
methodology: superpowers:systematic-debugging — every PASS below is backed by a mutation (break the
  load-bearing line, confirm red, restore, confirm byte-identical via checksum/diff) or an independent
  live reproduction that does not rely on the coder's own test files/claims.
prior_class_priors: DF-77/DF-78 establish that "a shared helper changed, nothing traced its consumers"
  is this sprint's dominant failure class; that prior directly motivated re-baselining EVERY red/green
  claim in this report against a clean `git stash` of the full W12 working tree, not just each step's
  own declared file_scope — which is exactly how the T3 finding below was caught.
---

## Scope reviewed

HEAD at audit start: `6f2eaa9` (confirmed via `git rev-parse HEAD`, matched the brief's stated wave-start
commit — no `WORKTREE-DRIFT`). All work this wave is **uncommitted** in the shared working tree (13
modified + 10 new untracked files, `git diff v6.4.4 --shortstat`: 453 files changed, 46611(+), 696(-)
including the 11 prior committed waves). All 4 declared steps reviewed against their declared
`file_scope`, cross-checked against `out_of_scope_writes` claims, and re-verified against a clean
`git stash` baseline at pure `6f2eaa9` where any claim of "pre-existing" needed confirming.

## Gate results (verbatim)

```
$ bash hooks/tests/run.sh
—— 85/87 passed ——            (exit 2)
Failures: test_v644_wiring.sh (v644-doctrine-wiring, 2 missing legs: #269, #268)
          test_cli_venv_selfheal.sh (cli-venv-selfheal, 7/8: "python3 fallback")

$ cd services/cli && poetry run pytest -q
1893 passed, 25 failed in 664.29s (0:11:04)   (exit 1)
25 failures: test_config_schema.py x2, test_doctor.py x1, test_issues.py x22
  — ALL 25 reproduce byte-for-byte identically at pure 6f2eaa9 baseline (see Verification 3)

$ node --test 'packages/harness-claude/test/*.test.mjs'
tests 8, pass 8, fail 0                        (exit 0)

$ node --test 'packages/harness-codex/test/*.test.mjs'
tests 7, pass 7, fail 0                        (exit 0)

$ node --test 'packages/harness-pi/test/*.test.mjs'
tests 9, pass 9, fail 0                        (exit 0)

$ bin/shepherd guard test
17/17 examples passed                          (exit 0)

$ bash conformance/run.sh --impl=python
conformance: 15/15 passed (suite=ALL)          (exit 0)

$ bash conformance/run.sh --impl=rust
conformance --impl=rust: FAIL -- 0 cases implemented (Rust port not yet built -- W1-W3)  (exit 1)

$ cargo check --workspace
Finished `dev` profile [optimized + debuginfo] target(s) in 0.20s   (exit 0)
```

`df-guard.sh --min=12` run before cargo: `20Gi available at . (min 12Gi) — OK` (re-checked before the
final cargo invocation: `17Gi available`, still OK). No lane `CARGO_TARGET_DIR` to share/delete — this
wave shipped zero crate changes (`git diff 6f2eaa9 --stat -- crates/` is empty), so cargo check is the
one workspace-root build, run last, alone, as instructed.

## Per-step verdicts

### T1-guard-regressions — **PASS**

Files: `hooks/scripts/conductor_write_guard.sh` (+41/-9), `hooks/scripts/session_open.sh` (+10/-2),
`hooks/tests/run.sh` (+15/-0), `hooks/tests/test_shctx_locator.sh` (+20/-2). `test_conductor_write_guard.sh`
genuinely needed no edits (`git diff 6f2eaa9` on that file: empty).

- **Hypothesis**: the Leg1 fix (`unknown` treated as `conductor`-turn) restores 24/24 without
  recreating DF-77's promotion escalation.
- **Falsification**: reverted Leg1 to the exact pre-fix line
  (`[[ "$ROLE" == "conductor" ]] || exit 0`) → `test_conductor_write_guard.sh` → **16/24**, reproducing
  the exact W11 regression number cited in the brief. Restored the original file
  (md5 `c6e6948181e8b523b010aed1cc78fdc3` before and after, byte-identical) → **24/24**.
- **Confidence**: HIGH (structurally verified, live mutation).

Q1's specific ask — "what can `unknown` now do through this guard that it could not do through
`coder_git_guard.sh`" — resolves to: **nothing contradictory for git.** `conductor_write_guard.sh`
explicitly stopped inspecting git at all in v6.3.1 (comment: "git is NO LONGER blocked here"), so both
guards let an `unknown`-resolved git write through — one via loud warn-then-pass
(`coder_git_guard.sh`), one via simply never looking at it. For **non-git** Edit/Write/FS-Bash,
`coder_git_guard.sh` has no opinion at all (`tool_name == "Bash"` gate, and even then only git-shaped
commands) — `conductor_write_guard.sh` is the sole authority and denies `unknown` there by default. The
one place `unknown` gets elevated treatment is the v6.4.1 lane-custody exemption (Edit/Write inside the
conductor's own lane dir passes silently) — this is **correct for the legitimate case** (the
conductor's own direct calls always resolve `unknown` post-DF-77-FIX-2, since they're never in a
dispatch record) and has one **narrow, pre-existing, already-disclosed** residual for the adversarial
case: an uncorrelated dispatched `@coder` sharing its teammate-conductor's `session_id` in TEAMMATE
mode could theoretically hit the same exemption if it targeted the exact lane-plan path. Live-replayed
via `test_conductor_write_guard.sh` case 17 (`tu-17`, an intentionally-unmatched `tool_use_id` — the
same shape an uncorrelated coder call has) — it legitimately PASSes as `lane-custody-exempt`. This is
**not a regression**: `_lib.sh`'s `current_role()` header documents this exact gap under "DF-77 FIX 3,
evidence trail" (root-cause-traced: `tool_use_id` is structurally fresh per call, `session_id` is
shared tree-wide — confirmed against this session's own live dispatch tree), and `dogfood.md` DF-78
independently names it "DOCTRINE GAP UNCLOSED and carried forward." Pre-T1, the state was **strictly
worse** — Leg1 didn't fire for ANY unresolved caller, so this exemption (and every other Leg1 check) was
bypassed for everyone, not just this one narrow path/role combination. T1 narrowed the leak; it did not
open a new one. See audit_findings row 56 (MEDIUM, informational — confirms rather than introduces).

**Undisclosed-but-verified addition**: T1's diff to `hooks/tests/run.sh` wires
`test_agent_invocation_tagger.sh` into the suite for the first time. That test file was added in the W11
commit (`6f2eaa9`) itself but never invoked by `run.sh` — a "gate that cannot fail" in the literal sense
(it could never even run). This is a genuine, valuable fix, but T1's own report narrates only ITEM 1
(Leg1) and ITEM 2 (`announce_registry`); this third change to a declared file goes unexplained. LOW,
filed as audit_findings row 57 — reporting completeness only, not a functional defect.

`announce_registry` gating (ITEM 2): mutation-tested by stripping the `[[ "$announce_registry" != "off" ]]`
guards from `session_open.sh` — reproduces exactly the pre-fix leak (registry line prints even with
`announce_registry = "off"`, and "all-off" silence breaks). Restored, sha1
`cde6c6cb987f1112b51a6b1882e15e13b9e1f5ce` before and after, both green.

### T2-serve-wiring — **PASS**

Files: `packages/harness-claude/{hooks/guard-eval.mjs, hooks/guard-broker-main.mjs (new), src/guard-serve-{engine,broker,client}.mjs (new), test/guard-serve-{corpus,transport}.test.mjs (new), test/support/predicate-corpus.mjs (new)}`,
`packages/harness-codex/{hooks/scripts/shepherd_guard.mjs, package.json, test/guard-serve-{corpus,transport}.test.mjs (new)}`.
LOC: independently summed via `git diff --numstat` (tracked) + `wc -l` (untracked) → +1293/-49 against
the claimed +1291/-49 (2-line rounding noise on one file, immaterial).

- **Q4, kill-mid-session — independently reproduced outside the coder's own test suite.** Wrote a
  standalone script hitting the real *shared default* socket (`defaultSocketPath(contentDir)` →
  `/tmp/shepherd-guard-3a36ae608acf3f49.sock` for this repo's `content/`), confirmed the broker
  (`guard-broker-main.mjs`, pid 98777) and engine (`python -m shepherd_cli guard serve`, pid 98780) were
  live via `lsof -t` + `ps`, then `kill -9 98780` on the **engine** directly (not through any test
  harness). Next request through the SAME socket: `{"ok":false,"detail":"guard serve exited
  (code=null, signal=SIGKILL)"}` in **4ms** — not a hang, not an allow. Confirmed `engineUnavailableVerdict`
  wraps this as `{"permissionDecision":"deny", ...}` (real code, `guard.mjs:176-181`). 500ms later:
  broker pid 98777 gone, engine pid 98780 gone, socket file unlinked (`ls`: No such file or directory) —
  `pgrep -fl "guard-broker-main"` / `"guard serve"` / `"shepherd_cli guard"`: zero hits. **No orphans.**
  The coder's own suite (`guard-serve-transport.test.mjs`, run separately, 8/8 + 7/7) demonstrates the
  same property via isolated tmp sockets; this independent run confirms it on the actual shared
  production socket path too.
- **Wire-shape stability**: `git diff 6f2eaa9 -- packages/harness-claude/src/guard.mjs
  packages/harness-codex/src/guard.mjs` — both empty. Claude's flat `{permissionDecision}` and Codex's
  nested `{hookSpecificOutput:{...}}` shapes confirmed unchanged by direct grep + the live deny payloads
  captured during the node test runs (verbatim in the run logs).
- **Self-caught process deviation** (T2's own disclosure): ran `git add -N` + `git reset` scoped to the
  two harness packages mid-task — a `CODER-GIT-WRITE`-class violation even though content-free.
  Independently confirmed no lasting residue: `git status --porcelain=2` shows the two packages'
  tracked files as plain `.M` (never staged), `git diff --cached --stat` empty. Self-corrected, disclosed
  per CLAUDE.md's honesty standard — LOW, procedural only, no artifact.

### T3-startup-cost — **REDO**

Files: `bin/shepherd` (+44/-0), `services/cli/shepherd_cli/commands/__init__.py` (+18/-7),
`services/cli/tests/test_cli_startup_cost.py` (+319, new).

**DEFECT-1 (venv-python-path cache) and DEFECT-2 (lazy `teammate` import) are both real and correctly
built** — verified below — **but T3 introduced a genuine test regression in a file it did not touch,
and its own report mischaracterizes that failure as pre-existing.** This is the blocking finding.

**Finding (HIGH, audit_findings row 55): `hooks/tests/test_cli_venv_selfheal.sh`'s "python3 fallback"
case is broken by T3's own change, not pre-existing.**
- Hypothesis: T3's report claims `test_cli_venv_selfheal.sh` failure is "pre-existing and outside
  file_scope," confirmed via stashing T1's 4 files. That verification method never touched `bin/shepherd`
  (T3's own file), so it cannot support the claim.
- Falsification, two independent methods:
  1. **Full-tree clean baseline.** `git stash push -u` (everything, all 4 steps) → pure `6f2eaa9` →
     `bash hooks/tests/run.sh` → **83/86**, and `test_cli_venv_selfheal.sh` section reads
     `PASS cli-venv-selfheal` (8/8). `git stash pop` restored the exact 453-file W12 tree
     (`git diff v6.4.4 --shortstat` byte-identical before/after). The arithmetic closes exactly: 83
     baseline + 2 (T1 fixes shctx-locator, conductor-write-guard) + 1 (T1's newly-wired
     agent-invocation-tagger test, itself passing) − 1 (this regression) = **85/87**, exactly what the
     live W12 tree shows.
  2. **Single-file isolation.** With the full W12 tree otherwise intact, copied W12's `bin/shepherd`
     aside, replaced it with `git show 6f2eaa9:bin/shepherd` (pre-T3), reran
     `test_cli_venv_selfheal.sh` alone → **8/8**. Restored the W12 `bin/shepherd` (sha1
     `79428a232cfee2c40c69ecc06714dcf75601be68` confirmed identical before and after) → **7/8**
     reproduces, "python3 fallback" fails again with `out=6.4.4`.
- **Root cause**: `test_cli_venv_selfheal.sh` sets `ROOT="$(cd "$(dirname "$0")/../.." && pwd)"` — the
  **real repo root**, not a throwaway sandbox — then runs the real `$WRAPPER` (`bin/shepherd`) with a
  synthetic `PATH` that has no `poetry`, expecting the documented python3-fallback branch to fire. T3's
  new fast path (`VENV_PY_CACHE="$CLI_DIR/.venv/.shepherd-venv-python"`) checks a cache file **before**
  poetry is ever consulted; on any machine that has ever run `bin/shepherd` successfully once (true of
  this dev machine, and true of CI mid-run once any earlier gate step has invoked `bin/shepherd`), that
  cache is valid and wins regardless of whether `poetry` is on `PATH` at all — the synthetic
  poetry-absent `PATH` the test constructs is never reached, and the stub `python3` (which would have
  printed `python3-fallback --version`) never runs; the real cached interpreter runs and prints the real
  `6.4.4` instead.
- **Why this matters beyond one red line**: the fallback branch this test protects — a machine that
  genuinely never had poetry, #266's literal scenario — is not actually broken (a truly fresh machine
  has no cache file yet, so the fast path correctly falls through; verified separately in Q3 below). What
  is broken is **test coverage**: this specific test can no longer exercise that branch under realistic
  conditions once any cache exists, and nothing in T3's diff or report acknowledges the interaction. The
  fix belongs to T3 (it owns `bin/shepherd` and understands the new cache's shape): isolate this test's
  `CLI_DIR`/cache under a throwaway root (the same pattern the coder itself used correctly for the
  `guard --help` import-graph test), rather than reusing the ambient real-repo cache state.
- **Confidence**: HIGH — reproduced two independent ways, both restore byte-identical.

Everything else in T3 verified sound:
- **DEFECT-1 stale-cache behavior, independently constructed (not the coder's own test), Q3's explicit
  ask**: (a) cache file rewritten with a nonexistent path → `bin/shepherd --version` still succeeds
  (falls through, self-heals the cache back to the real path); (b) synthetic root with a real, executable
  interpreter but *no* console script and *no* `typer` in site-packages (the literal emptied-venv shape
  of #266) → cache correctly refused (`venv_provisioned()` returns false), falls through to
  poetry-resolution, fails with a legible "Poetry could not find a pyproject.toml" — never the silent
  `ModuleNotFoundError` #266 was about. **Proved the check can fail**: stripped the `venv_provisioned`
  call from the fast path (trust any executable cached path blindly) against the same synthetic root →
  reproduced `No module named shepherd_cli` — the exact quieter-#266 shape Q3 warned about — confirming
  my test methodology detects the regression when it exists. Restored `bin/shepherd`, sha1
  `79428a232cfee2c40c69ecc06714dcf75601be68` both before and after.
- **DEFECT-2 lazy import, re-measured independently, 5 runs**: `python -X importtime -m shepherd_cli
  guard --help` → 0/5 runs contain `tortoise` or `commands.teammate` in the import graph (T3's own claim,
  reproduced). `grep -rn "from shepherd_cli.commands import teammate"` across `services/cli` (excluding
  the removed re-export itself): zero hits — nothing else in the codebase depended on the eager
  re-export. Root `--help` (which legitimately resolves every subcommand's help text, per
  `_LazyGroup`) still shows `tortoise`/`commands.teammate` in its import graph (50 matching lines) — the
  documented, deliberate, out-of-scope cost, unchanged by this fix.
- `guard --help` (5 runs, direct venv interpreter, no `poetry run` overhead): 178–280ms vs. root
  `--help`: 810–1220ms — directionally consistent with the claimed ~104–141ms vs. baseline, absolute
  numbers higher only because this machine was concurrently running the full node/pytest/cargo gate
  suite for this same audit.
- `test_cli_startup_cost.py` run standalone: **7/7 passed** in 4.52s.

### T4-plan-parity — **PASS**

Files: `skills/context/scripts/cmd_plan.sh` (+38/-1), `services/cli/tests/test_plan_amend.py` (+15/-0).

- **Delegation, not reimplementation**: `_cmd_amend`/`_cmd_lane_drift` resolve `shctx_repo_root` and exec
  `"$repo/bin/shepherd" plan amend/lane-drift "$@"` — confirmed by reading the diff directly; no
  bash+heredoc reimplementation exists. `services/cli/shepherd_cli/commands/plan.py` diff against
  `6f2eaa9`: **empty** — T4 touched none of the actual amend/lane-drift logic, exactly as scoped.
- **Working-tree fix is real, independently confirmed**: `bash skills/context/scripts/shctx plan amend`
  (the actual repo script, not the stale global wrapper) → `ERROR: --plan <path> required and must
  exist` (exit 2) — a real validation error, not `unknown subcommand: amend`. The globally-installed
  `~/.local/bin/shctx` wrapper globs `~/.claude/plugins/cache/*/shepherd/*` and resolves to the latest
  **installed** release (frozen at 6.4.4, confirmed via `ls -d`) — it cannot and does not reflect this
  uncommitted branch; T4's disclosure of this environmental fact is accurate.
- **`shepherd plan lane-drift v645` failure (test #269) independently reproduced and root-caused**:
  `~/.local/bin/shepherd` is a symlink straight to `bin/shepherd` in this working tree (`readlink -f` →
  `/Users/jo3/src/fl03/shepherd/bin/shepherd`), so it DOES reflect the fix — yet
  `shepherd plan lane-drift v645` → `Specified path '/Users/jo3/.local/services/cli' is not a valid
  directory` (exit 1). Root cause: `bin/shepherd`'s `SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"`
  does not dereference a symlinked invocation when `CLAUDE_PLUGIN_ROOT` is unset (true in this shell),
  so `ROOT` resolves to `~/.local` instead of the repo. Confirmed this exact code block (`ROOT`
  resolution, lines ~55-63) is **byte-identical** between `6f2eaa9` and the W12 tree (`diff` on that
  region: empty) — genuinely pre-existing, not caused by T3's cache addition despite both touching
  `bin/shepherd`. Neither T4 (bash-layer scope only) nor T3 (declared scope excludes this resolution
  block) could fix this within file_scope. `CLAUDE_PLUGIN_ROOT` is set by Claude Code in every real
  production invocation, so this only manifests via the operator's personal `~/.local/bin` convenience
  symlink — narrow, real, honestly red.
- **DF-77 message-fix regression test, mutation-proved**: reverted
  `services/cli/shepherd_cli/commands/plan.py`'s accurate conditional amend message back to the old,
  false unconditional "`'shctx plan verify' now passes...`" text → `test_plan_amend.py` →
  1 failed / 4 passed (the new pinning assertion catches it). Restored `plan.py`
  (sha1 `0f523444445e6661688ad354389ff1b474062684` before and after) → 5/5 passed. `plan.py` itself carries
  zero diff vs `6f2eaa9` — the accurate message was already shipped by DF-77 in W11; T4 only added the
  regression-pinning test, as claimed.

## Q1 — conductor_write_guard.sh enforcement

Answered in full under T1 above. **24/24 confirmed and mutation-proven.** No contradiction found with
`coder_git_guard.sh` for git (both consistently pass-through `unknown`-role git writes, by different but
compatible mechanisms). One narrow, pre-existing, already-disclosed residual (lane-custody exemption +
uncorrelated TEAMMATE-mode coder call) verified via live replay, not a new escalation — see audit_findings
row 56.

## Q2 — honest red/green

`test_shctx_locator.sh`: mutation-tested (stripped the `announce_registry` gate) → reproduces the exact
leak; restored → green, byte-identical. Behavior genuinely changed, not the assertion.

`test_v644_wiring.sh` / `test_cli_venv_selfheal.sh`: `git diff 6f2eaa9` on both test files is **empty** —
neither assertion was touched, loosened, or reworded. Both remaining reds are genuine:
- `test_v644_wiring.sh`'s two legs (#269, #268-bash) are honestly red, root-caused to two separate,
  verified-pre-existing environment facts (the `BASH_SOURCE` symlink-dereference gap in `bin/shepherd`,
  and the stale globally-installed `shctx` wrapper) — see T4 above.
- `test_cli_venv_selfheal.sh` is honestly red but **for a different reason than claimed**: it is a real
  regression from T3, not pre-existing (see T3 REDO finding above). The test itself was not edited or
  loosened; the code path it exercises changed under it.

## Q3 — startup fixes and #266

Both defects re-measured independently with the auditor's own commands, 5 runs each — see T3 section
above for full detail and numbers. **The stale-cache scenario was constructed twice**: a nonexistent
cached path (self-heals, falls through) and a fully-provisioned-looking-but-actually-empty synthetic
venv (the literal #266 shape — correctly refused by `venv_provisioned()`, falls through, fails with a
legible poetry error, never a bare `ModuleNotFoundError`). The check's ability to catch a real
regression was proven by deliberately breaking it (removing the `venv_provisioned` guard) and watching
`No module named shepherd_cli` reproduce — the exact "quieter #266" the brief warned about — then
restoring byte-identical. **#266 itself is not recreated.** What the cache DID break is an unrelated
sibling test's isolation (`test_cli_venv_selfheal.sh`'s "python3 fallback" case) — flagged as the T3 REDO
finding, not a #266 recurrence.

## Q4 — guard serve wiring

Answered in full under T2 above, with an **independent** live kill (not the coder's own test suite) against
the real shared default socket: engine killed directly by pid, next request denies in 4ms, broker and
engine both gone within 500ms, socket unlinked, zero orphan processes (`pgrep` clean). Both wire shapes
(`guard.mjs` in both packages) confirmed byte-unchanged.

## Q5 — sprint-close accounting

- `git diff v6.4.4..HEAD --shortstat` (committed, 11 waves, W1–W11): **448 files changed, 46383
  insertions(+), 677 deletions(-)**. Including this wave's uncommitted W12 diff on top
  (`git diff v6.4.4 --shortstat`): **453 files changed, 46611(+), 696(-)**.
- **Predicate interpreters in `packages/`: 1**, confirmed by direct inspection — `services/cli/
  shepherd_cli/predicates.py` (Python, `bin/shepherd guard eval`/`guard serve`) is the sole evaluator.
  `packages/harness-claude/src/guard.mjs` and `packages/harness-codex/src/guard.mjs` are both explicitly,
  by their own module-header contract, "deliberately NOT a predicate interpreter" — pure relays.
  `packages/harness-pi/src/guard-client.ts`'s header states outright: "Replaces `src/guard.ts`'s local
  predicate interpreter (C1-pi-collapse): the local port is gone, this is the one interpreter... Pi's
  guard layer defers to." That deletion (`guard.ts` −137, `predicates.mjs` −105 = −242 lines, matching
  the CHANGELOG's figure exactly) landed in the W11 commit (`6f2eaa9`), confirmed via `git show
  6f2eaa9 --stat`. `crates/cli/src/*.rs` and `crates/core/**`: zero guard/predicate files
  (`find crates -iname '*guard*' -o -iname '*predicate*'`: empty). Target of 1 (down from 3) is **met**.
- `hooks/tests/run.sh`: **85/87.** Two named failures:
  1. `test_v644_wiring.sh` (`v644-doctrine-wiring`) — **honestly red, open issue.** Root-caused to two
     genuinely pre-existing, out-of-any-step's-file_scope bugs (the `bin/shepherd` symlink/`BASH_SOURCE`
     resolution gap, and the stale globally-cached `shctx` wrapper). Neither is a broken test.
  2. `test_cli_venv_selfheal.sh` (`cli-venv-selfheal`, "python3 fallback") — **honestly red, but
     misattributed.** Not pre-existing; caused by T3's own change (see REDO finding). Not a broken test
     either — the assertion is sound, the code path it protects moved.
- `conformance/run.sh --impl=rust`: **still 0 cases, exit 1**, matching seed deliverable #239's
  acceptance exactly. Openly unmet, correctly so — `crates/cli` has no `guard`/`run init`/`run show`
  surface yet (confirmed by grep), and no wave this sprint claimed otherwise.
- `services/cli` pytest: **1893 passed, 25 failed.** All 25 (`test_config_schema.py` x2,
  `test_doctor.py::test_version_match_emits_no_row`, `test_issues.py` x22) reproduce **byte-for-byte
  identically** against a pure `6f2eaa9` baseline via `git stash push -u` / `pop` (26 selected via
  targeted node-id matching against the full failure list, 24 matched by name-pattern + 1 confirmed
  individually — `test_classify_md_renders_full_detail_sections_bash_crashes_here`). Root cause for all
  25: this machine's `bash --version` is `3.2.57(1)-release`; `cmd_issues.sh` requires bash 4+ for
  associative arrays and self-guards with `ERROR: shctx issues requires bash 4+`
  (`skills/context/scripts/cmd_issues.sh:20-22`, explicitly documents "macOS ships bash 3.2 by default").
  None of the 4 W12 steps touch `commands/issues.py`, `cmd_issues.sh`, `config_schema`, or `doctor.py` —
  confirmed via file_scope review. Pre-existing, environmental, not this sprint's regression, matching
  this repo's own standing `bash 3.2 portability` constraint.

## Verifications (hypotheses disproved)

1. "T1's Leg1 fix re-creates the DF-77 escalation" — disproved; mutation-tested, and the one residual
   gap found is pre-existing/disclosed, not new (see Q1).
2. "The venv-python-path cache can exec a dead interpreter, recreating #266 quietly" — disproved for the
   cache's own contract (stale-path and unprovisioned-but-present cases both correctly fall through);
   the real defect found is a sibling test-isolation break, not a #266 recurrence (see T3 REDO).
3. "The 25 services/cli pytest failures are new, undisclosed regressions from this wave" — disproved;
   all 25 reproduce identically at the pure `6f2eaa9` baseline via full-tree `git stash`.
4. "guard serve leaves orphan processes or hangs/allows on engine death" — disproved via an independent
   live kill against the real shared socket (not the coder's own isolated-tmp-socket tests).
5. "test_v644_wiring.sh's two reds are broken tests, not real gaps" — disproved; both test files carry
   zero diff vs. `6f2eaa9`, and both failures root-cause to real, reproducible environment facts.

## Open questions

- Whether `#266` (still OPEN on GitHub) should be administratively closed: its underlying self-heal
  mechanism (`venv_provisioned`, pre-dating this wave) already resolves the original symptom; this
  wave's caching layer does not reopen it. Closing is a conductor/root call, not this audit's to make.
- Whether `bin/shepherd`'s `BASH_SOURCE`-symlink-resolution gap (surfaced via `test_v644_wiring.sh` #269)
  merits its own GH issue distinct from #239 ("retire the bash layer") — it currently has no dedicated
  tracking; low urgency since it only manifests through an operator convenience symlink, never through
  the `CLAUDE_PLUGIN_ROOT`-set production path.

## Pattern delta

DF-77/DF-78 (prior waves) established "a shared helper changes, nothing traces consumers with equal
rigor to what changed vs. what's inherited" as this sprint's dominant failure class. The T3 finding in
this wave is a direct instance of the SAME pattern one layer up the stack: a step verified its own new
code's correctness in isolation (and did so well — DEFECT-1/DEFECT-2 are both solid) but verified
"pre-existing" for a failing test in its own declared file_scope by stashing a *different* step's files,
not its own. **Systemic risk: not yet 3+ occurrences across 3+ sprints in this exact shape (single-wave
first observation), but flagged because it is the third time this sprint a "confirmed pre-existing via
stash" claim used an incomplete stash set** (DF-78 itself documents S1 and S4 both flagging
`conductor_write_guard.sh:93` without either acting; this is the same "the verification method's scope
didn't match the claim's scope" shape, not a coincidence). Recommend: any "confirmed pre-existing" claim
during multi-lane concurrent waves must stash the FULL working tree, not just the claiming step's own
files, before it can be asserted in a CODER REPORT.

## Cache telemetry

`shctx query cache-usage` view: not probed this audit (out of the explicit Q1–Q5 scope given in the
dispatch brief; the brief's own required-gates list does not include it, and this is a custom
central-verify brief, not a standard completeness-concern close audit).

## Grade

n/a — this is a custom central-verification brief (PASS/REDO per step, no letter grade requested).

## Grade rationale

3 of 4 steps PASS outright (T1, T2, T4), each with at least one load-bearing mutation test proving the
gate can fail before certifying it green. T3 REDO is scoped narrowly: DEFECT-1 and DEFECT-2 (the actual
performance work) are sound and independently re-verified; the blocking item is a single test file
(`hooks/tests/test_cli_venv_selfheal.sh`) whose isolation assumption broke under T3's own new code, plus
a report that asserted "pre-existing" without a baseline strong enough to support that claim. Fix
direction: give that test its own throwaway `CLI_DIR`/cache root (mirroring the isolation pattern T3
itself used correctly elsewhere in the same PR), then re-run `hooks/tests/run.sh` to confirm 86/87 (only
the genuinely pre-existing `test_v644_wiring.sh` red remaining).

## Output to conductor

```
## AUDITOR REPORT
- deliverable: 15 (status: delivered)
- Concern: regression + completeness (custom central-verify, closing wave W12)
- Mode: custom (PASS/REDO per step)
- Files reviewed: 23 (13 modified + 10 new, all 4 steps' declared file_scope + cross-checked
  out_of_scope_writes)
- Findings: CRITICAL=0, HIGH=1, MEDIUM=1, LOW=2
- Verifications (disproved): 5
- Open questions: 2
- GH issues filed: none (all relevant gaps already tracked: #266, #268, #269, #287, #288, #239 — all
  confirmed OPEN and accurately described by existing bodies; no new issue needed)
- Grade: n/a (custom PASS/REDO brief, not close-mode grading)
- Report path: /Users/jo3/src/fl03/shepherd/.shepherd/runs/v645/reports/auditor-W12-central-verify.md
- Hot-fix-lane recommendations: 1 — T3-startup-cost: isolate test_cli_venv_selfheal.sh's CLI_DIR/cache
  root instead of reusing the ambient real-repo state; re-run hooks/tests/run.sh to confirm 86/87.
- Sprint-pattern entry: written (Pattern delta section — "verification scope narrower than claim scope"
  recurrence, third instance this sprint)
- Agent ID + timestamp: central-verification-w12 @ 2026-08-13T23:58:00Z
```

## PER-STEP VERDICT SUMMARY (as required by the dispatch brief)

| Step | Verdict | Blocking items |
|---|---|---|
| T1-guard-regressions | **PASS** | none |
| T2-serve-wiring | **PASS** | none |
| T3-startup-cost | **REDO** | `hooks/tests/test_cli_venv_selfheal.sh` "python3 fallback" case broken by the new `VENV_PY_CACHE` fast path in `bin/shepherd`; report mischaracterized it as pre-existing. Isolate the test's venv/cache root, re-verify 86/87 on `hooks/tests/run.sh`. |
| T4-plan-parity | **PASS** | none |
