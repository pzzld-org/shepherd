#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."

hook='.githooks/pre-push'
test -x "$hook"

if rg -q 'GATE=|open-sprint-pr|SHEPHERD_SKIP_GATE' "$hook"; then
  printf 'pre-push must not run a gate, create a PR, or require a bypass\n' >&2
  exit 1
fi

output=$(bash "$hook" </dev/null 2>&1)
grep -Fq 'no local gate or PR automation ran' <<<"$output"
printf 'ok: pre-push is non-blocking and has no network or build side effect\n'
