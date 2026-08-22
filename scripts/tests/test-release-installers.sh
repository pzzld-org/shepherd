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

rg -Fq 'ready=$(mktemp "$destination_dir/.shepherd-ready.XXXXXX")' "$installer" || { rc=$?; printf 'FAIL: release installer must stage the ready file via mktemp under the destination directory (rg rc=%s)\n' "$rc" >&2; exit 1; }
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
  actual=$(SHEPHERD_OS="$os" SHEPHERD_ARCH="$arch" SHEPHERD_VERSION=6.5.6 \
    "$installer" --print-asset)
  expect_eq "$actual" "$expected" "asset for $os/$arch"
}

asset_for Darwin arm64 shepherd-6.5.6-aarch64-apple-darwin.tar.gz
asset_for Darwin x86_64 shepherd-6.5.6-x86_64-apple-darwin.tar.gz
asset_for Linux aarch64 shepherd-6.5.6-aarch64-unknown-linux-gnu.tar.gz
asset_for Linux x86_64 shepherd-6.5.6-x86_64-unknown-linux-gnu.tar.gz
asset_for MINGW64_NT x86_64 shepherd-6.5.6-x86_64-pc-windows-msvc.zip

if SHEPHERD_OS=MINGW64_NT SHEPHERD_ARCH=arm64 SHEPHERD_VERSION=6.5.6 \
  "$installer" --print-asset >/dev/null 2>&1; then
  fail 'Windows ARM64 must fail until the release matrix publishes that asset'
fi
if SHEPHERD_OS=Linux SHEPHERD_LIBC=musl SHEPHERD_ARCH=x86_64 SHEPHERD_VERSION=6.5.6 \
  "$installer" --print-asset >/dev/null 2>&1; then
  fail 'musl Linux must fail until the release matrix publishes that asset'
fi

explicit_url=$(SHEPHERD_OS=Linux SHEPHERD_ARCH=x86_64 SHEPHERD_VERSION=6.5.6 \
  "$installer" --print-url)
expect_eq "$explicit_url" \
  'https://github.com/pzzld-org/shepherd/releases/download/v6.5.6/shepherd-6.5.6-x86_64-unknown-linux-gnu.tar.gz' \
  'explicit version URL'

latest_url=$(SHEPHERD_OS=Linux SHEPHERD_ARCH=x86_64 "$installer" --print-url)
expect_eq "$latest_url" \
  'https://github.com/pzzld-org/shepherd/releases/latest/download/shepherd-x86_64-unknown-linux-gnu.tar.gz' \
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
asset_dir="$release_root/download/v6.5.6"
mkdir -p "$asset_dir" "$tmp_dir/payload"
payload="$tmp_dir/payload/shepherd"
cat >"$payload" <<'EOF'
#!/usr/bin/env sh
printf 'shepherd fixture 6.5.6\n'
EOF
chmod 755 "$payload"

# Installer behavior needs a valid archive shape, not the repository's complete
# dependency inventory. Build an isolated legal fixture so this test remains
# independent of generated release payloads committed at repository root.
cp LICENSE "$tmp_dir/payload/"
mkdir -p "$tmp_dir/payload/THIRD_PARTY_LICENSES"
if command -v sha256sum >/dev/null 2>&1; then
  legal_hash=$(sha256sum LICENSE | awk '{print $1}')
else
  legal_hash=$(shasum -a 256 LICENSE | awk '{print $1}')
fi
cp LICENSE "$tmp_dir/payload/THIRD_PARTY_LICENSES/$legal_hash.txt"
printf '# fixture notices\n\nTHIRD_PARTY_LICENSES/%s.txt\n' "$legal_hash" \
  >"$tmp_dir/payload/THIRD_PARTY_NOTICES.md"

legal_entries=()
while IFS= read -r entry; do
  legal_entries+=("$entry")
done < <(cd "$tmp_dir/payload" && find THIRD_PARTY_LICENSES -type f -name '*.txt' -print | LC_ALL=C sort)
asset='shepherd-6.5.6-x86_64-unknown-linux-gnu.tar.gz'
(
  cd "$tmp_dir/payload"
  tar -czf "$asset_dir/$asset" LICENSE THIRD_PARTY_NOTICES.md "${legal_entries[@]}" shepherd
)
(
  cd "$asset_dir"
  shasum -a 256 "$asset" >"$asset.sha256"
)

install_dir="$tmp_dir/install/bin"
SHEPHERD_OS=Linux SHEPHERD_ARCH=x86_64 SHEPHERD_VERSION=6.5.6 \
  SHEPHERD_RELEASE_BASE="file://$release_root" SHEPHERD_INSTALL_DIR="$install_dir" \
  "$installer" >/dev/null
[[ -x "$install_dir/shepherd" ]] || fail 'installer did not install an executable'
expect_eq "$("$install_dir/shepherd")" 'shepherd fixture 6.5.6' 'installed executable'

printf 'do-not-replace\n' >"$install_dir/shepherd"
if SHEPHERD_OS=Linux SHEPHERD_ARCH=x86_64 SHEPHERD_VERSION=6.5.6 \
  SHEPHERD_RELEASE_BASE="file://$release_root" SHEPHERD_INSTALL_DIR="$install_dir" \
  "$installer" >/dev/null 2>&1; then
  fail 'existing installation must not be clobbered without SHEPHERD_FORCE=1'
fi
expect_eq "$(cat "$install_dir/shepherd")" 'do-not-replace' 'no-clobber preserves old binary'

SHEPHERD_OS=Linux SHEPHERD_ARCH=x86_64 SHEPHERD_VERSION=6.5.6 \
  SHEPHERD_RELEASE_BASE="file://$release_root" SHEPHERD_INSTALL_DIR="$install_dir" \
  SHEPHERD_FORCE=1 "$installer" >/dev/null
expect_eq "$("$install_dir/shepherd")" 'shepherd fixture 6.5.6' 'forced atomic replacement'

directory_destination="$tmp_dir/directory-destination/bin"
mkdir -p "$directory_destination/shepherd"
if SHEPHERD_OS=Linux SHEPHERD_ARCH=x86_64 SHEPHERD_VERSION=6.5.6 \
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
if SHEPHERD_OS=Linux SHEPHERD_ARCH=x86_64 SHEPHERD_VERSION=6.5.6 \
  SHEPHERD_RELEASE_BASE="file://$release_root" SHEPHERD_INSTALL_DIR="$symlink_destination" \
  SHEPHERD_FORCE=1 "$installer" >/dev/null 2>&1; then
  fail 'force must refuse a symlink-to-directory destination'
fi
[[ -L "$symlink_destination/shepherd" ]] || fail 'destination symlink was replaced'
if find "$symlink_target" -mindepth 1 -print -quit | grep -q .; then
  fail 'forced publication followed the destination symlink'
fi

live_symlink_destination="$tmp_dir/live-symlink-destination/bin"
live_symlink_target="$tmp_dir/live-symlink-destination/real-target"
live_symlink_stderr="$tmp_dir/live-symlink-destination/stderr.log"
mkdir -p "$live_symlink_destination"
printf 'do-not-touch-live-target\n' >"$live_symlink_target"
ln -s "$live_symlink_target" "$live_symlink_destination/shepherd"
# Regression coverage for guard_existing_destination()'s live-symlink branch
# (install-shepherd.sh around line 254): a symlink whose target is a real,
# existing regular FILE -- distinct from the symlink-to-directory case above.
# No SHEPHERD_VERSION/release fixture is staged for this destination, on
# purpose: the guard must refuse before ever reaching the download step, so
# this case needs nothing beyond the destination itself. Exit status alone is
# not enough to prove the guard fired -- the no-clobber `ln` a few lines below
# guard_existing_destination() also refuses an existing destination entry, so
# removing the explicit refusal still leaves the installer failing, just via
# a different message and only after attempting a network download. Assert
# the guard's own wording landed on stderr so this fails specifically when
# the guard itself is gone, then assert the symlink, its target, and the
# target's content all survive untouched.
if SHEPHERD_OS=Linux SHEPHERD_ARCH=x86_64 \
  SHEPHERD_RELEASE_BASE="file://$release_root" SHEPHERD_INSTALL_DIR="$live_symlink_destination" \
  "$installer" >/dev/null 2>"$live_symlink_stderr"; then
  fail 'live symlink destination must not be replaced without SHEPHERD_FORCE=1'
fi
if ! grep -Fq "a symlink to '$live_symlink_target'" "$live_symlink_stderr"; then
  fail "refusal did not come from the live-symlink guard; stderr was: $(cat "$live_symlink_stderr")"
fi
[[ -L "$live_symlink_destination/shepherd" ]] \
  || fail 'live destination symlink was replaced without SHEPHERD_FORCE'
expect_eq "$(readlink "$live_symlink_destination/shepherd")" "$live_symlink_target" \
  'live destination symlink target unchanged'
expect_eq "$(cat "$live_symlink_target")" 'do-not-touch-live-target' \
  'live symlink target content unchanged'
if find "$live_symlink_destination" -maxdepth 1 -name '.shepherd-*' -print -quit | grep -q .; then
  fail 'refused live-symlink install left a temporary artifact behind'
fi

dangling_dir="$tmp_dir/dangling/bin"
mkdir -p "$dangling_dir"
ln -s "$tmp_dir/does-not-exist" "$dangling_dir/shepherd"
# POLICY INVERSION -- deliberate, not a regression. Do not "fix" this back.
# This lane deletes the repo's bin/shepherd Bash-compatibility launcher
# outright, so every pre-existing ~/.local/bin/shepherd symlink that used to
# point into a checkout is now dangling. The sprint seed names the old
# behaviour as the defect in so many words: the installer "defaults to the
# exact directory the launcher symlink occupies and then refuses to repair
# it." An installer that cannot repair exactly the breakage this sprint
# creates is useless at its one remaining job. guard_existing_destination()
# in install-shepherd.sh (around line 245) now self-heals a dangling
# destination symlink without requiring SHEPHERD_FORCE: nothing live depends
# on a broken pointer, so there is nothing to protect by refusing. This case
# therefore asserts the installer succeeds and leaves a real regular file in
# place -- the opposite of what it asserted before. The live-symlink refusal
# case above (a symlink whose target still exists) is untouched and must
# keep failing without SHEPHERD_FORCE; only the dangling case changed.
SHEPHERD_OS=Linux SHEPHERD_ARCH=x86_64 SHEPHERD_VERSION=6.5.6 \
  SHEPHERD_RELEASE_BASE="file://$release_root" SHEPHERD_INSTALL_DIR="$dangling_dir" \
  "$installer" >/dev/null
[[ ! -L "$dangling_dir/shepherd" && -f "$dangling_dir/shepherd" ]] \
  || fail 'dangling destination symlink was not self-healed into a regular file'
expect_eq "$("$dangling_dir/shepherd")" 'shepherd fixture 6.5.6' 'dangling symlink self-heal'

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
  SHEPHERD_OS=Linux SHEPHERD_ARCH=x86_64 SHEPHERD_VERSION=6.5.6 \
  SHEPHERD_RELEASE_BASE="file://$release_root" SHEPHERD_INSTALL_DIR="$race_dir" \
  "$installer" >/dev/null 2>&1; then
  fail 'concurrent destination creator must win the no-clobber race'
fi
expect_eq "$(cat "$race_dir/shepherd")" 'concurrent creator' \
  'atomic no-clobber preserves concurrent destination'

printf 'not-a-checksum\n' >"$asset_dir/$asset.sha256"
if SHEPHERD_OS=Linux SHEPHERD_ARCH=x86_64 SHEPHERD_VERSION=6.5.6 \
  SHEPHERD_RELEASE_BASE="file://$release_root" SHEPHERD_INSTALL_DIR="$tmp_dir/checksum-bin" \
  "$installer" >/dev/null 2>&1; then
  fail 'malformed checksum must fail'
fi
[[ ! -e "$tmp_dir/checksum-bin/shepherd" ]] || fail 'checksum failure wrote a destination binary'

bad_dir="$release_root/download/v6.5.7"
mkdir -p "$bad_dir" "$tmp_dir/extra-payload"
cp "$payload" "$tmp_dir/extra-payload/shepherd"
cp LICENSE "$tmp_dir/extra-payload/"
cp "$tmp_dir/payload/THIRD_PARTY_NOTICES.md" "$tmp_dir/extra-payload/"
cp -R "$tmp_dir/payload/THIRD_PARTY_LICENSES" "$tmp_dir/extra-payload/"
bad_legal_entries=()
while IFS= read -r entry; do
  bad_legal_entries+=("$entry")
done < <(cd "$tmp_dir/extra-payload" && find THIRD_PARTY_LICENSES -type f -name '*.txt' -print | LC_ALL=C sort)
printf 'unexpected\n' >"$tmp_dir/extra-payload/extra.txt"
bad_asset='shepherd-6.5.7-x86_64-unknown-linux-gnu.tar.gz'
(
  cd "$tmp_dir/extra-payload"
  tar -czf "$bad_dir/$bad_asset" LICENSE THIRD_PARTY_NOTICES.md "${bad_legal_entries[@]}" shepherd extra.txt
  shasum -a 256 "$bad_dir/$bad_asset" >"$bad_dir/$bad_asset.sha256"
)
if SHEPHERD_OS=Linux SHEPHERD_ARCH=x86_64 SHEPHERD_VERSION=6.5.7 \
  SHEPHERD_RELEASE_BASE="file://$release_root" SHEPHERD_INSTALL_DIR="$tmp_dir/archive-bin" \
  "$installer" >/dev/null 2>&1; then
  fail 'archive with unexpected entries must fail'
fi
[[ ! -e "$tmp_dir/archive-bin/shepherd" ]] || fail 'unsafe archive wrote a destination binary'

printf 'ok: release installer platform, URL, checksum, and atomic replacement contracts\n'
