#!/usr/bin/env bash
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/_lib.sh"

command -v gh >/dev/null || { echo "shctx: gh CLI not installed; skipping github refresh"; exit 0; }
command -v jq >/dev/null || { echo "shctx: jq required"; exit 1; }

project_id=$(shctx_project_id)
now=$(shctx_now)
repo=$(shctx_gh_retry repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || echo "unknown/unknown")

epoch_iso() { date -j -f "%Y-%m-%dT%H:%M:%SZ" "$1" +%s 2>/dev/null || date -d "$1" +%s 2>/dev/null || echo 0; }

# NOTE: shctx_sql opens a fresh connection per invocation, so a single
# BEGIN/COMMIT pair across calls is a no-op (and the trailing COMMIT errors
# with "no transaction is active"). Each shctx_sql call below is its own
# auto-committed transaction, which is acceptable for refresh idempotency.

# Issues
shctx_gh_retry issue list --state all --limit 500 \
  --json number,title,state,labels,milestone,assignees,body,url,createdAt,updatedAt \
  | jq -c '.[]' | while read -r row; do
  num=$(jq -r .number <<<"$row")
  id_esc="$(esc "github:$repo#$num")"
  title=$(esc "$(jq -r .title <<<"$row")")
  state=$(esc "$(jq -r '.state | ascii_downcase' <<<"$row")")
  # GH #292: labels/assignees/milestone were the fields left UNESCAPED next
  # to title/body, which WERE correctly escaped two lines away in the same
  # file — a GitHub label containing an apostrophe (e.g. "Won't Fix") broke
  # the INSERT and, under `set -eu -o pipefail` with no per-row error
  # handling, aborted the whole sync for every row after the bad one.
  labels=$(esc "$(jq -c '[.labels[].name]' <<<"$row")")
  # Preserve the pre-existing "empty milestone -> literal NULL text" shape
  # (a pre-existing, non-security quoting quirk out of this fix's scope) —
  # esc() only needs to guard the non-empty case.
  milestone=$(esc "$(jq -r '.milestone.title // empty' <<<"$row")")
  [[ -n "$milestone" ]] || milestone="NULL"
  assignees=$(esc "$(jq -c '[.assignees[].login]' <<<"$row")")
  body=$(esc "$(jq -r .body <<<"$row")")
  url=$(esc "$(jq -r .url <<<"$row")")
  ca=$(epoch_iso "$(jq -r .createdAt <<<"$row")")
  ua=$(epoch_iso "$(jq -r .updatedAt <<<"$row")")
  shctx_sql "INSERT INTO index_issues
    (id, project_id, source, number, title, state, labels, milestone, assignees, body, url, created_at, updated_at, refreshed_at)
    VALUES ('$id_esc','$(esc "$project_id")','github',$num,'$title','$state','$labels','$milestone','$assignees','$body','$url',$ca,$ua,$now)
    ON CONFLICT(id) DO UPDATE SET
      title=excluded.title, state=excluded.state, labels=excluded.labels,
      milestone=excluded.milestone, assignees=excluded.assignees, body=excluded.body,
      url=excluded.url, updated_at=excluded.updated_at, refreshed_at=excluded.refreshed_at;"
done

# PRs
shctx_gh_retry pr list --state all --limit 500 \
  --json number,title,state,baseRefName,headRefName,labels,url,createdAt,updatedAt,mergedAt \
  | jq -c '.[]' | while read -r row; do
  num=$(jq -r .number <<<"$row")
  id_esc="$(esc "github:$repo#pr$num")"
  title=$(esc "$(jq -r .title <<<"$row")")
  state=$(esc "$(jq -r '.state | ascii_downcase' <<<"$row")")
  # base/head are branch refs — a real git ref may legally contain an
  # apostrophe (`git check-ref-format`), so these need the same guard as
  # labels/assignees/milestone below (#292).
  base=$(esc "$(jq -r .baseRefName <<<"$row")")
  head=$(esc "$(jq -r .headRefName <<<"$row")")
  labels=$(esc "$(jq -c '[.labels[].name]' <<<"$row")")
  url=$(esc "$(jq -r .url <<<"$row")")
  ca=$(epoch_iso "$(jq -r .createdAt <<<"$row")")
  ua=$(epoch_iso "$(jq -r .updatedAt <<<"$row")")
  ma=$(jq -r '.mergedAt // empty' <<<"$row")
  ma_e=$([[ -n "$ma" ]] && epoch_iso "$ma" || echo NULL)
  shctx_sql "INSERT INTO index_prs
    (id, project_id, source, number, title, state, base_branch, head_branch, labels, url, created_at, updated_at, merged_at, refreshed_at)
    VALUES ('$id_esc','$(esc "$project_id")','github',$num,'$title','$state','$base','$head','$labels','$url',$ca,$ua,$ma_e,$now)
    ON CONFLICT(id) DO UPDATE SET
      title=excluded.title, state=excluded.state, labels=excluded.labels,
      url=excluded.url, updated_at=excluded.updated_at, merged_at=excluded.merged_at, refreshed_at=excluded.refreshed_at;"
done

# Releases
shctx_gh_retry release list --limit 200 --json tagName,name,isDraft,isPrerelease,publishedAt \
  | jq -c '.[]' | while read -r row; do
  tag=$(jq -r .tagName <<<"$row")
  tag_esc=$(esc "$tag")
  id_esc="$(esc "github:$repo:tag:$tag")"
  name=$(esc "$(jq -r '.name // empty' <<<"$row")")
  draft=$(jq -r 'if .isDraft then 1 else 0 end' <<<"$row")
  pre=$(jq -r 'if .isPrerelease then 1 else 0 end' <<<"$row")
  # gh CLI does not expose `url` on releases; construct it. A tag name is
  # attacker/upstream-influenced (any collaborator can push one), so escape
  # it before it lands in the same INSERT even though it is also embedded
  # in $url here (a tag containing a quote is unusual but not forbidden by
  # git's tag-name rules).
  url=$(esc "https://github.com/$repo/releases/tag/$tag")
  pa=$(jq -r '.publishedAt // empty' <<<"$row")
  pa_e=$([[ -n "$pa" ]] && epoch_iso "$pa" || echo NULL)
  shctx_sql "INSERT INTO index_releases
    (id, project_id, source, tag, name, prerelease, draft, body, url, published_at, refreshed_at)
    VALUES ('$id_esc','$(esc "$project_id")','github','$tag_esc','$name',$pre,$draft,NULL,'$url',$pa_e,$now)
    ON CONFLICT(project_id,source,tag) DO UPDATE SET
      name=excluded.name, prerelease=excluded.prerelease, draft=excluded.draft,
      url=excluded.url, published_at=excluded.published_at, refreshed_at=excluded.refreshed_at;"
done

# Milestones (REST API)
shctx_gh_retry api "repos/$repo/milestones?state=all&per_page=100" 2>/dev/null \
  | jq -c '.[]?' | while read -r row; do
  num=$(jq -r .number <<<"$row")
  id_esc="$(esc "github:$repo:ms:$num")"
  title=$(esc "$(jq -r .title <<<"$row")")
  state=$(esc "$(jq -r .state <<<"$row")")
  due=$(jq -r '.due_on // empty' <<<"$row")
  due_e=$([[ -n "$due" ]] && epoch_iso "$due" || echo NULL)
  desc=$(esc "$(jq -r '.description // empty' <<<"$row")")
  url=$(esc "$(jq -r .html_url <<<"$row")")
  shctx_sql "INSERT INTO index_milestones
    (id, project_id, source, number, title, state, due_on, description, url, refreshed_at)
    VALUES ('$id_esc','$(esc "$project_id")','github',$num,'$title','$state',$due_e,'$desc','$url',$now)
    ON CONFLICT(project_id,source,number) DO UPDATE SET
      title=excluded.title, state=excluded.state, due_on=excluded.due_on,
      description=excluded.description, url=excluded.url, refreshed_at=excluded.refreshed_at;"
done

echo "shctx refresh github: ok"
