#!/usr/bin/env bash
set -euo pipefail
source_dir="$1"; output="$2"; shift 2

# GNU tar has --owner/--group and no --uid/--gid. Older libarchive has the
# inverse. There is NO flag set shared by both, which is why this probes rather
# than asserting. The probe tests behaviour, not `tar --version`: the version
# string already lied on this codepath once and shipped a zero-asset release.
OWNER_FLAGS=()
probe=$(mktemp -d "${TMPDIR:-/tmp}/tarprobe.XXXXXX")
printf 'p\n' > "$probe/f"
if tar --format=ustar --owner 0 --group 0 --numeric-owner \
     -C "$probe" -cf /dev/null -- f 2>/dev/null; then
  OWNER_FLAGS=(--owner 0 --group 0 --numeric-owner)
elif tar --format=ustar --uid 0 --gid 0 --uname "" --gname "" \
     -C "$probe" -cf /dev/null -- f 2>/dev/null; then
  OWNER_FLAGS=(--uid 0 --gid 0 --uname "" --gname "")
else
  rm -rf "$probe"
  printf 'create-release-tar: no supported ownership flag set for this tar\n' >&2
  exit 1
fi
rm -rf "$probe"

COPYFILE_DISABLE=1 LC_ALL=C \
  tar --format=ustar "${OWNER_FLAGS[@]}" -C "$source_dir" -cf - -- "$@" \
  | gzip -n > "$output"
