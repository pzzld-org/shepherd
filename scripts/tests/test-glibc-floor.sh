#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

helper='scripts/assert-glibc-floor.py'
tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/shepherd-glibc-floor.XXXXXX")
trap 'find "$tmp_dir" -depth -delete' EXIT

cat > "$tmp_dir/at-floor.txt" <<'EOF'
Version needs section:
  0x0010:   Name: GLIBC_2.17  Flags: none  Version: 4
EOF
cat > "$tmp_dir/above-floor.txt" <<'EOF'
Version needs section:
  0x0010:   Name: GLIBC_2.18  Flags: none  Version: 4
EOF
cat > "$tmp_dir/no-glibc.txt" <<'EOF'
Version needs section:
  0x0010:   Name: GLIBCXX_3.4  Flags: none  Version: 2
EOF

python3 "$helper" 2.17 < "$tmp_dir/at-floor.txt"
if python3 "$helper" 2.17 < "$tmp_dir/above-floor.txt" >"$tmp_dir/above.out" 2>&1; then
  printf 'glibc helper accepted a symbol above the compatibility floor\n' >&2
  exit 1
fi
grep -Fq 'requires GLIBC_2.18, exceeds supported GLIBC_2.17' "$tmp_dir/above.out"
if python3 "$helper" 2.17 < "$tmp_dir/no-glibc.txt" >"$tmp_dir/missing.out" 2>&1; then
  printf 'glibc helper accepted input with no GLIBC symbols\n' >&2
  exit 1
fi
grep -Fq 'no GLIBC symbol versions found' "$tmp_dir/missing.out"
printf 'ok: glibc floor helper accepts 2.17, rejects newer and missing symbols\n'
