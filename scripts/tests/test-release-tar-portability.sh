#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

creator="$PWD/scripts/create-release-tar.sh"
tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/shepherd-release-tar.XXXXXX")
trap 'find "$tmp_dir" -depth -delete' EXIT

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

source_dir="$tmp_dir/source"
mkdir -p "$source_dir/THIRD_PARTY_LICENSES"
printf 'license\n' > "$source_dir/LICENSE"
printf 'notices\n' > "$source_dir/THIRD_PARTY_NOTICES.md"
printf 'dependency license\n' > "$source_dir/THIRD_PARTY_LICENSES/dependency.txt"
printf 'payload\n' > "$source_dir/payload"
printf 'option-shaped filename\n' > "$source_dir/--exclude=payload"
TZ=UTC find "$source_dir" -type f -exec touch -t 198001010000 {} +

real_tar=$(command -v tar)

# Two stubs modelling REAL tar implementations, not the script under test.
# GNU tar has --owner/--group and rejects --uid/--gid/--uname/--gname; older
# libarchive (bsdtar) rejects --owner/--group in every spelling and requires
# --uid/--gid/--uname/--gname instead. No real implementation accepts every
# option this script might send, which is exactly the bug: create-release-tar.sh
# must detect which family its tar actually supports rather than assume one.

mkdir -p "$tmp_dir/bin/gnu"
cat > "$tmp_dir/bin/gnu/tar" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
options_terminated=0
for argument in "$@"; do
  case "$argument" in
    --)
      options_terminated=1
      ;;
    --owner|--owner=*|--group|--group=*)
      # GNU tar: accepted, in both the separated and compact spelling.
      ;;
    --uid|--uid=*|--gid|--gid=*|--uname|--uname=*|--gname|--gname=*)
      printf 'portable tar regression: GNU-like tar rejects BSD-only option %s\n' "$argument" >&2
      exit 64
      ;;
    --exclude=payload)
      if ((options_terminated == 0)); then
        printf 'portable tar regression: option-shaped entry reached tar without --\n' >&2
        exit 64
      fi
      ;;
  esac
done
exec "${REAL_TAR:?}" "$@"
SH
chmod 755 "$tmp_dir/bin/gnu/tar"

mkdir -p "$tmp_dir/bin/libarchive"
cat > "$tmp_dir/bin/libarchive/tar" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
options_terminated=0
for argument in "$@"; do
  case "$argument" in
    --)
      options_terminated=1
      ;;
    --owner|--owner=*)
      printf 'tar: Option --owner=0 is not supported\n' >&2
      exit 1
      ;;
    --group|--group=*)
      printf 'tar: Option --group=0 is not supported\n' >&2
      exit 1
      ;;
    --exclude=payload)
      if ((options_terminated == 0)); then
        printf 'portable tar regression: option-shaped entry reached tar without --\n' >&2
        exit 64
      fi
      ;;
  esac
done
exec "${REAL_TAR:?}" "$@"
SH
chmod 755 "$tmp_dir/bin/libarchive/tar"

entries=(
  LICENSE
  THIRD_PARTY_NOTICES.md
  THIRD_PARTY_LICENSES/dependency.txt
  payload
  --exclude=payload
)

check_archive_properties() {
  local archive="$1" label="$2" actual expected

  actual=$(tar -tzf "$archive")
  expected=$'LICENSE\nTHIRD_PARTY_NOTICES.md\nTHIRD_PARTY_LICENSES/dependency.txt\npayload\n--exclude=payload'
  [[ "$actual" == "$expected" ]] || \
    fail "$label: release tar contains an unexpected entry set or order"

  python3 - "$archive" "$label" <<'PY'
from pathlib import Path
import sys
import tarfile

archive = Path(sys.argv[1])
label = sys.argv[2]
with tarfile.open(archive, "r:gz") as handle:
    members = handle.getmembers()

if not members:
    raise SystemExit(f"{label}: release tar is empty")
for member in members:
    if (member.uid, member.gid) != (0, 0):
        raise SystemExit(f"{label}: non-canonical owner for {member.name}: {member.uid}:{member.gid}")
    if member.mtime != 315532800:
        raise SystemExit(f"{label}: non-canonical mtime for {member.name}: {member.mtime}")
PY
}

first_archives=()
for label in gnu libarchive; do
  first="$tmp_dir/$label-first.tar.gz"
  second="$tmp_dir/$label-second.tar.gz"

  for archive in "$first" "$second"; do
    PATH="$tmp_dir/bin/$label:$PATH" REAL_TAR="$real_tar" \
      "$creator" "$source_dir" "$archive" "${entries[@]}" || \
      fail "$label: create-release-tar.sh failed under the $label-like tar stub"
  done

  cmp -s "$first" "$second" || \
    fail "$label: release tar must be byte-reproducible across two runs under the $label-like tar stub"

  check_archive_properties "$first" "$label"

  first_archives+=("$first")
done

# The GNU-owner-flags path and the libarchive-uid-flags path must produce
# byte-identical ustar headers. Release targets build on different runner
# images; if the two flag sets diverged, the same version would ship
# non-comparable artifacts depending on which runner packaged it.
cmp -s "${first_archives[0]}" "${first_archives[1]}" || \
  fail 'the GNU-like and old-libarchive-like tar stubs must produce byte-identical archives from identical staged inputs'

printf 'ok: release tar creation is portable, exact, and reproducible under both GNU-like and old-libarchive-like tar\n'
