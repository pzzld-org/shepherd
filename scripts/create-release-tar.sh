#!/usr/bin/env bash
set -euo pipefail

fail() {
  printf 'create-release-tar: %s\n' "$*" >&2
  exit 1
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

temporary=$(mktemp "$output_dir/.shepherd-release-tar.XXXXXX")
trap 'rm -f "$temporary"' EXIT

# This option set is shared by GNU tar on Linux and bsdtar on macOS. Numeric
# owner normalization avoids the BSD-only --uid/--gid/--uname/--gname flags
# while preserving byte-reproducible ustar headers on every release runner.
COPYFILE_DISABLE=1 LC_ALL=C \
  tar --format=ustar --owner=0 --group=0 --numeric-owner \
    -C "$source_dir" -cf - -- "$@" \
  | gzip -n > "$temporary"

mv -f "$temporary" "$output"
trap - EXIT
