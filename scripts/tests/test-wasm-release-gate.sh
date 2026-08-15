#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKFLOW="${ROOT}/.github/workflows/rust-wasm.yml"
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

check_contains "workflow validates extracted WIT bytes" "${WORKFLOW}" 'test -s "${RUNNER_TEMP}/shepherd.wit"'
check_contains "feature matrix validates the component" "${FEATURES}" 'wasm-tools validate'
check_contains "feature matrix extracts non-empty WIT" "${FEATURES}" 'wasm-tools component wit'
check_contains "local wasm gate validates extracted WIT bytes" "${GATE}" 'test -s "${wit_output}"'
check_contains "local wasm gate validates the resolved component export" "${GATE}" "grep -Fq 'export fl03:shepherd/engine@"
check_contains "workflow validates the resolved component export" "${WORKFLOW}" "grep -Fq 'export fl03:shepherd/engine@"
check_contains "toolchain installs wasip2" "${TOOLCHAIN}" 'wasm32-wasip2'
check_contains "setup installs wasip2" "${SETUP}" 'wasm32-wasip2'
check_contains "setup pins wasm-tools version" "${SETUP}" 'WASM_TOOLS_VERSION="1.254.0"'
check_contains "setup installs pinned wasm-tools" "${SETUP}" 'cargo install wasm-tools --version "${WASM_TOOLS_VERSION}" --locked --quiet'
check_contains "workflow pins wasm-tools version" "${WORKFLOW}" 'WASM_TOOLS_VERSION: "1.254.0"'
check_contains "workflow installs pinned wasm-tools" "${WORKFLOW}" 'cargo install wasm-tools --version "${WASM_TOOLS_VERSION}" --locked'
check_contains "local wasm gate validates exact import count" "${GATE}" 'resolved_import_count'
check_contains "workflow validates exact import count" "${WORKFLOW}" 'resolved_import_count'
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
