#!/usr/bin/env bash
# conformance/scripts/checksum.sh -- content-address conformance/cases/**.
#
# Prints ONE hex sha256 line to stdout: sha256 of a sorted manifest of
# "<relpath>\t<sha256 of that file's bytes>\n" lines, one per file under
# cases/. Sorting by relpath (not physical/mtime order) is what makes the
# result reproducible across machines and checkouts; hashing each file's
# bytes individually first (rather than concatenating raw file contents)
# means a rename with unchanged content still changes the checksum, which
# is the correct behavior for a corpus whose path IS part of its meaning
# (case_id comes from the directory path).
#
# Used two ways: `run.sh --verify-checksum` calls this and diffs the output
# against the committed conformance/CHECKSUM; a human/coder re-authoring the
# corpus calls it directly and writes the output to CHECKSUM.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CASES_DIR="$HERE/../cases"

# macOS ships no sha256sum (GNU coreutils); shasum -a 256 is the portable
# first choice, sha256sum the Linux/CI fallback (code-style/shell skill).
_sha256() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    sha256sum "$1" | awk '{print $1}'
  fi
}

[[ -d "$CASES_DIR" ]] || { printf 'checksum.sh: no cases dir at %s\n' "$CASES_DIR" >&2; exit 1; }

manifest="$(mktemp)"
trap 'rm -f "$manifest"' EXIT

cd "$CASES_DIR"
while IFS= read -r f; do
  printf '%s\t%s\n' "$f" "$(_sha256 "$f")" >>"$manifest"
done < <(find . -type f | sort)

_sha256 "$manifest"
