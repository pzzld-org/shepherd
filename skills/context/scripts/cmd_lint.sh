#!/usr/bin/env bash
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

root="$(shctx_artifacts_root)"
fail=0

# Files in plans/ must end in *.seed.md or *.plan.md.
while IFS= read -r -d '' f; do
  case "$(basename "$f")" in
    *.seed.md|*.plan.md) ;;
    *) echo "lint: $f does not match *.seed.md or *.plan.md"; fail=1 ;;
  esac
done < <(find "$root/plans" -type f -name '*.md' -print0 2>/dev/null)

# Files in reports/ must end in *.phase0.md, *.close.md, or *.walk.md.
while IFS= read -r -d '' f; do
  case "$(basename "$f")" in
    *.phase0.md|*.close.md|*.walk.md) ;;
    *) echo "lint: $f does not match *.phase0.md|*.close.md|*.walk.md"; fail=1 ;;
  esac
done < <(find "$root/reports" -type f -name '*.md' -print0 2>/dev/null)

# Files in docs/journal/ must match YYYY-MM-DD.md.
while IFS= read -r -d '' f; do
  case "$(basename "$f")" in
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].md) ;;
    *) echo "lint: $f does not match YYYY-MM-DD.md"; fail=1 ;;
  esac
done < <(find "$root/docs/journal" -type f -name '*.md' -print0 2>/dev/null)

if (( fail == 0 )); then
  echo "lint: ok"
else
  echo "lint: FAIL ($fail violation(s))"
  exit 1
fi
