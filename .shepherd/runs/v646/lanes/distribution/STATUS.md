# distribution lane - checkpoint status

**Gate: `bash scripts/gate.sh fast` GREEN, 0 failures.** Baseline was green; handed back green.
**Base:** 24e3d17. **Nothing committed by this lane yet** - all work is uncommitted in the worktree.

## Deliverables

| Item | State | Proven by |
|---|---|---|
| 1a tar detection | DONE | gate red under hardcoded GNU flags AND under hardcoded libarchive flags; green restored |
| 1b PowerShell `-Force` | DONE | contract gate red when `-Force` stripped |
| 1c derived package names | DONE | 0 `fl03-` literals; transform pinned vs synthetic ground truth; corrupt-transform contrast confirmed |
| 1d crates.io precedence | DONE | fail-closed pre-tag assertion; ordering gate red when reordered |
| 2 launcher removal | DONE | `bin/shepherd` deleted; authority gate exits 1 on its presence |
| 7 release gate can fail | DONE | full truth table; version mismatch exits 1 naming both versions |
| S6+S9 trigger move | DONE | one predicate, one home; 0 hand-rolled regexes in any workflow |
| S7 archive layout | DONE | binary-at-root asserted; one shared assertion, two callers |
| S8 README | DONE | launcher reference removed |

## Files this lane owns (for the pathspec-explicit commit)

```
bin/shepherd                                        (DELETED)
scripts/tests/test_shepherd_native_launcher.sh      (DELETED)
scripts/create-release-tar.sh
scripts/install-shepherd.sh
scripts/check-cli-authority.py
scripts/verify-release-distribution.sh
scripts/verify-release-assets.sh
scripts/version-bump.py
scripts/detect-release-commit.sh                    (NEW)
scripts/lib/release-package-names.sh                (NEW)
scripts/tests/test-release-tar-portability.sh
scripts/tests/test-release-installer-windows.ps1
scripts/tests/test-release-installer-powershell-contract.sh
scripts/tests/test-release-installers.sh
scripts/tests/test-release-distribution-license.sh
scripts/tests/test-release-workflow.sh
scripts/tests/test-release-package-names.sh         (NEW)
scripts/tests/test-release-archive-layout.sh        (NEW)
scripts/tests/test-version-bump.py
scripts/tests/test_cli_authority_gate.sh
.github/workflows/release.yml
.github/workflows/cargo-publish.yml
.github/workflows/gitflow.yml
.github/workflows/rust.yml
docs/cargo-distribution.md
README.md
```
Stage ONLY these. Never `git add -A`: the tree is shared and carries other sessions' work.

## Known-open

1. `scripts/tests/test_cli_authority_gate.sh` exits 1. **ENV-BLOCKED, NOT FAILED** - caused by the
   harness lane's approved `hooks/hooks.json` telemetry re-registration adding 7 hooks that do not
   match the command shape this gate enforces. `hooks/**` is outside this lane. Routed to that lane.
   It is deliberately NOT wired into `gate.sh` until it clears.
2. 8 of 55 `rg -Fq` assertions in `test-release-workflow.sh` remain bare (47 converted). Residual
   silent-failure risk, non-blocking.
3. Re-audit of the four post-audit redos (R1, R2, R3, and the corrected `w0-reproduce.sh` oracles)
   has NOT been run. The first audit's verdict was REDO; its findings are addressed but unverified
   by a second independent pass.

## CI-PENDING - asserted, NOT observed. Do not describe these as verified.

1. The real `macos-14` runner's tar behaving like the libarchive stub. Detection logic IS proven
   locally against both stubs; the runner's actual binary is not.
2. `test-release-installer-windows.ps1` passing under Windows PowerShell 5.1. No Windows host here.
3. `npm pack` emitting exactly the derived names. Derivation proven against the manifests; the
   packer was never executed.
4. The crates.io assertion against the live API, including its retry ceiling and network-failure path.
5. `cargo-publish.yml`'s moved trigger firing on a real release-commit push, and its idempotent path
   returning success against a genuinely already-published version.
6. A real no-op release run concluding RED. The PREDICATE is proven locally; only a live run proves
   the workflow conclusion.
