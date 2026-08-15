#!/usr/bin/env bash
# Verify legal material inside the fixed release assets before publication.
set -euo pipefail

fail() {
  printf 'release distribution: %s\n' "$*" >&2
  exit 1
}

[[ $# -eq 2 ]] || fail 'usage: verify-release-distribution.sh <asset-dir> <version>'
asset_dir=$1
version=$2
[[ -d "$asset_dir" && ! -L "$asset_dir" ]] || fail 'asset directory must be a real directory'
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "invalid version: $version"
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/shepherd-release-legal-verify.XXXXXX")
trap 'find "$tmp_dir" -depth -delete' EXIT

check_legal_material() {
  local tree=$1
  test -f "$tree/LICENSE" || fail "missing LICENSE in $tree"
  test -f "$tree/THIRD_PARTY_NOTICES.md" || fail "missing notices in $tree"
  cmp -s "$repo_root/LICENSE" "$tree/LICENSE" || fail "LICENSE differs in $tree"
  local licenses="$tree/THIRD_PARTY_LICENSES"
  [[ -d "$licenses" && ! -L "$licenses" ]] || fail "missing license-text directory in $tree"
  local texts=()
  while IFS= read -r path; do
    texts+=("$path")
  done < <(find "$licenses" -mindepth 1 -maxdepth 1 -type f -name '[0-9a-f]*.txt' -print | LC_ALL=C sort)
  ((${#texts[@]} > 0)) || fail "no bundled license texts in $tree"
  local expected actual path filename hash
  expected=$(grep -Eo 'THIRD_PARTY_LICENSES/[0-9a-f]{64}\.txt' "$tree/THIRD_PARTY_NOTICES.md" | LC_ALL=C sort -u)
  actual=$(printf '%s\n' "${texts[@]##*/}" | sed 's#^#THIRD_PARTY_LICENSES/#' | LC_ALL=C sort)
  [[ "$expected" == "$actual" ]] || fail "notice pointers do not match bundled texts in $tree"
  for path in "${texts[@]}"; do
    filename=$(basename "$path")
    hash=${filename%.txt}
    if command -v sha256sum >/dev/null 2>&1; then
      [[ "$(sha256sum "$path" | awk '{print $1}')" == "$hash" ]] || fail "license text hash mismatch: $filename"
    else
      [[ "$(shasum -a 256 "$path" | awk '{print $1}')" == "$hash" ]] || fail "license text hash mismatch: $filename"
    fi
  done
}

check_legal_tree() {
  local tree=$1 binary=$2
  check_legal_material "$tree"
  test -f "$tree/$binary" || fail "missing $binary in $tree"
  local unexpected
  unexpected=$(find "$tree" -mindepth 1 -maxdepth 1 \
    ! -name LICENSE ! -name THIRD_PARTY_NOTICES.md ! -name THIRD_PARTY_LICENSES ! -name "$binary" \
    -print -quit)
  [[ -z "$unexpected" ]] || fail "unexpected top-level entry in $tree"
}

extract_tar() {
  local archive=$1 destination=$2
  mkdir -p "$destination"
  tar -xzf "$archive" -C "$destination"
}

extract_zip() {
  local archive=$1 destination=$2
  mkdir -p "$destination"
  unzip -qq "$archive" -d "$destination"
}

for target in aarch64-apple-darwin aarch64-unknown-linux-gnu x86_64-apple-darwin x86_64-unknown-linux-gnu; do
  for name in "shepherd-${version}-${target}.tar.gz" "shepherd-${target}.tar.gz"; do
    destination="$tmp_dir/${name}.d"
    extract_tar "$asset_dir/$name" "$destination"
    check_legal_tree "$destination" shepherd
  done
done
for name in "shepherd-${version}-x86_64-pc-windows-msvc.zip" 'shepherd-x86_64-pc-windows-msvc.zip'; do
  destination="$tmp_dir/${name}.d"
  extract_zip "$asset_dir/$name" "$destination"
  check_legal_tree "$destination" shepherd.exe
done
for name in "shepherd-component-${version}-wasm32-wasip2.tar.gz" 'shepherd-component-wasm32-wasip2.tar.gz'; do
  destination="$tmp_dir/${name}.d"
  extract_tar "$asset_dir/$name" "$destination"
  check_legal_tree "$destination" shepherd-component.wasm
done
for package in component-runtime harness-claude harness-codex harness-pi; do
  destination="$tmp_dir/${package}.d"
  extract_tar "$asset_dir/fl03-${package}-${version}.tgz" "$destination"
  check_legal_material "$destination/package"
  test -f "$destination/package/package.json" || fail "missing package.json in $package tarball"
done
printf 'verified legal material inside 16 exact release assets\n'
