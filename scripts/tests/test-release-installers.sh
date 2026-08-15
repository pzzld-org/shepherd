#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

installer="$PWD/scripts/install-shepherd.sh"
tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/shepherd-release-installer.XXXXXX")
trap 'find "$tmp_dir" -depth -delete' EXIT
export SHEPHERD_LIBC=gnu

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

rg -Fq 'ready=$(mktemp "$destination_dir/.shepherd-ready.XXXXXX")' "$installer"
if rg -Fq 'mv -f "$temporary/$binary.ready" "$destination"' "$installer"; then
  fail 'publication candidate must live on the destination filesystem'
fi

expect_eq() {
  local actual="$1"
  local expected="$2"
  local label="$3"
  [[ "$actual" == "$expected" ]] || fail "$label: expected '$expected', got '$actual'"
}

asset_for() {
  local os="$1"
  local arch="$2"
  local expected="$3"
  local actual
  actual=$(SHEPHERD_OS="$os" SHEPHERD_ARCH="$arch" SHEPHERD_VERSION=6.4.6 \
    "$installer" --print-asset)
  expect_eq "$actual" "$expected" "asset for $os/$arch"
}

asset_for Darwin arm64 shepherd-6.4.6-aarch64-apple-darwin.tar.gz
asset_for Darwin x86_64 shepherd-6.4.6-x86_64-apple-darwin.tar.gz
asset_for Linux aarch64 shepherd-6.4.6-aarch64-unknown-linux-gnu.tar.gz
asset_for Linux x86_64 shepherd-6.4.6-x86_64-unknown-linux-gnu.tar.gz
asset_for MINGW64_NT x86_64 shepherd-6.4.6-x86_64-pc-windows-msvc.zip

if SHEPHERD_OS=MINGW64_NT SHEPHERD_ARCH=arm64 SHEPHERD_VERSION=6.4.6 \
  "$installer" --print-asset >/dev/null 2>&1; then
  fail 'Windows ARM64 must fail until the release matrix publishes that asset'
fi
if SHEPHERD_OS=Linux SHEPHERD_LIBC=musl SHEPHERD_ARCH=x86_64 SHEPHERD_VERSION=6.4.6 \
  "$installer" --print-asset >/dev/null 2>&1; then
  fail 'musl Linux must fail until the release matrix publishes that asset'
fi

explicit_url=$(SHEPHERD_OS=Linux SHEPHERD_ARCH=x86_64 SHEPHERD_VERSION=6.4.6 \
  "$installer" --print-url)
expect_eq "$explicit_url" \
  'https://github.com/FL03/shepherd/releases/download/v6.4.6/shepherd-6.4.6-x86_64-unknown-linux-gnu.tar.gz' \
  'explicit version URL'

latest_url=$(SHEPHERD_OS=Linux SHEPHERD_ARCH=x86_64 "$installer" --print-url)
expect_eq "$latest_url" \
  'https://github.com/FL03/shepherd/releases/latest/download/shepherd-x86_64-unknown-linux-gnu.tar.gz' \
  'latest URL'

if SHEPHERD_OS=Plan9 SHEPHERD_ARCH=x86_64 "$installer" --print-asset >/dev/null 2>&1; then
  fail 'unsupported OS must fail'
fi
if SHEPHERD_OS=Linux SHEPHERD_ARCH=ppc64 "$installer" --print-asset >/dev/null 2>&1; then
  fail 'unsupported architecture must fail'
fi
if SHEPHERD_OS=Linux SHEPHERD_ARCH=x86_64 SHEPHERD_VERSION=not-a-version \
  "$installer" --print-url >/dev/null 2>&1; then
  fail 'invalid explicit version must fail'
fi

release_root="$tmp_dir/releases"
asset_dir="$release_root/download/v6.4.6"
mkdir -p "$asset_dir" "$tmp_dir/payload"
payload="$tmp_dir/payload/shepherd"
cat >"$payload" <<'EOF'
#!/usr/bin/env sh
printf 'shepherd fixture 6.4.6\n'
EOF
chmod 755 "$payload"
cp LICENSE THIRD_PARTY_NOTICES.md "$tmp_dir/payload/"
cp -R THIRD_PARTY_LICENSES "$tmp_dir/payload/"
legal_entries=()
while IFS= read -r entry; do
  legal_entries+=("$entry")
done < <(cd "$tmp_dir/payload" && find THIRD_PARTY_LICENSES -type f -name '*.txt' -print | LC_ALL=C sort)
asset='shepherd-6.4.6-x86_64-unknown-linux-gnu.tar.gz'
(
  cd "$tmp_dir/payload"
  tar -czf "$asset_dir/$asset" LICENSE THIRD_PARTY_NOTICES.md "${legal_entries[@]}" shepherd
)
(
  cd "$asset_dir"
  shasum -a 256 "$asset" >"$asset.sha256"
)

install_dir="$tmp_dir/install/bin"
SHEPHERD_OS=Linux SHEPHERD_ARCH=x86_64 SHEPHERD_VERSION=6.4.6 \
  SHEPHERD_RELEASE_BASE="file://$release_root" SHEPHERD_INSTALL_DIR="$install_dir" \
  "$installer" >/dev/null
[[ -x "$install_dir/shepherd" ]] || fail 'installer did not install an executable'
expect_eq "$("$install_dir/shepherd")" 'shepherd fixture 6.4.6' 'installed executable'

printf 'do-not-replace\n' >"$install_dir/shepherd"
if SHEPHERD_OS=Linux SHEPHERD_ARCH=x86_64 SHEPHERD_VERSION=6.4.6 \
  SHEPHERD_RELEASE_BASE="file://$release_root" SHEPHERD_INSTALL_DIR="$install_dir" \
  "$installer" >/dev/null 2>&1; then
  fail 'existing installation must not be clobbered without SHEPHERD_FORCE=1'
fi
expect_eq "$(cat "$install_dir/shepherd")" 'do-not-replace' 'no-clobber preserves old binary'

SHEPHERD_OS=Linux SHEPHERD_ARCH=x86_64 SHEPHERD_VERSION=6.4.6 \
  SHEPHERD_RELEASE_BASE="file://$release_root" SHEPHERD_INSTALL_DIR="$install_dir" \
  SHEPHERD_FORCE=1 "$installer" >/dev/null
expect_eq "$("$install_dir/shepherd")" 'shepherd fixture 6.4.6' 'forced atomic replacement'

directory_destination="$tmp_dir/directory-destination/bin"
mkdir -p "$directory_destination/shepherd"
if SHEPHERD_OS=Linux SHEPHERD_ARCH=x86_64 SHEPHERD_VERSION=6.4.6 \
  SHEPHERD_RELEASE_BASE="file://$release_root" SHEPHERD_INSTALL_DIR="$directory_destination" \
  SHEPHERD_FORCE=1 "$installer" >/dev/null 2>&1; then
  fail 'force must refuse a destination directory instead of moving inside it'
fi
[[ -d "$directory_destination/shepherd" ]] || fail 'destination directory was replaced'
if find "$directory_destination/shepherd" -mindepth 1 -print -quit | grep -q .; then
  fail 'forced publication leaked its ready file inside the destination directory'
fi

symlink_destination="$tmp_dir/symlink-destination/bin"
symlink_target="$tmp_dir/symlink-destination/target"
mkdir -p "$symlink_destination" "$symlink_target"
ln -s "$symlink_target" "$symlink_destination/shepherd"
if SHEPHERD_OS=Linux SHEPHERD_ARCH=x86_64 SHEPHERD_VERSION=6.4.6 \
  SHEPHERD_RELEASE_BASE="file://$release_root" SHEPHERD_INSTALL_DIR="$symlink_destination" \
  SHEPHERD_FORCE=1 "$installer" >/dev/null 2>&1; then
  fail 'force must refuse a symlink-to-directory destination'
fi
[[ -L "$symlink_destination/shepherd" ]] || fail 'destination symlink was replaced'
if find "$symlink_target" -mindepth 1 -print -quit | grep -q .; then
  fail 'forced publication followed the destination symlink'
fi

dangling_dir="$tmp_dir/dangling/bin"
mkdir -p "$dangling_dir"
ln -s "$tmp_dir/does-not-exist" "$dangling_dir/shepherd"
if SHEPHERD_OS=Linux SHEPHERD_ARCH=x86_64 SHEPHERD_VERSION=6.4.6 \
  SHEPHERD_RELEASE_BASE="file://$release_root" SHEPHERD_INSTALL_DIR="$dangling_dir" \
  "$installer" >/dev/null 2>&1; then
  fail 'dangling destination symlink must not be replaced without force'
fi
[[ -L "$dangling_dir/shepherd" ]] || fail 'dangling destination symlink was replaced'

fake_bin="$tmp_dir/fake-bin"
mkdir -p "$fake_bin"
cat > "$fake_bin/ln" <<'EOF'
#!/bin/sh
printf 'concurrent creator\n' > "$2"
exec "$SHEPHERD_REAL_LN" "$@"
EOF
chmod 755 "$fake_bin/ln"
race_dir="$tmp_dir/race/bin"
if PATH="$fake_bin:$PATH" SHEPHERD_REAL_LN="$(command -v ln)" \
  SHEPHERD_OS=Linux SHEPHERD_ARCH=x86_64 SHEPHERD_VERSION=6.4.6 \
  SHEPHERD_RELEASE_BASE="file://$release_root" SHEPHERD_INSTALL_DIR="$race_dir" \
  "$installer" >/dev/null 2>&1; then
  fail 'concurrent destination creator must win the no-clobber race'
fi
expect_eq "$(cat "$race_dir/shepherd")" 'concurrent creator' \
  'atomic no-clobber preserves concurrent destination'

printf 'not-a-checksum\n' >"$asset_dir/$asset.sha256"
if SHEPHERD_OS=Linux SHEPHERD_ARCH=x86_64 SHEPHERD_VERSION=6.4.6 \
  SHEPHERD_RELEASE_BASE="file://$release_root" SHEPHERD_INSTALL_DIR="$tmp_dir/checksum-bin" \
  "$installer" >/dev/null 2>&1; then
  fail 'malformed checksum must fail'
fi
[[ ! -e "$tmp_dir/checksum-bin/shepherd" ]] || fail 'checksum failure wrote a destination binary'

bad_dir="$release_root/download/v6.4.7"
mkdir -p "$bad_dir" "$tmp_dir/extra-payload"
cp "$payload" "$tmp_dir/extra-payload/shepherd"
cp LICENSE THIRD_PARTY_NOTICES.md "$tmp_dir/extra-payload/"
cp -R THIRD_PARTY_LICENSES "$tmp_dir/extra-payload/"
bad_legal_entries=()
while IFS= read -r entry; do
  bad_legal_entries+=("$entry")
done < <(cd "$tmp_dir/extra-payload" && find THIRD_PARTY_LICENSES -type f -name '*.txt' -print | LC_ALL=C sort)
printf 'unexpected\n' >"$tmp_dir/extra-payload/extra.txt"
bad_asset='shepherd-6.4.7-x86_64-unknown-linux-gnu.tar.gz'
(
  cd "$tmp_dir/extra-payload"
  tar -czf "$bad_dir/$bad_asset" LICENSE THIRD_PARTY_NOTICES.md "${bad_legal_entries[@]}" shepherd extra.txt
  shasum -a 256 "$bad_dir/$bad_asset" >"$bad_dir/$bad_asset.sha256"
)
if SHEPHERD_OS=Linux SHEPHERD_ARCH=x86_64 SHEPHERD_VERSION=6.4.7 \
  SHEPHERD_RELEASE_BASE="file://$release_root" SHEPHERD_INSTALL_DIR="$tmp_dir/archive-bin" \
  "$installer" >/dev/null 2>&1; then
  fail 'archive with unexpected entries must fail'
fi
[[ ! -e "$tmp_dir/archive-bin/shepherd" ]] || fail 'unsafe archive wrote a destination binary'

printf 'ok: release installer platform, URL, checksum, and atomic replacement contracts\n'
