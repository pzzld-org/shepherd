#!/usr/bin/env bash
# check-features.sh — prove the workspace feature graph resolves.
#
# WHY THIS EXISTS.
#
# A feature flag rots silently. `cargo check --workspace` builds exactly one
# combination -- the union of every member's defaults -- so a `wasm` flag that
# resolves to a dependency-not-found error, an `alloc` floor that stopped being
# no_std six commits ago, or a `full` that pulls a crate with no wasm backend
# all keep passing CI indefinitely. Nothing references them, so nothing breaks.
#
# Shepherd is being rewritten because the last implementation could not reach a
# new host. The flags are the mechanism that keeps the next host reachable, so
# they are worth exactly as much as the check that runs them.
#
# Usage:
#   scripts/check-features.sh            # host combinations only
#   scripts/check-features.sh --targets  # add wasm32-unknown-unknown + wasip2
#
# Cross-target checks need a clang with a WebAssembly backend. Apple's system
# clang has none; install LLVM (`brew install llvm`) and this script finds it.
set -euo pipefail

cd "$(dirname "${0}")/.."

WITH_TARGETS=0
[[ "${1:-}" == "--targets" ]] && WITH_TARGETS=1

failures=0
checked=0

check() {
  local label="${1}"
  shift
  checked=$((checked + 1))
  printf '  %-58s' "${label}"
  if output=$(cargo check "$@" --quiet 2>&1); then
    printf 'ok\n'
  else
    printf 'FAILED\n'
    printf '%s\n' "${output}" | sed 's/^/      /'
    failures=$((failures + 1))
  fi
}

echo "== engine: the no_std floor and the capability flags =="
# `alloc` is the floor an embedder without a filesystem builds against. If this
# stops compiling, `no_std` support has been lost, not merely untested.
check "core --no-default-features --features alloc" \
  -p shepherd-core --no-default-features --features alloc
check "core --no-default-features --features std" \
  -p shepherd-core --no-default-features --features std
for ff in chrono json parse schema tracing uuid; do
  check "core --no-default-features --features ${ff}" \
    -p shepherd-core --no-default-features --features "${ff}"
done
check "core --features full" -p shepherd-core --features full

echo
echo "== umbrella: each capability alone, then together =="
# Each capability is checked in isolation because the weak (`?/`) fan-out is
# only correct if enabling `json` does NOT conjure the registry. A combined
# check cannot tell the difference.
check "sdk --no-default-features --features alloc" \
  -p shepherd --no-default-features --features alloc
for ff in json parse schema registry render tracing; do
  check "sdk --no-default-features --features std,${ff}" \
    -p shepherd --no-default-features --features "std,${ff}"
done
check "sdk --features full" -p shepherd --features full

echo
echo "== members: standalone, and the binary =="
check "registry --features full" -p shepherd-registry --features full
check "render  --features full" -p shepherd-render --features full
check "cli --all-targets" -p shepherd-cli --all-targets
check "cli --features full --all-targets" -p shepherd-cli --features full --all-targets

if [[ "${WITH_TARGETS}" == "1" ]]; then
  echo
  echo "== cross-target: the reason the boundary exists =="

  # Homebrew LLVM ships a clang with a wasm backend; Apple's does not.
  for llvm in /opt/homebrew/opt/llvm/bin /usr/local/opt/llvm/bin; do
    if [[ -x "${llvm}/clang" ]]; then
      export CC="${llvm}/clang"
      export AR="${llvm}/llvm-ar"
      break
    fi
  done

  check "core   -> wasm32-unknown-unknown" \
    -p shepherd-core --target wasm32-unknown-unknown --no-default-features --features wasm
  check "sdk    -> wasm32-unknown-unknown" \
    -p shepherd --target wasm32-unknown-unknown --no-default-features --features wasm
  # The registry is the interesting one: rusqlite picks its backend by target
  # cfg, so this is what proves `sqlite-wasm` is wired to the right one.
  check "registry -> wasm32-unknown-unknown" \
    -p shepherd-registry --target wasm32-unknown-unknown --no-default-features --features wasm
  check "render -> wasm32-unknown-unknown" \
    -p shepherd-render --target wasm32-unknown-unknown --no-default-features --features wasm
fi

echo
if [[ "${failures}" -gt 0 ]]; then
  echo "FAILED: ${failures} of ${checked} feature combinations do not resolve."
  exit 1
fi
echo "ok: all ${checked} feature combinations resolve."
