#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
artifact="${SHEPHERD_COMPONENT_WASM:-target/wasm32-wasip2/release/shepherd_component.wasm}"
if [[ ! -s "$artifact" ]]; then
  printf 'component artifact is missing: %s\n' "$artifact" >&2
  exit 1
fi

node_root="${SHEPHERD_COMPONENT_NODE_ROOT:-$PWD}"
node_root=$(cd "$node_root" && pwd)
jco="$node_root/node_modules/.bin/jco"
if [[ ! -x "$jco" ]]; then
  printf 'locked jco is missing: %s\n' "$jco" >&2
  exit 1
fi

tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/shepherd-packed-plugin.XXXXXX")
trap 'find "$tmp_dir" -depth -delete' EXIT
stage="$tmp_dir/stage"
mkdir -p "$stage/packages"
for package in component-runtime harness-claude harness-codex harness-pi; do
  cp -R "packages/$package" "$stage/packages/$package"
done
SHEPHERD_COMPONENT_NODE_ROOT="$node_root" SHEPHERD_COMPONENT_WASM="$artifact" \
  scripts/stage-component-runtime.sh "$stage"
scripts/stage-distribution-legal.sh "$stage"
ln -s "$node_root/node_modules" "$stage/packages/component-runtime/node_modules"

tarballs="$tmp_dir/tarballs"
mkdir -p "$tarballs"
for package in component-runtime harness-claude harness-codex harness-pi; do
  (
    cd "$stage/packages/$package"
    npm pack --json --ignore-scripts --pack-destination "$tarballs" >/dev/null
  )
done
test -f "$tarballs/fl03-component-runtime-6.4.5.tgz"
test -f "$tarballs/fl03-harness-claude-6.4.5.tgz"
test -f "$tarballs/fl03-harness-codex-6.4.5.tgz"
test -f "$tarballs/fl03-harness-pi-6.4.5.tgz"
tar -tzf "$tarballs/fl03-component-runtime-6.4.5.tgz" | grep -q 'package/runtime/shepherd-component.js'
tar -tzf "$tarballs/fl03-component-runtime-6.4.5.tgz" | grep -q 'package/runtime/shepherd-component.wasm'
for package in component-runtime harness-claude harness-codex harness-pi; do
  tar -tzf "$tarballs/fl03-${package}-6.4.5.tgz" | grep -qx 'package/LICENSE'
  tar -tzf "$tarballs/fl03-${package}-6.4.5.tgz" | grep -qx 'package/THIRD_PARTY_NOTICES.md'
  tar -tzf "$tarballs/fl03-${package}-6.4.5.tgz" | grep -Eq '^package/THIRD_PARTY_LICENSES/[0-9a-f]{64}\.txt$'
done

install="$tmp_dir/install"
mkdir -p "$install"
npm install --prefix "$install" --ignore-scripts --offline --no-save \
  "$tarballs/fl03-component-runtime-6.4.5.tgz" \
  "$tarballs/fl03-harness-claude-6.4.5.tgz" \
  "$tarballs/fl03-harness-codex-6.4.5.tgz" \
  "$tarballs/fl03-harness-pi-6.4.5.tgz" >/dev/null
test -s "$install/node_modules/@fl03/component-runtime/runtime/shepherd-component.js"
test -s "$install/node_modules/@fl03/component-runtime/runtime/shepherd-component.wasm"
node packages/scripts/test-active-adapters.mjs \
  "$install/node_modules/@fl03/component-runtime/runtime/shepherd-component.js" \
  "$install/node_modules/@fl03"
printf 'ok: clean packed fixture installed all harness packages with adjacent component runtime\n'
