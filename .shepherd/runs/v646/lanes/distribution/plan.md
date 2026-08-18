# v6.4.6 lane: distribution

Make `cargo binstall shepherd-cli` reach a real asset, make `shepherd` on PATH always be the
native binary, and make the release gate capable of failing. Authored by the lane conductor
after a full recon pass; every file:line below was read, not inferred. Baseline evidence is
`w0-reproduce.sh` in this directory, which reproduces all five defects and is re-runnable.

## Defect map

| Defect | Severity | Step | Files | Locally provable? |
|---|---|---|---|---|
| 1a macOS arm64 packaging dies on the runner's tar | BLOCKER | S1 | `scripts/create-release-tar.sh`, `scripts/tests/test-release-tar-portability.sh` | YES, in full, via stubs modelling both real tars |
| 1b PowerShell 5.1 refuses a dangling symlink | BLOCKER | S2 | `scripts/tests/test-release-installer-windows.ps1`, `scripts/tests/test-release-installer-powershell-contract.sh` | Contract gate only; the ps1 needs Windows |
| 1c asset verifier expects tarballs npm never emits | BLOCKER | S3 | `scripts/verify-release-distribution.sh`, `scripts/tests/test-release-distribution-license.sh`, NEW helper, `scripts/verify-release-assets.sh` | YES, in full |
| 1d release can be cut before crates.io; tag cannot trigger publish | BLOCKER | S4 | `.github/workflows/release.yml`, `scripts/tests/test-release-workflow.sh`, `docs/cargo-distribution.md` | Assertion logic YES; runner behaviour NO |
| 2 repo launcher shadows the native binary | BLOCKER | S5 | `bin/shepherd` DELETE, `scripts/install-shepherd.sh`, `scripts/check-cli-authority.py`, `scripts/tests/test_cli_authority_gate.sh`, `scripts/tests/test_shepherd_native_launcher.sh` DELETE | YES for the repo half; `doctor` half is PENDING-ESCALATION |
| 7 the release gate reports success for a no-op | HIGH | S6 | `.github/workflows/release.yml` detect step, `.github/workflows/gitflow.yml`, `scripts/tests/test-release-workflow.sh` | YES, by extracting the predicate |

S4 and S6 both touch `release.yml` and `test-release-workflow.sh`. They are therefore
SEQUENTIAL, not parallel: S6 runs in wave 1b after S4 is reviewed. Everything else is
file-disjoint and fires together.

## Constraints

1. GitHub Actions references use FLOATING MAJOR VERSION TAGS (`@v7`, `@v2`), never commit
   SHAs. `scripts/check-github-actions.py` enforces the major tag and rejects a SHA.
2. Do not relax `disabled-strategies` in `crates/cli/Cargo.toml:63`. A loud binstall 404 is
   the specified behaviour.
3. Do not author a new release workflow. `gitflow.yml` already implements tag -> release ->
   version bump -> next patch branch -> draft PR -> milestone roll, and mod-10 is enforced
   twice (`gitflow.yml:130-145`, `scripts/version-bump.py:86` `successor()`).
4. Do not add a post-release `gh workflow run` dispatch for cargo-publish; that inverts
   phases 2 and 3. The fix is a fail-closed PRE-TAG assertion.
5. Do not run installers, publish anything, `git commit`, or `git push`.
6. Every gate touched or added must be shown to fail on purpose, with the failing output
   recorded in the lane artifact.
7. Tests ship in the same change as the fix. Prefer Rust-native tests. Introduce no new
   Python FILE; an inline `python3 -c` inside an existing bash script matches repo practice.
8. Bash must be bash-3.2 safe: no `${var,,}`, no `mapfile`, no `declare -A`.
9. Much of deliverable 1 is verifiable only on CI. Say plainly what remains unverified.
   Never claim a CI-only fix is locally verified.

## Wave 1

### S1 - tar implementation detection

**file_scope (exclusive):** `scripts/create-release-tar.sh` EDIT,
`scripts/tests/test-release-tar-portability.sh` EDIT.

**Defect.** `scripts/create-release-tar.sh:41` runs
`tar --format=ustar --owner 0 --group 0 --numeric-owner` under a comment at `:37-39`
asserting that flag set is shared by GNU tar and bsdtar. False. GNU tar has
`--owner`/`--group` and no `--uid`/`--gid`; older libarchive has the inverse. Run
`31895705712` died on `macos-14` with `tar: Option --owner=0 is not supported`.

**The gate was fitted to the bug, and this is the real finding.**
`scripts/tests/test-release-tar-portability.sh:26-53` already stubs a tar. That stub rejects
`--uid`/`--gid`/`--uname`/`--gname` AND rejects the compact `--owner=0`/`--group=0`, while
accepting the separated `--owner 0`/`--group 0`. No implementation behaves that way: GNU
accepts both spellings of `--owner`, old libarchive rejects both. The stub is a fingerprint
of the current script, not a portability model. Measured: the gate PASSES while the script
dies under a realistic old-libarchive stub, and the runner's actual error string appears
**0 times** in the gate. That is why commit `4c7c050` (`--owner=0` -> `--owner 0`) read as a
fix. Do not preserve this stub's semantics.

**Change.** Detect the tar implementation once, then emit the matching ownership flags.
Probe `tar --version` for `bsdtar`/`libarchive` versus `GNU tar`, and prefer a capability
probe over a version string where practical (run the candidate flags against an empty
archive and fall back). GNU gets `--owner 0 --group 0 --numeric-owner`; libarchive gets
`--uid 0 --gid 0 --uname "" --gname ""` or its supported equivalent. Delete the false
comment and replace it with the actual asymmetry. Output must stay byte-reproducible ustar
with uid/gid 0 and pinned mtime. Keep the `--` options terminator that protects
option-shaped entry names.
Rebuild the test so it runs the script against TWO stubs that model REAL implementations:
one GNU-like (accepts `--owner`/`--group` in both spellings, exits non-zero on `--uid`/
`--gid`), one old-libarchive-like (exits non-zero on `--owner`/`--group` in both spellings
with the runner's exact `Option --owner=0 is not supported` text, accepts `--uid`/`--gid`).
The script must produce a valid, byte-identical-on-repeat archive under BOTH.

**ACCEPTANCE.**
```
bash scripts/tests/test-release-tar-portability.sh          # exit 0
bash .shepherd/runs/v646/lanes/distribution/w0-reproduce.sh # 1a no longer reproduces
bash scripts/gate.sh fast                                   # still green
```

**FALSIFICATION.** Hardcode a single flag set in `create-release-tar.sh` (either
`--owner 0 --group 0` or `--uid 0 --gid 0`) and re-run the gate. It MUST go red under
whichever stub that set offends, naming the stub. Record both the edit and the failing
output. A gate that stays green under a hardcoded flag set has reproduced the original
defect and is not done.

### S2 - PowerShell dangling symlink

**file_scope (exclusive):** `scripts/tests/test-release-installer-windows.ps1` EDIT,
`scripts/tests/test-release-installer-powershell-contract.sh` EDIT.

**Defect.** `scripts/tests/test-release-installer-windows.ps1:371` runs
`New-Item -ItemType SymbolicLink -Path $danglingDestination -Target $missingTarget` to build
a DELIBERATELY dangling symlink. Windows PowerShell 5.1 refuses to create a symlink whose
target does not exist without `-Force`, so the test dies before it can assert anything:
`New-Item : Cannot find path '...\missing.exe' because it does not exist.`

**Change.** Add `-Force` to the dangling-symlink creation at `:371` only. Leave `:358`
alone: its target exists, so `-Force` there would mask a real failure rather than enable an
intentional one. Add a comment stating WHY `-Force` is required, so it is not removed later
as noise. Then extend the contract gate so the requirement is machine-checked: assert that
any `New-Item -ItemType SymbolicLink` whose target is the known-missing fixture carries
`-Force`.

**ACCEPTANCE.**
```
bash scripts/tests/test-release-installer-powershell-contract.sh   # exit 0
bash scripts/gate.sh fast                                          # still green
```

**FALSIFICATION.** Remove `-Force` from `:371` and re-run the contract gate. It MUST go red
and name the line. Record the failing output.

### S3 - derive package names from package.json

**file_scope (exclusive):** `scripts/verify-release-distribution.sh` EDIT,
`scripts/tests/test-release-distribution-license.sh` EDIT, `scripts/verify-release-assets.sh`
EDIT, and ONE NEW shared helper `scripts/lib/release-package-names.sh` NEW (create
`scripts/lib/` if absent).

**Defect.** `scripts/verify-release-distribution.sh:87-92` loops
`for package in component-runtime harness-claude harness-codex harness-pi` and extracts
`fl03-${package}-${version}.tgz`. Those are DIRECTORY names with a wrong scope prefix. The
real package names are `@pzzld/component-runtime`, `@pzzld/pi-claude`, `@pzzld/pi-codex`,
`@pzzld/pi-shepherd`, so `npm pack` emits `pzzld-component-runtime-6.4.6.tgz`,
`pzzld-pi-claude-6.4.6.tgz`, `pzzld-pi-codex-6.4.6.tgz`, `pzzld-pi-shepherd-6.4.6.tgz`.
Measured overlap: **0 of 4**. Not three of four wrong; four of four. This runs at
`release.yml:483` inside the publish job, so even a green build dies here.
`scripts/tests/test-release-distribution-license.sh:79` synthesizes its fixtures under the
SAME stale `fl03-*` names, which is precisely why the gate stayed green: the test builds the
wrong artifact and the verifier looks for the wrong artifact, and they agree.

**Corroborating fact the coder must use.** `scripts/verify-release-assets.sh:33-36` ALREADY
uses the correct `pzzld-*` names. The repo ships two asset verifiers that disagree, and
`release.yml` calls the wrong one. Do not "fix" this by copying the correct literals into
the second file; that leaves three hardcoded lists free to drift again.

**Change.** Write `scripts/lib/release-package-names.sh` exposing one function that scans
`packages/*/package.json`, reads `name` and `version`, and emits the exact npm-pack tarball
name per package: scope `@a/b` -> `a-b-<version>.tgz`, unscoped `b` -> `b-<version>.tgz`.
Bash 3.2 safe: no associative arrays, no `mapfile`; emit newline-delimited text and read it
with a `while read` loop. An inline `python3 -c` for the JSON read is acceptable and matches
`scripts/gate.sh` practice; do NOT add a new `.py` file. All THREE consumers source this
helper. No `fl03-` literal survives anywhere in `scripts/`. The license gate's fixtures must
be generated from the same helper, so a rename in any `package.json` moves the fixture and
the verifier together and can never again agree on a name that does not exist.

**ACCEPTANCE.**
```
bash scripts/lib/release-package-names.sh 6.4.6    # prints exactly the four pzzld-* names
bash scripts/tests/test-release-distribution-license.sh   # exit 0
git grep -n 'fl03-' -- scripts/                    # no hits
bash scripts/gate.sh fast                          # still green
```

**FALSIFICATION.** Two required, because this defect is a mirror:
1. Point the helper at a bogus name (e.g. force `pzzld-pi-claude` -> `pzzld-pi-bogus`) and
   re-run the license gate. It MUST go red on a missing tarball.
2. THE IMPORTANT ONE: change ONLY the verifier's expectation while leaving the fixture
   generator alone. The gate MUST go red. If it stays green, the mirror is still in place
   and the fix has not landed. Record both.

### S4 - release.yml crates.io ordering and macOS packaging job

**file_scope (exclusive):** `.github/workflows/release.yml` EDIT,
`scripts/tests/test-release-workflow.sh` EDIT, `docs/cargo-distribution.md` EDIT.

**Defect.** `release.yml:502` creates the tag and `:515` pushes it, from a job that checked
out with `token: ${{ secrets.GITHUB_TOKEN }}` (`:389`, `persist-credentials: true`). GitHub
does not trigger workflows from `GITHUB_TOKEN`-authored events, so once `release.yml` is the
tag authority, `cargo-publish.yml` (which triggers on `push: tags: ["v*.*.*"]`,
`cargo-publish.yml:4-5`) stops firing. `release.yml` also contains ZERO crates.io references
(measured), so it can cut a GitHub release while crates.io has nothing, violating
`docs/cargo-distribution.md:47-49`: "GitHub release publication is a later phase. It must
not start until all six crate receipts are published."

**Known topology deadlock, escalated, do not try to solve it here.** The tag is
simultaneously the trigger that STARTS crate publication and the artifact that must not
exist until publication FINISHED. Fixing the credential alone makes an out-of-order chain
fire reliably, which is worse than not firing. Secret inventory across all workflows:
`GITHUB_TOKEN`, `CARGO_REGISTRY_TOKEN`, `ANTHROPIC_API_KEY` only. There is NO PAT. Do NOT
reference a secret that does not exist; a workflow referencing an empty secret fails at
runtime in a way no local gate catches.

**Change.**
(a) Add a fail-closed PRE-TAG step, ordered strictly before the tag step at `:502`, that
    queries `https://crates.io/api/v1/crates/shepherd-cli` and asserts the EXACT release
    version appears in `.versions[].num`. Absent version -> exit non-zero. Network or parse
    failure -> exit non-zero (fail closed, never fail open). The failure message must name
    the exact recovery command:
    `gh workflow run cargo-publish.yml -f version=X.Y.Z -f publish=true`.
    Set a bounded retry with a hard ceiling so a slow index does not hang the job forever,
    and make the timeout itself a failure.
(b) Do NOT change the tag push credential in this step. Record in
    `docs/cargo-distribution.md` that with (a) in place the correct ordering is crates first,
    tag second, and that automating the publish requires either moving
    `cargo-publish.yml`'s trigger off the tag or adding a PAT. Both are outside this lane.
    State plainly that for v6.4.6 the crate publish is operator-dispatched.
(c) Add a `macos-14` job that runs `scripts/create-release-tar.sh` on a built or stubbed
    binary and asserts the archive layout binstall expects: the binary at the archive ROOT,
    matching `bin-dir = "{ bin }{ binary-ext }"` at `crates/cli/Cargo.toml:60`. Any action
    reference uses a floating major tag.
Extend `scripts/tests/test-release-workflow.sh` so all three are locally falsifiable by
parsing `release.yml`: the crates.io assertion exists AND is ordered before the tag step;
the macos-14 packaging job exists and invokes the packaging script; no step references an
undefined secret.

**ACCEPTANCE.**
```
bash scripts/tests/test-release-workflow.sh    # exit 0
python3 scripts/check-github-actions.py        # exit 0, floating majors intact
bash scripts/gate.sh fast                      # still green
```

**FALSIFICATION.** Three, one per change: (1) move the crates.io step to AFTER the tag step;
the gate MUST go red on ordering. (2) delete the crates.io step entirely; the gate MUST go
red on absence. (3) delete the macos-14 job; the gate MUST go red. Record all three.

### S5 - delete the launcher, harden the installer

**file_scope (exclusive):** `bin/shepherd` DELETE,
`scripts/tests/test_shepherd_native_launcher.sh` DELETE, `scripts/install-shepherd.sh` EDIT,
`scripts/check-cli-authority.py` EDIT, `scripts/tests/test_cli_authority_gate.sh` EDIT.

**Defect.** `bin/shepherd:25` derives `root` from the UNRESOLVED `${BASH_SOURCE[0]}`.
`resolve_executable` is applied to `$launcher` and `$installed` but never to
`${BASH_SOURCE[0]}` before `root` is computed. Through a `~/.local/bin` symlink `root`
becomes `$HOME/.local`, so it hunts `$HOME/.local/target/{release,debug}/shepherd`, then
falls back to PATH, gets ITSELF back from `command -v`, correctly rejects the self-match, and
STOPS instead of continuing down PATH to `~/.cargo/bin/shepherd`. Exit 127. Reproduced in
`w0-reproduce.sh`. Every registered hook is `"command": "shepherd"`, so this one script turns
every hook in every harness into exit 127 at once. Seed decision D4: prefer DELETION over
patching the resolution logic.

**Change.** Delete `bin/shepherd`. Delete `scripts/tests/test_shepherd_native_launcher.sh`,
which tests it; note that this file is an ORPHAN, referenced by nothing except the v6.4.5
lane plan and absent from `scripts/gate.sh`, so the seed's claim that its "existing test is
wired into a gate that runs" is currently FALSE. It has never run.
Rewrite `scripts/check-cli-authority.py` so it ASSERTS THE ABSENCE of `bin/shepherd`,
inverting `:18` `PUBLIC_LAUNCHER` and the hard requirement at `:70-76`. This is not optional
cleanup: that check runs inside `gate.sh fast` and hard-requires the launcher to exist, be
executable, and contain `exec "$candidate" "$@"`, so deleting the launcher without rewriting
the gate turns `gate.sh` RED. Deletion is a multi-file atomic change, not a `git rm`. Update
`_write_fixture`/`self_test` (~`:80-100`) to match, and keep `--self-test` passing.
CONSTRAINT: `conformance/legacy-command-disposition.json:152` carries
`"public_launcher": "bin/shepherd"` and `check-cli-authority.py:17` reads that manifest.
`conformance/` is OUTSIDE this lane's scope. The rewritten gate must therefore stop
depending on that field, or treat it as a historical retirement record. Do not edit
`conformance/`.
Harden `scripts/install-shepherd.sh`. Deleting the launcher makes NEW installs safe, but a
pre-existing `~/.local/bin/shepherd` symlink into an old checkout survives on the operator's
machine and becomes a DANGLING symlink pointing at a file that no longer exists. The
installer defaults its destination to exactly that directory (`:279`, documented at `:23`)
and today refuses to repair it. Detect an existing `shepherd` at the destination that is not
the artifact being installed - symlink, dangling symlink, or foreign script - and either
replace it or refuse with the exact recovery command. `:27` says the installer never modifies
PATH; keep that promise, this is about the destination file, not PATH.

**ACCEPTANCE.**
```
test ! -e bin/shepherd
python3 scripts/check-cli-authority.py --self-test   # exit 0
python3 scripts/check-cli-authority.py               # exit 0
bash scripts/tests/test_cli_authority_gate.sh        # exit 0
bash scripts/gate.sh fast                            # STILL GREEN, this is the sharp one
bash .shepherd/runs/v646/lanes/distribution/w0-reproduce.sh   # defect 2 no longer reproduces
```

**FALSIFICATION.** Restore `bin/shepherd` (`git checkout HEAD -- bin/shepherd`) and re-run
`python3 scripts/check-cli-authority.py`. It MUST go red on the launcher's PRESENCE. Also
stage a dangling `shepherd` symlink in a scratch destination and confirm the installer's new
guard fires. Record both. Do not run the installer against a real PATH directory.

## Wave 1b (sequential, after S4 review)

### S6 - the release gate must be able to fail

**file_scope (exclusive):** `.github/workflows/release.yml` detect step EDIT,
`.github/workflows/gitflow.yml` EDIT, `scripts/tests/test-release-workflow.sh` EDIT.
Runs AFTER S4 is reviewed, because it shares two files with it.

**Defect.** `release.yml:47-68` sets `proceed=false` on three distinct conditions and treats
them identically. Every downstream job is `if:`-skipped and the run concludes **success**.
`gitflow.yml:26-27` chains on `workflow_run ... conclusion == 'success'`, so the entire
post-release automation hangs off a signal that is green for a no-op. Measured at seed time:
two runs concluded `success` having released nothing. This is why gitflow has never run end
to end and reads as missing when it is fully implemented.

**The distinction to encode.** Of the three `proceed=false` paths:
- `:49-53` ref is not the default branch. LEGITIMATE SKIP. Stays green.
- `:55` subject does not match the release regex. LEGITIMATE SKIP, an ordinary commit to
  main. Stays green.
- `:68` reached when the subject DOES match `^(release:\s+)?vX.Y.Z` but `current != plugin`
  (the `.claude-plugin/plugin.json` cross-check at `:57-58` failed). **THIS IS A RELEASE
  COMMIT THAT PRODUCED NOTHING and it must turn the run RED.**
Today all three fall through to the same `printf 'proceed=false'` at `:68`, so the third is
indistinguishable from the first two.

**Change.** Split the third case out of the shared fallthrough and `exit 1` with a message
naming both versions: the subject's version and the `plugin.json` version. Keep cases 1 and 2
as clean green skips with an explicit `::notice::`. Do not author a second workflow
(constraint 3). In `gitflow.yml`, `skip_automatic_or_fail` (`:60-69`) emits a `::notice::`
and exits 0 on every `workflow_run` path; tighten the branch at `:83`
("did not build the default branch") so a run whose head commit IS a release commit fails
rather than no-ops. Leave `:96` ("is not a release commit") as a green skip; that one is
legitimate.

**ACCEPTANCE.** The predicate must be testable without GitHub. Extract the subject-and-
version decision into a form `scripts/tests/test-release-workflow.sh` can execute directly,
then assert the full truth table:
```
non-default ref                      -> skip, green
subject 'chore: whatever'            -> skip, green
subject 'v6.4.6' + plugin 6.4.6      -> proceed
subject 'v6.4.6' + plugin 6.4.5      -> FAIL, non-zero, message names both versions
subject 'release: v6.4.6' + mismatch -> FAIL, non-zero
bash scripts/tests/test-release-workflow.sh   # exit 0
```

**FALSIFICATION (team-lead named this the acceptance).** Construct the deliberately-broken
release commit condition - subject `v6.4.6` against a `plugin.json` reading something else -
and SHOW the gate failing, with the output recorded. Then revert the S6 change and show the
same input concluding green, which is the bug. Both halves go in the lane artifact. A run
that cannot be made red by a broken release commit has not fixed deliverable 7.

## Wave 2

Adversarial read-only review of every landed change by an auditor that did not write it.
The auditor independently re-runs each step's ACCEPTANCE and each step's FALSIFICATION, and
does not accept a coder's self-report. Specific things it must refuse to take on trust:
- that a gate can fail (it must watch it fail),
- that `gate.sh fast` is still green (it must run it),
- that no `fl03-` literal survives (it must grep),
- that S1's stubs model real tars rather than the current script's spelling.
Anything not clean goes back as a redo before the lane is committed.

## PENDING-ESCALATION

The `shepherd doctor` half of deliverable 2 - detect and report when the resolved `shepherd`
is not the native binary - lives in `crates/cli/src/cmd/wave_c_bootstrap.rs`
(`WaveCDoctorCmd` `:152`, `health_report` `:373`). That path is OUTSIDE this lane's scope AND
collides with the identity lane, which must edit `initialize_project` at `:282` in the same
file for deliverable 3. Escalated to the team lead; recommended disposition is to hand the
doctor check to the identity lane as an extra step in the file it already owns.
Worth folding into that check when it is assigned: the operator's own memory records that
`~/.cargo/bin/shepherd` goes stale silently, sitting at 6.4.5 while 6.4.6 source was being
edited, because hooks invoke the binary on PATH. So `doctor` should report the resolved path,
whether it is the native binary, AND the version skew between the resolved binary and the
checkout. That covers both this sprint's defect and the v6.4.5 DF-54 finding.

Two smaller items also escalated and unresolved: a pre-merge macos-14 packaging job belongs
in `.github/workflows/rust.yml` (out of scope; S4c puts it in `release.yml`, which is
release-time rather than merge-time), and `README.md:107` documents the launcher S5 deletes.

## CI-PENDING - NOT LOCALLY VERIFIABLE

State these as unverified in the handoff. Do not describe any of them as tested.
1. That the real `macos-14` runner image's tar behaves like S1's libarchive stub. The
   DETECTION LOGIC is proven locally against both stubs; the runner's actual binary is not.
2. That `test-release-installer-windows.ps1` passes under Windows PowerShell 5.1 with
   `-Force`. No Windows host here. Only the contract gate is locally proven.
3. That `npm pack` on the real runner emits exactly the names S3 derives. The derivation is
   proven against the checked-in `package.json` files; the packer is not executed.
4. That the crates.io assertion behaves correctly against the live API, including its retry
   ceiling and its network-failure path.
5. That the tag push, with the credential unchanged, does or does not trigger
   `cargo-publish.yml`. This is asserted from GitHub's documented behaviour, not observed.
6. That a real no-op release run now concludes red. S6 proves the PREDICATE locally; only a
   live run proves the workflow conclusion.
