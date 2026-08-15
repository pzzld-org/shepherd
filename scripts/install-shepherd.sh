#!/usr/bin/env bash
# Install the single native Shepherd CLI from an immutable GitHub release.
#
# No checkout, package manager, or generated adapter owns this operation. The
# release archive is checksum-verified before its exact root binary is moved
# into place. Existing installations are intentionally preserved unless the
# caller explicitly sets SHEPHERD_FORCE=1.
set -euo pipefail

readonly DEFAULT_RELEASE_BASE='https://github.com/FL03/shepherd/releases'

fail() {
  printf 'shepherd installer: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: install-shepherd.sh [--print-asset|--print-url|--help]

Environment:
  SHEPHERD_VERSION       Exact version without a leading v, or unset for latest.
  SHEPHERD_INSTALL_DIR   Destination directory, default: $HOME/.local/bin.
  SHEPHERD_RELEASE_BASE  GitHub releases base, default: FL03/shepherd.
  SHEPHERD_FORCE=1       Atomically replace an existing shepherd binary.

The installer never modifies PATH. Add SHEPHERD_INSTALL_DIR to PATH yourself.
EOF
}

normalized_linux_libc() {
  local libc="${SHEPHERD_LIBC:-}"
  if [[ -z "$libc" ]]; then
    if getconf GNU_LIBC_VERSION >/dev/null 2>&1; then
      libc=gnu
    elif command -v ldd >/dev/null 2>&1; then
      local details
      details=$(ldd --version 2>&1 || true)
      if printf '%s' "$details" | grep -qi musl; then
        libc=musl
      elif printf '%s' "$details" | grep -Eqi 'glibc|gnu libc'; then
        libc=gnu
      fi
    fi
  fi
  case "$libc" in
    gnu|glibc) printf '%s\n' gnu ;;
    musl) fail 'musl Linux release asset is not published' ;;
    *) fail 'could not identify Linux libc; set SHEPHERD_LIBC=gnu only for a GNU libc host' ;;
  esac
}

normalized_os() {
  local os="${SHEPHERD_OS:-$(uname -s)}"
  case "$os" in
    Darwin) printf '%s\n' 'apple-darwin' ;;
    Linux)
      normalized_linux_libc >/dev/null
      printf '%s\n' 'unknown-linux-gnu'
      ;;
    MINGW*|MSYS*|CYGWIN*|Windows_NT) printf '%s\n' 'pc-windows-msvc' ;;
    *) fail "unsupported operating system '$os'" ;;
  esac
}

normalized_arch() {
  local arch="${SHEPHERD_ARCH:-$(uname -m)}"
  case "$arch" in
    arm64|aarch64) printf '%s\n' aarch64 ;;
    x86_64|amd64) printf '%s\n' x86_64 ;;
    *) fail "unsupported architecture '$arch'" ;;
  esac
}

release_target() {
  local arch os
  arch=$(normalized_arch)
  os=$(normalized_os)
  if [[ "$os" == pc-windows-msvc && "$arch" != x86_64 ]]; then
    fail 'Windows ARM64 release asset is not published'
  fi
  printf '%s-%s\n' "$arch" "$os"
}

archive_extension() {
  case "$(normalized_os)" in
    pc-windows-msvc) printf '%s\n' zip ;;
    *) printf '%s\n' tar.gz ;;
  esac
}

version_value() {
  local value="${SHEPHERD_VERSION:-}"
  value="${value#v}"
  if [[ -n "$value" && ! "$value" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    fail "SHEPHERD_VERSION must be an exact semantic version, got '$value'"
  fi
  printf '%s\n' "$value"
}

asset_name() {
  local target
  target=$(release_target)
  local ext
  ext=$(archive_extension)
  local version
  version=$(version_value)
  if [[ -n "$version" ]]; then
    printf 'shepherd-%s-%s.%s\n' "$version" "$target" "$ext"
  else
    printf 'shepherd-%s.%s\n' "$target" "$ext"
  fi
}

asset_url() {
  local base="${SHEPHERD_RELEASE_BASE:-$DEFAULT_RELEASE_BASE}"
  base="${base%/}"
  local version
  version=$(version_value)
  if [[ -n "$version" ]]; then
    printf '%s/download/v%s/%s\n' "$base" "$version" "$(asset_name)"
  else
    printf '%s/latest/download/%s\n' "$base" "$(asset_name)"
  fi
}

checksum() {
  local archive="$1"
  local check_file="$2"
  local line
  line=$(cat "$check_file")
  [[ $(wc -l <"$check_file" | tr -d ' ') == 1 ]] || fail 'checksum file must contain exactly one entry'
  local declared
  declared=${line%% *}
  local remainder
  remainder=${line#"$declared"}
  [[ "$declared" =~ ^[0-9A-Fa-f]{64}$ && "$remainder" == "  $(basename "$archive")" ]] \
    || fail 'checksum file is malformed or names a different asset'

  local actual
  if command -v sha256sum >/dev/null 2>&1; then
    actual=$(sha256sum "$archive" | awk '{print $1}')
  elif command -v shasum >/dev/null 2>&1; then
    actual=$(shasum -a 256 "$archive" | awk '{print $1}')
  else
    fail 'requires sha256sum or shasum for SHA-256 verification'
  fi
  actual=$(printf '%s' "$actual" | tr '[:upper:]' '[:lower:]')
  declared=$(printf '%s' "$declared" | tr '[:upper:]' '[:lower:]')
  [[ "$actual" == "$declared" ]] || fail 'SHA-256 checksum verification failed'
}

archive_binary() {
  case "$(normalized_os)" in
    pc-windows-msvc) printf '%s\n' shepherd.exe ;;
    *) printf '%s\n' shepherd ;;
  esac
}

extract_binary() {
  local archive="$1"
  local staging="$2"
  local binary
  binary=$(archive_binary)
  local listed
  mkdir -p "$staging"
  validate_entries() {
    local entries="$1"
    if ! printf '%s\n' "$entries" | awk -v binary="$binary" '
      $0 == binary { binary_seen = 1; next }
      $0 == "LICENSE" { license_seen = 1; next }
      $0 == "THIRD_PARTY_NOTICES.md" { notices_seen = 1; next }
      $0 ~ /^THIRD_PARTY_LICENSES\/[0-9a-f]{64}\.txt$/ { legal_seen += 1; next }
      { exit 1 }
      END { exit !(binary_seen && license_seen && notices_seen && legal_seen > 0) }
    '; then
      fail "release archive must contain $binary, LICENSE, THIRD_PARTY_NOTICES.md, and only hashed third-party license texts"
    fi
  }

  case "$archive" in
    *.tar.gz)
      listed=$(tar -tzf "$archive" | LC_ALL=C sort) || fail 'could not read release archive'
      validate_entries "$listed"
      tar -xzf "$archive" -C "$staging" "$binary" || fail 'could not extract release archive'
      ;;
    *.zip)
      command -v unzip >/dev/null 2>&1 || fail 'requires unzip for the Windows archive'
      listed=$(unzip -Z1 "$archive" | LC_ALL=C sort) || fail 'could not read release archive'
      validate_entries "$listed"
      unzip -qq "$archive" "$binary" -d "$staging" || fail 'could not extract release archive'
      ;;
    *) fail "unsupported archive format '$archive'" ;;
  esac

  [[ -f "$staging/$binary" ]] || fail "release archive did not produce '$binary'"
  printf '%s\n' "$staging/$binary"
}

publish_forced() {
  local source="$1"
  local target="$2"
  local target_dir="$3"

  # POSIX mv interprets an existing directory, including a followed symlink,
  # as a container. Force means replace one regular-file directory entry; it
  # never means move the candidate somewhere below that entry.
  [[ ! -d "$target" ]] || fail "refusing to replace non-file destination '$target'"

  # Keep a same-filesystem hard-link witness so the postcondition can prove
  # which inode was published. This also lets the BSD fallback identify and
  # remove its own candidate if a directory wins the check/rename race.
  local witness
  witness=$(mktemp "$target_dir/.shepherd-witness.XXXXXX")
  rm -f "$witness"
  ln "$source" "$witness" || fail 'could not create forced-publication witness'

  if mv --help 2>&1 | grep -q -- '--no-target-directory'; then
    if ! mv -fT "$source" "$target"; then
      rm -f "$witness"
      fail "could not atomically replace '$target'"
    fi
  elif ! mv -fh "$source" "$target"; then
    rm -f "$witness"
    fail "could not atomically replace '$target'"
  fi

  if [[ -f "$target" && ! -L "$target" && "$target" -ef "$witness" ]]; then
    rm -f "$witness"
    return 0
  fi

  # BSD mv lacks GNU's --no-target-directory. If a directory appeared after
  # the precheck, mv may have placed the source below it. Remove only the inode
  # proven by the witness, then fail instead of reporting a false success.
  local leaked
  leaked="$target/$(basename "$source")"
  if [[ -f "$leaked" && ! -L "$leaked" && "$leaked" -ef "$witness" ]]; then
    rm -f "$leaked"
  fi
  rm -f "$witness"
  fail "forced publication did not replace exact regular-file destination '$target'"
}

main() {
  case "${1:---install}" in
    --help|-h) usage; return 0 ;;
    --print-asset)
      normalized_os >/dev/null
      normalized_arch >/dev/null
      asset_name
      return 0
      ;;
    --print-url)
      normalized_os >/dev/null
      normalized_arch >/dev/null
      version_value >/dev/null
      asset_url
      return 0
      ;;
    --install) ;;
    *) usage >&2; fail "unknown option '$1'" ;;
  esac

  normalized_os >/dev/null
  normalized_arch >/dev/null
  version_value >/dev/null

  case "$(normalized_os)" in
    pc-windows-msvc)
      fail 'use scripts/install-shepherd.ps1 from PowerShell on Windows'
      ;;
  esac

  command -v curl >/dev/null 2>&1 || fail 'requires curl'
  command -v tar >/dev/null 2>&1 || fail 'requires tar'
  command -v ln >/dev/null 2>&1 || fail 'requires ln for atomic no-clobber publication'

  local destination_dir="${SHEPHERD_INSTALL_DIR:-${HOME:?HOME is required}/.local/bin}"
  local binary
  binary=$(archive_binary)
  local destination="$destination_dir/$binary"
  if [[ ( -e "$destination" || -L "$destination" ) && "${SHEPHERD_FORCE:-0}" != 1 ]]; then
    fail "refusing to replace existing '$destination'; rerun with SHEPHERD_FORCE=1"
  fi

  local parent
  parent=$(dirname "$destination_dir")
  mkdir -p "$parent"
  local temporary
  temporary=$(mktemp -d "$parent/.shepherd-install.XXXXXX")
  trap 'find "$temporary" -depth -delete' EXIT

  local archive
  archive="$temporary/$(asset_name)"
  local url
  url=$(asset_url)
  curl --fail --location --proto '=https,file' --silent --show-error \
    --output "$archive" "$url" || fail "failed to download $url"
  curl --fail --location --proto '=https,file' --silent --show-error \
    --output "$archive.sha256" "$url.sha256" || fail "failed to download $url.sha256"
  checksum "$archive" "$archive.sha256"

  local extracted
  extracted=$(extract_binary "$archive" "$temporary/extract")
  chmod 755 "$extracted"
  mkdir -p "$destination_dir"
  # The publication candidate lives inside the destination directory. This
  # guarantees that both the no-clobber hard link and the forced rename stay on
  # the destination filesystem even when SHEPHERD_INSTALL_DIR is a mountpoint
  # or resolves through a symlink.
  local ready
  ready=$(mktemp "$destination_dir/.shepherd-ready.XXXXXX")
  trap 'rm -f "$ready" 2>/dev/null || true; find "$temporary" -depth -delete' EXIT
  mv -f "$extracted" "$ready"
  if [[ "${SHEPHERD_FORCE:-0}" == 1 ]]; then
    publish_forced "$ready" "$destination" "$destination_dir"
  else
    # A same-filesystem hard link is an atomic no-replace publication: `ln`
    # fails with EEXIST for files and dangling symlinks, including a destination
    # created after the earlier diagnostic check.
    if ! ln "$ready" "$destination"; then
      fail "refusing to replace concurrently created '$destination'"
    fi
    rm -f "$ready"
  fi
  trap - EXIT
  find "$temporary" -depth -delete
  printf 'installed %s to %s\n' "$(asset_name)" "$destination"
}

main "${1:---install}"
