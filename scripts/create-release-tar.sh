#!/usr/bin/env bash
set -euo pipefail

fail() {
  printf 'create-release-tar: %s\n' "$*" >&2
  exit 1
}

# GNU tar accepts --owner/--group (and rejects --uid/--gid/--uname/--gname);
# older libarchive (bsdtar) is the exact inverse and rejects --owner/--group
# in every spelling, including the compact --owner=0. No flag set is shared
# by both, so `owner_flags` is chosen by probing tar's real behaviour on a
# throwaway archive rather than trusting a `tar --version` string, which is
# exactly the assumption that produced this defect in the first place.
detect_owner_flags() {
  local probe_dir
  probe_dir=$(mktemp -d "${TMPDIR:-/tmp}/create-release-tar-probe.XXXXXX")
  printf 'p\n' > "$probe_dir/probe"

  if tar --format=ustar --owner 0 --group 0 --numeric-owner \
       -C "$probe_dir" -cf /dev/null -- probe >/dev/null 2>&1; then
    owner_flags=(--owner 0 --group 0 --numeric-owner)
  elif tar --format=ustar --uid 0 --gid 0 --uname '' --gname '' \
       -C "$probe_dir" -cf /dev/null -- probe >/dev/null 2>&1; then
    owner_flags=(--uid 0 --gid 0 --uname '' --gname '')
  else
    rm -rf "$probe_dir"
    fail 'no supported tar ownership flag set (checked GNU --owner/--group and libarchive --uid/--gid)'
  fi

  rm -rf "$probe_dir"
}

if (($# < 3)); then
  fail 'usage: create-release-tar.sh <source-dir> <output.tar.gz> <entry>...'
fi

source_dir="$1"
output="$2"
shift 2

[[ -d "$source_dir" && ! -L "$source_dir" ]] || \
  fail "source directory is missing, not a directory, or a symlink: $source_dir"

for entry in "$@"; do
  case "$entry" in
    ''|/*|..|../*|*/../*|*/..)
      fail "entry must be a non-empty relative path without parent traversal: $entry"
      ;;
  esac
  [[ -f "$source_dir/$entry" && ! -L "$source_dir/$entry" ]] || \
    fail "entry is missing, not a regular file, or a symlink: $entry"
done

output_dir=$(dirname "$output")
[[ -d "$output_dir" && ! -L "$output_dir" ]] || \
  fail "output directory is missing, not a directory, or a symlink: $output_dir"

owner_flags=()
detect_owner_flags

temporary=$(mktemp "$output_dir/.shepherd-release-tar.XXXXXX")
trap 'rm -f "$temporary"' EXIT

COPYFILE_DISABLE=1 LC_ALL=C \
  tar --format=ustar "${owner_flags[@]}" \
    -C "$source_dir" -cf - -- "$@" \
  | gzip -n > "$temporary"

mv -f "$temporary" "$output"
trap - EXIT
