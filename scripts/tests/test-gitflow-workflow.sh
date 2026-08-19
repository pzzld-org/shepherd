#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

workflow='.github/workflows/gitflow.yml'
test -f "$workflow"
ruby -e 'require "yaml"; YAML.load_file(ARGV.fetch(0)); puts "ok: gitflow workflow parses"' "$workflow"
rg -Fq 'name: gitflow' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must declare '\''name: gitflow'\'' (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'workflow_run:' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must trigger on workflow_run events (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'workflows: ["release"]' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must scope the workflow_run trigger to the release workflow (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'types: [completed]' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must trigger only on completed workflow_run events (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'workflow_dispatch:' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must support manual workflow_dispatch invocation (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'release_run_id:' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow manual dispatch must accept a release_run_id input (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'workflow_run.conclusion == '\''success'\''' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must gate on the release runs conclusion being success (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'EVENT_NAME: ${{ github.event_name }}' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must expose the triggering event name to its steps (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'skip_automatic_or_fail' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must define the skip_automatic_or_fail no-op helper (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'release run ${RELEASE_RUN_ID} did not build the default branch' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must reject a release run that did not build the default branch (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'proceed=false' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must be able to signal a no-op via proceed=false (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'automatic gitflow handoff is a no-op' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must explain that an automatic run was skipped as a no-op (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'RELEASE_RUN_ID' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must carry the release run id through its steps (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'gh run view "$RELEASE_RUN_ID"' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must look up the release run via gh run view (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'headSha' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must read the release runs head sha (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'headBranch' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must read the release runs head branch (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'workflowName' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must read the release runs workflow name (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'release_sha' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must publish the release sha as a step output (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'git show "${RELEASE_SHA}:.claude-plugin/plugin.json"' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must read plugin.json from the release commit, not the checkout (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'git ls-remote --tags origin "refs/tags/${TAG}^{}"' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must verify the release tag exists on the remote before acting (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'gh release view "$TAG" --json isDraft,isPrerelease,tagName' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must inspect the published releases draft and prerelease state (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'isDraft' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must refuse to act on a draft release (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'isPrerelease' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must refuse to act on a prerelease (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'git checkout -b "$PATCH" "$RELEASE_SHA"' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must branch the patch line from the release sha (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'git merge-base --is-ancestor "$RELEASE_SHA" "origin/$PATCH"' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must verify the release sha is an ancestor of the existing patch branch before reusing it (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'python3 scripts/version-bump.py check --root . --version "$NEXT"' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must check the next version before bumping it (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'python3 scripts/version-bump.py bump' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must invoke the version-bump script to bump the version (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'tail -n +2 "$bump_output" > "$changed_paths"' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must capture the paths changed by the version bump (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'git add -- "${version_paths[@]}"' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must stage exactly the version-bumped paths (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'git commit -m "chore(${PATCH}/version): bump plugin ${CURRENT} → ${NEXT}"' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must commit the version bump with a conventional commit message (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'git push -u origin "$PATCH"' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must push the patch branch upstream (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'gh pr create' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must open a pull request for the patch branch (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'gh issue edit "$N" --milestone "$NEW"' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must move issues onto the new milestone (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'contents: write' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must request contents write permission (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'pull-requests: write' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must request pull-requests write permission (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -Fq 'issues: write' "$workflow" || { rc=$?; printf 'FAIL: gitflow workflow must request issues write permission (rg rc=%s)\n' "$rc" >&2; exit 1; }
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
