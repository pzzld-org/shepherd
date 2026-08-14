#!/usr/bin/env bash
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

project_id=$(shctx_project_id)
now=$(shctx_now)
root="$(shctx_artifacts_root)"

classify() {
  local f="$1"
  # Primary patterns: dot-separated kind suffix (e.g. foo.seed.md).
  # Fallback patterns: hyphen-prefixed kind suffix (e.g. 2026-05-04-foo-seed.md).
  case "$f" in
    *.seed.md|*-seed.md)         echo seed ;;
    *.plan.md|*-plan.md)         echo plan ;;
    *.phase0.md|*-phase0.md)     echo phase0 ;;
    *.close.md|*-close.md)       echo close ;;
    *.walk.md|*-walk.md)         echo walk ;;
    *.handoff.md|*-handoff.md)   echo handoff ;;
    *.spec.md|*-spec.md)         echo spec ;;
    *.design.md|*-design.md)     echo design ;;
    *.addendum.md|*-addendum.md) echo addendum ;;
    */docs/diagrams/*)           echo diagram ;;
    */docs/journal/*)            echo journal ;;
    *) echo "" ;;
  esac
}

# v5.0.3: detect whether the schema has the artifacts.content column (added by
# 0004_fts_search.sql). If yes, also persist file content for FTS search; if
# no (DB still on schema 1–3), the existing UPSERT stays compatible.
has_content_col=0
if shctx_sql "PRAGMA table_info(artifacts);" | grep -q '|content|'; then
  has_content_col=1
fi

# NOTE: BEGIN/COMMIT omitted — shctx_sql spawns a fresh sqlite3 process per
# call, so a wrapping transaction cannot persist. Each INSERT auto-commits.
while IFS= read -r -d '' f; do
  rel=${f#$(shctx_repo_root)/}
  kind=$(classify "$f")
  [[ -n "$kind" ]] || continue
  hash=$(shasum -a 256 "$f" | awk '{print $1}')
  # Found this wave: the previous title line built its sed script as
  # `'s/^#+ //;s/'\''/''/g'` — a bash single-quote/escape puzzle that does
  # NOT evaluate to `s/'/''/g` as intended. It collapses to `s/'//g`
  # (DELETE every apostrophe, not double it) once bash finishes quote
  # removal, so a title like "Joe's Plan" silently became "Joes Plan" in the
  # DB — a round-trip violation, and the same class of bug as #296 even
  # though it isn't the `${var//\'/\'\'}` byte pattern. esc() replaces it.
  title=$(esc "$(head -1 "$f" | sed -E 's/^#+ //' | head -c 200)")
  # $rel is a repo-relative file path — plausible to contain an apostrophe
  # (e.g. "Joe's notes.md"), the same class of gap as #291's dirname finding.
  rel_esc="$(esc "$rel")"
  uid=$(shctx_uuid7)
  if (( has_content_col )); then
    # Read full content (capped at 256KB to keep DB lean). esc() takes its
    # argument positionally (not stdin), so capture first, then escape.
    raw_content=$(LC_ALL=C head -c 262144 "$f" 2>/dev/null || true)
    content=$(esc "$raw_content")
    shctx_sql "INSERT INTO artifacts
      (id, project_id, kind, path, sprint_branch, title, hash, content, created_at, updated_at)
      VALUES ('$uid','$(esc "$project_id")','$kind','$rel_esc',NULL,'$title','$hash','$content',$now,$now)
      ON CONFLICT(project_id, path) DO UPDATE SET
        kind=excluded.kind, title=excluded.title, hash=excluded.hash,
        content=excluded.content, updated_at=excluded.updated_at;"
  else
    shctx_sql "INSERT INTO artifacts
      (id, project_id, kind, path, sprint_branch, title, hash, created_at, updated_at)
      VALUES ('$uid','$(esc "$project_id")','$kind','$rel_esc',NULL,'$title','$hash',$now,$now)
      ON CONFLICT(project_id, path) DO UPDATE SET
        kind=excluded.kind, title=excluded.title, hash=excluded.hash, updated_at=excluded.updated_at;"
  fi
done < <(find "$root" -type f -name '*.md' -print0)
echo "shctx refresh artifacts: ok"
