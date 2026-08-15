#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

workflow='.github/workflows/release.yml'
packed_probe='scripts/test-packed-plugin.sh'
ruby -e 'require "yaml"; YAML.load_file(ARGV.fetch(0)); puts "ok: release workflow parses"' "$workflow"

for forbidden in \
  'python3 scripts/version-bump.py bump' \
  'git checkout -b "$PATCH" "$GITHUB_SHA"' \
  'git push -u origin "$PATCH"' \
  'gh pr create' \
  'git push origin --delete' \
  'gh issue edit'; do
  if rg -Fq "$forbidden" "$workflow"; then
    printf 'release workflow must hand post-publication gitflow to gitflow.yml: %s\n' \
      "$forbidden" >&2
    exit 1
  fi
done
if rg -n 'tar -tzf .*\\|.*grep -q' "$packed_probe"; then
  printf 'packed-plugin probe must drain GNU tar before filtering its listing\n' >&2
  exit 1
fi
if rg -n "<<'PY'" "$workflow" || rg -Fq 'python3 - "$maximum" "$floor"' "$workflow"; then
  printf 'release workflow must use the tested glibc helper, not an inline heredoc\n' >&2
  exit 1
fi

python3 scripts/check-github-actions.py

sha_checkout_count=$(rg -Fc 'ref: ${{ github.sha }}' "$workflow")
if [[ "$sha_checkout_count" -ne 4 ]]; then
  printf 'expected all four release job checkouts to pin github.sha, found %s\n' \
    "$sha_checkout_count" >&2
  exit 1
fi
rg -Fq 'python3 scripts/version-bump.py check --root . --version "$current"' "$workflow"
if rg -q 'jq --arg v|sed -i\.bak' "$workflow"; then
  printf 'release workflow must delegate version authority to version-bump.py\n' >&2
  exit 1
fi
rg -Fq 'DEFAULT_BRANCH_REF: refs/heads/${{ github.event.repository.default_branch }}' "$workflow"
rg -Fq '[[ "$GITHUB_REF" != "$DEFAULT_BRANCH_REF" ]]' "$workflow"
rg -Fq 'git rev-list -n 1 "$TAG"' "$workflow"
rg -Fq 'refs/tags/${TAG}^{}' "$workflow"
rg -Fq 'gh release download "$TAG"' "$workflow"
rg -Fq 'gh release view "$TAG" --json isDraft,isPrerelease,tagName' "$workflow"
rg -Fq 'gh release edit "$TAG" --draft=false' "$workflow"
rg -Fq 'diff --recursive --brief "$ASSET_DIR" "$remote_dir"' "$workflow"
if rg -Fq -- '--clobber' "$workflow"; then
  printf 'release recovery must not delete published assets with --clobber\n' >&2
  exit 1
fi

for target in \
  aarch64-apple-darwin \
  x86_64-apple-darwin \
  aarch64-unknown-linux-gnu \
  x86_64-unknown-linux-gnu \
  x86_64-pc-windows-msvc; do
  rg -Fq "$target" "$workflow"
done
rg -Fq 'wasm32-wasip2' "$workflow"
rg -Fq 'scripts/test-component-node.sh' "$workflow"
rg -Fq 'scripts/test-packed-plugin.sh' "$workflow"
rg -Fq 'node packages/scripts/check-package-boundary.mjs' "$workflow"
for adapter_test in \
  'node packages/harness-claude/test.mjs' \
  'node packages/harness-codex/test.mjs' \
  'node packages/harness-pi/test.mjs'; do
  rg -Fq "$adapter_test" "$workflow"
  rg -Fq "$adapter_test" scripts/gate.sh
done
rg -Fq 'node "$probe"' scripts/tests/test-package-boundary.sh
rg -Fq 'scripts/tests/test-release-distribution-license.sh' scripts/gate.sh
rg -Fq 'cargo build --locked --release --package shepherd-cli' "$workflow"
rg -Fq 'cargo zigbuild --locked --release --package shepherd-cli --target "${TARGET}.2.17"' "$workflow"
rg -Fq 'scripts/assert-glibc-floor.py 2.17' "$workflow"
rg -Fq 'RuntimeInformation]::OSArchitecture' scripts/install-shepherd.ps1
if rg -Fq 'RuntimeInformation]::ProcessArchitecture' scripts/install-shepherd.ps1; then
  printf 'Windows installer must select the OS architecture, not the emulated process architecture\n' >&2
  exit 1
fi
rg -Fq 'actual=$("$binary" --version)' "$workflow"
rg -Fq 'expected="shepherd-cli ${VERSION}"' "$workflow"
[[ $(rg -Fc 'scripts/create-release-tar.sh' "$workflow") -eq 2 ]]
[[ $(rg -Fc 'TZ=UTC find' "$workflow") -eq 2 ]]
if rg -Fq -- '--uid 0' "$workflow" || rg -Fq -- '--gid 0' "$workflow"; then
  printf 'release workflow must not use BSD-only tar ownership flags\n' >&2
  exit 1
fi
rg -Fq "LastWriteTimeUtc = [DateTime]'1980-01-01T00:00:00Z'" "$workflow"
rg -Fq 'function New-DeterministicZip' "$workflow"
rg -Fq 'CreateEntry($relative, [System.IO.Compression.CompressionLevel]::Optimal)' "$workflow"
rg -Fq '$entry.LastWriteTime = [DateTimeOffset]' "$workflow"
rg -Fq 'Windows release ZIP is not reproducible from identical staged inputs' "$workflow"
if rg -Fq 'Compress-Archive' "$workflow"; then
  printf 'Windows release archive must use deterministic ZipArchive entries, not Compress-Archive\n' >&2
  exit 1
fi
rg -Fq 'scripts/tests/test-release-installer-windows.ps1' "$workflow"
rg -Fq 'npm ci --ignore-scripts' "$workflow"
rg -Fq 'gh release create' "$workflow"
rg -Fq -- '--verify-tag' "$workflow"
if rg -Fq 'gh release upload' "$workflow"; then
  printf 'existing releases must be verified, never overwritten in place\n' >&2
  exit 1
fi
rg -Fq 'sha256sum' scripts/verify-release-assets.sh
rg -Fq '((${#release_files[@]} == 32))' "$workflow"
rg -Fq 'ASSET_LIST="${ASSET_DIR}.txt"' "$workflow"
rg -Fq 'scripts/verify-release-assets.sh "$ASSET_DIR" "$ASSET_LIST" "$VERSION"' "$workflow"
rg -Fq 'scripts/verify-release-distribution.sh "$ASSET_DIR" "$VERSION"' "$workflow"
rg -Fq 'expected exactly 32 files (16 assets and 16 sidecars)' scripts/verify-release-assets.sh
if rg -n '== 34|17 assets|17 checksum' "$workflow" scripts/verify-release-assets.sh; then
  printf 'release workflow retains the removed Claude ZIP asset inventory\n' >&2
  exit 1
fi
if rg -Fq '$ASSET_DIR/assets.txt' "$workflow"; then
  printf 'release workflow must not enumerate a manifest inside its asset directory\n' >&2
  exit 1
fi
for release_test in \
  test-release-assets.sh \
  test-release-installers.sh \
  test-release-installer-powershell-contract.sh \
  test-release-distribution-license.sh \
  test-release-workflow.sh; do
  rg -Fq "$release_test" scripts/gate.sh
done
bash scripts/tests/test-packed-plugin-portability.sh
bash scripts/tests/test-glibc-floor.sh
bash scripts/tests/test-gitflow-workflow.sh
printf 'ok: release workflow declares native matrix, component/adapters, locked builds, and verified upload\n'
