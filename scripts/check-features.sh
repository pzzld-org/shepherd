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

run_checked() {
  local label="${1}"
  shift
  checked=$((checked + 1))
  printf '  %-58s' "${label}"
  if output=$("$@" 2>&1); then
    printf 'ok\n'
  else
    printf 'FAILED\n'
    printf '%s\n' "${output}" | sed 's/^/      /'
    failures=$((failures + 1))
  fi
}

check_cargo() {
  local label="${1}"
  shift
  run_checked "${label}" cargo check "$@" --quiet
}

echo "== engine: the no_std floor and the capability flags =="
# Content compilation is a pure allocation-only layer. Check every advertised
# floor independently so embedding it in a WASM component cannot silently
# acquire host I/O through the umbrella SDK.
check_cargo "compiler --no-default-features --features alloc" \
  -p shepherd-compiler --no-default-features --features alloc
check_cargo "compiler --no-default-features --features std" \
  -p shepherd-compiler --no-default-features --features std
check_cargo "compiler --no-default-features --features wasm" \
  -p shepherd-compiler --no-default-features --features wasm
check_cargo "compiler --features full" -p shepherd-compiler --features full

# The engine's `alloc` flag is the common floor every embedding layer must
# preserve. It has its own rows because its feature graph is larger.
# `alloc` is the floor an embedder without a filesystem builds against. If this
# stops compiling, `no_std` support has been lost, not merely untested.
check_cargo "core --no-default-features --features alloc" \
  -p shepherd-core --no-default-features --features alloc
check_cargo "core --no-default-features --features std" \
  -p shepherd-core --no-default-features --features std
for ff in chrono config json parse schema tracing uuid; do
  check_cargo "core --no-default-features --features ${ff}" \
    -p shepherd-core --no-default-features --features "${ff}"
done
check_cargo "core --features full" -p shepherd-core --features full

echo
echo "== umbrella: each capability alone, then together =="
# Each capability is checked in isolation because the weak (`?/`) fan-out is
# only correct if enabling `json` does NOT conjure the registry. A combined
# check cannot tell the difference.
check_cargo "sdk --no-default-features --features alloc" \
  -p shepherd-sdk --no-default-features --features alloc
check_cargo "sdk --no-default-features --features compiler" \
  -p shepherd-sdk --no-default-features --features compiler
for ff in config json parse schema registry render tracing; do
  check_cargo "sdk --no-default-features --features std,${ff}" \
    -p shepherd-sdk --no-default-features --features "std,${ff}"
done
check_cargo "sdk --features full" -p shepherd-sdk --features full

echo
echo "== members: standalone, and the binary =="
check_cargo "registry --features full" -p shepherd-registry --features full
check_cargo "render  --features full" -p shepherd-render --features full
check_cargo "component --features full" -p shepherd-component --features full
check_cargo "cli --all-targets" -p shepherd-cli --all-targets
check_cargo "cli --features full --all-targets" -p shepherd-cli --features full --all-targets

if [[ "${WITH_TARGETS}" == "1" ]]; then
  echo
  echo "== cross-target: the reason the boundary exists =="

  # Homebrew LLVM ships a clang with a wasm backend; Apple's does not.
  #
  # TARGET-SCOPED on purpose. A bare `CC` would also capture a wasm32-wasip1
  # build, and Homebrew's clang has a wasm backend but no WASI sysroot, so it
  # compiles this leg and silently breaks that one. cc-rs reads
  # `CC_wasm32_unknown_unknown` -- the triple with `-` replaced by `_`.
  for llvm in /opt/homebrew/opt/llvm/bin /usr/local/opt/llvm/bin; do
    if [[ -x "${llvm}/clang" ]]; then
      export CC_wasm32_unknown_unknown="${llvm}/clang"
      export AR_wasm32_unknown_unknown="${llvm}/llvm-ar"
      break
    fi
  done

  check_cargo "core   -> wasm32-unknown-unknown" \
    -p shepherd-core --target wasm32-unknown-unknown --no-default-features --features wasm
  check_cargo "compiler -> wasm32-unknown-unknown" \
    -p shepherd-compiler --target wasm32-unknown-unknown --no-default-features --features wasm
  # `cargo check` does not promise to leave a linkable component artifact.
  # Build this leg so the validation and WIT extraction below inspect the
  # exact binary a release job would distribute.
  check_build() {
    checked=$((checked + 1))
    printf '  %-58s' "${1}"
    shift
    if output=$(cargo build "$@" --quiet 2>&1); then
      printf 'ok\n'
    else
      printf 'FAILED\n'
      printf '%s\n' "${output}" | sed 's/^/      /'
      failures=$((failures + 1))
    fi
  }
  check_build "component -> wasm32-wasip2" \
    -p shepherd-component --target wasm32-wasip2 --features full
  if command -v wasm-tools >/dev/null 2>&1; then
    component_artifact="target/wasm32-wasip2/debug/shepherd_component.wasm"
    component_wit="target/wasm32-wasip2/debug/shepherd.wit"
    run_checked "component validate -> wasm32-wasip2" \
      wasm-tools validate "${component_artifact}"
    extract_component_wit() {
      local source_package='package fl03:shepherd@6.4.6;'
      wasm-tools component wit "${component_artifact}" > "${component_wit}"
      test -s "${component_wit}"
      grep -Fq "${source_package%;} {" "${component_wit}"
    }
    run_checked "component extract WIT -> wasm32-wasip2" extract_component_wit
  else
    checked=$((checked + 1))
    failures=$((failures + 1))
    printf '  %-58sFAILED\n' "wasm-tools required for component validation"
    printf '      wasm-tools is required; install it before --targets\n'
  fi
  check_cargo "sdk    -> wasm32-unknown-unknown" \
    -p shepherd-sdk --target wasm32-unknown-unknown --no-default-features --features wasm
  # The registry is the interesting one: rusqlite picks its backend by target
  # cfg, so this is what proves `sqlite-wasm` is wired to the right one.
  check_cargo "registry -> wasm32-unknown-unknown" \
    -p shepherd-registry --target wasm32-unknown-unknown --no-default-features --features wasm
  check_cargo "render -> wasm32-unknown-unknown" \
    -p shepherd-render --target wasm32-unknown-unknown --no-default-features --features wasm
fi

echo
if [[ "${failures}" -gt 0 ]]; then
  echo "FAILED: ${failures} of ${checked} feature combinations do not resolve."
  exit 1
fi
echo "ok: all ${checked} feature combinations resolve."
