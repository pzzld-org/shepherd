#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/shepherd-packed-tar.XXXXXX")
trap 'find "$tmp_dir" -depth -delete' EXIT
mkdir -p "$tmp_dir/package"
printf 'first member\n' > "$tmp_dir/package/early.txt"
for index in $(seq 1 5000); do
  printf 'member %s\n' "$index" > "$tmp_dir/package/member-${index}.txt"
done

archive="$tmp_dir/archive.tgz"
(cd "$tmp_dir" && tar -czf "$archive" package)

if tar --version 2>/dev/null | grep -q 'GNU tar'; then
  if (set -o pipefail; tar -tzf "$archive" | grep -q 'package/early.txt'); then
    printf 'GNU tar early-match pipeline unexpectedly succeeded\n' >&2
    exit 1
  fi
  printf 'ok: GNU tar + pipefail negative control reproduces producer SIGPIPE\n'
else
  printf 'skip: GNU tar is unavailable on this host; static workflow check covers the production pipeline\n'
fi

listing="$tmp_dir/archive.list"
tar -tzf "$archive" > "$listing"
grep -Fxq 'package/early.txt' "$listing"
grep -Fxq 'package/member-5000.txt' "$listing"
printf 'ok: full tar listing is drained before grep filtering\n'
