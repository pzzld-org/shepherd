#!/usr/bin/env bash
# Resolve the operator-installed native Shepherd binary for non-interactive hooks.
set -uo pipefail

if [[ -n "${SHEPHERD_NATIVE_BIN:-}" ]]; then
  exec "$SHEPHERD_NATIVE_BIN" "$@"
fi

resolved="$(command -v shepherd 2>/dev/null || true)"
if [[ -n "$resolved" ]]; then
  exec "$resolved" "$@"
fi

for candidate in \
  "${HOME:-}/.cargo/bin/shepherd" \
  "${HOME:-}/.local/bin/shepherd" \
  "${HOME:-}/bin/shepherd"
do
  if [[ -x "$candidate" ]]; then
    exec "$candidate" "$@"
  fi
done

printf '[shepherd] native shepherd binary not found; set SHEPHERD_NATIVE_BIN or install shepherd in PATH, ~/.cargo/bin, ~/.local/bin, or ~/bin\n' >&2
exit 127
