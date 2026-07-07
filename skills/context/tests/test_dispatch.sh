#!/usr/bin/env bash
source "$(dirname "$0")/_setup.sh"
source "$(dirname "$0")/_assert.sh"
SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"

# `shctx help` exits 0 and lists every subcommand.
out=$("$SHCTX" help)
for sub in init status refresh query inject mem lock lint migrate export; do
  assert_contains "help.$sub" "$out" "$sub"
done

# Unknown subcommand exits non-zero.
if "$SHCTX" notarealthing 2>/dev/null; then
  echo "FAIL: unknown subcommand should exit non-zero" >&2; exit 1
fi
