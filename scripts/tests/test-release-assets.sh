#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

verifier="$PWD/scripts/verify-release-assets.sh"
tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/shepherd-release-assets.XXXXXX")
trap 'find "$tmp_dir" -depth -delete' EXIT

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

hash_sidecar() {
  local directory="$1" name="$2"
  if command -v sha256sum >/dev/null 2>&1; then
    (cd "$directory" && sha256sum "$name" > "$name.sha256")
  else
    (cd "$directory" && shasum -a 256 "$name" > "$name.sha256")
  fi
}

asset_dir="$tmp_dir/assets"
mkdir -p "$asset_dir"
asset_dir=$(cd "$asset_dir" && pwd -P)
targets=(
  aarch64-apple-darwin.tar.gz
  x86_64-apple-darwin.tar.gz
  aarch64-unknown-linux-gnu.tar.gz
  x86_64-unknown-linux-gnu.tar.gz
  x86_64-pc-windows-msvc.zip
)
for target in "${targets[@]}"; do
  printf 'versioned %s\n' "$target" > "$asset_dir/shepherd-6.5.4-$target"
  printf 'stable %s\n' "$target" > "$asset_dir/shepherd-$target"
done
for name in \
  shepherd-component-6.5.4-wasm32-wasip2.tar.gz \
  shepherd-component-wasm32-wasip2.tar.gz \
  pzzld-component-runtime-6.5.4.tgz \
  pzzld-claude-shepherd-6.5.4.tgz \
  pzzld-codex-shepherd-6.5.4.tgz \
  pzzld-pi-shepherd-6.5.4.tgz; do
  printf 'fixture %s\n' "$name" > "$asset_dir/$name"
done
for asset in "$asset_dir"/*; do
  hash_sidecar "$asset_dir" "$(basename "$asset")"
done

asset_list="$tmp_dir/release-files.txt"
"$verifier" "$asset_dir" "$asset_list" 6.5.4
[[ $(wc -l < "$asset_list" | tr -d ' ') == 32 ]] || fail 'expected 32 publishable files'
rg -Fxq "$asset_dir/shepherd-6.5.4-aarch64-apple-darwin.tar.gz" "$asset_list" || { rc=$?; printf 'FAIL: release asset manifest must list the aarch64-apple-darwin tarball (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fxq "$asset_dir/shepherd-6.5.4-aarch64-apple-darwin.tar.gz.sha256" "$asset_list" || { rc=$?; printf 'FAIL: release asset manifest must list the aarch64-apple-darwin tarball checksum sidecar (rg rc=%s)\n' "$rc" >&2; exit 1; }

cp -R "$asset_dir" "$tmp_dir/missing"
find "$tmp_dir/missing" -name '*.sha256' -exec rm -f {} +
if "$verifier" "$tmp_dir/missing" "$tmp_dir/missing.txt" 6.5.4 >/dev/null 2>&1; then
  fail 'missing checksum sidecar must fail'
fi

cp -R "$asset_dir" "$tmp_dir/wrong-name"
mv "$tmp_dir/wrong-name/pzzld-pi-shepherd-6.5.4.tgz" \
  "$tmp_dir/wrong-name/pzzld-pi-shepherd-6.5.5.tgz"
mv "$tmp_dir/wrong-name/pzzld-pi-shepherd-6.5.4.tgz.sha256" \
  "$tmp_dir/wrong-name/pzzld-pi-shepherd-6.5.5.tgz.sha256"
if "$verifier" "$tmp_dir/wrong-name" "$tmp_dir/wrong-name.txt" 6.5.4 >/dev/null 2>&1; then
  fail 'wrong package version must fail the exact asset inventory'
fi

cp -R "$asset_dir" "$tmp_dir/tampered"
printf 'tampered\n' >> "$tmp_dir/tampered/shepherd-x86_64-unknown-linux-gnu.tar.gz"
if "$verifier" "$tmp_dir/tampered" "$tmp_dir/tampered.txt" 6.5.4 >/dev/null 2>&1; then
  fail 'checksum mismatch must fail'
fi

if "$verifier" "$asset_dir" "$asset_dir/release-files.txt" 6.5.4 >/dev/null 2>&1; then
  fail 'publication manifest inside the asset directory must fail'
fi

printf 'ok: exact release inventory, checksum, version, and external manifest contracts\n'
