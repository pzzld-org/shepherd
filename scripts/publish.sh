#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

# Define package manifests in the exact order they must be published.
# Dependencies must appear before crates that depend on them.
CRATE_MANIFESTS=(
#   "crates/core/Cargo.toml"
#   "crates/compiler/Cargo.toml"
#   "crates/component/Cargo.toml"
  "crates/registry/Cargo.toml"
  "crates/render/Cargo.toml"
  "crates/sdk/Cargo.toml"
  "crates/cli/Cargo.toml"
)

# These can also be overridden with environment variables.
REGISTRY="${PUBLISH_REGISTRY:-crates-io}"
DELAY_SECONDS="${PUBLISH_DELAY_SECONDS:-0}"

DRY_RUN=0
ALLOW_DIRTY=0
USE_LOCKED=1
ASSUME_YES=0
START_AT=""

usage() {
  cat <<'USAGE'
Usage: ./publish-crates.sh [options]

Publishes the manifests in CRATE_MANIFESTS sequentially, preserving the
array's exact order. The script stops immediately if any publication fails.

Options:
  --dry-run             Run Cargo's publish checks without uploading.
  --registry NAME       Publish to NAME instead of crates-io.
  --from MANIFEST       Resume at the specified manifest path.
  --delay SECONDS       Wait between successful uploads; default: 0.
  --allow-dirty         Pass --allow-dirty to cargo publish.
  --no-locked           Do not pass --locked to Cargo.
  -y, --yes             Skip the live-publish confirmation prompt.
  -h, --help            Show this help text.

Environment:
  REPO_ROOT              Base directory for relative manifest paths.
  PUBLISH_REGISTRY       Default registry name.
  PUBLISH_DELAY_SECONDS  Default inter-publication delay.
USAGE
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

while (($# > 0)); do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --registry)
      (($# >= 2)) || die "--registry requires a value"
      REGISTRY="$2"
      shift 2
      ;;
    --from)
      (($# >= 2)) || die "--from requires a manifest path"
      START_AT="$2"
      shift 2
      ;;
    --delay)
      (($# >= 2)) || die "--delay requires a non-negative integer"
      DELAY_SECONDS="$2"
      shift 2
      ;;
    --allow-dirty)
      ALLOW_DIRTY=1
      shift
      ;;
    --no-locked)
      USE_LOCKED=0
      shift
      ;;
    -y|--yes)
      ASSUME_YES=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      (($# == 0)) || die "unexpected positional arguments: $*"
      ;;
    *)
      die "unknown option: $1"
      ;;
  esac
done

case "$DELAY_SECONDS" in
  ''|*[!0-9]*)
    die "--delay must be a non-negative integer"
    ;;
esac

command -v cargo >/dev/null 2>&1 ||
  die "cargo is not installed or not on PATH"

((${#CRATE_MANIFESTS[@]} > 0)) ||
  die "CRATE_MANIFESTS is empty; define the package manifests to publish"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

if [[ -n "${REPO_ROOT:-}" ]]; then
  ROOT="$REPO_ROOT"
elif ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"; then
  :
elif ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null)"; then
  :
else
  ROOT="$(pwd -P)"
fi

[[ -d "$ROOT" ]] || die "repository root does not exist: $ROOT"
cd "$ROOT"

# Validate the complete configuration before uploading any crate.
for ((i = 0; i < ${#CRATE_MANIFESTS[@]}; i++)); do
  manifest="${CRATE_MANIFESTS[$i]}"

  [[ -n "$manifest" ]] ||
    die "CRATE_MANIFESTS contains an empty entry"

  [[ -f "$manifest" ]] ||
    die "manifest not found: $manifest"

  # Prevent a virtual workspace root from accidentally selecting many packages.
  grep -Eq '^[[:space:]]*\[package\][[:space:]]*(#.*)?$' "$manifest" ||
    die "manifest must identify one package with a [package] table: $manifest"

  for ((j = 0; j < i; j++)); do
    [[ "$manifest" != "${CRATE_MANIFESTS[$j]}" ]] ||
      die "duplicate manifest in CRATE_MANIFESTS: $manifest"
  done

  metadata_args=(
    metadata
    --format-version 1
    --no-deps
    --manifest-path "$manifest"
  )

  ((USE_LOCKED == 0)) || metadata_args+=(--locked)

  cargo "${metadata_args[@]}" >/dev/null
done

selected_manifests=()
start_found=0

if [[ -z "$START_AT" ]]; then
  selected_manifests=("${CRATE_MANIFESTS[@]}")
else
  for manifest in "${CRATE_MANIFESTS[@]}"; do
    if [[ "$manifest" == "$START_AT" ]]; then
      start_found=1
    fi

    if ((start_found == 1)); then
      selected_manifests+=("$manifest")
    fi
  done

  ((start_found == 1)) ||
    die "--from manifest is not in CRATE_MANIFESTS: $START_AT"
fi

if ((DRY_RUN == 1)); then
  mode="dry run"
else
  mode="LIVE PUBLISH"
fi

printf 'Repository: %s\n' "$ROOT"
printf 'Registry:   %s\n' "$REGISTRY"
printf 'Mode:       %s\n' "$mode"
printf 'Order:\n'

for manifest in "${selected_manifests[@]}"; do
  printf '  - %s\n' "$manifest"
done

if ((DRY_RUN == 0 && ASSUME_YES == 0)); then
  [[ -t 0 ]] ||
    die "non-interactive live publishing requires --yes"

  printf '\nPublish these crates in this order? [y/N] '
  read -r reply

  case "$reply" in
    y|Y|yes|Yes|YES)
      ;;
    *)
      printf 'Publication cancelled.\n'
      exit 1
      ;;
  esac
fi

print_resume_command() {
  local resume_manifest="$1"

  printf '  %q --from %q' "$0" "$resume_manifest" >&2

  ((DRY_RUN == 0)) ||
    printf ' --dry-run' >&2

  [[ "$REGISTRY" == "crates-io" ]] ||
    printf ' --registry %q' "$REGISTRY" >&2

  ((DELAY_SECONDS == 0)) ||
    printf ' --delay %q' "$DELAY_SECONDS" >&2

  ((ALLOW_DIRTY == 0)) ||
    printf ' --allow-dirty' >&2

  ((USE_LOCKED == 1)) ||
    printf ' --no-locked' >&2

  printf '\n' >&2
}

total=${#selected_manifests[@]}

for ((i = 0; i < total; i++)); do
  manifest="${selected_manifests[$i]}"

  publish_args=(
    publish
    --manifest-path "$manifest"
    --registry "$REGISTRY"
  )

  ((USE_LOCKED == 0)) ||
    publish_args+=(--locked)

  ((ALLOW_DIRTY == 0)) ||
    publish_args+=(--allow-dirty)

  ((DRY_RUN == 0)) ||
    publish_args+=(--dry-run)

  printf '\n[%d/%d] %s: %s\n' \
    "$((i + 1))" \
    "$total" \
    "$mode" \
    "$manifest"

  if ! cargo "${publish_args[@]}"; then
    printf '\nPublication stopped at: %s\n' "$manifest" >&2
    printf 'No later manifest was attempted.\n' >&2
    printf 'Resume after fixing the failure with:\n' >&2

    print_resume_command "$manifest"

    if ((i + 1 < total)); then
      printf '%s\n' \
        'If the registry already contains this version, resume at the next manifest:' \
        >&2

      print_resume_command "${selected_manifests[$((i + 1))]}"
    fi

    exit 1
  fi

  if ((DRY_RUN == 0 && DELAY_SECONDS > 0 && i + 1 < total)); then
    sleep "$DELAY_SECONDS"
  fi
done

printf '\nCompleted %d %s operation(s).\n' "$total" "$mode"
