#!/usr/bin/env bash
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

root="$(shctx_artifacts_root)"
fail=0

# plans/ — legacy top-level AND new docs/plans/ (both accepted; back-compat).
for plans_dir in "$root/plans" "$root/docs/plans"; do
  while IFS= read -r -d '' f; do
    b="$(basename "$f")"
    [[ "$b" == ".gitkeep" ]] && continue
    case "$b" in
      *.seed.md|*.plan.md) ;;
      *) echo "lint: $f does not match *.seed.md or *.plan.md"; fail=1 ;;
    esac
  done < <(find "$plans_dir" -type f -name '*.md' -print0 2>/dev/null)
done

# reports/ — legacy top-level AND new docs/reports/ (both accepted; back-compat).
for reports_dir in "$root/reports" "$root/docs/reports"; do
  while IFS= read -r -d '' f; do
    b="$(basename "$f")"
    [[ "$b" == ".gitkeep" ]] && continue
    case "$b" in
      *.phase0.md|*.close.md|*.walk.md) ;;
      # Date-prefixed reports — the documented form for discovery / intro-audit /
      # planter-mesh reports (intro-combo-wave writes reports/<date>-discovery-*.md)
      # and any <date>-<sprint>-<group>.md report. See naming-conventions.md.
      [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]-*.md) ;;
      *) echo "lint: $f does not match *.{phase0,close,walk}.md or YYYY-MM-DD-*.md"; fail=1 ;;
    esac
  done < <(find "$reports_dir" -type f -name '*.md' -print0 2>/dev/null)
done

# docs/journal/ — YYYY-MM-DD.md.
while IFS= read -r -d '' f; do
  b="$(basename "$f")"
  [[ "$b" == ".gitkeep" ]] && continue
  case "$b" in
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].md) ;;
    *) echo "lint: $f does not match YYYY-MM-DD.md"; fail=1 ;;
  esac
done < <(find "$root/docs/journal" -type f -name '*.md' -print0 2>/dev/null)

# logs/ — accepted patterns (back-compat + new *.{group}.md convention):
#   events-YYYY-MM-DD.jsonl  (legacy event stream)
#   YYYY-MM-DD.log.jsonl     (new machine event stream)
#   YYYY-MM-DD.log.md        (new human-readable daily log)
#   YYYY-MM-DDTHH-MM-SS.log.jsonl  (machine, timestamped)
#   hooks/YYYY-MM-DD.log.jsonl etc (sub-dirs not linted at this depth)
while IFS= read -r -d '' f; do
  b="$(basename "$f")"
  [[ "$b" == ".gitkeep" ]] && continue
  case "$b" in
    events-[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].jsonl) ;;
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].log.jsonl) ;;
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].log.md) ;;
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]-[0-9][0-9]-[0-9][0-9].log.jsonl) ;;
    *) echo "lint: $f has unrecognized log filename pattern"; fail=1 ;;
  esac
done < <(find "$root/logs" -maxdepth 1 -type f -print0 2>/dev/null)

if (( fail == 0 )); then
  echo "lint: ok"
else
  echo "lint: FAIL ($fail violation(s))"
  exit 1
fi
