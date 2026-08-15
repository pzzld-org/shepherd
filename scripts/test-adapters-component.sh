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
  printf 'locked jco is missing from %s\n' "$node_root" >&2
  exit 1
fi
tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/shepherd-adapters-component.XXXXXX")
trap 'find "$tmp_dir" -depth -delete' EXIT
mkdir -p "$tmp_dir/runtime"
cp "$artifact" "$tmp_dir/runtime/shepherd-component.wasm"
cp packages/scripts/test-adapters-component.mjs "$tmp_dir/runtime/test-adapters-component.mjs"
"$jco" transpile "$tmp_dir/runtime/shepherd-component.wasm" --out-dir "$tmp_dir/runtime/component" --name shepherd-component >/dev/null
ln -s "$node_root/node_modules" "$tmp_dir/runtime/node_modules"
node packages/scripts/test-adapters-component.mjs "$tmp_dir/runtime/component/shepherd-component.js"
