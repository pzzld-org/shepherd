# v6.4.5 release distribution lane

## Outcome

The canonical Rust `shepherd` executable is distributable without a checkout:

- `scripts/install-shepherd.sh` selects a supported macOS/Linux target, fetches
  either a versioned release or `latest`, verifies a strict SHA-256 sidecar,
  accepts an archive containing only the expected executable, and publishes via
  an atomic same-filesystem move. Existing binaries are preserved unless
  `SHEPHERD_FORCE=1` is explicit.
- `scripts/install-shepherd.ps1` carries the equivalent Windows x64 contract.
  Its publication path uses `System.IO.File.Replace` for a forced replacement
  and `System.IO.File.Move` for a first install.
- `.github/workflows/release.yml` builds the native `shepherd-cli` directly on
  macOS arm64/x64, Linux arm64/x64, and Windows x64. It also builds the locked
  `wasm32-wasip2` Component Model artifact and packs the component runtime plus
  Claude, Codex, and Pi adapters. Every versioned asset has an immutable
  SHA-256 sidecar; a stable-name alias permits the `latest` installer URL.
- Release publication happens only after build artifacts have crossed the
  checksum gate. Re-runs upload checked assets with `--clobber` rather than
  silently skipping an existing GitHub release.

## Green evidence

Run from `/Users/jo3/src/fl03/shepherd` on 2026-08-14:

```text
bash scripts/tests/test-release-installers.sh
ok: release installer platform, URL, checksum, and atomic replacement contracts

bash scripts/tests/test-release-installer-powershell-contract.sh
ok: PowerShell installer declares versioned/latest, checksum, no-clobber, and atomic contracts

bash scripts/tests/test-release-workflow.sh
ok: release workflow parses
ok: release workflow declares native matrix, component/adapters, locked builds, and verified upload

shellcheck scripts/install-shepherd.sh scripts/tests/test-release-installers.sh \
  scripts/tests/test-release-installer-powershell-contract.sh scripts/tests/test-release-workflow.sh
# exit 0

git diff --check -- .github/workflows/release.yml scripts/install-shepherd.sh \
  scripts/install-shepherd.ps1 scripts/tests/test-release-installers.sh \
  scripts/tests/test-release-installer-powershell-contract.sh scripts/tests/test-release-workflow.sh
# exit 0
```

The release staging command also produced all four expected npm tarballs from
the generated Component Model runtime:

```text
fl03-component-runtime-6.4.5.tgz
fl03-harness-claude-6.4.5.tgz
fl03-harness-codex-6.4.5.tgz
fl03-harness-pi-6.4.5.tgz
```

## Remaining concern

PowerShell was not installed in this macOS execution environment, so its
runtime behavior cannot be claimed locally. Its contract is statically gated;
the new `windows-2025` release matrix job is the first real execution gate.
No release was created, published, installed globally, committed, or pushed.
