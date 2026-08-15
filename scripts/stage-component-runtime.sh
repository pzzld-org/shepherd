#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

artifact="${SHEPHERD_COMPONENT_WASM:-target/wasm32-wasip2/release/shepherd_component.wasm}"
stage_root="${1:-}"
if [[ -z "$stage_root" ]]; then
  printf 'usage: %s <clean-stage-root>\n' "$0" >&2
  exit 64
fi
if [[ ! -s "$artifact" ]]; then
  printf 'component artifact is missing: %s\n' "$artifact" >&2
  exit 1
fi

node_root="${SHEPHERD_COMPONENT_NODE_ROOT:-$PWD}"
jco="${SHEPHERD_JCO_BIN:-$node_root/node_modules/.bin/jco}"
if [[ ! -x "$jco" ]]; then
  printf 'locked jco is missing: %s\n' "$jco" >&2
  exit 1
fi

mkdir -p "$stage_root/packages/component-runtime/runtime"
cp -R packages/component-runtime/src packages/component-runtime/README.md packages/component-runtime/package.json "$stage_root/packages/component-runtime/"
cp "$artifact" "$stage_root/packages/component-runtime/runtime/shepherd-component.wasm"
"$jco" transpile "$stage_root/packages/component-runtime/runtime/shepherd-component.wasm" \
  --out-dir "$stage_root/packages/component-runtime/runtime" --name shepherd-component --quiet
test -s "$stage_root/packages/component-runtime/runtime/shepherd-component.js"
test -s "$stage_root/packages/component-runtime/runtime/shepherd-component.d.ts"
printf 'staged component runtime at %s\n' "$stage_root/packages/component-runtime/runtime"
