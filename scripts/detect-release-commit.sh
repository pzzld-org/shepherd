#!/usr/bin/env bash
# Single source of truth for "is this commit a release commit, and for which
# version". release.yml, cargo-publish.yml, and gitflow.yml all gate on this
# same predicate; there must be exactly one place that owns it.
#
# Every push to the default branch lands in exactly one of three outcomes,
# and the three must never collapse into each other:
#
#   skip    - legitimate no-op. Either the ref is not the default branch, or
#             the subject is an ordinary commit that does not match the
#             release pattern. Exit 0. Prints `verdict=skip` and a `reason=`.
#
#   proceed - the subject names a release version AND that version matches
#             .claude-plugin/plugin.json. Exit 0. Prints `verdict=proceed`
#             and `version=X.Y.Z`.
#
#   fail    - the subject names a release version but plugin.json disagrees:
#             a release commit that would produce nothing. Exit 1. The
#             message names BOTH versions (subject's and plugin.json's) on
#             stderr. This is the one outcome that must never be silently
#             treated as a skip -- collapsing it into `skip` is the defect
#             this script exists to remove.
#
# Every input arrives as a flag; nothing is read from GitHub-only context,
# so the whole truth table is provable with a local invocation:
#
#   scripts/detect-release-commit.sh \
#     --subject "$(git log -1 --format=%s HEAD)" \
#     --ref "$GITHUB_REF" \
#     --default-branch main \
#     --plugin-json .claude-plugin/plugin.json
set -euo pipefail

# gh squash-merges append " (#N)"; tolerated by the trailing [[:space:]:] or
# end-of-string alternative below.
RELEASE_SUBJECT_PATTERN='^(release:[[:space:]]+)?v([0-9]+\.[0-9]+\.[0-9]+)([[:space:]:]|$)'

usage() {
  cat <<'EOF' >&2
usage: detect-release-commit.sh --subject SUBJECT --ref REF \
         --default-branch BRANCH --plugin-json PATH

  --subject        the commit subject under evaluation (e.g. `git log -1 --format=%s`)
  --ref             the full ref the commit was pushed on (e.g. refs/heads/main)
  --default-branch  the repository's default branch name (e.g. main, no refs/heads/ prefix)
  --plugin-json     path to a checked-out .claude-plugin/plugin.json to cross-check

On success (exit 0) prints one of:
  verdict=skip
  reason=<why this is a legitimate no-op>
or:
  verdict=proceed
  version=X.Y.Z

On a release-shaped subject whose version disagrees with plugin.json, prints
an error to stderr naming both versions and exits 1.
EOF
}

detect_release_commit() {
  local subject="$1" ref="$2" default_branch="$3" plugin_json="$4"
  local default_branch_ref subject_version plugin_version

  default_branch_ref="refs/heads/${default_branch}"
  if [ "$ref" != "$default_branch_ref" ]; then
    printf 'verdict=skip\n'
    printf 'reason=ref %s is not the default branch (%s)\n' "$ref" "$default_branch_ref"
    return 0
  fi

  if ! [[ "$subject" =~ $RELEASE_SUBJECT_PATTERN ]]; then
    printf 'verdict=skip\n'
    printf 'reason=subject does not match the release pattern: %s\n' "$subject"
    return 0
  fi
  subject_version="${BASH_REMATCH[2]}"

  if [ ! -f "$plugin_json" ]; then
    printf 'detect-release-commit: plugin manifest not found: %s\n' "$plugin_json" >&2
    return 2
  fi
  plugin_version=$(jq -r '.version' "$plugin_json")
  if [ -z "$plugin_version" ] || [ "$plugin_version" = null ]; then
    printf 'detect-release-commit: plugin manifest has no .version: %s\n' "$plugin_json" >&2
    return 2
  fi

  if [ "$subject_version" != "$plugin_version" ]; then
    printf '::error::release commit version mismatch: subject %s names v%s, %s reports v%s\n' \
      "$subject" "$subject_version" "$plugin_json" "$plugin_version" >&2
    return 1
  fi

  printf 'verdict=proceed\n'
  printf 'version=%s\n' "$subject_version"
  return 0
}

main() {
  local subject='' ref='' default_branch='' plugin_json=''

  while [ $# -gt 0 ]; do
    case "$1" in
      --subject)
        [ $# -ge 2 ] || { printf 'detect-release-commit: --subject requires a value\n' >&2; usage; exit 2; }
        subject="$2"
        shift 2
        ;;
      --ref)
        [ $# -ge 2 ] || { printf 'detect-release-commit: --ref requires a value\n' >&2; usage; exit 2; }
        ref="$2"
        shift 2
        ;;
      --default-branch)
        [ $# -ge 2 ] || { printf 'detect-release-commit: --default-branch requires a value\n' >&2; usage; exit 2; }
        default_branch="$2"
        shift 2
        ;;
      --plugin-json)
        [ $# -ge 2 ] || { printf 'detect-release-commit: --plugin-json requires a value\n' >&2; usage; exit 2; }
        plugin_json="$2"
        shift 2
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        printf 'detect-release-commit: unknown argument: %s\n' "$1" >&2
        usage
        exit 2
        ;;
    esac
  done

  if [ -z "$ref" ] || [ -z "$default_branch" ] || [ -z "$plugin_json" ]; then
    printf 'detect-release-commit: --ref, --default-branch, and --plugin-json are all required\n' >&2
    usage
    exit 2
  fi
  # An empty subject is a legitimate "does not match" case, not a usage
  # error, so it is not checked here: it falls through to the skip branch.

  detect_release_commit "$subject" "$ref" "$default_branch" "$plugin_json"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
