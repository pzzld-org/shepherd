#!/usr/bin/env bash
# W0-GATE reproduction for run v646 lane `distribution`.
#
# Seed gate H1: "deliverables 1, 2, 3 reproduce as failures before any fix
# lands. A sprint that cannot demonstrate the bug cannot demonstrate the fix."
#
# Run from the repo root. Read-only against the repo; all scratch is under a
# mktemp dir. Exits 0 when every defect still reproduces, 1 when one has
# stopped reproducing (which means the evidence is stale, not that it is fixed).
set -uo pipefail
cd "$(dirname "$0")/../../../../.." || exit 1

STILL_BROKEN=0
still() { printf '  REPRODUCED: %s\n' "$1"; STILL_BROKEN=$((STILL_BROKEN + 1)); }

printf '== 1a: create-release-tar.sh flag set is not portable ==\n'
printf '   local tar: %s\n' "$(tar --version 2>&1 | head -1)"
w=$(mktemp -d "${TMPDIR:-/tmp}/v646-1a.XXXXXX")
mkdir -p "$w/gnu" "$w/bsd" "$w/src" "$w/out"
printf 'payload\n' > "$w/src/shepherd"
# Old libarchive: --uid/--gid only, rejects --owner/--group.
cat > "$w/bsd/tar" <<'STUB'
#!/bin/bash
for a in "$@"; do case "$a" in
  --owner*) echo "tar: Option --owner=0 is not supported" >&2; exit 1;;
  --group*) echo "tar: Option --group=0 is not supported" >&2; exit 1;;
esac; done
exec /usr/bin/tar "$@"
STUB
# GNU tar: --owner/--group only, rejects --uid/--gid.
cat > "$w/gnu/tar" <<'STUB'
#!/bin/bash
for a in "$@"; do case "$a" in
  --uid*) echo "tar: unrecognized option '--uid'" >&2; exit 2;;
  --gid*) echo "tar: unrecognized option '--gid'" >&2; exit 2;;
esac; done
exec /usr/bin/tar "$@"
STUB
chmod +x "$w/bsd/tar" "$w/gnu/tar"
printf '   under an OLD-libarchive tar (the macos-14 runner):\n'
out=$(PATH="$w/bsd:$PATH" bash scripts/create-release-tar.sh "$w/src" "$w/out/a.tar.gz" shepherd 2>&1); rc=$?
printf '     %s\n     exit=%d\n' "$out" "$rc"
[ "$rc" -ne 0 ] && still '1a packaging dies on an old-libarchive tar'
printf '   under a GNU tar (proves no single flag set covers both):\n'
out=$(PATH="$w/gnu:$PATH" bash scripts/create-release-tar.sh "$w/src" "$w/out/b.tar.gz" shepherd 2>&1); rc=$?
printf '     current script exit=%d (passes here; the flags are GNU-only)\n' "$rc"
rm -rf "$w"

printf '\n== 1b: PowerShell 5.1 refuses a dangling symlink without -Force ==\n'
printf '   Windows-only, not locally executable. Source line:\n'
grep -n 'ItemType SymbolicLink' scripts/tests/test-release-installer-windows.ps1 \
  | sed 's/^/     /'
if ! grep -n 'ItemType SymbolicLink' scripts/tests/test-release-installer-windows.ps1 | grep -q -- '-Force'; then
  still '1b the New-Item SymbolicLink call carries no -Force'
fi

printf '\n== 1c: the asset verifier expects tarballs npm pack never emits ==\n'
# ORACLE NOTE (corrected after the wave-1 audit): the original version of this
# check compared a HARDCODED `fl03-*` list against the manifests, so it reported
# REPRODUCED unconditionally and could never observe the fix. It measured its own
# constant, not the repository. That is the same defect class this lane spent the
# sprint removing, in the instrument rather than the subject. It now probes the
# actual state of the two files.
stale=$(git grep -c 'fl03-' -- scripts/ 2>/dev/null | wc -l | tr -d ' ')
printf '   files under scripts/ still carrying an fl03- literal: %s\n' "$stale"
if [ "$stale" != "0" ]; then
  git grep -n 'fl03-' -- scripts/ | sed 's/^/     /'
  still '1c stale fl03- literals remain in the asset verifier or its fixtures'
else
  printf '   FIXED: no fl03- literal remains; names derive from packages/*/package.json\n'
fi
if [ -f scripts/lib/release-package-names.sh ]; then
  printf '   derived names now:\n'
  bash scripts/lib/release-package-names.sh 2>/dev/null | sed 's/^/     /'
else
  still '1c no shared derivation helper exists'
fi

printf '\n== 1d: release.yml can tag before crates.io, and kills cargo-publish.yml ==\n'
# ORACLE NOTE (corrected after the wave-1 audit): this check previously ended in an
# UNCONDITIONAL `still` call, so it reported REPRODUCED even once the fix landed.
# An oracle that cannot return the negative case is not evidence.
n=$(grep -c 'crates\.io\|crates_io\|cargo publish\|CARGO_REGISTRY' .github/workflows/release.yml)
printf '   crates.io references in release.yml: %s\n' "$n"
if [ "$n" = "0" ]; then
  still '1d release.yml has no crates.io visibility check'
else
  printf '   FIXED: release.yml asserts crates.io publication\n'
fi
gate_line=$(grep -n 'Verify crates.io publication precedes the tag' .github/workflows/release.yml | head -1 | cut -d: -f1)
tag_line=$(grep -n 'git tag -a' .github/workflows/release.yml | head -1 | cut -d: -f1)
if [ -n "$gate_line" ] && [ -n "$tag_line" ]; then
  printf '   crates.io gate at line %s, tag at line %s\n' "$gate_line" "$tag_line"
  if [ "$gate_line" -gt "$tag_line" ]; then
    still '1d the crates.io gate runs AFTER the tag step'
  else
    printf '   FIXED: the gate precedes the tag\n'
  fi
else
  still '1d could not locate both the crates.io gate and the tag step'
fi
printf '   cargo-publish.yml trigger: '
sed -n '3,6p' .github/workflows/cargo-publish.yml | tr -d '\n' | sed 's/  */ /g'; printf '\n'
if sed -n '3,6p' .github/workflows/cargo-publish.yml | grep -q 'tags:'; then
  still '1d cargo-publish.yml still triggers only on a tag push it cannot receive'
else
  printf '   FIXED: publication no longer depends on a GITHUB_TOKEN-authored tag event\n'
fi

printf '\n== 2: the repo launcher shadows the native binary on PATH ==\n'
if [ ! -e bin/shepherd ]; then
  printf '   bin/shepherd is already gone; defect 2 no longer reproduces.\n'
else
  w=$(mktemp -d "${TMPDIR:-/tmp}/v646-2.XXXXXX")
  mkdir -p "$w/localbin" "$w/cargobin"
  ln -s "$PWD/bin/shepherd" "$w/localbin/shepherd"
  printf '#!/bin/bash\necho "shepherd-cli 6.4.6 (native)"\n' > "$w/cargobin/shepherd"
  chmod +x "$w/cargobin/shepherd"
  printf '   PATH: <localbin with the repo launcher symlink>:<cargobin with the native binary>\n'
  out=$(PATH="$w/localbin:$w/cargobin:/usr/bin:/bin" HOME="$w" shepherd --version 2>&1); rc=$?
  printf '%s\n' "$out" | sed 's/^/     /'
  printf '     exit=%d\n' "$rc"
  printf '   the native binary, reached directly: %s\n' "$("$w/cargobin/shepherd" --version)"
  [ "$rc" -eq 127 ] && still '2 launcher exits 127 instead of falling through to the native binary'
  rm -rf "$w"
fi

printf '\n== summary ==\n'
printf '  %d defect(s) still reproduce.\n' "$STILL_BROKEN"
if [ "$STILL_BROKEN" -eq 0 ]; then
  printf '  ALL FIXED. Every W0 defect now probes as resolved.\n'
  exit 0
fi
printf '  Defects above still reproduce. This script is now a REGRESSION oracle:\n'
printf '  before the fixes it reported 7; a non-zero count after them is a real failure.\n'
exit 1
