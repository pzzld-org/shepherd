#!/usr/bin/env bash
# The release payload is intentionally fixed at 17 assets. License material
# therefore belongs inside each archive, never as an unverified extra upload.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

notices='THIRD_PARTY_NOTICES.md'
test -s LICENSE
test -s "$notices"
python3 scripts/generate-third-party-notices.py --check --output "$notices" --licenses-dir THIRD_PARTY_LICENSES
# Version bumps change first-party package records in both lockfiles. The legal
# inventory must remain stable across that transaction: it records registry
# crates and locked shipped Node closure only, never a raw lockfile digest or
# workspace package version.
if rg -Fq '## Locked inputs' "$notices"; then
  printf 'legal inventory must not couple itself to a whole-lock digest\n' >&2
  exit 1
fi
python3 scripts/tests/test-generate-third-party-notices.py

closure_dir=$(mktemp -d "${TMPDIR:-/tmp}/shepherd-legal-closure.XXXXXX")
python3 scripts/generate-third-party-notices.py --scope native --target x86_64-apple-darwin \
  --output "$closure_dir/native.md" --licenses-dir "$closure_dir/native-licenses"
python3 scripts/generate-third-party-notices.py --scope component --target wasm32-wasip2 \
  --output "$closure_dir/component.md" --licenses-dir "$closure_dir/component-licenses"
python3 scripts/generate-third-party-notices.py --scope npm-harness-claude \
  --output "$closure_dir/npm.md" --licenses-dir "$closure_dir/npm-licenses"
rg -Fq '`wit-bindgen`' "$closure_dir/component.md"
if rg -Fq '`wit-bindgen`' "$closure_dir/native.md"; then
  printf 'native notice must exclude the component-only Rust closure\n' >&2
  exit 1
fi
rg -Fq '`@bytecodealliance/preview2-shim`' "$closure_dir/npm.md"
if rg -Fq '`@babel/parser`' "$closure_dir/npm.md"; then
  printf 'npm notice must exclude root build tooling\n' >&2
  exit 1
fi

# Every producer must place the same legal material inside its payload. The
# archive-inspection gates below exercise the byte-level result in CI.
workflow='.github/workflows/release.yml'
rg -Fq 'scripts/stage-distribution-legal.sh "$staging"' "$workflow"
rg -Fq 'scripts/stage-distribution-legal.sh stage' "$workflow"
rg -Fq 'scripts/stage-distribution-legal.sh "$plugin_root"' scripts/build-claude-plugin-release.sh

tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/shepherd-release-license.XXXXXX")
trap 'find "$closure_dir" "$tmp_dir" -depth -delete' EXIT
assets="$tmp_dir/assets"
payload="$tmp_dir/payload"
mkdir -p "$assets" "$payload"
printf 'binary\n' > "$payload/shepherd"
printf 'windows binary\n' > "$payload/shepherd.exe"
printf 'component\n' > "$payload/shepherd-component.wasm"
cp LICENSE "$payload/"
mkdir -p "$payload/THIRD_PARTY_LICENSES"
if command -v sha256sum >/dev/null 2>&1; then
  legal_hash=$(sha256sum LICENSE | awk '{print $1}')
else
  legal_hash=$(shasum -a 256 LICENSE | awk '{print $1}')
fi
cp LICENSE "$payload/THIRD_PARTY_LICENSES/$legal_hash.txt"
printf '# fixture notices\n\nTHIRD_PARTY_LICENSES/%s.txt\n' "$legal_hash" > "$payload/THIRD_PARTY_NOTICES.md"
for target in aarch64-apple-darwin aarch64-unknown-linux-gnu x86_64-apple-darwin x86_64-unknown-linux-gnu; do
  for name in "shepherd-6.4.5-${target}.tar.gz" "shepherd-${target}.tar.gz"; do
    tar -C "$payload" -czf "$assets/$name" LICENSE THIRD_PARTY_NOTICES.md THIRD_PARTY_LICENSES shepherd
  done
done
for name in shepherd-6.4.5-x86_64-pc-windows-msvc.zip shepherd-x86_64-pc-windows-msvc.zip; do
  (cd "$payload" && zip -qr "$assets/$name" LICENSE THIRD_PARTY_NOTICES.md THIRD_PARTY_LICENSES shepherd.exe)
done
for name in shepherd-component-6.4.5-wasm32-wasip2.tar.gz shepherd-component-wasm32-wasip2.tar.gz; do
  tar -C "$payload" -czf "$assets/$name" LICENSE THIRD_PARTY_NOTICES.md THIRD_PARTY_LICENSES shepherd-component.wasm
done
mkdir -p "$payload/package"
printf '{}\n' > "$payload/package/package.json"
cp "$payload/LICENSE" "$payload/THIRD_PARTY_NOTICES.md" "$payload/package/"
cp -R "$payload/THIRD_PARTY_LICENSES" "$payload/package/"
for package in component-runtime harness-claude harness-codex harness-pi; do
  tar -C "$payload" -czf "$assets/fl03-${package}-6.4.5.tgz" package
done
(cd "$payload" && zip -qr "$assets/shepherd-claude-plugin-6.4.5.zip" LICENSE THIRD_PARTY_NOTICES.md THIRD_PARTY_LICENSES)
scripts/verify-release-distribution.sh "$assets" 6.4.5

cp -R "$assets" "$tmp_dir/tampered"
tampered_payload="$tmp_dir/tampered-payload"
cp -R "$payload" "$tampered_payload"
printf 'tampered\n' >> "$tampered_payload/THIRD_PARTY_LICENSES/$legal_hash.txt"
tar -C "$tampered_payload" -czf "$tmp_dir/tampered/shepherd-component-6.4.5-wasm32-wasip2.tar.gz" \
  LICENSE THIRD_PARTY_NOTICES.md THIRD_PARTY_LICENSES shepherd-component.wasm
if scripts/verify-release-distribution.sh "$tmp_dir/tampered" 6.4.5 >/dev/null 2>&1; then
  printf 'tampered legal component archive must fail verification\n' >&2
  exit 1
fi

printf 'ok: release sources carry locked notices and package license copies\n'
