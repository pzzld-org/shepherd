# Wave audit - distribution lane

**Overall verdict: REDO.** Every falsifiable defect fix (S1, S2, S3 core, S4, S5 core, S6+S9, S7 core, S5f) reproduced correctly under my own independent re-execution and every gate I sabotaged went RED on the exact input the plan specified, then restored clean. But three acceptance lines the plan itself states are currently FALSE in this workspace, and one gate I proved falsifiable is never actually run by anything: `test-release-package-names.sh` (the S3 mirror test) is wired into nothing, `test_cli_authority_gate.sh` (S5's stated acceptance) currently exits 1, `docs/cargo-distribution.md` (in-scope) describes an architecture S6+S9 already replaced, and S7's "one shared assertion" requirement was not met (two independent implementations exist). None of these are self-reported successes I took on trust — I ran every command myself and pasted the output below.

## Summary table

| Step | Claim | Verdict | Evidence command |
|---|---|---|---|
| S1 tar detection | probe-based flag selection, byte-reproducible, false comment gone | **PASS** | `bash scripts/tests/test-release-tar-portability.sh` + 2 falsifications |
| S2 PowerShell `-Force` | only line 371 has `-Force`, contract gate catches its removal | **PASS** | `bash scripts/tests/test-release-installer-powershell-contract.sh` + falsification |
| S3 derived package names (core) | helper + 3 consumers + self-test; corrupted-transform contrast reproduces exactly as predicted | **PASS** | see S3 section |
| S3 gate wiring | `test-release-package-names.sh` runs automatically somewhere | **REDO** | `grep -rl test-release-package-names.sh scripts/gate.sh .github/workflows/*.yml` → no hit |
| S4 crates.io precedence | pre-tag assertion, fail-closed, correct line-boundary ordering check | **PASS** | 3 falsifications, all RED with correct line numbers |
| S4 docs | `docs/cargo-distribution.md` in scope and accurate | **REDO** | doc still says trigger is `push: tags`, contradicts actual `cargo-publish.yml` |
| S5 launcher deletion + authority gate | `bin/shepherd` absent, gate rejects its presence | **PASS** | restore-from-git falsification, `check-cli-authority.py` exit=1 |
| S5 installer dangling self-heal | unconditional self-heal, no FORCE required | **PASS** | read + `test-release-installers.sh` |
| S5 installer live-symlink refusal test coverage | refusal-without-force is unit-tested | **REDO** | sabotaged `install-shepherd.sh:254-256`, full suite stayed green |
| S5 `test_cli_authority_gate.sh` | exit 0 per plan's stated acceptance | **REDO (env-blocked)** | exit=1, traced to cross-lane `hooks/hooks.json` edit outside scope |
| S6+S9 release chain predicate | single script, full truth table, mismatch fails closed | **PASS** | 6/6 truth-table cases + revert-shows-old-bug falsification |
| S6+S9 cargo-publish.yml | trigger off tag, gated on predicate, no publish-on-every-push | **PASS** | read of `cargo-publish.yml:1-81` |
| S7 archive-layout self-test | distinguishes `shepherd` from `dir/shepherd` | **PASS** | `bash scripts/tests/test-release-archive-layout.sh --self-test` |
| S7 one shared assertion | release.yml (S4c) and rust.yml (S7) call the same check | **REDO** | release.yml inlines its own check, does not call the S7 script |
| S7 rust.yml scope | only one job added, `features` untouched | **PASS** | `git diff --stat/--` shows 23 lines added, nothing else |
| S8 README.md line 107 | one-line change, no usable-launcher reference remains | **PASS (content) / REDO (scope literal)** | `git grep bin/shepherd README.md` → none; but diff is 6+4 lines, not one line |
| S5f version-bump self-test | derived, not tautological | **PASS** | sabotaged `_apply_rules` to a no-op independently, went RED |
| Global: `gate.sh fast` | green | **PASS** | exit=0, twice (before and after all falsification work) |
| Global: `w0-reproduce.sh` | defects no longer reproduce | **UNVERIFIED / SCRIPT DEFECT** | 2/5 report "REPRODUCED" but the script's own 1c/1d logic is unconditional/stale, not a fair re-test |
| Global: scope | no file outside lane scope modified by this lane | **PASS (lane itself) / FLAG cross-lane** | see Scope compliance |
| Global: no new `.py`, bash 3.2 safe | | **PASS** | grep, empty |
| Global: floating major action tags | `check-github-actions.py` | **PASS** | exit=0 |

---

## S1 - tar implementation detection

Read `scripts/create-release-tar.sh`: `detect_owner_flags()` runs a real capability probe (creates a throwaway archive) rather than parsing `tar --version`, uses an array (`owner_flags=(...)`) not a string, and the false "shared flag set" comment is gone, replaced with an accurate one at lines 9-14.

```
$ bash scripts/tests/test-release-tar-portability.sh
ok: release tar creation is portable, exact, and reproducible under both GNU-like and old-libarchive-like tar
exit=0
```

Falsification 1 - hardcoded `--owner 0 --group 0` (backed up original first):
```
$ bash scripts/tests/test-release-tar-portability.sh
tar: Option --owner=0 is not supported
FAIL: libarchive: create-release-tar.sh failed under the libarchive-like tar stub
exit=1
```
Restored, `diff` against backup returned exit=0 (byte-identical).

Falsification 2 - hardcoded `--uid 0 --gid 0`:
```
$ bash scripts/tests/test-release-tar-portability.sh
portable tar regression: GNU-like tar rejects BSD-only option --uid
FAIL: gnu: create-release-tar.sh failed under the gnu-like tar stub
exit=1
```
Restored, re-ran: `ok: ... exit=0`.

Stubs verified to model real implementations, not the script's spelling: `tests/test-release-tar-portability.sh`'s GNU stub accepts `--owner`/`--group` in BOTH the separated and compact spelling and rejects `--uid/--gid/--uname/--gname`; the libarchive stub rejects `--owner`/`--group` in BOTH spellings with the runner's exact `tar: Option --owner=0 is not supported` text. Neither stub has the old "accepts `--owner 0` but rejects `--owner=0`" fingerprint bug.

**Verdict: PASS.**

## S2 - PowerShell dangling symlink

```
$ grep -n 'ItemType SymbolicLink' scripts/tests/test-release-installer-windows.ps1
358:    New-Item -ItemType SymbolicLink -Path $linkDestination -Target $linkTarget | Out-Null
371:    New-Item -ItemType SymbolicLink -Path $danglingDestination -Target $missingTarget -Force | Out-Null # -Force: ...
$ bash scripts/tests/test-release-installer-powershell-contract.sh
ok: PowerShell installer declares versioned/latest, checksum, no-clobber, atomic recovery, and path-kind contracts
exit=0
```
Line 358 (live-target symlink) has no `-Force`; line 371 (dangling) does. Correct per plan (`-Force` at the dangling target masks nothing there since the target already exists).

Falsification - stripped `-Force` from line 371:
```
$ bash scripts/tests/test-release-installer-powershell-contract.sh
scripts/tests/test-release-installer-windows.ps1: the dangling-symlink New-Item must pass -Force (PowerShell 5.1 refuses a symlink to an unresolved target)
exit=1
```
Restored, `diff` clean, re-ran: `ok: ... exit=0`.

**Verdict: PASS.**

## S3 - derived package names

```
$ git grep -n 'fl03-' -- scripts/
(no output, exit=1)
$ grep -n 'release-package-names' scripts/verify-release-distribution.sh scripts/verify-release-assets.sh scripts/tests/test-release-distribution-license.sh
scripts/verify-release-distribution.sh:16:source "$repo_root/scripts/lib/release-package-names.sh"
scripts/verify-release-assets.sh:32:source "$(dirname "${BASH_SOURCE[0]}")/lib/release-package-names.sh"
scripts/tests/test-release-distribution-license.sh:7:source scripts/lib/release-package-names.sh
$ bash scripts/lib/release-package-names.sh 6.4.6
pzzld-component-runtime-6.4.6.tgz
pzzld-pi-claude-6.4.6.tgz
pzzld-pi-codex-6.4.6.tgz
pzzld-pi-shepherd-6.4.6.tgz
```
All three consumers source the shared helper, no `fl03-` literal survives in `scripts/`, direct invocation prints exactly the four expected names.

**The critical mirror falsification (mandated, not skipped).** Backed up `scripts/lib/release-package-names.sh`, then corrupted the transform to prepend `fl03-` to every emitted name, and ran BOTH gates:

```
$ bash scripts/tests/test-release-package-names.sh
  FAIL  @pzzld/pi-claude at 2.0.0 -> got "fl03-pzzld-pi-claude-2.0.0.tgz", want "pzzld-pi-claude-2.0.0.tgz"
  FAIL  scoped @acme/widget-tool at 9.9.9 -> got "fl03-acme-widget-tool-9.9.9.tgz", want "acme-widget-tool-9.9.9.tgz"
  FAIL  unscoped widget at 1.2.3 -> got "fl03-widget-1.2.3.tgz", want "widget-1.2.3.tgz"
  FAIL  real manifests produced: fl03-pzzld-... (want pzzld-...)
::error::4 self-test control(s) failed — the transform is not trustworthy.
exit=1

$ bash scripts/tests/test-release-distribution-license.sh
.....
Ran 5 tests in 0.001s
OK
verified legal material inside 16 exact release assets
ok: release sources carry locked notices and package license copies
exit=0
```
Exactly the predicted contrast: the transform self-test goes RED, the license gate stays GREEN because its fixtures and its verifier both derive from the same (now-corrupted) helper and agree with each other even though both are wrong. This is the entire justification for the transform test's existence, and it held under my own sabotage, not the coder's claim. Restored, `diff` against backup clean, both gates re-ran green/expected.

**Gap found - the transform test is never run automatically.**
```
$ grep -rl "test-release-package-names.sh" scripts/gate.sh .github/workflows/*.yml
(no output)
```
`scripts/gate.sh` enumerates each release test explicitly by name (lines 65-72); `test-release-package-names.sh` is not one of them, and no workflow references it either. The exact gate I just proved catches the historical 4-releases-shipped-zero-assets bug class will never run in CI or in `gate.sh fast`/`gate.sh` unless a human invokes it by hand. This is the same "cannot fail because it never runs" pattern the sprint exists to eliminate, just moved one level up (the check itself is fully falsifiable; its execution isn't wired anywhere).

**Verdict: PASS (mechanism) / REDO (wiring).**

## S4 - release.yml crates.io ordering + macOS packaging job

```
$ grep -n 'name: Verify crates.io publication precedes the tag\|name: Tag the verified release commit' .github/workflows/release.yml
539:      - name: Verify crates.io publication precedes the tag
579:      - name: Tag the verified release commit
```
Crates.io check precedes the tag step (539 < 579). Read the step body (lines 539-576): loop of up to 6 attempts / 20s apart / 15s per-request timeout, `curl --fail` failure -> `body=''` -> loop continues -> fails closed after the ceiling; a non-JSON body fails the `jq -e` match -> same fail-closed path; version absent from `.versions[].num` -> same path. Failure message at line 572 names `gh workflow run cargo-publish.yml -f version=%s -f publish=true` exactly.

```
$ bash scripts/tests/test-release-workflow.sh   # baseline
exit=0
$ python3 scripts/check-github-actions.py
ok: 8 workflow files, 54 external uses, 11 repositories; lock age 2d
exit=0
```

Falsification 1 - swapped the crates.io step block to AFTER the tag step:
```
$ bash scripts/tests/test-release-workflow.sh
crates.io publication gate must run BEFORE the tag step (gate at line 587, tag at line 539)
exit=1
```
Correct, non-inverted line numbers (587 > 539, matching the actual post-swap positions). Confirms the "text-matched the word tag in its own prose" bug from a prior version is fixed - it keys on the literal step-name string and the crates.io URL literal, not a loose word match. Restored, diff clean.

Falsification 2 - deleted the crates.io step entirely:
```
$ bash scripts/tests/test-release-workflow.sh
release workflow must gate the tag on a crates.io publication check
exit=1
```
Restored, diff clean.

Falsification 3 - deleted the `verify-macos-archive-layout` job:
```
$ bash scripts/tests/test-release-workflow.sh
expected all five release job checkouts to pin github.sha, found 4
exit=1
```
Caught RED, via a different (earlier, structural) assertion than the macos-14-specific one further down the same script - still a valid, correctly-triggered failure. Restored, diff clean, `gate.sh fast` re-run green (exit=0) after full restoration.

**Finding - `docs/cargo-distribution.md` is stale.** It is IN this lane's file scope and WAS edited (confirmed: `git diff --stat docs/cargo-distribution.md` shows changes), but it still asserts as current fact:
```
$ grep -n 'triggers on\|operator-dispatched' docs/cargo-distribution.md
66:automatic. `cargo-publish.yml` triggers on `push: tags: ["v*.*.*"]`
79:**The crate publish is operator-dispatched.** This is a property of the
```
but the actual file:
```
$ sed -n '1,6p' .github/workflows/cargo-publish.yml
on:
  push:
    branches: [main, master]
```
The trigger was moved off tags by S9, exactly the change the doc's own closing sentence (line 91-93) anticipates: "If a later change moves cargo-publish.yml's trigger off the tag push, this operator step becomes unnecessary and this section should say so instead." That later change landed; the doc was not updated to say so. An operator following this doc today would manually dispatch a now-automatic step, or worse, distrust that automation exists.

**Verdict: PASS (workflow content and falsifiability) / REDO (docs/cargo-distribution.md is out of date within this lane's own scope).**

## S5 / S5b - launcher and installer

```
$ test -e bin/shepherd && echo EXISTS || echo ABSENT
ABSENT
$ python3 scripts/check-cli-authority.py --self-test
check-cli-authority: self-test OK
exit=0
$ python3 scripts/check-cli-authority.py
check-cli-authority: OK (python-routes=106, bash-routes=40, native=73)
exit=0
```

Falsification - restored `bin/shepherd` from `git show HEAD:bin/shepherd` (not `git checkout`, to avoid any index mutation), confirmed the gate rejects it, removed it again:
```
$ python3 scripts/check-cli-authority.py
check-cli-authority: bin/shepherd must not exist: the compatibility launcher is retired (D4) and the native binary resolved from PATH/SHEPHERD_NATIVE_BIN is the sole CLI authority
exit=1
$ rm -f bin/shepherd; rmdir bin
$ git status --porcelain -- bin/
 D bin/shepherd          <- identical to the pre-falsification state
$ python3 scripts/check-cli-authority.py
check-cli-authority: OK (python-routes=106, bash-routes=40, native=73)
exit=0
```

**Installer.** Read `install-shepherd.sh`'s `guard_existing_destination()` (lines 245-277): live symlink -> refuse unless `SHEPHERD_FORCE=1` (line 254-256, exact message names the recovery command); dangling symlink -> unconditional self-heal via `rm -f` (lines 258-271, matches the ROOT-approved policy inversion - **not reported as a defect**, this is intentional per the escalation memo); other existing file -> refuse unless force (274-276). PATH is never touched.

```
$ bash scripts/tests/test-release-installers.sh
shepherd installer: removing dangling symlink at .../dangling/bin/shepherd
ok: release installer platform, URL, checksum, and atomic replacement contracts
exit=0
```

**Load-bearing-half falsification, per the escalation memo's explicit instruction to check this.** I searched the test file for any assertion exercising the live-symlink-without-force refusal (`install-shepherd.sh:255`'s exact message):
```
$ grep -rn "refusing to replace\|symlink to" scripts/tests/test-release-installers.sh scripts/install-shepherd.sh
scripts/install-shepherd.sh:255:  ... fail "refusing to replace ... a symlink to '...'"
```
Zero hits in the test file. To confirm this is a real coverage gap and not a misread, I backed up `install-shepherd.sh`, replaced the live-symlink guard's `fail` with a bare `return 0` (removing the refusal entirely), and ran the full installer suite:
```
$ bash scripts/tests/test-release-installers.sh
shepherd installer: removing dangling symlink at ...
ok: release installer platform, URL, checksum, and atomic replacement contracts
exit=0
```
The suite stayed fully GREEN with the refusal removed. I then manually built the exact scenario (live symlink to an existing target file, installer run without `SHEPHERD_FORCE`) and confirmed the sabotaged installer still refuses in practice - but only because `ln "$ready" "$destination"` (the non-force no-clobber path, line 354) independently fails with EEXIST since a directory entry already exists at that path:
```
--- BEFORE: destination is a live symlink ---
lrwxr-xr-x ... shepherd -> .../real-target
$ SHEPHERD_INSTALL_DIR=... bash scripts/install-shepherd.sh
ln: .../shepherd: File exists
shepherd installer: refusing to replace concurrently created '.../shepherd'
exit=1
--- AFTER: symlink and target content both untouched ---
```
So the end-user-visible behavior survives as an accident of the `ln` hard-link no-clobber mechanism, not because the intended `guard_existing_destination` refusal is verified. If a future change swaps that publication step for anything that doesn't inherently choke on an existing path (e.g. `cp` or a different atomic-rename strategy), this exact refusal could silently disappear with zero test signal - which is the precise risk the escalation memo flagged as "load-bearing." Restored, `diff` against backup clean, suite re-ran green.

**S5's own stated acceptance line currently fails in this workspace.**
```
$ bash scripts/tests/test_cli_authority_gate.sh
check-cli-authority: self-test OK
check-cli-authority: OK (python-routes=106, bash-routes=40, native=73)
rg: /Users/jo3/src/fl03/shepherd/bin: No such file or directory (os error 2)
Traceback (most recent call last):
  File "<stdin>", line 11, in <module>
AssertionError
exit=1
```
Root-caused: the script's hooks.json shape assertion requires every hook be exactly `{"type":"command","command":"shepherd","args":["claude-hook"]}`. Verified against the last COMMITTED `hooks/hooks.json` (via `git show HEAD:hooks/hooks.json`, no working-tree mutation) that all 4 hooks there conform (0 non-conforming). The WORKING-TREE copy of `hooks/hooks.json` (modified by another lane sharing this worktree, outside `distribution`'s scope) now has 11 hooks, 7 of which are non-conforming (added `${CLAUDE_PLUGIN_ROOT}/hooks/scripts/*.sh` hooks). This is NOT a defect in the distribution lane's own S5 work - it is a cross-lane integration collision. But it is a real, currently-reproducible failure of a plan-stated acceptance criterion, and it will keep failing until `hooks/hooks.json` is reconciled before merge.

Also noted: `test_cli_authority_gate.sh` itself is not referenced by `scripts/gate.sh` or any workflow (same orphan-gate pattern as the retired `test_shepherd_native_launcher.sh`), so this failure would go completely unnoticed by any automated run today.

**Verdict: PASS (S5's own code: deletion, gate inversion, dangling self-heal, live-refusal restore falsification) / REDO (missing unit coverage for the live-symlink-without-force path; `test_cli_authority_gate.sh` currently red and unwired, needs conductor attention before merge even though root cause is cross-lane).**

## S6+S9 - release chain fires correctly and can fail

Read `scripts/detect-release-commit.sh` in full: single predicate, three outcomes (`skip`/`proceed`/exit-1-fail), the fail path names both versions on stderr.

Independently built my own scratch `plugin.json` fixtures and ran the full truth table myself (not copy-pasting the coder's fixtures):
```
$ bash scripts/detect-release-commit.sh --subject "v6.4.6" --ref "refs/heads/feature-x" --default-branch main --plugin-json match.json
verdict=skip / reason=ref ... is not the default branch ... / exit=0

$ bash scripts/detect-release-commit.sh --subject "fix: something" --ref "refs/heads/main" --default-branch main --plugin-json match.json
verdict=skip / reason=subject does not match the release pattern ... / exit=0

$ bash scripts/detect-release-commit.sh --subject "v6.4.6" --ref "refs/heads/main" --default-branch main --plugin-json match.json
verdict=proceed / version=6.4.6 / exit=0

$ bash scripts/detect-release-commit.sh --subject "v1.2.3 (#123)" --ref "refs/heads/main" --default-branch main --plugin-json match123.json
verdict=proceed / version=1.2.3 / exit=0

$ bash scripts/detect-release-commit.sh --subject "release: v1.2.3" --ref "refs/heads/main" --default-branch main --plugin-json match123.json
verdict=proceed / version=1.2.3 / exit=0

$ bash scripts/detect-release-commit.sh --subject "v6.4.6" --ref "refs/heads/main" --default-branch main --plugin-json mismatch.json
::error::release commit version mismatch: subject v6.4.6 names v6.4.6, .../mismatch.json reports v6.4.5
exit=1
```
All six cases exactly as specified, both versions named in the mismatch case.

```
$ for f in .github/workflows/*.yml; do grep -c 'release:\[\[:space:\]\]' "$f"; done
0 (all 8 files)
$ grep -rn 'detect-release-commit.sh' .github/workflows/*.yml
cargo-publish.yml:58, release.yml:50, release.yml:439, gitflow.yml:93, gitflow.yml:124
```
No hand-rolled regex copy remains anywhere; both release.yml call sites (step names "Detect exact release version" at line 42 and "Detect release commit" at line 431 - the brief's phrasing assumes identical names, they differ slightly, but both functionally invoke the single script) route through the one predicate, as do gitflow.yml and cargo-publish.yml.

**Revert-and-show-old-bug falsification (the plan names this the acceptance, not optional).** Backed up `detect-release-commit.sh`, reverted the mismatch branch to the OLD behavior (silently `verdict=skip` instead of exit 1):
```
$ bash scripts/detect-release-commit.sh --subject "v6.4.6" --ref "refs/heads/main" --default-branch main --plugin-json mismatch.json
verdict=skip
reason=REVERTED-TO-OLD-BUG version mismatch silently treated as skip
exit=0
```
Confirmed the exact old bug reproduces on revert: a release commit that produced nothing reports green. Restored, `diff` clean, re-ran the mismatch case and got `exit=1` with both versions named again.

**cargo-publish.yml** (read in full, lines 1-103): trigger is `push: branches: [main, master]` (moved off tags, confirmed); the non-`workflow_dispatch` path gates on the identical `scripts/detect-release-commit.sh` call and sets `proceed=false` for anything that isn't `verdict=proceed` (constraint 1, no publish-on-every-push, satisfied); `workflow_dispatch` path is the recovery lane and is not gated on the predicate (by design, an operator names the exact version). `CARGO_REGISTRY_TOKEN` used, no invented secret. `scripts/cargo-publish.py` (the idempotent-download/resume logic referenced by the docs) is unmodified by this lane - confirmed via `git status --porcelain -- scripts/cargo-publish.py` (empty output) - so its already-published-is-success behavior predates this sprint and was not independently re-verified here; flagging as UNVERIFIED BY ME, inherited.

**gitflow.yml** read at lines 55-140: `skip_automatic_or_fail()`'s `:83`-area branch now probes `detect-release-commit.sh` when the release run built a non-default branch, and refuses to silently no-op (`exit 1`) if that head commit IS release-shaped (proceed or fail), while the genuine `:140` "is not a release commit" path stays a clean `skip_automatic_or_fail` (green). This matches the plan; confirmed via static read plus corroborated by `gate.sh fast`'s own "ok: automatic no-op boundary precedes branch and tag custody checks" line, which is this exact assertion running.

**Verdict: PASS.**

## S7 - pre-merge macOS packaging gate

```
$ bash scripts/tests/test-release-archive-layout.sh
ok: release archive places the binary at the archive root, matching bin-dir = "{ bin }{ binary-ext }"
exit=0
$ bash scripts/tests/test-release-archive-layout.sh --self-test
self-test: the layout assertion must be able to fail
binstall archive layout violation
...
wrong entry: "shepherd-1.2.3-aarch64-apple-darwin/shepherd" -- bin-dir = "{ bin }{ binary-ext }" (crates/cli/Cargo.toml:61) requires a bare "shepherd" entry at the archive root; binstall extraction fails on any leading directory component
self-test: confirmed -- a nested "shepherd-1.2.3-aarch64-apple-darwin/shepherd" entry is rejected
ok: self-test passed -- the layout assertion can fail, and does not fail on a correct archive
exit=0
```
The built-in self-test IS the falsification: it builds an archive with `shepherd` nested one directory down and confirms `assert_root_layout` names the offending entry and rejects it, then confirms a correctly-shaped archive still passes. Watched it fail on the broken input and pass on the correct one, in one run.

```
$ git diff --stat .github/workflows/rust.yml
.github/workflows/rust.yml | 23 +++++++++++++++++++++++
1 file changed, 23 insertions(+)
```
Exactly one new job block (`binstall-layout`) added, 23 lines, nothing else in the file touched - confirms the "narrowly granted, nothing else may change" constraint, `features` job (line 152 area) untouched.

**Finding - the "one shared assertion" requirement was not met.** The plan is explicit: "S4's release.yml job catches it at release time. Both are wanted; they must not be two copies of the assertion." Read `release.yml`'s `verify-macos-archive-layout` job (lines 285-317, added under S4c): it does its own independent inline check -
```
entries=$(tar -tzf "$archive")
[[ "$entries" == 'shepherd' ]] || { printf 'binstall archive layout violation: ...'; exit 1; }
```
- rather than calling `scripts/tests/test-release-archive-layout.sh`, which is what `rust.yml`'s new job calls (`scripts/tests/test-release-archive-layout.sh --self-test` and `scripts/tests/test-release-archive-layout.sh`, confirmed in the `rust.yml` diff above). Both check "binary sits at archive root," but they are two independently maintained implementations - the release.yml version doesn't stage LICENSE/THIRD_PARTY_NOTICES/THIRD_PARTY_LICENSES at all and compares against a single-entry string, while the shared script compares an ordered four-entry set. They can drift out of sync with each other with no shared source of truth, exactly the class of duplication the plan called out and forbade.

**Verdict: PASS (self-test falsifiability, rust.yml scope discipline) / REDO (duplicate assertion, not the single shared one the plan required).**

## S8 - README launcher reference

```
$ git grep -n 'bin/shepherd' -- README.md
(no output, exit=1)
$ git diff --stat README.md
README.md | 10 ++++++----
 1 file changed, 6 insertions(+), 4 deletions(-)
```
Content is correct: no reference to `bin/shepherd` as a usable launcher remains; the replacement paragraph correctly documents `cargo install`/`cargo binstall`/`install-shepherd.sh` and states a non-native `shepherd` on PATH is a misconfiguration. But the plan's own file_scope says "README.md EDIT, line 107 ONLY" and its acceptance says `git diff --stat README.md` should show "a one-line change" - the actual diff is a 6-insertion/4-deletion paragraph rewrite spanning several lines, not one line. Minor scope-discipline miss; the substance is right, the literal constraint was exceeded.

**Verdict: PASS (content) / minor REDO (exceeded the plan's stated one-line-only scope).**

## S5f - version authority self-test

```
$ python3 scripts/tests/test-version-bump.py
Ran 5 tests in 0.295s
OK
exit=0
```
Independently sabotaged `_apply_rules` in `scripts/version-bump.py` to a bare no-op (`return dict(contents)`, discarding every rule), differently from however the conductor phrased their own sabotage:
```
$ python3 scripts/tests/test-version-bump.py
FAIL: test_bump_updates_every_authority_and_preserves_history ... 2 != 0 : version-bump: ERROR: 48 files: contains an unclassified 6.4.5 version reference
FAIL: test_stale_surface_refuses_without_partial_write ...
FAILED (failures=2)
exit=1
```
Went RED immediately and correctly (48 stale-version errors surfaced, both dependent tests failed). Restored, `diff` against backup clean, re-ran: `OK`, exit=0.

**Verdict: PASS. Not a tautology - proven by my own independent sabotage, not a re-run of the conductor's.**

---

## Global checks

**`bash scripts/gate.sh fast`** - run twice, before any falsification work and again after all falsifications were restored:
```
[32mgate (fast): green in 15s[0m
exit=0            (both times)
```

**`bash .shepherd/runs/v646/lanes/distribution/w0-reproduce.sh`**
```
== 1a ...        exit=0 under both stubs -> NOT flagged REPRODUCED (fixed)
== 1b ...        -Force present -> NOT flagged REPRODUCED (fixed)
== 1c ...        REPRODUCED: 1c zero of four expected npm assets can ever exist
== 1d ...        REPRODUCED: 1d the tag push cannot trigger cargo-publish.yml
== 2  ...        bin/shepherd is already gone; defect 2 no longer reproduces (fixed)
2 defect(s) still reproduce. Expected 5 or more... exit=1
```
I read `w0-reproduce.sh` line by line rather than trusting the "2 still reproduce" number at face value, because the deliverable statement told me to expect 0. Findings:
- The **1c** check's overlap computation (lines 66-70) unconditionally builds the OLD `fl03-*` list and compares it against the real `pzzld-*` names - `comm -12` of two disjoint-by-construction sets is always `0`, regardless of what the current `verify-release-distribution.sh` actually does. It does NOT re-invoke the current script or its helper.
- The **1d** check (lines 79-84) calls `still '1d the tag push cannot trigger cargo-publish.yml'` completely unconditionally - there is no `if` around it at all. It will report REPRODUCED forever, even now that S9 moved `cargo-publish.yml`'s trigger off the tag entirely (making the "tag push cannot trigger it" framing moot, since it no longer depends on the tag).
- I independently confirmed (S3, S6+S9 sections above) that both underlying defects (1c and 1d) are in fact fixed. **`w0-reproduce.sh`'s 1c/1d checks are themselves broken oracles** - they cannot report anything except REPRODUCED for those two, by construction, regardless of the true state of the code. This file is not in the distribution lane's file scope (owned by whoever wrote the run-level reproduction gate), but its "2 still reproduce" output should NOT be read as evidence the lane is incomplete - it is evidence the reproduction script itself needs a rewrite.

**Scope compliance**

Lane scope: `bin/`, `scripts/` (except `check-github-actions.py`/`check-workspace.sh`/`gate.sh`), `.github/workflows/{release,gitflow,cargo-publish,rust}.yml`, `docs/cargo-distribution.md`, `README.md`.

All tracked modifications inside that scope, confirmed via `git status --porcelain`:
`.github/workflows/{cargo-publish,gitflow,release,rust}.yml`, `README.md`, `bin/shepherd` (D), `docs/cargo-distribution.md`, `scripts/check-cli-authority.py`, `scripts/create-release-tar.sh`, `scripts/install-shepherd.sh`, `scripts/tests/test-release-distribution-license.sh`, `scripts/tests/test-release-installer-powershell-contract.sh`, `scripts/tests/test-release-installer-windows.ps1`, `scripts/tests/test-release-installers.sh`, `scripts/tests/test-release-tar-portability.sh`, `scripts/tests/test-release-workflow.sh`, `scripts/tests/test-version-bump.py`, `scripts/tests/test_cli_authority_gate.sh`, `scripts/tests/test_shepherd_native_launcher.sh` (D), `scripts/verify-release-assets.sh`, `scripts/verify-release-distribution.sh`, `scripts/version-bump.py`, plus new files `scripts/detect-release-commit.sh`, `scripts/lib/release-package-names.sh`, `scripts/tests/test-release-archive-layout.sh`, `scripts/tests/test-release-package-names.sh`. All in scope.

**Outside lane scope, modified by other lanes sharing this worktree** (not this lane's violation, listed for conductor attribution):
- `Cargo.lock` - not `crates/**` or `content/**`, not pre-announced as expected; likely a byproduct of another lane's `crates/cli/Cargo.toml` edit.
- `content/roles/{conductor,engineer,planter}.md` - matches the pre-announced `content/**` exception.
- `crates/cli/Cargo.toml`, `crates/cli/src/cmd/{dispatch,wave_c_bootstrap,wave_f_knowledge}.rs`, `crates/cli/tests/*.rs` - matches the pre-announced `crates/**` exception.
- `hooks/hooks.json`, `hooks/scripts/hook_authority_inventory.py`, `hooks/tests/{lint_agent_capabilities,run,test_legacy_policy_retirement,test_registered_hook_authority,test_registered_hooks_no_python}.sh` - **NOT** in the pre-announced exception list. `hooks/hooks.json` specifically is the direct cause of the `test_cli_authority_gate.sh` failure documented in the S5 section above; this needs reconciliation before any merge that runs that gate.
- `packages/harness-pi/shepherd.pi.json` - not pre-announced.
- New untracked, all outside scope: `.shepherd/runs/v645/carry-forward.md`, `.shepherd/runs/v646/harness-parity.md`, `.shepherd/runs/v646/lanes/harness/`, `.shepherd/runs/v646/lanes/identity/gates-{D,E,F,G,I}.md`, `hooks/scripts/generate_harness_parity.sh`, `hooks/tests/test_harness_parity_generator.sh`, `hooks/tests/test_pi_manifest_drift.sh` - all clearly other lanes' (harness/identity) work products in the shared run directory.

**No file was left modified by my own falsification work.** Every sabotage was backed up before editing and restored byte-for-byte afterward, each confirmed with a `diff`/`cmp` against the backup returning clean, and `git diff --stat` re-checked to show only the lane's own intended changes remaining. `bin/shepherd` was restored via `git show HEAD:bin/shepherd > bin/shepherd` (not `git checkout`) specifically to avoid any index mutation, then `rm -f` + `rmdir` to return it to the exact pre-falsification `D bin/shepherd` working-tree state - confirmed with `git status --porcelain -- bin/` before and after.

**No new `.py` file:**
```
$ git status --porcelain | grep '^??' | grep '\.py$'
(no output, exit=1)
```

**bash 3.2 safety:**
```
$ grep -rn '\${[a-zA-Z_]*,,}\|mapfile\|declare -A' scripts/
(no output, exit=1)
```
(`bin/` no longer exists as a directory at all, consistent with the launcher's total deletion.)

**Floating major action tags:**
```
$ python3 scripts/check-github-actions.py
ok: 8 workflow files, 54 external uses, 11 repositories; lock age 2d
exit=0
```

## Findings

1. **HIGH** - `scripts/tests/test-release-package-names.sh` (the S3 transform self-test, the one gate that proves the derivation isn't a tautology) is not referenced by `scripts/gate.sh` or any `.github/workflows/*.yml`. It is fully falsifiable (I proved it) but will never run unless invoked by hand.
2. **HIGH** - `scripts/tests/test_cli_authority_gate.sh` (S5's own stated acceptance line) currently exits 1 in this workspace, caused by a cross-lane, out-of-scope edit to `hooks/hooks.json` adding 7 hooks that don't match the required `{"type":"command","command":"shepherd","args":["claude-hook"]}` shape. Also itself unwired into `gate.sh`/CI, same orphan-gate pattern as the file it was meant to replace. Needs conductor reconciliation before merge.
3. **HIGH** - `docs/cargo-distribution.md` (in this lane's own scope) describes `cargo-publish.yml` as tag-triggered and crate publish as "operator-dispatched," but S6+S9 already moved the trigger to a gated `push: branches: [main, master]`, making publish automatic. The doc's own closing sentence anticipated this exact change and asked to be updated when it landed; it was not.
4. **MEDIUM** - `install-shepherd.sh`'s live-symlink-without-force refusal (`:254-256`, the escalation memo's named "load-bearing half") has no dedicated regression test. Sabotaging it entirely left `test-release-installers.sh` green; the refusal survives today only as a side effect of the `ln` no-clobber hard-link mechanism in the non-force path, not because it is verified.
5. **MEDIUM** - S7's archive-layout assertion exists in two independently-maintained forms: `release.yml`'s inline check (S4c, single-entry comparison, no legal-file staging) and `scripts/tests/test-release-archive-layout.sh` (S7, four-entry ordered comparison) called only from `rust.yml`. The plan explicitly required one shared assertion; this is a duplicate that can silently drift.
6. **LOW/INFO** - `w0-reproduce.sh`'s 1c/1d checks are structurally broken oracles (unconditional `still` calls / comparison against a hardcoded stale list) and will report REPRODUCED regardless of the true state of the fix. Not this lane's file, but its "2 still reproduce" output should not be read as evidence against this lane.
7. **LOW/INFO** - README.md's S8 edit spans a 6+4-line paragraph rewrite, not the "line 107 ONLY" the plan's file_scope and acceptance both specify; content is correct.
8. **INFO** - `release.yml`'s two `detect-release-commit.sh` call sites are named "Detect exact release version" and "Detect release commit" respectively, not both "Detect release commit" as the audit brief assumed; both correctly call the single script, this is a naming nit only.

## Gate falsifiability

I personally watched each of the following fail on purpose, with the failing output pasted above, then personally restored and re-confirmed green:

| Gate | Watched it fail? | How |
|---|---|---|
| `test-release-tar-portability.sh` | YES (x2) | hardcoded `--owner 0 --group 0`, then `--uid 0 --gid 0` |
| `test-release-installer-powershell-contract.sh` | YES | stripped `-Force` from line 371 |
| `test-release-package-names.sh` | YES | corrupted the helper to emit `fl03-` prefix |
| `test-release-distribution-license.sh` | YES, confirmed it STAYS GREEN under the same corruption (the required contrast) | same corruption as above |
| `test-release-workflow.sh` (crates.io ordering) | YES (x3) | reordered, deleted the crates.io step, deleted the macos-14 job |
| `check-cli-authority.py` | YES | restored `bin/shepherd` from git |
| `test-release-installers.sh` | Attempted, but it did NOT go red when I sabotaged the load-bearing live-symlink refusal (see Finding 4) - this is itself the finding | sabotaged `install-shepherd.sh:254-256` |
| `detect-release-commit.sh` (mismatch case) | YES, both directions | ran the real mismatch input (exit 1), then reverted the fix and re-ran the same input (exit 0, reproducing the old bug) |
| `test-release-archive-layout.sh` | YES, via its own built-in `--self-test` | nested-directory archive rejected by name |
| `test-version-bump.py` self-test | YES | independently sabotaged `_apply_rules` to a no-op |
| `test_cli_authority_gate.sh` | N/A - already red for an unrelated (cross-lane) reason before I touched anything | ran as-is |

## Scope compliance

See the "Scope compliance" subsection under Global checks above for the full accounting. Summary: every tracked file this lane modified is inside its declared scope. `Cargo.lock`, `hooks/**`, and `packages/harness-pi/shepherd.pi.json` are modified in this shared worktree by other lanes and were **not** in the pre-announced `crates/**`/`content/**` exception list - flagged for conductor attribution, and `hooks/hooks.json` specifically is the active cause of one of this report's REDO findings (S5 / `test_cli_authority_gate.sh`). No falsification I performed left any file in a modified state; every sabotage was backed up, diffed clean on restore, and re-verified green before moving to the next step.
