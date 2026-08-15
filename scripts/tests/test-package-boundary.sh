#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
probe="$repo_root/packages/scripts/check-package-boundary.mjs"

if [[ ! -f "$probe" ]]; then
  printf 'FAIL package boundary probe is missing: %s\n' "$probe"
  exit 1
fi

node "$probe" --self-test
printf 'ok: package boundary probe self-test\n'

# The mutation/self-test proves the checker can fail. This second invocation is
# the release assertion: it inspects every publishable package, runs the real
# retired-authority scan, and asks npm for each actual packlist.
node "$probe"
printf 'ok: actual package boundary audit\n'
