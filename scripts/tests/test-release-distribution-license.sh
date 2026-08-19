#!/usr/bin/env bash
# The release payload is intentionally fixed at 16 assets. License material
# therefore belongs inside each archive, never as an unverified extra upload.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."
source scripts/lib/release-package-names.sh

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
rg -Fq '`wit-bindgen`' "$closure_dir/component.md" || { rc=$?; printf 'FAIL: component notice must list the wit-bindgen crate (rg rc=%s)\n' "$rc" >&2; exit 1; }
if rg -Fq '`wit-bindgen`' "$closure_dir/native.md"; then
  printf 'native notice must exclude the component-only Rust closure\n' >&2
  exit 1
fi
rg -Fq '`@bytecodealliance/preview2-shim`' "$closure_dir/npm.md" || { rc=$?; printf 'FAIL: npm harness notice must list the @bytecodealliance/preview2-shim package (rg rc=%s)\n' "$rc" >&2; exit 1; }
if rg -Fq '`@babel/parser`' "$closure_dir/npm.md"; then
  printf 'npm notice must exclude root build tooling\n' >&2
  exit 1
fi

# Every producer must place the same legal material inside its payload. The
# archive-inspection gates below exercise the byte-level result in CI.
# Legal staging happens where the ASSETS are built, which is cargo-build.yml
# since the release pipeline was split; release.yml orchestrates and tags but
# stages nothing itself.
workflow='.github/workflows/cargo-build.yml'
rg -Fq 'scripts/stage-distribution-legal.sh "$staging"' "$workflow" || { rc=$?; printf 'FAIL: build workflow must invoke stage-distribution-legal.sh against the staging directory (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'scripts/stage-distribution-legal.sh stage' "$workflow" || { rc=$?; printf 'FAIL: build workflow must invoke stage-distribution-legal.sh with the stage subcommand (rg rc=%s)\n' "$rc" >&2; exit 1; }

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
  for name in "shepherd-6.5.4-${target}.tar.gz" "shepherd-${target}.tar.gz"; do
    tar -C "$payload" -czf "$assets/$name" LICENSE THIRD_PARTY_NOTICES.md THIRD_PARTY_LICENSES shepherd
  done
done
for name in shepherd-6.5.4-x86_64-pc-windows-msvc.zip shepherd-x86_64-pc-windows-msvc.zip; do
  (cd "$payload" && zip -qr "$assets/$name" LICENSE THIRD_PARTY_NOTICES.md THIRD_PARTY_LICENSES shepherd.exe)
done
for name in shepherd-component-6.5.4-wasm32-wasip2.tar.gz shepherd-component-wasm32-wasip2.tar.gz; do
  tar -C "$payload" -czf "$assets/$name" LICENSE THIRD_PARTY_NOTICES.md THIRD_PARTY_LICENSES shepherd-component.wasm
done
mkdir -p "$payload/package"
printf '{}\n' > "$payload/package/package.json"
cp "$payload/LICENSE" "$payload/THIRD_PARTY_NOTICES.md" "$payload/package/"
cp -R "$payload/THIRD_PARTY_LICENSES" "$payload/package/"
package_tarballs=$(release_package_names 6.5.4)
while IFS= read -r tarball; do
  tar -C "$payload" -czf "$assets/$tarball" package
done <<<"$package_tarballs"
scripts/verify-release-distribution.sh "$assets" 6.5.4

cp -R "$assets" "$tmp_dir/tampered"
tampered_payload="$tmp_dir/tampered-payload"
cp -R "$payload" "$tampered_payload"
printf 'tampered\n' >> "$tampered_payload/THIRD_PARTY_LICENSES/$legal_hash.txt"
tar -C "$tampered_payload" -czf "$tmp_dir/tampered/shepherd-component-6.5.4-wasm32-wasip2.tar.gz" \
  LICENSE THIRD_PARTY_NOTICES.md THIRD_PARTY_LICENSES shepherd-component.wasm
if scripts/verify-release-distribution.sh "$tmp_dir/tampered" 6.5.4 >/dev/null 2>&1; then
  printf 'tampered legal component archive must fail verification\n' >&2
  exit 1
fi


# ---------------------------------------------------------------------------
# Line endings. LICENSE is a byte-for-byte payload inside all 16 assets:
# verify-release-distribution.sh compares each extracted copy against the
# repository file. GitHub's Windows runners check out with core.autocrlf=true,
# which rewrote LICENSE to CRLF. The release job then failed at
# "LICENSE differs in ...windows-msvc.zip.d" only after all five native
# targets, the component job, and the crates.io publication had succeeded --
# an unrecoverable ordering, because the published crates pin that commit.
# Two gates now stand in front of that, and both are falsified below.
# ---------------------------------------------------------------------------

eol_attr=$(git check-attr eol -- LICENSE)
if [[ "$eol_attr" != 'LICENSE: eol: lf' ]]; then
  printf '.gitattributes must pin LICENSE to LF, found: %s\n' "$eol_attr" >&2
  exit 1
fi

# The assertion above must be reading a real attribute, not a constant: an
# identical query against a repository with no .gitattributes reports
# `unspecified`, which is exactly the state that shipped the broken zip.
attr_probe="$tmp_dir/attr-probe"
mkdir -p "$attr_probe"
git -C "$attr_probe" init -q
: > "$attr_probe/LICENSE"
probe_attr=$(git -C "$attr_probe" check-attr eol -- LICENSE)
if [[ "$probe_attr" != 'LICENSE: eol: unspecified' ]]; then
  printf 'attribute probe cannot observe an unpinned LICENSE: %s\n' "$probe_attr" >&2
  exit 1
fi

# The staging script is the second gate: it runs on the packaging runner, so it
# fails the one job that would have produced the divergence.
eol_root="$tmp_dir/crlf-checkout"
eol_stage="$tmp_dir/crlf-stage"
mkdir -p "$eol_root/scripts" "$eol_stage"
cp scripts/stage-distribution-legal.sh "$eol_root/scripts/"
printf 'a rewritten license\r\nsecond line\r\n' > "$eol_root/LICENSE"
if crlf_output=$(bash "$eol_root/scripts/stage-distribution-legal.sh" \
  "$eol_stage" --scope native --target x86_64-pc-windows-msvc 2>&1); then
  printf 'legal staging must refuse a CRLF checkout\n' >&2
  exit 1
fi
if ! rg -Fq 'LICENSE carries CR bytes' <<<"$crlf_output"; then
  printf 'legal staging failed for the wrong reason: %s\n' "$crlf_output" >&2
  exit 1
fi
test ! -e "$eol_stage/LICENSE"

# And it must let an LF checkout through -- a guard that refuses everything is
# not a guard. The staged copy proves execution reached the payload copy; the
# notices renderer then fails only because this fixture has no workspace.
printf 'a rewritten license\nsecond line\n' > "$eol_root/LICENSE"
lf_output=$(bash "$eol_root/scripts/stage-distribution-legal.sh" \
  "$eol_stage" --scope native --target x86_64-pc-windows-msvc 2>&1) || true
if rg -Fq 'LICENSE carries CR bytes' <<<"$lf_output"; then
  printf 'legal staging rejects an LF checkout: %s\n' "$lf_output" >&2
  exit 1
fi
cmp -s "$eol_root/LICENSE" "$eol_stage/LICENSE"

printf 'ok: release sources carry locked notices and package license copies\n'
