#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

workflow='.github/workflows/release.yml'
packed_probe='scripts/test-packed-plugin.sh'
ruby -e 'require "yaml"; YAML.load_file(ARGV.fetch(0)); puts "ok: release workflow parses"' "$workflow"

# Detect-release-commit predicate: the single source of truth for whether a
# commit is a release commit and for which version, exercised directly
# (outside GitHub) against the full truth table. Distinguishing the
# version-mismatch case from a legitimate skip is the whole point of the
# script; this is the assertion that would have caught it collapsed.
detect='scripts/detect-release-commit.sh'
detect_fixtures=$(mktemp -d)
# Synthetic versions, not the current release: this proves the comparison is
# general (any subject vs. any plugin.json), never edited at bump time, and
# never misclassified as a real version surface by version-bump.py.
printf '{"version":"1.2.3"}\n' > "$detect_fixtures/plugin-123.json"
printf '{"version":"1.2.2"}\n' > "$detect_fixtures/plugin-122.json"

assert_detect_skip() {
  local subject="$1" ref="$2" out rc
  out=$("$detect" --subject "$subject" --ref "$ref" --default-branch main \
    --plugin-json "$detect_fixtures/plugin-646.json") && rc=0 || rc=$?
  [[ "$rc" -eq 0 ]] || {
    printf 'expected skip (exit 0) for subject=%q ref=%q, got exit %s\n' "$subject" "$ref" "$rc" >&2
    exit 1
  }
  grep -qx 'verdict=skip' <<<"$out" || {
    printf 'expected verdict=skip for subject=%q ref=%q, got:\n%s\n' "$subject" "$ref" "$out" >&2
    exit 1
  }
}

assert_detect_proceed() {
  local subject="$1" plugin="$2" expected_version="$3" out rc
  out=$("$detect" --subject "$subject" --ref refs/heads/main --default-branch main \
    --plugin-json "$plugin") && rc=0 || rc=$?
  [[ "$rc" -eq 0 ]] || {
    printf 'expected proceed (exit 0) for subject=%q, got exit %s\n' "$subject" "$rc" >&2
    exit 1
  }
  grep -qx 'verdict=proceed' <<<"$out" || {
    printf 'expected verdict=proceed for subject=%q, got:\n%s\n' "$subject" "$out" >&2
    exit 1
  }
  grep -qx "version=${expected_version}" <<<"$out" || {
    printf 'expected version=%s for subject=%q, got:\n%s\n' "$expected_version" "$subject" "$out" >&2
    exit 1
  }
}

assert_detect_fail() {
  local subject="$1" plugin="$2" subject_version="$3" plugin_version="$4" err rc
  err=$("$detect" --subject "$subject" --ref refs/heads/main --default-branch main \
    --plugin-json "$plugin" 2>&1 >/dev/null) && rc=0 || rc=$?
  [[ "$rc" -ne 0 ]] || {
    printf 'expected non-zero exit for mismatched subject=%q, got exit 0\n' "$subject" >&2
    exit 1
  }
  grep -Fq "$subject_version" <<<"$err" || {
    printf 'fail message for subject=%q missing subject version %s: %s\n' "$subject" "$subject_version" "$err" >&2
    exit 1
  }
  grep -Fq "$plugin_version" <<<"$err" || {
    printf 'fail message for subject=%q missing plugin version %s: %s\n' "$subject" "$plugin_version" "$err" >&2
    exit 1
  }
}

assert_detect_skip 'v1.2.3' 'refs/heads/feature-x'
assert_detect_skip 'chore: whatever' 'refs/heads/main'
assert_detect_proceed 'v1.2.3' "$detect_fixtures/plugin-123.json" '1.2.3'
assert_detect_fail 'v1.2.3' "$detect_fixtures/plugin-122.json" '1.2.3' '1.2.2'
assert_detect_fail 'release: v1.2.3' "$detect_fixtures/plugin-122.json" '1.2.3' '1.2.2'
assert_detect_proceed 'v1.2.3 (#123)' "$detect_fixtures/plugin-123.json" '1.2.3'
rm -rf "$detect_fixtures"
printf 'ok: detect-release-commit truth table (non-default ref, non-release subject, proceed, version-mismatch fail, squash suffix) verified\n'

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
if [[ "$sha_checkout_count" -ne 5 ]]; then
  printf 'expected all five release job checkouts to pin github.sha, found %s\n' \
    "$sha_checkout_count" >&2
  exit 1
fi
if ! rg -Fq 'python3 scripts/version-bump.py check --root . --version "$current"' "$workflow"; then
  printf '%s: release workflow must call version-bump.py check with the current version before proceeding\n' \
    "$workflow" >&2
  exit 1
fi
if rg -q 'jq --arg v|sed -i\.bak' "$workflow"; then
  printf 'release workflow must delegate version authority to version-bump.py\n' >&2
  exit 1
fi
if ! rg -Fq 'DEFAULT_BRANCH: ${{ github.event.repository.default_branch }}' "$workflow"; then
  printf '%s: release workflow must pin DEFAULT_BRANCH from github.event.repository.default_branch\n' \
    "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'scripts/detect-release-commit.sh' "$workflow"; then
  printf '%s: release workflow must invoke scripts/detect-release-commit.sh to classify the commit\n' \
    "$workflow" >&2
  exit 1
fi
if ! rg -Fq -- '--plugin-json .claude-plugin/plugin.json' "$workflow"; then
  printf '%s: detect-release-commit.sh call must pass --plugin-json .claude-plugin/plugin.json\n' \
    "$workflow" >&2
  exit 1
fi
if rg -q '^\s*(#\s*)?\[\[ "\$subject" =~ \^\(release:' "$workflow"; then
  printf 'release-metadata detect step must delegate to detect-release-commit.sh, not inline the regex\n' >&2
  exit 1
fi

# No workflow file may hand-roll the release-subject regex; its only
# legitimate home is detect-release-commit.sh. This is the tripwire against
# a fourth copy: release.yml's second "Detect release commit" step and
# gitflow.yml's release-custody check both used to inline this pattern
# (under $SUBJECT, not $subject, so the narrower check above missed them).
duplicate_predicate_hits=$(grep -o 'release:\[\[:space:\]\]' .github/workflows/*.yml 2>/dev/null | wc -l) || true
duplicate_predicate_hits="${duplicate_predicate_hits//[[:space:]]/}"
if [[ "${duplicate_predicate_hits:-0}" -ne 0 ]]; then
  printf 'a workflow file hand-rolls the release-subject regex; delegate to scripts/detect-release-commit.sh instead:\n' >&2
  grep -n 'release:\[\[:space:\]\]' .github/workflows/*.yml >&2 || true
  exit 1
fi
if ! rg -Fq 'git rev-list -n 1 "$TAG"' "$workflow"; then
  printf '%s: release workflow must resolve the tag commit via git rev-list -n 1 "$TAG" before recovery\n' \
    "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'refs/tags/${TAG}^{}' "$workflow"; then
  printf '%s: release workflow must dereference the annotated tag via refs/tags/${TAG}^{} before recovery\n' \
    "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'gh release download "$TAG"' "$workflow"; then
  printf '%s: release workflow must re-download the existing release via gh release download "$TAG" before recovery\n' \
    "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'gh release view "$TAG" --json isDraft,isPrerelease,tagName' "$workflow"; then
  printf '%s: release workflow must inspect the existing release draft/prerelease/tag state via gh release view\n' \
    "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'gh release edit "$TAG" --draft=false' "$workflow"; then
  printf '%s: release workflow must promote a recovered draft release via gh release edit "$TAG" --draft=false\n' \
    "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'diff --recursive --brief "$ASSET_DIR" "$remote_dir"' "$workflow"; then
  printf '%s: release workflow must diff recovered assets against $ASSET_DIR before trusting them\n' \
    "$workflow" >&2
  exit 1
fi
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
  if ! rg -Fq "$target" "$workflow"; then
    printf '%s: release workflow is missing the native build target %s\n' "$workflow" "$target" >&2
    exit 1
  fi
done
if ! rg -Fq 'wasm32-wasip2' "$workflow"; then
  printf '%s: release workflow is missing the wasm32-wasip2 component target\n' "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'scripts/test-component-node.sh' "$workflow"; then
  printf '%s: release workflow must run scripts/test-component-node.sh\n' "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'scripts/test-packed-plugin.sh' "$workflow"; then
  printf '%s: release workflow must run scripts/test-packed-plugin.sh\n' "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'node packages/scripts/check-package-boundary.mjs' "$workflow"; then
  printf '%s: release workflow must run the package-boundary check via node packages/scripts/check-package-boundary.mjs\n' \
    "$workflow" >&2
  exit 1
fi
for adapter_test in \
  'node packages/harness-claude/test.mjs' \
  'node packages/harness-codex/test.mjs' \
  'node packages/harness-pi/test.mjs'; do
  if ! rg -Fq "$adapter_test" "$workflow"; then
    printf '%s: release workflow must run %s\n' "$workflow" "$adapter_test" >&2
    exit 1
  fi
  if ! rg -Fq "$adapter_test" scripts/gate.sh; then
    printf 'scripts/gate.sh: local gate must also run %s\n' "$adapter_test" >&2
    exit 1
  fi
done
if ! rg -Fq 'node "$probe"' scripts/tests/test-package-boundary.sh; then
  printf 'scripts/tests/test-package-boundary.sh: must invoke node "$probe" to run the boundary check\n' >&2
  exit 1
fi
if ! rg -Fq 'scripts/tests/test-release-distribution-license.sh' scripts/gate.sh; then
  printf 'scripts/gate.sh: must run scripts/tests/test-release-distribution-license.sh\n' >&2
  exit 1
fi
if ! rg -Fq 'cargo build --locked --release --package shepherd-cli' "$workflow"; then
  printf '%s: release workflow must build shepherd-cli via cargo build --locked --release\n' "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'cargo zigbuild --locked --release --package shepherd-cli --target "${TARGET}.2.17"' "$workflow"; then
  printf '%s: linux release build must use cargo zigbuild pinned to the glibc 2.17 target\n' "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'scripts/assert-glibc-floor.py 2.17' "$workflow"; then
  printf '%s: release workflow must assert the glibc 2.17 floor on the linux binary\n' "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'RuntimeInformation]::OSArchitecture' scripts/install-shepherd.ps1; then
  printf 'scripts/install-shepherd.ps1: installer must select the OS architecture via RuntimeInformation]::OSArchitecture\n' >&2
  exit 1
fi
if rg -Fq 'RuntimeInformation]::ProcessArchitecture' scripts/install-shepherd.ps1; then
  printf 'Windows installer must select the OS architecture, not the emulated process architecture\n' >&2
  exit 1
fi
if ! rg -Fq 'actual=$("$binary" --version)' "$workflow"; then
  printf '%s: release workflow must capture the built binary --version output as actual\n' "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'expected="shepherd-cli ${VERSION}"' "$workflow"; then
  printf '%s: release workflow must assert the built binary reports shepherd-cli ${VERSION}\n' "$workflow" >&2
  exit 1
fi
[[ $(rg -Fc 'scripts/create-release-tar.sh' "$workflow") -eq 3 ]]
[[ $(rg -Fc 'TZ=UTC find' "$workflow") -eq 2 ]]
if rg -Fq -- '--uid 0' "$workflow" || rg -Fq -- '--gid 0' "$workflow"; then
  printf 'release workflow must not use BSD-only tar ownership flags\n' >&2
  exit 1
fi
if ! rg -Fq "LastWriteTimeUtc = [DateTime]'1980-01-01T00:00:00Z'" "$workflow"; then
  printf '%s: Windows zip staging must pin LastWriteTimeUtc to the epoch 1980-01-01T00:00:00Z\n' "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'function New-DeterministicZip' "$workflow"; then
  printf '%s: Windows packaging must define function New-DeterministicZip\n' "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'CreateEntry($relative, [System.IO.Compression.CompressionLevel]::Optimal)' "$workflow"; then
  printf '%s: New-DeterministicZip must add entries via CreateEntry at Optimal compression\n' "$workflow" >&2
  exit 1
fi
if ! rg -Fq '$entry.LastWriteTime = [DateTimeOffset]' "$workflow"; then
  printf '%s: New-DeterministicZip must stamp each zip entry LastWriteTime deterministically\n' "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'Windows release ZIP is not reproducible from identical staged inputs' "$workflow"; then
  printf '%s: Windows packaging must self-verify zip reproducibility with a named failure message\n' "$workflow" >&2
  exit 1
fi
if rg -Fq 'Compress-Archive' "$workflow"; then
  printf 'Windows release archive must use deterministic ZipArchive entries, not Compress-Archive\n' >&2
  exit 1
fi
if ! rg -Fq 'scripts/tests/test-release-installer-windows.ps1' "$workflow"; then
  printf '%s: release workflow must run scripts/tests/test-release-installer-windows.ps1\n' "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'npm ci --ignore-scripts' "$workflow"; then
  printf '%s: release workflow must install npm dependencies via npm ci --ignore-scripts\n' "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'gh release create' "$workflow"; then
  printf '%s: release workflow must create the GitHub release via gh release create\n' "$workflow" >&2
  exit 1
fi
if ! rg -Fq -- '--verify-tag' "$workflow"; then
  printf '%s: gh release create must pass --verify-tag\n' "$workflow" >&2
  exit 1
fi
if rg -Fq 'gh release upload' "$workflow"; then
  printf 'existing releases must be verified, never overwritten in place\n' >&2
  exit 1
fi
if ! rg -Fq 'sha256sum' scripts/verify-release-assets.sh; then
  printf 'scripts/verify-release-assets.sh: must verify checksums via sha256sum\n' >&2
  exit 1
fi
if ! rg -Fq '((${#release_files[@]} == 32))' "$workflow"; then
  printf '%s: release workflow must assert exactly 32 release_files before uploading\n' "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'ASSET_LIST="${ASSET_DIR}.txt"' "$workflow"; then
  printf '%s: release workflow must derive ASSET_LIST from ASSET_DIR.txt\n' "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'scripts/verify-release-assets.sh "$ASSET_DIR" "$ASSET_LIST" "$VERSION"' "$workflow"; then
  printf '%s: release workflow must run scripts/verify-release-assets.sh against the staged assets\n' "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'scripts/verify-release-distribution.sh "$ASSET_DIR" "$VERSION"' "$workflow"; then
  printf '%s: release workflow must run scripts/verify-release-distribution.sh against the staged assets\n' "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'expected exactly 32 files (16 assets and 16 sidecars)' scripts/verify-release-assets.sh; then
  printf 'scripts/verify-release-assets.sh: must name the 32-file (16 assets and 16 sidecars) expectation in its failure message\n' >&2
  exit 1
fi
if rg -n '== 34|17 assets|17 checksum' "$workflow" scripts/verify-release-assets.sh; then
  printf 'release workflow retains the removed Claude ZIP asset inventory\n' >&2
  exit 1
fi
if rg -Fq '$ASSET_DIR/assets.txt' "$workflow"; then
  printf 'release workflow must not enumerate a manifest inside its asset directory\n' >&2
  exit 1
fi

# S4(a): the tag must never precede crates.io actually reporting the release published.
crates_line=$(rg -Fn 'https://crates.io/api/v1/crates/${CRATE}' "$workflow" | head -1 | cut -d: -f1 || true)
if [[ -z "$crates_line" ]]; then
  printf 'release workflow must gate the tag on a crates.io publication check\n' >&2
  exit 1
fi
tag_line=$(rg -Fn -- '- name: Tag the verified release commit' "$workflow" | head -1 | cut -d: -f1 || true)
if [[ -z "$tag_line" ]]; then
  printf 'release workflow is missing its tag step; cannot verify crates.io ordering\n' >&2
  exit 1
fi
if ((crates_line >= tag_line)); then
  printf 'crates.io publication gate must run BEFORE the tag step (gate at line %s, tag at line %s)\n' \
    "$crates_line" "$tag_line" >&2
  exit 1
fi
if ! rg -Fq 'gh workflow run cargo-publish.yml -f version=' "$workflow"; then
  printf '%s: release workflow must trigger cargo-publish.yml with -f version=\n' "$workflow" >&2
  exit 1
fi
if ! rg -Fq -- '-f publish=true' "$workflow"; then
  printf '%s: cargo-publish.yml dispatch must pass -f publish=true\n' "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'User-Agent' "$workflow"; then
  printf '%s: release workflow polling the GitHub API must set a User-Agent header\n' "$workflow" >&2
  exit 1
fi
if ! rg -Fq 'MAX_ATTEMPTS' "$workflow"; then
  printf '%s: cargo-publish polling loop must bound its retries with MAX_ATTEMPTS\n' "$workflow" >&2
  exit 1
fi
if ! rg -Fq '"$published" != true' "$workflow"; then
  printf '%s: cargo-publish polling loop must check "$published" != true before proceeding\n' "$workflow" >&2
  exit 1
fi

# S4(c): the macos-14 binstall archive-layout job must exist and invoke the packaging script.
if ! rg -Fq 'runs-on: macos-14' "$workflow"; then
  printf 'release workflow is missing the macos-14 binstall archive-layout job\n' >&2
  exit 1
fi
# The archive-layout check itself lives in one place, scripts/tests/test-release-archive-layout.sh
# (a stronger, four-entry ordered check than release.yml ever inlined). Assert the release path
# calls it both as a self-test (proving the checker itself still fails on bad input) and for real
# (proving it actually runs against the built archive) -- never that release.yml re-implements it.
archive_layout_calls=$(rg -Fc 'scripts/tests/test-release-archive-layout.sh' "$workflow") || true
archive_layout_calls="${archive_layout_calls:-0}"
if [[ "$archive_layout_calls" -lt 2 ]]; then
  printf '%s: macos-14 job must both self-test and actually run scripts/tests/test-release-archive-layout.sh (the shared archive-layout check), found %s call(s)\n' \
    "$workflow" "$archive_layout_calls" >&2
  exit 1
fi

# S4: no step may reference a secret outside the known set (an undefined secret resolves
# to empty and fails at runtime in a way no local gate catches).
known_secrets=$'secrets.GITHUB_TOKEN\nsecrets.CARGO_REGISTRY_TOKEN\nsecrets.ANTHROPIC_API_KEY'
unknown_secrets=$(rg -o 'secrets\.[A-Z_]+' "$workflow" | sort -u | comm -23 - <(printf '%s\n' "$known_secrets" | sort))
if [[ -n "$unknown_secrets" ]]; then
  printf 'release workflow references an undefined secret:\n%s\n' "$unknown_secrets" >&2
  exit 1
fi

for release_test in \
  test-release-assets.sh \
  test-release-installers.sh \
  test-release-installer-powershell-contract.sh \
  test-release-distribution-license.sh \
  test-release-workflow.sh; do
  if ! rg -Fq "$release_test" scripts/gate.sh; then
    printf 'scripts/gate.sh: must run %s as part of the release gate\n' "$release_test" >&2
    exit 1
  fi
done
bash scripts/tests/test-packed-plugin-portability.sh
bash scripts/tests/test-glibc-floor.sh
bash scripts/tests/test-gitflow-workflow.sh
printf 'ok: release workflow declares native matrix, component/adapters, locked builds, and verified upload\n'
