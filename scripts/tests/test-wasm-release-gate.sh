#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKFLOW="${ROOT}/.github/workflows/rust-wasm.yml"
RUST_WORKFLOW="${ROOT}/.github/workflows/rust.yml"
FEATURES="${ROOT}/scripts/check-features.sh"
GATE="${ROOT}/scripts/gate.sh"
TOOLCHAIN="${ROOT}/rust-toolchain.toml"
SETUP="${ROOT}/scripts/setup.sh"
WIT="${ROOT}/crates/component/wit/shepherd.wit"
REGISTRY_MIGRATE="${ROOT}/crates/registry/src/migrate.rs"
REGISTRY_API_TEST="${ROOT}/crates/registry/tests/registry.rs"
WASM_TOOLS_VERSION="1.254.0"

failures=0
check_contains() {
  local label="$1"
  local file="$2"
  local needle="$3"
  if grep -Fq -- "${needle}" "${file}"; then
    printf '  PASS  %s\n' "${label}"
  else
    printf '  FAIL  %s\n' "${label}"
    printf '        missing %s in %s\n' "${needle}" "${file}"
    failures=$((failures + 1))
  fi
}

check_absent() {
  local label="$1"
  local file="$2"
  local needle="$3"
  if grep -Fq -- "${needle}" "${file}"; then
    printf '  FAIL  %s\n' "${label}"
    printf '        forbidden %s in %s\n' "${needle}" "${file}"
    failures=$((failures + 1))
  else
    printf '  PASS  %s\n' "${label}"
  fi
}

check_exactly_once() {
  local label="$1"
  local file="$2"
  local needle="$3"
  local count
  count=$(grep -Fxc -- "${needle}" "${file}" || true)
  if [ "${count}" -eq 1 ]; then
    printf '  PASS  %s\n' "${label}"
  else
    printf '  FAIL  %s\n' "${label}"
    printf '        expected one %s in %s, found %s\n' "${needle}" "${file}" "${count}"
    failures=$((failures + 1))
  fi
}

check_job_contains() {
  local label="$1"
  local workflow="$2"
  local start_job="$3"
  local end_job="$4"
  local needle="$5"
  if sed -n "/^  ${start_job}:/,/^  ${end_job}:/p" "${workflow}" | grep -Fq -- "${needle}"; then
    printf '  PASS  %s\n' "${label}"
  else
    printf '  FAIL  %s\n' "${label}"
    printf '        missing %s in %s job of %s\n' "${needle}" "${start_job}" "${workflow}"
    failures=$((failures + 1))
  fi
}

check_trigger_paths_contains() {
  local label="$1"
  local workflow="$2"
  local trigger="$3"
  local end_trigger="$4"
  local needle="$5"
  if sed -n "/^  ${trigger}:/,/^  ${end_trigger}:/p" "${workflow}" | grep -Fq -- "${needle}"; then
    printf '  PASS  %s\n' "${label}"
  else
    printf '  FAIL  %s\n' "${label}"
    printf '        missing %s in %s trigger paths of %s\n' "${needle}" "${trigger}" "${workflow}"
    failures=$((failures + 1))
  fi
}

check_contains "workflow validates extracted WIT bytes" "${WORKFLOW}" 'test -s "${wit_output}"'
check_contains "feature matrix validates the component" "${FEATURES}" 'wasm-tools validate'
check_contains "feature matrix extracts non-empty WIT" "${FEATURES}" 'wasm-tools component wit'
check_contains "local wasm gate validates extracted WIT bytes" "${GATE}" 'test -s "${wit_output}"'
check_contains "local wasm gate validates the resolved component export" "${GATE}" "grep -Fq 'export fl03:shepherd/engine@"
check_contains "workflow validates the resolved component export" "${WORKFLOW}" 'expected_export=' \
  "the workflow must pin the exported interface"
check_contains "workflow reports its import count" "${WORKFLOW}" 'component imports %s WASI interfaces'
check_contains "workflow derives the expected import count" "${WORKFLOW}" 'expected_count=$(wc -l < "${pinned}"'
check_contains "toolchain installs wasip2" "${TOOLCHAIN}" 'wasm32-wasip2'
check_contains "toolchain installs Windows cfg target" "${TOOLCHAIN}" 'x86_64-pc-windows-msvc'
check_contains "setup installs wasip2" "${SETUP}" 'wasm32-wasip2'
check_contains "setup pins wasm-tools version" "${SETUP}" 'WASM_TOOLS_VERSION="1.254.0"'
check_contains "setup installs pinned wasm-tools" "${SETUP}" 'cargo install wasm-tools --version "${WASM_TOOLS_VERSION}" --locked --quiet'
check_contains "workflow pins wasm-tools version" "${WORKFLOW}" 'WASM_TOOLS_VERSION: "1.254.0"'
# The install moved to taiki-e/install-action; what must not move is the pin.
check_contains "workflow installs pinned wasm-tools" "${WORKFLOW}" 'tool: wasm-tools@${{ env.WASM_TOOLS_VERSION }}'
check_job_contains "feature matrix pins wasm-tools version" "${RUST_WORKFLOW}" "features" "msrv" 'WASM_TOOLS_VERSION: "1.254.0"'
check_job_contains "feature matrix installs pinned wasm-tools" "${RUST_WORKFLOW}" "features" "msrv" 'cargo install wasm-tools --version "${WASM_TOOLS_VERSION}" --locked'
check_job_contains "feature matrix is bounded" "${RUST_WORKFLOW}" "features" "msrv" 'timeout-minutes: 5'
check_job_contains "feature matrix uses the runner clang" "${RUST_WORKFLOW}" "features" "msrv" 'clang --version'
check_absent "Rust workflow never installs clang through apt" "${RUST_WORKFLOW}" 'apt-get install -y clang'
check_absent "WASM workflow never installs clang through apt" "${WORKFLOW}" 'apt-get install -y clang'
check_contains "local wasm gate validates exact import count" "${GATE}" 'resolved_import_count'
check_contains "local wasm gate runs the packed distribution probe" "${GATE}" 'scripts/test-packed-plugin.sh'
check_exactly_once "WASM workflow runs the Claude marketplace carrier once" "${WORKFLOW}" '          bash scripts/tests/test-claude-marketplace.sh'
for path in ".claude-plugin/**" "plugins/shepherd/**" "hooks/hooks.json" "agents/**" "skills/**" "scripts/tests/test-claude-marketplace.sh"; do
  check_trigger_paths_contains "PR trigger watches ${path}" "${WORKFLOW}" "pull_request" "push" "      - \"${path}\""
  check_trigger_paths_contains "push trigger watches ${path}" "${WORKFLOW}" "push" "repository_dispatch" "      - \"${path}\""
done
check_contains "aggregate gate cross-checks Windows cfg" "${GATE}" 'x86_64-pc-windows-msvc --no-default-features --features std'
check_contains "workflow validates exact import count" "${WORKFLOW}" 'resolved_import_count'
check_absent "WASM workflow excludes retired Claude release builder" "${WORKFLOW}" 'scripts/build-claude-plugin-release.sh'
check_absent "WASM workflow excludes retired Claude release test" "${WORKFLOW}" 'scripts/tests/test-claude-plugin-release.sh'
check_contains "WIT exports canonical compile" "${WIT}" 'compile-canonical: func'
check_contains "WIT exports canonical guard" "${WIT}" 'guard-eval-canonical: func'
check_contains "WASI registry tests reserve process-safe database paths" "${REGISTRY_MIGRATE}" '.create_new(true)'
check_absent "WASI registry tests never call unsupported process id" "${REGISTRY_MIGRATE}" 'std::process::id()'
check_contains "WASI registry tests embed their frozen fixture" "${REGISTRY_MIGRATE}" 'include_str!(concat!('
check_absent "WASI registry tests never open a host build path" "${REGISTRY_MIGRATE}" 'std::fs::read_to_string(frozen_sqlite_master_path())'
check_contains "WASI registry API tests reserve relative fixture directories" "${REGISTRY_API_TEST}" 'std::fs::create_dir(&path)'
check_absent "WASI registry API tests never query an ambient temp directory" "${REGISTRY_API_TEST}" 'std::env::temp_dir()'
check_absent "WASI registry API tests never call unsupported process id" "${REGISTRY_API_TEST}" 'std::process::id()'

tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT

# Exercise the feature-matrix dispatcher with real shell commands and a fake
# tool boundary. The fake cargo deliberately rejects the two non-Cargo
# commands so this fails if `check-features.sh` accidentally prepends
# `cargo check` to either one.
feature_bin="${tmp_dir}/feature-bin"
mkdir -p "${feature_bin}"
cat >"${feature_bin}/cargo" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "${FEATURE_TEST_CARGO_LOG}"
case " ${*} " in
  *" wasm-tools "*|*" extract_component_wit "*)
    printf 'cargo: unexpected non-Cargo command: %s\n' "$*" >&2
    exit 2
    ;;
esac
if [ "${1:-}" = "build" ]; then
  mkdir -p "${FEATURE_TEST_ROOT}/target/wasm32-wasip2/debug"
fi
EOF
cat >"${feature_bin}/wasm-tools" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "${FEATURE_TEST_WASM_TOOLS_LOG}"
case "${1:-}:${2:-}" in
  validate:*)
    ;;
  component:wit)
    printf '%s\n' \
      'package root:component;' \
      'world root {' \
      "  export fl03:shepherd/engine@${FEATURE_TEST_COMPONENT_VERSION};" \
      '}' \
      "package fl03:shepherd@${FEATURE_TEST_COMPONENT_VERSION} {" \
      '}'
    ;;
  *)
    printf 'unexpected wasm-tools command: %s\n' "$*" >&2
    exit 2
    ;;
esac
EOF
chmod +x "${feature_bin}/cargo" "${feature_bin}/wasm-tools"

export FEATURE_TEST_ROOT="${ROOT}"
export FEATURE_TEST_CARGO_LOG="${tmp_dir}/feature-cargo.log"
export FEATURE_TEST_WASM_TOOLS_LOG="${tmp_dir}/feature-wasm-tools.log"
FEATURE_TEST_COMPONENT_VERSION="$(sed -n 's/^package fl03:shepherd@\([^;]*\);$/\1/p' "${WIT}")"
export FEATURE_TEST_COMPONENT_VERSION
if PATH="${feature_bin}:/usr/bin:/bin" bash "${FEATURES}" --targets >"${tmp_dir}/features.out" 2>&1; then
  printf '  PASS  feature matrix dispatches component inspection outside cargo\n'
else
  printf '  FAIL  feature matrix dispatches component inspection outside cargo\n'
  sed 's/^/        /' "${tmp_dir}/features.out"
  failures=$((failures + 1))
fi
if grep -Fqx -- 'validate target/wasm32-wasip2/debug/shepherd_component.wasm' "${FEATURE_TEST_WASM_TOOLS_LOG}" \
  && grep -Fqx -- 'component wit target/wasm32-wasip2/debug/shepherd_component.wasm' "${FEATURE_TEST_WASM_TOOLS_LOG}"; then
  printf '  PASS  feature matrix invokes both wasm-tools operations directly\n'
else
  printf '  FAIL  feature matrix invokes both wasm-tools operations directly\n'
  failures=$((failures + 1))
fi
if grep -Eq -- '(^| )wasm-tools( |$)|(^| )extract_component_wit( |$)' "${FEATURE_TEST_CARGO_LOG}"; then
  printf '  FAIL  feature matrix never leaks non-Cargo commands into cargo check\n'
  failures=$((failures + 1))
else
  printf '  PASS  feature matrix never leaks non-Cargo commands into cargo check\n'
fi

fake_bin="${tmp_dir}/bin"
fake_sdk="${tmp_dir}/wasi-sdk"
mkdir -p "${fake_bin}" "${fake_sdk}/bin"

cat >"${fake_bin}/rustup" <<'EOF'
#!/usr/bin/env bash
if [ "${1:-}" = "target" ] && [ "${2:-}" = "list" ]; then
  printf '%s\n' wasm32-unknown-unknown wasm32-wasip1 wasm32-wasip2
fi
EOF
cat >"${fake_bin}/cargo" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "${SETUP_TEST_CARGO_LOG}"
EOF
for tool in cargo-deny cargo-nextest wasmtime; do
  : >"${fake_bin}/${tool}"
done
: >"${fake_sdk}/bin/clang"
chmod +x "${fake_bin}/rustup" "${fake_bin}/cargo" "${fake_bin}/cargo-deny" \
  "${fake_bin}/cargo-nextest" "${fake_bin}/wasmtime" "${fake_sdk}/bin/clang"

export PATH="${fake_bin}:/usr/bin:/bin"
export WASI_SDK_PATH="${fake_sdk}"
export SETUP_TEST_CARGO_LOG="${tmp_dir}/cargo.log"

before_hooks="$(git -C "${ROOT}" config --local --get core.hooksPath || true)"
if PATH="${fake_bin}:/usr/bin:/bin" bash "${SETUP}" --check --wasm >"${tmp_dir}/check.out" 2>&1; then
  printf '  FAIL  --check --wasm exits non-zero when wasm-tools is missing\n'
  failures=$((failures + 1))
else
  printf '  PASS  --check --wasm exits non-zero when wasm-tools is missing\n'
fi
if grep -Fq -- "wasm-tools  (cargo install wasm-tools --version ${WASM_TOOLS_VERSION} --locked)" "${tmp_dir}/check.out"; then
  printf '  PASS  --check --wasm reports the pinned wasm-tools install\n'
else
  printf '  FAIL  --check --wasm reports the pinned wasm-tools install\n'
  failures=$((failures + 1))
fi

cat >"${fake_bin}/wasm-tools" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' 'wasm-tools 0.1.0'
EOF
chmod +x "${fake_bin}/wasm-tools"
if bash "${SETUP}" --check --wasm >"${tmp_dir}/wrong-version.out" 2>&1; then
  printf '  FAIL  --check --wasm rejects a wrong wasm-tools version\n'
  failures=$((failures + 1))
else
  printf '  PASS  --check --wasm rejects a wrong wasm-tools version\n'
fi
if grep -Fq -- "wasm-tools  (cargo install wasm-tools --version ${WASM_TOOLS_VERSION} --locked)" "${tmp_dir}/wrong-version.out"; then
  printf '  PASS  wrong wasm-tools version reports the pinned install\n'
else
  printf '  FAIL  wrong wasm-tools version reports the pinned install\n'
  failures=$((failures + 1))
fi
after_hooks="$(git -C "${ROOT}" config --local --get core.hooksPath || true)"
if [ "${before_hooks}" = "${after_hooks}" ] && [ ! -e "${SETUP_TEST_CARGO_LOG}" ]; then
  printf '  PASS  --check --wasm does not mutate setup state\n'
else
  printf '  FAIL  --check --wasm does not mutate setup state\n'
  failures=$((failures + 1))
fi

rm -f "${SETUP_TEST_CARGO_LOG}"
bash "${SETUP}" --wasm >"${tmp_dir}/install.out" 2>&1
if grep -Fqx -- "install wasm-tools --version ${WASM_TOOLS_VERSION} --locked --quiet" "${SETUP_TEST_CARGO_LOG}"; then
  printf '  PASS  --wasm installs the exact locked wasm-tools CLI\n'
else
  printf '  FAIL  --wasm installs the exact locked wasm-tools CLI\n'
  failures=$((failures + 1))
fi

if [ "${failures}" -gt 0 ]; then
  printf 'FAILED: %s wasm release-gate invariant(s) missing\n' "${failures}"
  exit 1
fi
printf 'ok: wasm release-gate invariants present\n'
