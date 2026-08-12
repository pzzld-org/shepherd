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
  id="github:$repo#$num"
  title=$(jq -r .title <<<"$row" | sed "s/'/''/g")
  state=$(jq -r '.state | ascii_downcase' <<<"$row")
  labels=$(jq -c '[.labels[].name]' <<<"$row")
  milestone=$(jq -r '.milestone.title // empty' <<<"$row")
  assignees=$(jq -c '[.assignees[].login]' <<<"$row")
  body=$(jq -r .body <<<"$row" | sed "s/'/''/g")
  url=$(jq -r .url <<<"$row")
  ca=$(epoch_iso "$(jq -r .createdAt <<<"$row")")
  ua=$(epoch_iso "$(jq -r .updatedAt <<<"$row")")
  shctx_sql "INSERT INTO index_issues
    (id, project_id, source, number, title, state, labels, milestone, assignees, body, url, created_at, updated_at, refreshed_at)
    VALUES ('$id','$project_id','github',$num,'$title','$state','$labels','${milestone:-NULL}','$assignees','$body','$url',$ca,$ua,$now)
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
  id="github:$repo#pr$num"
  title=$(jq -r .title <<<"$row" | sed "s/'/''/g")
  state=$(jq -r '.state | ascii_downcase' <<<"$row")
  base=$(jq -r .baseRefName <<<"$row")
  head=$(jq -r .headRefName <<<"$row")
  labels=$(jq -c '[.labels[].name]' <<<"$row")
  url=$(jq -r .url <<<"$row")
  ca=$(epoch_iso "$(jq -r .createdAt <<<"$row")")
  ua=$(epoch_iso "$(jq -r .updatedAt <<<"$row")")
  ma=$(jq -r '.mergedAt // empty' <<<"$row")
  ma_e=$([[ -n "$ma" ]] && epoch_iso "$ma" || echo NULL)
  shctx_sql "INSERT INTO index_prs
    (id, project_id, source, number, title, state, base_branch, head_branch, labels, url, created_at, updated_at, merged_at, refreshed_at)
    VALUES ('$id','$project_id','github',$num,'$title','$state','$base','$head','$labels','$url',$ca,$ua,$ma_e,$now)
    ON CONFLICT(id) DO UPDATE SET
      title=excluded.title, state=excluded.state, labels=excluded.labels,
      url=excluded.url, updated_at=excluded.updated_at, merged_at=excluded.merged_at, refreshed_at=excluded.refreshed_at;"
done

# Releases
shctx_gh_retry release list --limit 200 --json tagName,name,isDraft,isPrerelease,publishedAt \
  | jq -c '.[]' | while read -r row; do
  tag=$(jq -r .tagName <<<"$row")
  id="github:$repo:tag:$tag"
  name=$(jq -r '.name // empty' <<<"$row" | sed "s/'/''/g")
  draft=$(jq -r 'if .isDraft then 1 else 0 end' <<<"$row")
  pre=$(jq -r 'if .isPrerelease then 1 else 0 end' <<<"$row")
  # gh CLI does not expose `url` on releases; construct it.
  url="https://github.com/$repo/releases/tag/$tag"
  pa=$(jq -r '.publishedAt // empty' <<<"$row")
  pa_e=$([[ -n "$pa" ]] && epoch_iso "$pa" || echo NULL)
  shctx_sql "INSERT INTO index_releases
    (id, project_id, source, tag, name, prerelease, draft, body, url, published_at, refreshed_at)
    VALUES ('$id','$project_id','github','$tag','$name',$pre,$draft,NULL,'$url',$pa_e,$now)
    ON CONFLICT(project_id,source,tag) DO UPDATE SET
      name=excluded.name, prerelease=excluded.prerelease, draft=excluded.draft,
      url=excluded.url, published_at=excluded.published_at, refreshed_at=excluded.refreshed_at;"
done

# Milestones (REST API)
shctx_gh_retry api "repos/$repo/milestones?state=all&per_page=100" 2>/dev/null \
  | jq -c '.[]?' | while read -r row; do
  num=$(jq -r .number <<<"$row")
  id="github:$repo:ms:$num"
  title=$(jq -r .title <<<"$row" | sed "s/'/''/g")
  state=$(jq -r .state <<<"$row")
  due=$(jq -r '.due_on // empty' <<<"$row")
  due_e=$([[ -n "$due" ]] && epoch_iso "$due" || echo NULL)
  desc=$(jq -r '.description // empty' <<<"$row" | sed "s/'/''/g")
  url=$(jq -r .html_url <<<"$row")
  shctx_sql "INSERT INTO index_milestones
    (id, project_id, source, number, title, state, due_on, description, url, refreshed_at)
    VALUES ('$id','$project_id','github',$num,'$title','$state',$due_e,'$desc','$url',$now)
    ON CONFLICT(project_id,source,number) DO UPDATE SET
      title=excluded.title, state=excluded.state, due_on=excluded.due_on,
      description=excluded.description, url=excluded.url, refreshed_at=excluded.refreshed_at;"
done

echo "shctx refresh github: ok"
