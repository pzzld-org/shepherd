#!/usr/bin/env bash
# test_pause_retired.sh — no-residual-dependency proof for Lane F (#70/#53/#58).
#
# Asserts the pause-for-dependency mechanic is fully retired: the files are gone,
# nothing in the active plugin tree references the deleted scripts/doctrine, and
# no agent definition still instructs emitting the PAUSE-FOR-DEPENDENCY halt code.
# (Historical .artifacts/ records + CHANGELOG.md are intentionally NOT scrubbed —
# they are dated design records. native-coordination.md / workflow-compile-down.md
# may name the *concept* as retired, but must not link the deleted file or scripts.)
#
# Exit 0 on pass; exit 1 listing every residual.

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
cd "$ROOT"

fails=0
note() { printf '  %s\n' "$*"; }

# Active plugin dirs (exclude historical .artifacts/, CHANGELOG.md, and this test).
ACTIVE=(agents commands hooks skills)
EXCLUDE='--include=*.md --include=*.sh --include=*.json'
SELF="hooks/tests/test_pause_retired.sh"

scan() { # scan "<regex>" "<human label>" -- searches ACTIVE dirs, drops SELF
  local re="$1" label="$2" hits
  hits=$(grep -rInE "$re" "${ACTIVE[@]}" $EXCLUDE 2>/dev/null | grep -v "^$SELF:" || true)
  if [[ -n "$hits" ]]; then
    note "RESIDUAL ($label):"
    printf '%s\n' "$hits" | sed 's/^/      /'
    fails=$((fails+1))
  fi
}

# 1. The deleted files must not exist.
for f in hooks/scripts/agent_pause_detector.sh \
         skills/context/scripts/cmd_pauses.sh \
         skills/shepherd/doctrines/pause-for-dependency.md; do
  [[ -e "$f" ]] && { note "STILL EXISTS: $f"; fails=$((fails+1)); }
done

# 2. No reference to the deleted scripts anywhere active.
scan 'agent_pause_detector' 'deleted hook agent_pause_detector.sh'
scan 'cmd_pauses'           'deleted script cmd_pauses.sh'
scan 'shctx pauses'         'deleted CLI verb `shctx pauses`'

# 3. No dangling link to the deleted doctrine file.
scan 'pause-for-dependency\.md' 'deleted doctrine pause-for-dependency.md'

# 4. No agent definition still instructs emitting the retired halt code.
agenthits=$(grep -rInE 'Halt code:[[:space:]]*PAUSE-FOR-DEPENDENCY|emit[[:space:]]+.?PAUSE-FOR-DEPENDENCY' \
  agents skills/shepherd/agents --include=*.md 2>/dev/null || true)
if [[ -n "$agenthits" ]]; then
  note "RESIDUAL (agent still emits PAUSE-FOR-DEPENDENCY):"
  printf '%s\n' "$agenthits" | sed 's/^/      /'
  fails=$((fails+1))
fi

# 5. hooks.json must not register the deleted hook; shctx must not route `pauses`.
grep -q 'agent_pause_detector' hooks/hooks.json 2>/dev/null && { note "hooks.json still registers agent_pause_detector"; fails=$((fails+1)); }
grep -qE '\|pauses\||pauses\)' skills/context/scripts/shctx 2>/dev/null && { note "shctx still routes 'pauses'"; fails=$((fails+1)); }

if [[ "$fails" -gt 0 ]]; then
  printf 'test_pause_retired: %d residual(s) — pause-for-dependency not fully retired (#70)\n' "$fails"
  exit 1
fi
printf 'test_pause_retired: OK — pause-for-dependency fully retired; nothing depends on it (#70/#53/#58)\n'
exit 0
