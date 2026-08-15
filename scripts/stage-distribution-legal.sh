#!/usr/bin/env bash
# Copy the one canonical legal inventory into a staging tree. The copies are
# distribution payloads, not independently authored sources.
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
