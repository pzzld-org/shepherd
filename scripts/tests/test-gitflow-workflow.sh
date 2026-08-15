#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

workflow='.github/workflows/gitflow.yml'
test -f "$workflow"
ruby -e 'require "yaml"; YAML.load_file(ARGV.fetch(0)); puts "ok: gitflow workflow parses"' "$workflow"
rg -Fq 'name: gitflow' "$workflow"
rg -Fq 'workflow_run:' "$workflow"
rg -Fq 'workflows: ["release"]' "$workflow"
rg -Fq 'types: [completed]' "$workflow"
rg -Fq 'workflow_dispatch:' "$workflow"
rg -Fq 'release_run_id:' "$workflow"
rg -Fq 'workflow_run.conclusion == '\''success'\''' "$workflow"
rg -Fq 'EVENT_NAME: ${{ github.event_name }}' "$workflow"
rg -Fq 'skip_automatic_or_fail' "$workflow"
rg -Fq 'release run ${RELEASE_RUN_ID} did not build the default branch' "$workflow"
rg -Fq 'proceed=false' "$workflow"
rg -Fq 'automatic gitflow handoff is a no-op' "$workflow"
rg -Fq 'RELEASE_RUN_ID' "$workflow"
rg -Fq 'gh run view "$RELEASE_RUN_ID"' "$workflow"
rg -Fq 'headSha' "$workflow"
rg -Fq 'headBranch' "$workflow"
rg -Fq 'workflowName' "$workflow"
rg -Fq 'release_sha' "$workflow"
rg -Fq 'git show "${RELEASE_SHA}:.claude-plugin/plugin.json"' "$workflow"
rg -Fq 'git ls-remote --tags origin "refs/tags/${TAG}^{}"' "$workflow"
rg -Fq 'gh release view "$TAG" --json isDraft,isPrerelease,tagName' "$workflow"
rg -Fq 'isDraft' "$workflow"
rg -Fq 'isPrerelease' "$workflow"
rg -Fq 'git checkout -b "$PATCH" "$RELEASE_SHA"' "$workflow"
rg -Fq 'git merge-base --is-ancestor "$RELEASE_SHA" "origin/$PATCH"' "$workflow"
rg -Fq 'python3 scripts/version-bump.py check --root . --version "$NEXT"' "$workflow"
rg -Fq 'python3 scripts/version-bump.py bump' "$workflow"
rg -Fq 'tail -n +2 "$bump_output" > "$changed_paths"' "$workflow"
rg -Fq 'git add -- "${version_paths[@]}"' "$workflow"
rg -Fq 'git commit -m "chore(${PATCH}/version): bump plugin ${CURRENT} → ${NEXT}"' "$workflow"
rg -Fq 'git push -u origin "$PATCH"' "$workflow"
rg -Fq 'gh pr create' "$workflow"
rg -Fq 'gh issue edit "$N" --milestone "$NEW"' "$workflow"
rg -Fq 'contents: write' "$workflow"
rg -Fq 'pull-requests: write' "$workflow"
rg -Fq 'issues: write' "$workflow"
python3 - "$workflow" <<'PY'
from pathlib import Path
import sys

workflow = Path(sys.argv[1]).read_text(encoding="utf-8")
helper = workflow.index("skip_automatic_or_fail()")
branch_guard = workflow.index("did not build the default branch")
tag_guard = workflow.index("remote_peeled=")
if helper > branch_guard or helper > tag_guard:
    raise SystemExit("automatic no-op helper must be defined before branch and tag custody guards")
if 'if [[ "$EVENT_NAME" == workflow_run ]]; then' not in workflow:
    raise SystemExit("automatic workflow_run no-op boundary is missing")
if 'skip_automatic_or_fail "published release ${TAG} is unavailable"' not in workflow:
    raise SystemExit("missing-release recovery must fail when manually dispatched")
if 'skip_automatic_or_fail "published release ${TAG} is still a draft"' not in workflow:
    raise SystemExit("draft-release recovery must fail when manually dispatched")
print("ok: automatic no-op boundary precedes branch and tag custody checks")
PY
if rg -n 'gh release (create|edit|upload)|git push origin "\$TAG"' "$workflow"; then
  printf 'gitflow workflow must not publish or mutate release tags\n' >&2
  exit 1
fi
python3 - "$workflow" <<'PY'
from pathlib import Path
import sys

workflow = Path(sys.argv[1]).read_text(encoding="utf-8")
required = [
    'RELEASE_SHA: ${{ steps.release.outputs.release_sha }}',
    'REMOTE_TIP=$(git ls-remote --heads origin "refs/heads/${BRANCH}"',
    'git merge-base --is-ancestor "$REMOTE_TIP" "$RELEASE_SHA"',
    'gh pr list --state merged --head "$BRANCH" --json headRefOid --jq \'.[].headRefOid\'',
    'grep -Fxq "$REMOTE_TIP" <<<"$merged_pr_heads"',
    '--force-with-lease="refs/heads/${BRANCH}:${REMOTE_TIP}"',
    'done < <(gh issue list --milestone "$OLD" --state open',
]
for marker in required:
    if marker not in workflow:
        raise SystemExit(f"missing gitflow recovery safety marker: {marker}")
if 'git push origin --delete "$BRANCH"' in workflow:
    raise SystemExit("orphan sweep deletes branches without a tip lease")
if '|| echo "::warning::Failed to move #$N"' in workflow:
    raise SystemExit("milestone issue edit failures are swallowed")
if 'milestones?state=open" --jq \'.[].title\' || echo ""' in workflow:
    raise SystemExit("open-milestone lookup turns GitHub API failures into an empty result")
if 'milestones?state=all" --jq \'.[].title\' || echo ""' in workflow:
    raise SystemExit("all-milestone lookup turns GitHub API failures into an empty result")
print("ok: orphan cleanup proves branch custody and milestone moves fail closed")
PY
printf 'ok: gitflow workflow owns post-publication branch, bump, PR, and housekeeping choreography\n'
