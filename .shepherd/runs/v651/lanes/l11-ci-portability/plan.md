# Lane l11-ci-portability

Worktree: /Users/jo3/src/pzzld/shepherd/.worktrees/v651-l11-ci-portability
Branch: v651-l11-ci-portability  Base: 4cff898  Owner: root (shepherd)
Scope (exclusive): scripts/tests/test-release-tar-portability.sh,
                   scripts/create-release-tar.sh,
                   scripts/tests/test-release-workflow.sh

## W0-GATE reproduction (recorded BEFORE any fix)

Linux reproduction is MEASURED, not inferred: docker (server 29.7.2) on this host.

F1 macOS  bsdtar 3.5.3 / libarchive 3.7.4: PASS rc=0
F1 Linux  GNU tar 1.35 (python:3.12-slim): FAIL rc=1, byte-identical to CI:
    create-release-tar: no supported tar ownership flag set (checked GNU --owner/--group and libarchive --uid/--gid)
    FAIL: libarchive: create-release-tar.sh failed under the libarchive-like tar stub

F2 macOS  bash 3.2.57: PASS rc=0 (reaches final ok:)
F2 Linux  bash 5.2.21 (ubuntu:24.04, ruby 3.2.3, ripgrep 14.1.0): FAIL rc=1
    same three ok: lines then silent exit, byte-identical to CI.
    ERR-trap pinpoint: FAILED_AT_LINE=270

## Root cause F2 (root had NOT diagnosed this)

bash 3.2 does not honor `set -e` for a failing `[[ ]]` or `(( ))` compound
command. bash 5.2 does. Measured both ways; ordinary commands abort on both.
=> every bare `[[ ]]` assertion is VACUOUS on macOS and LIVE on Linux.

test-release-workflow.sh:270 `[[ $(rg -Fc 'scripts/create-release-tar.sh' "$workflow") -eq 3 ]]`
Actual count is 2 on BOTH hosts. The assertion has been false since the day it
was written (f3d44b0, v6.4.6 bumped 2 -> 3 while release.yml already had 2).
It never fired because it was authored on macOS bash 3.2. It also prints
nothing when it does fire.

## Steps (wave 1, file-disjoint)

S1 [test-release-tar-portability.sh, create-release-tar.sh] make the libarchive
   stub a faithful double instead of delegating BSD flags to a host tar that
   may reject them; add argv assertions on the selected flag family.
S2 [test-release-workflow.sh] correct line 270 to the true property, give 270
   and 271 real diagnostics, and add a self-lint that bans bare compound
   assertions so the vacuous-on-macOS class cannot recur in this file.

## Status: COMPLETE (root gates; lane does not self-close)

S1 3986166  scripts/tests/test-release-tar-portability.sh
S2 d260436  scripts/tests/test-release-workflow.sh
Branch v651-l11-ci-portability pushed. Not merged; PR #328 untouched.

Wave review run by the lane lead (read-only), NOT by a gate role -- #332 bars
dispatching shepherd:critic or any gate role. Root gates.

Evidence:
  gate.sh fast (macOS): 32 steps, 0 FAILED, green in 16s
  cargo test --workspace --locked --features full: 428 passed, 0 failed / 53 bins
  cargo test --workspace --locked (no --features full): 224 passed, 0 failed / 30 bins
  hooks/tests/run.sh: 29/29, 0 failed
  test-release-tar-portability.sh: 47 checks macOS, 46 Linux, 46 old-libarchive sim
  Four independent negative controls on the tar gate: all caught
  Nine independent probe cases on the self-lint: all correct both directions

Bare-assertion sweep: 15 repo-wide, this lane fixed 2. Remaining 13 out of scope:
  hooks/scripts/_lib.sh 120,369,450 (l7-assertions)
  scripts/tests/test-codex-marketplace.sh 10,11,62,66,68,69,70,71,72
  scripts/tests/test-release-installer-powershell-contract.sh 14
