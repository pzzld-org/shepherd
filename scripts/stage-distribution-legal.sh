#!/usr/bin/env bash
# Generate an artifact-scoped legal inventory into a staging tree. Lockfiles,
# dependency sources, and the generator are authoritative; emitted files are
# distribution payloads, never independently authored repository source.
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
stage_root=${1:?usage: stage-distribution-legal.sh <stage-root> [--scope native|component|claude] [--target triple]}
shift
scope=auto
target=wasm32-wasip2
while [[ $# -gt 0 ]]; do
  case "$1" in
    --scope) scope=${2:?--scope needs a value}; shift 2 ;;
    --target) target=${2:?--target needs a value}; shift 2 ;;
    *) printf 'unknown legal staging argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done
[[ -d "$stage_root" && ! -L "$stage_root" ]] || {
  printf 'legal staging root must be a real directory: %s\n' "$stage_root" >&2
  exit 1
}
stage_root=$(cd "$stage_root" && pwd -P)
if [[ "$scope" == auto ]]; then
  if [[ -d "$stage_root/.claude-plugin" ]]; then
    scope=claude
  else
    scope=component
  fi
fi
case "$scope" in
  native|component|claude) ;;
  *) printf 'unknown legal staging scope: %s\n' "$scope" >&2; exit 2 ;;
esac

render_legal() {
  local output_root=$1 output_scope=$2
  python3 "$repo_root/scripts/generate-third-party-notices.py" \
    --scope "$output_scope" --target "$target" \
    --output "$output_root/THIRD_PARTY_NOTICES.md" \
    --licenses-dir "$output_root/THIRD_PARTY_LICENSES"
  python3 "$repo_root/scripts/generate-third-party-notices.py" \
    --scope "$output_scope" --target "$target" --check \
    --output "$output_root/THIRD_PARTY_NOTICES.md" \
    --licenses-dir "$output_root/THIRD_PARTY_LICENSES"
}

# The LICENSE copied below is a byte-for-byte payload: scripts/verify-release-
# distribution.sh compares every extracted archive against the repository copy.
# A checkout that rewrites line endings (GitHub's Windows runners default to
# core.autocrlf=true) silently makes the Windows zip diverge from the four
# tarballs. .gitattributes pins `* text=auto eol=lf`; fail here, on the runner
# that would have produced the divergence, instead of after every asset job and
# the crates.io publication have already succeeded.
if LC_ALL=C grep -q $'\r' "$repo_root/LICENSE"; then
  printf 'LICENSE carries CR bytes: this checkout rewrote line endings, so the staged archive would not match the repository copy. Verify .gitattributes pins `* text=auto eol=lf` and re-checkout.\n' >&2
  exit 1
fi

cp "$repo_root/LICENSE" "$stage_root/LICENSE"
render_legal "$stage_root" "$scope"

if [[ -d "$stage_root/packages" ]]; then
  while IFS= read -r -d '' package; do
    case "$(basename "$package")" in
      component-runtime) package_scope=npm-component-runtime ;;
      harness-claude) package_scope=npm-harness-claude ;;
      harness-codex) package_scope=npm-harness-codex ;;
      harness-pi) package_scope=npm-harness-pi ;;
      *) printf 'unknown staged npm package: %s\n' "$package" >&2; exit 1 ;;
    esac
    cp "$repo_root/LICENSE" "$package/LICENSE"
    render_legal "$package" "$package_scope"
  done < <(find "$stage_root/packages" -mindepth 1 -maxdepth 1 -type d -print0 | LC_ALL=C sort -z)
fi
