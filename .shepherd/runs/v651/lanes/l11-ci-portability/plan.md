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

## Status
S1 dispatched | S2 dispatched
