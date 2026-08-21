#!/usr/bin/env bash
# gate.sh — the local gate suite, in one place.
#
# WHY ONE SCRIPT.
#
# The gate was previously four commands someone had to remember in the right
# order. A gate remembered as four commands gets run as three, and the one that
# gets dropped is whichever was slowest last time. Naming it once means the
# pre-commit hook, the pre-push hook, `cargo gate`, and CI all run the same
# thing, and adding a check to the gate is one edit rather than five.
#
# TIERS. CLAUDE.md draws the line at two seconds: gate tests are deterministic,
# local, free, and fast enough to run on every commit. Anything that compiles
# the workspace is not that, so it runs on push instead.
#
#   scripts/gate.sh fast     no compilation. formatting + workspace invariants.
#   scripts/gate.sh full     fast + clippy + tests + the feature matrix.
#   scripts/gate.sh wasm     the WASI execution suite (needs wasi-sdk, wasmtime).
#   scripts/gate.sh all      full + Windows cfg cross-check + wasm.
#
# Default is `full`. Every tier is safe to run on a dirty tree; nothing here
# writes to the repository.
set -euo pipefail

cd "$(dirname "${0}")/.."

TIER="${1:-full}"
FAILURES=0
STARTED="${SECONDS}"

step() {
  local label="${1}"
  shift
  printf '\n\033[1m==> %s\033[0m\n' "${label}"
  if "$@"; then
    return 0
  fi
  printf '\033[31m    FAILED: %s\033[0m\n' "${label}"
  FAILURES=$((FAILURES + 1))
  return 0
}

# ---------------------------------------------------------------- fast --- #
# No compilation. This is what runs on every commit.
gate_fast() {
  step "rustfmt" cargo fmt --all --check
  step "Git hooks are non-blocking" bash scripts/tests/test-git-hooks.sh
  step "engine boundary negative controls" bash .github/scripts/boundary-selftest.sh
  step "npm adapter dependency rules are falsifiable" node packages/scripts/check-deps.mjs --self-test
  step "npm adapter dependency rules" node packages/scripts/check-deps.mjs
  # The invariants are checked for falsifiability first: a validator with a
  # typo'd key name passes everything forever and is worse than no validator.
  step "workspace invariants are falsifiable" ./scripts/check-workspace.sh --self-test
  step "workspace invariants" ./scripts/check-workspace.sh
  step "compiler package projection is falsifiable" python3 scripts/tests/test-generate-compiler-package-content.py
  step "Cargo distribution contract" python3 scripts/tests/test-cargo-distribution.py
  step "Cargo distribution inventory" python3 scripts/check-cargo-distribution.py
  step "Cargo publisher recovery contract" python3 scripts/tests/test-cargo-publish.py
  # There has never been an `npm publish` in this repository's CI. Seven
  # releases shipped crates and nothing to npm, which is why the published
  # pi-shepherd is still the inert 6.4.5.
  step "npm publisher contract is falsifiable" python3 scripts/npm-publish.py --self-test
  step "WASM release boundary is falsifiable" bash scripts/tests/test-wasm-release-gate.sh
  step "component Node boundary is falsifiable" bash scripts/tests/test-component-node-gate.sh
  step "package distribution boundary is falsifiable" bash scripts/tests/test-package-boundary.sh
  step "generated carrier authority" bash scripts/tests/test-generated-carrier-authority.sh
  # @pzzld/pi-shepherd shipped with no `pi` key for its entire history, so Pi
  # loaded nothing from it -- not the nine skills, not src/extension.mjs. The
  # package installed cleanly and was inert. Nothing asked what Pi ships.
  # Two field-level breaks shipped across the WIT/native boundary and no test
  # noticed: the missing `schema` envelope (every operation rejected) and
  # tool_use_id vs tool_call_id (every resolve rejected, so the Pi guard denied
  # everything). Both were invisible because the extension never loaded at all.
  step "wire contract parity is falsifiable" python3 scripts/check-wire-contract.py --self-test
  step "wire contract parity" python3 scripts/check-wire-contract.py
  step "native dispatch wire contract" bash scripts/tests/test-native-dispatch-wire.sh
  step "Pi package surface is falsifiable" bash scripts/tests/test-pi-package-surface.sh --self-test
  step "Pi package surface" bash scripts/tests/test-pi-package-surface.sh
  # The cross-harness claim itself. Each harness was checked in isolation and
  # the COMPARISON between them -- the whole product claim -- was checked by
  # nobody, which is how "Claude 10, Codex 9, Pi 0" shipped repeatedly.
  step "harness surface parity is falsifiable" bash scripts/tests/test-harness-surface-parity.sh --self-test
  step "harness surface parity" bash scripts/tests/test-harness-surface-parity.sh
  step "native CLI authority inventory is falsifiable" python3 scripts/check-cli-authority.py --self-test
  step "native CLI authority inventory" python3 scripts/check-cli-authority.py
  # This harness shipped correct, falsifiable, and referenced by NOTHING, so it
  # was free to rot and did: an rg sweep over the retired bin/ (exit 2 scored as
  # "clean"), a hooks.json assertion that broke when the seven carrier scripts
  # were restored, and three lifecycle assertions left pointing at
  # claude_hook.rs after the lifecycle moved to native_hook.rs. Three failures,
  # zero signal, because nothing executed it.
  step "native CLI authority regression harness" bash scripts/tests/test_cli_authority_gate.sh
  # ...and the rule that makes the above structurally unrepeatable. gate.sh
  # names its members one `step` at a time, so a new file under scripts/tests/
  # is unwired until someone remembers this list. This is the fourth instance
  # of that shape; it is now the gate's problem, not a reviewer's.
  step "every test is reachable from a runner (falsifiable)" python3 scripts/check-gate-wiring.py --self-test
  step "every test is reachable from a runner" python3 scripts/check-gate-wiring.py
  step "release asset inventory" bash scripts/tests/test-release-assets.sh
  step "release installers" bash scripts/tests/test-release-installers.sh
  step "PowerShell installer contract" bash scripts/tests/test-release-installer-powershell-contract.sh
  step "release distribution legal material" bash scripts/tests/test-release-distribution-license.sh
  step "portable deterministic release tar" bash scripts/tests/test-release-tar-portability.sh
  # Both of these shipped correct, falsifiable and referenced by NOTHING. The
  # distribution lane's own headline finding was that
  # test_shepherd_native_launcher.sh had never run in any gate; it then produced
  # two more of the same shape. A correct unwired gate is worth exactly what an
  # inert one is.
  step "release package-name derivation" bash scripts/tests/test-release-package-names.sh
  step "release archive layout" bash scripts/tests/test-release-archive-layout.sh
  step "GitHub Action pin checker is falsifiable" python3 scripts/tests/test-check-github-actions.py
  step "GitHub Action pins" python3 scripts/check-github-actions.py
  step "release workflow contract" bash scripts/tests/test-release-workflow.sh
  step "release version authority is falsifiable" python3 scripts/tests/test-version-bump.py
  check_release_version() {
    local version
    version=$(python3 -c 'import json; print(json.load(open(".claude-plugin/plugin.json"))["version"])')
    python3 scripts/version-bump.py check --root . --version "$version"
  }
  step "release version authority" check_release_version
  # The plugin layout is an interface contract with the harness. `claude plugin
  # validate` passes clean on a tree whose hooks all point at deleted scripts,
  # so it cannot be the thing that catches this.
  step "plugin contract is falsifiable" ./scripts/check-plugin.py --self-test
  step "plugin contract" ./scripts/check-plugin.py
  step "Codex regular carrier projection" python3 scripts/generate-codex-carrier.py --check
  # The target-final oracle had no generator (#341), so every content change
  # meant hand-editing three trees of hashes -- which produced a wrong-shaped
  # file once and a regenerated-but-uncommitted one once, five red CI checks.
  step "content oracle matches the live compiler" python3 scripts/generate-content-oracle.py --check
  # Reusable-workflow wiring (workflow_call inputs, forwarded secrets, needs:
  # targets) parses fine when it is wrong and fails only at dispatch time.
  # actionlint is the checker for that. It is optional locally, but a SKIP is
  # stated out loud -- a gate that silently no-ops when a tool is absent is
  # indistinguishable from one that passed.
  lint_workflows() {
    if ! command -v actionlint >/dev/null 2>&1; then
      printf '    SKIP: actionlint not installed (brew install actionlint); CI runs it pinned\n'
      return 0
    fi
    local workflows=()
    local workflow_file
    while IFS= read -r workflow_file; do
      workflows+=("$workflow_file")
    done < <(find .github/workflows -maxdepth 1 -name '*.yml' | sort)
    if [[ "${#workflows[@]}" -eq 0 ]]; then
      printf '    no workflow files discovered\n' >&2
      return 1
    fi
    # SC2016 ("expressions don't expand in single quotes") is INFO-level and
    # fires on every `printf 'format %s\n' "$value"` in the repo -- where the
    # single quotes are correct, because printf consumes the %s, not the shell.
    # Excluding one noisy info check keeps the real warnings visible; SC2209
    # (an unquoted literal that shadows a real binary) was found by this lint
    # and fixed in gitflow.yml rather than suppressed.
    SHELLCHECK_OPTS=--exclude=SC2016 actionlint "${workflows[@]}" || return 1
    printf '    actionlint: %s workflow file(s) clean\n' "${#workflows[@]}"
  }
  step "workflow wiring (actionlint)" lint_workflows
}

# ---------------------------------------------------------------- full --- #
gate_full() {
  gate_fast
  step "cold Cargo Binstall metadata fixture" python3 scripts/tests/test-cargo-binstall-local.py
  # The fast tier can only SKIP this (it compiles nothing by contract); here a
  # binary is guaranteed, so it runs for real.
  step "content oracle matches the live compiler (full)" python3 scripts/generate-content-oracle.py --check
  step "clippy (default)" env RUSTFLAGS="-D warnings" cargo clippy --workspace --all-targets --locked
  step "clippy (full)" env RUSTFLAGS="-D warnings" cargo clippy --workspace --all-targets --locked --features full
  step "tests" cargo test --workspace --locked
  # Do not "fix" this by adding `cargo test --workspace --locked --all-features`
  # below. That was tried and measured wrong twice: `--all-features` on this
  # workspace turns on `nightly` (crates/core/Cargo.toml), which gates
  # `#![cfg_attr(feature = "nightly", feature(allocator_api))]`
  # (crates/core/src/lib.rs) behind an unstable `#[feature]` attribute, and
  # `rust-toolchain.toml` pins stable 1.97.0 -- the build fails outright with
  # `error[E0554]`, it does not run a fuller test set.
  #
  # The step above already runs every `required-features` target: workspace
  # feature unification pulls `full` into `shepherd-core` via `shepherd-cli`,
  # and every `required-features` in the workspace is `std`/`parse`/`json`/
  # `bundled`/`layout`, all satisfied by that unification. Measured directly
  # under plain `cargo test --workspace --locked`: shepherd_core 5, dispatch
  # 15, guard 69, loader 25, portable_dispatch 7, run_state 6, and the
  # `default` integration target (`crates/core/tests/default.rs`,
  # `required-features = []`, so it runs under every invocation) 4 -- 131 core
  # tests, including all 69 guard-engine tests. This comment previously totaled
  # 127, four short, because the enumeration omitted `default`; the miscount
  # was caught by re-deriving the count from `crates/core/Cargo.toml`'s
  # `[[test]]` list rather than trusting the prose. The "3 of 126, none of the
  # guard engine's 66" figure this comment used to cite does not reproduce
  # under `--workspace`; it only reproduces for a single-crate invocation
  # (`cargo test -p shepherd-core`), which drops feature unification and is not
  # what this gate runs. Trusting that single-crate number instead of
  # remeasuring under the actual gate command is, verbatim, how this comment
  # went stale in the first place -- do not repeat it.
  step "build typed component for adapter package suites" \
    cargo build --locked --release --package shepherd-component --target wasm32-wasip2
  step "component runtime package suite" \
    node --test packages/component-runtime/test/*.test.mjs
  step "Claude adapter package suite" node packages/harness-claude/test.mjs
  step "Codex adapter package suite" node packages/harness-codex/test.mjs
  step "Pi adapter package suite" node packages/harness-pi/test.mjs
  step "canonical Claude carrier is compiler-owned" \
    cargo run --quiet --locked -p shepherd-cli -- \
    compile --target claude --out "$PWD" --check
  compile_ephemeral_carriers() {
    local stage status=0
    stage=$(mktemp -d "${TMPDIR:-/tmp}/shepherd-carriers.XXXXXX")
    cargo run --quiet --locked -p shepherd-cli -- \
      compile --target codex --out "$stage/codex" || status=$?
    if [[ "$status" -eq 0 ]]; then
      cargo run --quiet --locked -p shepherd-cli -- \
        compile --target pi --out "$stage/pi" || status=$?
    fi
    if [[ "$status" -eq 0 ]]; then
      grep -Fq '"target": "codex"' "$stage/codex/.shepherd-generated.json" || status=1
      grep -Fq '"target": "pi"' "$stage/pi/.shepherd-generated.json" || status=1
    fi
    # The AUTHORITATIVE carrier check. `generate-codex-carrier.py` projects from
    # the Claude tree with a portability filter, which is fast and catches the
    # claude-only class; this compares the committed carrier against what the
    # compiler actually emits for Codex, which is the only thing that cannot be
    # fooled by the projector and the carrier agreeing with each other.
    if [[ "$status" -eq 0 ]]; then
      if ! diff -r "$stage/codex/skills" plugins/shepherd/codex/skills >/dev/null; then
        printf 'committed Codex carrier differs from `compile --target codex`:\n' >&2
        diff -r "$stage/codex/skills" plugins/shepherd/codex/skills >&2 || true
        status=1
      fi
    fi
    find "$stage" -depth -delete
    return "$status"
  }
  step "canonical Codex and Pi carriers compile from Rust" compile_ephemeral_carriers
  # `cargo check --workspace` builds exactly one feature combination; this is
  # what covers the rest. See the header of scripts/check-features.sh.
  step "feature matrix" ./scripts/check-features.sh
  if command -v cargo-deny >/dev/null 2>&1; then
    step "supply chain" cargo deny --workspace --all-features check
  else
    printf '\n\033[33m==> supply chain SKIPPED\033[0m (cargo-deny absent; scripts/setup.sh installs it)\n'
  fi
}

# ---------------------------------------------------------------- wasm --- #
# The reason the crate split exists. Requires wasi-sdk and wasmtime, so it is
# opt-in locally and always-on in CI (.github/workflows/rust-wasm.yml).
gate_wasm() {
  local missing=0
  local wasm_tools_version="1.254.0"

  # wasm32-unknown-unknown needs a clang with a WebAssembly backend, because
  # `sqlite-wasm-rs` compiles SQLite from C. Apple's system clang has no wasm
  # backend and fails deep inside cc-rs with a wall of `-D` flags that says
  # nothing about the actual cause, so it is worth finding Homebrew's up front.
  #
  # The variables are TARGET-SCOPED (`CC_wasm32_unknown_unknown`), not bare
  # `CC`. A bare `CC` also captures the wasip1 build below, and Homebrew's
  # clang has a wasm backend but no WASI sysroot -- so it compiles the
  # unknown-unknown leg and silently breaks the WASI one. That is exactly what
  # happened the first time this ran. Note underscores: cc-rs reads
  # `CC_wasm32_unknown_unknown`, matching the target triple with `-` replaced.
  local found_clang=0
  for llvm in /opt/homebrew/opt/llvm/bin /usr/local/opt/llvm/bin; do
    if [ -x "${llvm}/clang" ]; then
      export CC_wasm32_unknown_unknown="${llvm}/clang"
      export AR_wasm32_unknown_unknown="${llvm}/llvm-ar"
      found_clang=1
      break
    fi
  done
  if [ "$(uname -s)" = "Darwin" ] && [ "${found_clang}" = "0" ]; then
    printf 'no clang with a wasm backend found (brew install llvm)\n'
    missing=1
  fi

  command -v wasmtime >/dev/null 2>&1 || { printf 'wasmtime not on PATH\n'; missing=1; }
  command -v wasm-tools >/dev/null 2>&1 || { printf 'wasm-tools not on PATH\n'; missing=1; }
  if command -v wasm-tools >/dev/null 2>&1 \
    && [ "$(wasm-tools --version 2>/dev/null)" != "wasm-tools ${wasm_tools_version}" ]; then
    printf 'wasm-tools %s required\n' "${wasm_tools_version}"
    missing=1
  fi
  [ -n "${WASI_SDK_PATH:-}" ] && [ -x "${WASI_SDK_PATH}/bin/clang" ] || {
    printf 'WASI_SDK_PATH unset or not a wasi-sdk install\n'
    missing=1
  }
  if [ "${missing}" = "1" ]; then
    printf '\n\033[31m==> wasm BLOCKED\033[0m (run scripts/setup.sh --wasm)\n'
    return 1
  fi

  # wasm32-unknown-unknown proves reach: no OS, no C toolchain, no filesystem.
  for pkg in shepherd-core shepherd-compiler shepherd-sdk shepherd-registry shepherd-render; do
    step "build ${pkg} -> wasm32-unknown-unknown" \
      cargo build --locked --release --package "${pkg}" \
      --target wasm32-unknown-unknown --no-default-features --features wasm
  done

  step "build Shepherd WIT component (wasip2)" \
    cargo build --locked --release --package shepherd-component --target wasm32-wasip2
  step "validate Shepherd WIT component" \
    wasm-tools validate target/wasm32-wasip2/release/shepherd_component.wasm
  extract_component_wit() {
    local artifact="target/wasm32-wasip2/release/shepherd_component.wasm"
    local wit_output="target/wasm32-wasip2/release/shepherd.wit"
    local resolved_imports="${wit_output}.imports"
    local resolved_import_count
    wasm-tools component wit "${artifact}" > "${wit_output}"
    test -s "${wit_output}"
    grep -Fq 'export fl03:shepherd/engine@6.5.6;' "${wit_output}"
    sed -n 's/^  import \(wasi:[^;]*\);$/\1/p' "${wit_output}" \
      | LC_ALL=C sort > "${resolved_imports}"
    resolved_import_count=$(wc -l < "${resolved_imports}" | tr -d ' ')
    test "${resolved_import_count}" -eq 14
    diff -u crates/component/wit/resolved-imports.txt "${resolved_imports}"
  }
  step "extract Shepherd WIT contract" extract_component_wit
  step "call Shepherd component from Node through jco" bash scripts/test-component-node.sh
  step "Claude adapter package suite" node packages/harness-claude/test.mjs
  step "Codex adapter package suite" node packages/harness-codex/test.mjs
  step "Pi adapter package suite" node packages/harness-pi/test.mjs
  step "install the Claude marketplace plugin from source" \
    bash scripts/tests/test-claude-marketplace.sh
  step "install the Codex marketplace plugin from source" \
    bash scripts/tests/test-codex-marketplace.sh
  step "clean packed harness distribution" bash scripts/test-packed-plugin.sh

  # wasm32-wasip1 proves behaviour. Building only proves the C cross-compile;
  # these tests EXECUTE under wasmtime, and one of them opens a file-backed
  # database and reads a row back through the WASI VFS. SQLite correctly falls
  # back from requested WAL to delete journaling on WASI, whose VFS has no WAL
  # shared-memory locking. Real file persistence is the property
  # wasm32-unknown-unknown cannot satisfy in Node.
  step "execute registry gate tests under wasmtime (wasip1)" \
    cargo test --locked --package shepherd-registry \
    --target wasm32-wasip1 --no-default-features --features wasi
}

case "${TIER}" in
  fast) gate_fast ;;
  full) gate_full ;;
  wasm) gate_wasm ;;
  all)
    gate_full
    step "Windows CLI cfg boundary" env RUSTFLAGS="-D warnings" cargo check --locked -p shepherd-cli --target x86_64-pc-windows-msvc --no-default-features --features std
    gate_wasm
    ;;
  *)
    printf 'usage: scripts/gate.sh [fast|full|wasm|all]\n' >&2
    exit 2
    ;;
esac

ELAPSED=$((SECONDS - STARTED))
printf '\n'
if [ "${FAILURES}" -gt 0 ]; then
  printf '\033[31mgate (%s): %d check(s) failed in %ds\033[0m\n' "${TIER}" "${FAILURES}" "${ELAPSED}"
  exit 1
fi
printf '\033[32mgate (%s): green in %ds\033[0m\n' "${TIER}" "${ELAPSED}"
