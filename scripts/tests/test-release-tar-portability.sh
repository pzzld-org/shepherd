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
mkdir -p "$tmp_dir/bin"
cat > "$tmp_dir/bin/tar" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
options_terminated=0
for argument in "$@"; do
  case "$argument" in
    --)
      options_terminated=1
      ;;
    --uid|--gid|--uname|--gname)
      printf 'portable tar regression: rejected BSD-only option %s\n' "$argument" >&2
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
chmod 755 "$tmp_dir/bin/tar"

entries=(
  LICENSE
  THIRD_PARTY_NOTICES.md
  THIRD_PARTY_LICENSES/dependency.txt
  payload
  --exclude=payload
)
for archive in "$tmp_dir/first.tar.gz" "$tmp_dir/second.tar.gz"; do
  PATH="$tmp_dir/bin:$PATH" REAL_TAR="$real_tar" \
    "$creator" "$source_dir" "$archive" "${entries[@]}"
done

cmp -s "$tmp_dir/first.tar.gz" "$tmp_dir/second.tar.gz" || \
  fail 'release tar must be byte-reproducible from identical staged inputs'

actual=$(tar -tzf "$tmp_dir/first.tar.gz")
expected=$'LICENSE\nTHIRD_PARTY_NOTICES.md\nTHIRD_PARTY_LICENSES/dependency.txt\npayload\n--exclude=payload'
[[ "$actual" == "$expected" ]] || fail 'release tar contains an unexpected entry set or order'

python3 - "$tmp_dir/first.tar.gz" <<'PY'
from pathlib import Path
import sys
import tarfile

archive = Path(sys.argv[1])
with tarfile.open(archive, "r:gz") as handle:
    members = handle.getmembers()

if not members:
    raise SystemExit("release tar is empty")
for member in members:
    if (member.uid, member.gid) != (0, 0):
        raise SystemExit(f"non-canonical owner for {member.name}: {member.uid}:{member.gid}")
    if member.mtime != 315532800:
        raise SystemExit(f"non-canonical mtime for {member.name}: {member.mtime}")
print("ok: release tar entries use canonical ownership and timestamps")
PY

printf 'ok: release tar creation is portable, exact, and reproducible\n'
