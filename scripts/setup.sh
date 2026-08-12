#!/usr/bin/env bash
# setup.sh — make a fresh clone sprint-ready in one command.
#
# WHY THIS EXISTS.
#
# "Lost in translation" is not a metaphor here, it is the failure mode. A six
# sprint arc, several agents, and a handful of things that are only true if
# somebody remembered them: hooks are off until `core.hooksPath` is set (and
# that is LOCAL config, so it cannot be committed and every clone starts wrong);
# the wasm targets have to be installed before `scripts/check-features.sh
# --targets` means anything; the WASI suite needs a wasi-sdk and a wasmtime that
# nothing else in the toolchain provides. None of that is discoverable by
# reading the code. Each one produces a confusing failure at the worst moment.
#
# So it is one command, it is idempotent, and it prints what it changed.
#
#   scripts/setup.sh           toolchain, targets, tools, hooks
#   scripts/setup.sh --wasm    the above, plus wasi-sdk for the WASI suite
#   scripts/setup.sh --check   report what is missing, change nothing
set -euo pipefail

cd "$(dirname "${0}")/.."

WITH_WASM=0
CHECK_ONLY=0
for arg in "$@"; do
  case "${arg}" in
    --wasm) WITH_WASM=1 ;;
    --check) CHECK_ONLY=1 ;;
    -h | --help)
      sed -n '2,30p' "${0}"
      exit 0
      ;;
    *)
      printf 'unknown argument: %s\n' "${arg}" >&2
      exit 2
      ;;
  esac
done

CHANGES=0
MISSING=0

ok() { printf '  \033[32mok\033[0m      %s\n' "${1}"; }
did() {
  printf '  \033[36mset\033[0m     %s\n' "${1}"
  CHANGES=$((CHANGES + 1))
}
gap() {
  printf '  \033[33mmissing\033[0m %s\n' "${1}"
  MISSING=$((MISSING + 1))
}

need() { command -v "${1}" >/dev/null 2>&1; }

printf '\n\033[1mtoolchain\033[0m\n'
if need rustup; then
  # rust-toolchain.toml pins the channel, the components and the wasm targets,
  # so rustup installs the lot. This is only needed to force it to happen now
  # rather than on someone's first confusing cargo invocation.
  if [ "${CHECK_ONLY}" = "0" ]; then
    rustup show active-toolchain >/dev/null 2>&1 || true
    ok "toolchain from rust-toolchain.toml ($(rustup show active-toolchain 2>/dev/null | head -n1))"
  else
    ok "rustup present"
  fi
  for target in wasm32-unknown-unknown wasm32-wasip1; do
    if rustup target list --installed 2>/dev/null | grep -qx "${target}"; then
      ok "target ${target}"
    elif [ "${CHECK_ONLY}" = "1" ]; then
      gap "target ${target}  (rustup target add ${target})"
    else
      rustup target add "${target}" >/dev/null
      did "target ${target}"
    fi
  done
else
  gap "rustup  (https://rustup.rs)"
fi

printf '\n\033[1mtools\033[0m\n'
# cargo-deny enforces locked decision 7: the dependency stack is closed.
# cargo-nextest is what CI runs, so local results match CI results.
for tool in cargo-deny cargo-nextest; do
  if need "${tool}"; then
    ok "${tool}"
  elif [ "${CHECK_ONLY}" = "1" ]; then
    gap "${tool}  (cargo install ${tool} --locked)"
  else
    printf '  installing %s ...\n' "${tool}"
    cargo install "${tool}" --locked --quiet
    did "${tool}"
  fi
done

printf '\n\033[1mgit hooks\033[0m\n'
# `core.hooksPath` is local config and cannot be committed, so every clone
# starts with the hooks inert. This is the switch.
CURRENT_HOOKS="$(git config --get core.hooksPath || true)"
if [ "${CURRENT_HOOKS}" = ".githooks" ]; then
  ok "core.hooksPath = .githooks"
elif [ "${CHECK_ONLY}" = "1" ]; then
  gap "core.hooksPath  (git config core.hooksPath .githooks)"
else
  git config core.hooksPath .githooks
  did "core.hooksPath = .githooks"
fi
for hook in pre-commit commit-msg pre-push; do
  if [ -x ".githooks/${hook}" ]; then
    ok "${hook} executable"
  elif [ "${CHECK_ONLY}" = "1" ]; then
    gap "${hook} not executable"
  else
    chmod +x ".githooks/${hook}"
    did "${hook} executable"
  fi
done

if [ "${WITH_WASM}" = "1" ]; then
  printf '\n\033[1mWebAssembly\033[0m\n'

  # wasmtime executes the WASI test binaries. `.cargo/config.toml` wires it as
  # the runner for both wasip targets.
  if need wasmtime; then
    ok "wasmtime"
  elif [ "${CHECK_ONLY}" = "1" ]; then
    gap "wasmtime  (cargo install wasmtime-cli --locked)"
  else
    printf '  installing wasmtime-cli ...\n'
    cargo install wasmtime-cli --locked --quiet
    did "wasmtime"
  fi

  # wasi-sdk supplies the clang and sysroot that cross-compile SQLite's C to
  # WASI. `cc` finds everything from WASI_SDK_PATH alone.
  WASI_SDK_RELEASE="33.0"
  WASI_SDK_TAG="wasi-sdk-33"
  WASI_SDK_ROOT="${WASI_SDK_PATH:-${HOME}/.local/share/wasi-sdk}"

  if [ -x "${WASI_SDK_ROOT}/bin/clang" ]; then
    ok "wasi-sdk at ${WASI_SDK_ROOT}"
  elif [ "${CHECK_ONLY}" = "1" ]; then
    gap "wasi-sdk  (scripts/setup.sh --wasm)"
  else
    case "$(uname -s)-$(uname -m)" in
      Darwin-arm64) asset="wasi-sdk-${WASI_SDK_RELEASE}-arm64-macos" ;;
      Darwin-x86_64) asset="wasi-sdk-${WASI_SDK_RELEASE}-x86_64-macos" ;;
      Linux-x86_64) asset="wasi-sdk-${WASI_SDK_RELEASE}-x86_64-linux" ;;
      Linux-aarch64 | Linux-arm64) asset="wasi-sdk-${WASI_SDK_RELEASE}-arm64-linux" ;;
      *)
        gap "wasi-sdk: no published asset for $(uname -s)-$(uname -m)"
        asset=""
        ;;
    esac
    if [ -n "${asset}" ]; then
      url="https://github.com/WebAssembly/wasi-sdk/releases/download/${WASI_SDK_TAG}/${asset}.tar.gz"
      printf '  downloading %s (~180MB) ...\n' "${asset}"
      mkdir -p "${WASI_SDK_ROOT}"
      curl -fsSL "${url}" | tar xz -C "${WASI_SDK_ROOT}" --strip-components=1
      did "wasi-sdk at ${WASI_SDK_ROOT}"
    fi
  fi

  if [ -x "${WASI_SDK_ROOT}/bin/clang" ] && [ "${WASI_SDK_PATH:-}" != "${WASI_SDK_ROOT}" ]; then
    printf '\n  \033[33mAdd this to your shell profile:\033[0m\n'
    printf '      export WASI_SDK_PATH=%s\n' "${WASI_SDK_ROOT}"
    printf '  Then: scripts/gate.sh wasm\n'
  fi
fi

printf '\n'
if [ "${CHECK_ONLY}" = "1" ]; then
  if [ "${MISSING}" -gt 0 ]; then
    printf '\033[33m%d item(s) missing. Run scripts/setup.sh to fix.\033[0m\n' "${MISSING}"
    exit 1
  fi
  printf '\033[32msetup complete.\033[0m\n'
  exit 0
fi

if [ "${MISSING}" -gt 0 ]; then
  printf '\033[33m%d item(s) could not be set up automatically (see above).\033[0m\n' "${MISSING}"
fi
printf '\033[32m%d change(s) applied.\033[0m\n\n' "${CHANGES}"
cat <<'MSG'
Next:
    scripts/gate.sh fast     formatting + workspace invariants  (runs on commit)
    scripts/gate.sh full     the above, plus clippy, tests, feature matrix  (runs on push)
    scripts/gate.sh wasm     the WASI execution suite  (needs --wasm setup)
MSG
