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
expected=$(grep -o 'fl03-\${package}-\${version}.tgz' scripts/verify-release-distribution.sh | head -1)
printf '   hardcoded pattern in verify-release-distribution.sh: %s\n' "${expected:-<none>}"
printf '   hardcoded name list:  '
sed -n 's/^for package in \(.*\); do$/\1/p' scripts/verify-release-distribution.sh | head -1
printf '   real npm pack names (derived from packages/*/package.json):\n'
for f in packages/*/package.json; do
  python3 -c "import json;d=json.load(open('$f'));print('     '+d['name'].lstrip('@').replace('/','-')+'-'+d['version']+'.tgz')"
done
overlap=$(comm -12 \
  <(for p in component-runtime harness-claude harness-codex harness-pi; do echo "fl03-${p}-6.4.6.tgz"; done | sort) \
  <(for f in packages/*/package.json; do python3 -c "import json;d=json.load(open('$f'));print(d['name'].lstrip('@').replace('/','-')+'-'+d['version']+'.tgz')"; done | sort) | wc -l | tr -d ' ')
printf '   names in common: %s of 4\n' "$overlap"
[ "$overlap" = "0" ] && still '1c zero of four expected npm assets can ever exist'
if grep -q 'fl03-' scripts/tests/test-release-distribution-license.sh; then
  still '1c the license gate synthesizes fixtures under the SAME stale names, so it cannot catch this'
fi

printf '\n== 1d: release.yml can tag before crates.io, and kills cargo-publish.yml ==\n'
n=$(grep -c 'crates\.io\|crates_io\|cargo publish\|CARGO_REGISTRY' .github/workflows/release.yml)
printf '   crates.io references in release.yml: %s\n' "$n"
[ "$n" = "0" ] && still '1d release.yml has no crates.io visibility check'
printf '   tag push credential: '
grep -n 'token: ${{ secrets.GITHUB_TOKEN }}' .github/workflows/release.yml | head -1
printf '   cargo-publish.yml trigger: '
sed -n '4,5p' .github/workflows/cargo-publish.yml | tr -d '\n' | sed 's/  */ /g'; printf '\n'
printf '   GitHub does not fire workflows from GITHUB_TOKEN-authored events.\n'
still '1d the tag push cannot trigger cargo-publish.yml'

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
[ "$STILL_BROKEN" -ge 5 ] && exit 0
printf '  Expected 5 or more. Evidence is stale or a fix has landed; re-read before trusting.\n'
exit 1
