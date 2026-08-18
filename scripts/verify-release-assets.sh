#!/usr/bin/env bash
# Verify the complete v6.4.7 release payload before GitHub publication.
set -euo pipefail

fail() {
  printf 'release assets: %s\n' "$*" >&2
  exit 1
}

[[ $# -eq 3 ]] || fail 'usage: verify-release-assets.sh <asset-dir> <output-list> <version>'

asset_dir="$1"
asset_list="$2"
version="$3"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] \
  || fail "version must be an exact semantic version, got '$version'"
[[ -d "$asset_dir" && ! -L "$asset_dir" ]] || fail 'asset directory must be a real directory'

asset_dir=$(cd "$asset_dir" && pwd -P)
list_parent=$(dirname "$asset_list")
[[ -d "$list_parent" && ! -L "$list_parent" ]] \
  || fail 'output-list parent must be a real directory'
list_parent=$(cd "$list_parent" && pwd -P)
asset_list="$list_parent/$(basename "$asset_list")"
case "$asset_list" in
  "$asset_dir"/*) fail 'output list must live outside the asset directory' ;;
esac

bad_entry=$(find "$asset_dir" -mindepth 1 -maxdepth 1 ! -type f -print -quit)
[[ -z "$bad_entry" ]] || fail "asset directory contains a non-regular entry: $bad_entry"

source "$(dirname "${BASH_SOURCE[0]}")/lib/release-package-names.sh"

expected=()
package_tarballs=$(release_package_names "$version")
while IFS= read -r tarball; do
  expected+=("$tarball")
done <<<"$package_tarballs"
expected+=(
  "shepherd-${version}-aarch64-apple-darwin.tar.gz"
  "shepherd-${version}-aarch64-unknown-linux-gnu.tar.gz"
  "shepherd-${version}-x86_64-apple-darwin.tar.gz"
  "shepherd-${version}-x86_64-pc-windows-msvc.zip"
  "shepherd-${version}-x86_64-unknown-linux-gnu.tar.gz"
  'shepherd-aarch64-apple-darwin.tar.gz'
  'shepherd-aarch64-unknown-linux-gnu.tar.gz'
  "shepherd-component-${version}-wasm32-wasip2.tar.gz"
  'shepherd-component-wasm32-wasip2.tar.gz'
  'shepherd-x86_64-apple-darwin.tar.gz'
  'shepherd-x86_64-pc-windows-msvc.zip'
  'shepherd-x86_64-unknown-linux-gnu.tar.gz'
)

entry_count=$(find "$asset_dir" -mindepth 1 -maxdepth 1 -type f | wc -l | tr -d ' ')
[[ "$entry_count" -eq 32 ]] \
  || fail "expected exactly 32 files (16 assets and 16 sidecars), found $entry_count"

verify_checksum() {
  local asset="$1" check="$2" line_count line declared named actual
  line_count=$(awk 'END { print NR }' "$check")
  [[ "$line_count" -eq 1 ]] || fail "checksum must contain exactly one entry: $check"
  line=$(sed -n '1p' "$check")
  printf '%s\n' "$line" | grep -Eq '^[0-9A-Fa-f]{64}  [^/\\]+$' \
    || fail "malformed checksum sidecar: $check"
  declared=${line%% *}
  named=${line#"$declared  "}
  [[ "$named" == "$(basename "$asset")" ]] \
    || fail "checksum names a different asset: $check"

  if command -v sha256sum >/dev/null 2>&1; then
    actual=$(sha256sum "$asset" | awk '{print $1}')
  elif command -v shasum >/dev/null 2>&1; then
    actual=$(shasum -a 256 "$asset" | awk '{print $1}')
  else
    fail 'requires sha256sum or shasum'
  fi
  actual=$(printf '%s' "$actual" | tr '[:upper:]' '[:lower:]')
  declared=$(printf '%s' "$declared" | tr '[:upper:]' '[:lower:]')
  [[ "$actual" == "$declared" ]] || fail "checksum mismatch: $asset"
}

release_files=()
for name in "${expected[@]}"; do
  asset="$asset_dir/$name"
  check="$asset.sha256"
  [[ -f "$asset" && ! -L "$asset" ]] || fail "missing expected release asset: $name"
  [[ -f "$check" && ! -L "$check" ]] || fail "missing checksum sidecar: $name.sha256"
  verify_checksum "$asset" "$check"
  release_files+=("$asset" "$check")
done
[[ ${#release_files[@]} -eq 32 ]] || fail 'internal release inventory mismatch'

temporary=$(mktemp "$list_parent/.shepherd-release-files.XXXXXX")
cleanup() { [[ -n "${temporary:-}" ]] && rm -f "$temporary"; }
trap cleanup EXIT
printf '%s\n' "${release_files[@]}" | LC_ALL=C sort > "$temporary"
mv -f "$temporary" "$asset_list"
temporary=''
trap - EXIT
printf 'verified 16 exact release assets and 16 checksum sidecars\n'
