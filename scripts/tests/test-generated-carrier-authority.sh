#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

fail() {
  printf 'generated carrier authority: %s\n' "$*" >&2
  exit 1
}

test -s .shepherd-generated.json || fail 'canonical Claude ownership manifest is missing'
grep -Fq '"target": "claude"' .shepherd-generated.json \
  || fail 'root ownership manifest does not identify the Claude carrier'

# Codex and Pi carrier content is emitted on demand by the Rust compiler.
# Keeping hand-copied generated files inside adapter packages creates a second,
# inevitably stale authority that package tests cannot distinguish from Rust.
for retired in \
  packages/harness-codex/shepherd.codex.toml \
  packages/harness-codex/skills \
  packages/harness-pi/prompts \
  packages/harness-pi/skills; do
  [[ ! -e "$retired" && ! -L "$retired" ]] \
    || fail "adapter contains a duplicate generated carrier: $retired"
done

grep -Fq 'shepherd compile --target codex' packages/harness-codex/README.md \
  || fail 'Codex adapter does not route carrier generation through the native CLI'
grep -Fq 'shepherd compile' packages/harness-pi/README.md \
  || fail 'Pi adapter does not route carrier generation through the native CLI'

printf 'ok: generated carriers have one Rust compiler authority\n'
