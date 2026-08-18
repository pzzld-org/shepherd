#!/usr/bin/env bash
# test-release-archive-layout -- assert the packaged release archive places
# the binary at the archive ROOT, with no leading directory component.
#
# WHY THIS EXISTS.
#
# `cargo binstall shepherd-cli` resolves `pkg-url` to a release archive, then
# looks for the binary at the path `bin-dir` describes. crates/cli/Cargo.toml:61
# declares:
#
#     bin-dir = "{ bin }{ binary-ext }"
#
# ... a bare filename, with no directory prefix. If packaging ever emits an
# archive shaped like `shepherd-1.2.3-aarch64-apple-darwin/shepherd` instead
# of a root-level `shepherd`, binstall's extraction step cannot find the
# binary and fails exactly as if the download 404'd -- silently, and only
# once a user actually runs `cargo binstall`, not at upload time.
#
# Nothing else in this repository runs this check before a merge. Packaging
# has broken before (four consecutive releases shipped zero assets) and the
# local gate that was supposed to catch that regression modelled a tar
# implementation that does not exist. This script exists to fail fast, on
# every pull request, before a broken layout ever reaches a tag.
#
# Usage:
#     scripts/tests/test-release-archive-layout.sh              # check the layout
#     scripts/tests/test-release-archive-layout.sh --self-test  # prove the check can fail
#
# `--self-test` matters as much as the check itself: an assertion that
# cannot tell `shepherd` from `some-dir/shepherd` is worthless, since that
# exact distinction is what a leading-directory-component regression trips.

# NOTE: 1.2.3 below is a synthetic fixture version -- pinning it to the current release would make this test agree with today's number by accident and trip version-bump.py's unclassified-version-literal gate.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

creator="$PWD/scripts/create-release-tar.sh"

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/shepherd-archive-layout.XXXXXX")
trap 'rm -rf "$tmp_dir"' EXIT

# stage_payload <dir> -- populate <dir> with the same legal-file shape the
# real native release archives carry (LICENSE, THIRD_PARTY_NOTICES.md, one
# entry under THIRD_PARTY_LICENSES/), matching the fixture convention in
# scripts/tests/test-release-tar-portability.sh, plus a fake `shepherd`
# executable at the payload root.
stage_payload() {
  local dir="$1"
  mkdir -p "$dir/THIRD_PARTY_LICENSES"
  printf 'license\n' > "$dir/LICENSE"
  printf 'notices\n' > "$dir/THIRD_PARTY_NOTICES.md"
  printf 'dependency license\n' > "$dir/THIRD_PARTY_LICENSES/dependency.txt"
  printf '#!/bin/sh\nexit 0\n' > "$dir/shepherd"
  chmod 0755 "$dir/shepherd"
}

# assert_root_layout <archive> -- fail unless <archive> contains exactly the
# expected entry set, in order, with `shepherd` as a bare root-level entry.
# The check compares the FULL ordered entry set, not merely whether a member
# named "shepherd" appears somewhere: a leading-directory regression like
# "some-dir/shepherd" still contains the substring "shepherd", so a substring
# or "does shepherd appear" check cannot distinguish the broken layout from
# the correct one. Only an exact-set comparison can.
assert_root_layout() {
  local archive="$1" actual expected
  actual=$(tar -tzf "$archive")
  expected=$'LICENSE\nTHIRD_PARTY_NOTICES.md\nTHIRD_PARTY_LICENSES/dependency.txt\nshepherd'

  if [[ "$actual" == "$expected" ]]; then
    return 0
  fi

  printf 'binstall archive layout violation\n' >&2
  printf 'expected exactly:\n%s\n' "$expected" >&2
  printf 'got:\n%s\n' "$actual" >&2
  while IFS= read -r entry; do
    case "$entry" in
      LICENSE|THIRD_PARTY_NOTICES.md|THIRD_PARTY_LICENSES/dependency.txt|shepherd)
        ;;
      *)
        printf 'wrong entry: "%s" -- bin-dir = "{ bin }{ binary-ext }" (crates/cli/Cargo.toml:61) requires a bare "shepherd" entry at the archive root; binstall extraction fails on any leading directory component\n' \
          "$entry" >&2
        ;;
    esac
  done <<< "$actual"
  return 1
}

if [[ "${1:-}" == '--self-test' ]]; then
  printf 'self-test: the layout assertion must be able to fail\n'

  # A deliberately WRONG archive: the binary nested one directory down --
  # exactly the shape a broken packaging step would emit, and exactly what
  # bin-dir = "{ bin }{ binary-ext }" cannot resolve.
  broken_dir="$tmp_dir/broken-source"
  stage_payload "$broken_dir"
  mkdir -p "$broken_dir/shepherd-1.2.3-aarch64-apple-darwin"
  mv "$broken_dir/shepherd" "$broken_dir/shepherd-1.2.3-aarch64-apple-darwin/shepherd"
  broken_archive="$tmp_dir/broken.tar.gz"
  "$creator" "$broken_dir" "$broken_archive" \
    LICENSE THIRD_PARTY_NOTICES.md THIRD_PARTY_LICENSES/dependency.txt \
    shepherd-1.2.3-aarch64-apple-darwin/shepherd

  if assert_root_layout "$broken_archive"; then
    fail 'self-test: the layout assertion accepted a binary nested under a leading directory'
  fi
  printf 'self-test: confirmed -- a nested "shepherd-1.2.3-aarch64-apple-darwin/shepherd" entry is rejected\n'

  # The correctly-shaped archive must still pass.
  good_dir="$tmp_dir/good-source"
  stage_payload "$good_dir"
  good_archive="$tmp_dir/good.tar.gz"
  "$creator" "$good_dir" "$good_archive" \
    LICENSE THIRD_PARTY_NOTICES.md THIRD_PARTY_LICENSES/dependency.txt shepherd
  assert_root_layout "$good_archive" || fail 'self-test: the correctly-shaped archive was rejected'

  printf 'ok: self-test passed -- the layout assertion can fail, and does not fail on a correct archive\n'
  exit 0
fi

source_dir="$tmp_dir/source"
stage_payload "$source_dir"
archive="$tmp_dir/archive.tar.gz"
"$creator" "$source_dir" "$archive" \
  LICENSE THIRD_PARTY_NOTICES.md THIRD_PARTY_LICENSES/dependency.txt shepherd

assert_root_layout "$archive" || fail 'release archive does not satisfy the binstall root-layout contract'

printf 'ok: release archive places the binary at the archive root, matching bin-dir = "{ bin }{ binary-ext }"\n'
