#!/usr/bin/env bash
# hooks/tests/test_pi_manifest_drift.sh — Pi manifest/extension parity gate.
#
# packages/harness-pi/shepherd.pi.json's "hooks" block declares the events Pi
# handles; packages/harness-pi/src/extension.mjs is the in-process JS that
# actually implements them (pi.on(event, handler) callbacks registered once
# at load, not a per-event exec of the shepherd binary — contrast
# hooks/hooks.json's command/args exec form). This test is the tripwire that
# keeps the declaration and the implementation from drifting apart, in either
# direction:
#   1. every event the manifest declares has a matching pi.on(...) or
#      pi.events.on(...) handler
#   2. every public Pi handler in extension.mjs is declared in the manifest
#      (catches an orphaned handler)
#   3. the manifest's guarded-tool list matches GUARDED_TOOL_NAMES exactly,
#      in both directions
#
# Accepts SHEPHERD_PI_MANIFEST / SHEPHERD_PI_EXTENSION overrides (mirrors the
# SHEPHERD_LINT_AGENTS_DIR pattern at hooks/tests/lint_agent_capabilities.sh)
# so falsification runs against temp copies without ever mutating the
# tracked files.
#
# bash 3.2 safe: no ${var,,}, no mapfile, no declare -A.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"

MANIFEST="${SHEPHERD_PI_MANIFEST:-$REPO_ROOT/packages/harness-pi/shepherd.pi.json}"
EXTENSION="${SHEPHERD_PI_EXTENSION:-$REPO_ROOT/packages/harness-pi/src/extension.mjs}"

checks=0
fails=0
pass() { checks=$((checks + 1)); printf '  PASS  %s\n' "$1"; }
fail() { checks=$((checks + 1)); printf '  FAIL  %s -- %s\n' "$1" "$2" >&2; fails=$((fails + 1)); }

finish() {
  printf '%s/%s passed\n' "$((checks - fails))" "$checks"
  if [[ "$fails" -eq 0 ]]; then
    printf 'PASS: test_pi_manifest_drift\n'
    exit 0
  fi
  printf 'FAIL: test_pi_manifest_drift (%d)\n' "$fails" >&2
  exit 1
}

if ! command -v jq >/dev/null 2>&1; then
  printf 'SKIP: jq is required by test_pi_manifest_drift\n'
  exit 0
fi

if [[ ! -f "$MANIFEST" ]]; then
  fail "manifest file exists" "not found: $MANIFEST"
  finish
fi
if [[ ! -f "$EXTENSION" ]]; then
  fail "extension file exists" "not found: $EXTENSION"
  finish
fi

tmp="$(mktemp -d -t shep-pi-manifest-drift.XXXXXX)"
trap 'rm -rf "$tmp"' EXIT

# --- manifest-declared events -----------------------------------------------
if ! manifest_events_raw="$(jq -r 'if has("hooks") then (.hooks | keys[]) else empty end' "$MANIFEST" 2>"$tmp/jq_err")"; then
  fail "manifest hooks block parses as JSON" "$(cat "$tmp/jq_err")"
  finish
fi
printf '%s\n' "$manifest_events_raw" | sed '/^$/d' | sort -u > "$tmp/manifest_events"

if [[ -s "$tmp/manifest_events" ]]; then
  pass "manifest declares a non-empty hooks block"
else
  fail "manifest declares a non-empty hooks block" "no keys under .hooks in $MANIFEST"
fi

# --- extension.mjs public handlers ------------------------------------------
{
  grep -oE 'pi\.on\("[^"]+"' "$EXTENSION" 2>/dev/null \
    | sed -E 's/^pi\.on\("//; s/"$//'
  grep -oE 'pi\.events\.on\("[^"]+"' "$EXTENSION" 2>/dev/null \
    | sed -E 's/^pi\.events\.on\("//; s/"$//'
} | sort -u > "$tmp/extension_events"

if [[ -s "$tmp/extension_events" ]]; then
  pass "extension.mjs registers public Pi handlers"
else
  fail "extension.mjs registers public Pi handlers" "no pi.on(...) or pi.events.on(...) calls found in $EXTENSION"
fi

# 1. every manifest-declared event has a matching public handler
missing_handlers="$(comm -23 "$tmp/manifest_events" "$tmp/extension_events")"
if [[ -z "$missing_handlers" ]]; then
  pass "every manifest-declared event has a public Pi handler"
else
  fail "every manifest-declared event has a public Pi handler" \
    "declared in manifest but no public handler in extension.mjs: $(printf '%s' "$missing_handlers" | tr '\n' ' ')"
fi

# 2. every public handler is declared in the manifest (catches an orphan)
orphaned_handlers="$(comm -13 "$tmp/manifest_events" "$tmp/extension_events")"
if [[ -z "$orphaned_handlers" ]]; then
  pass "every public Pi handler is declared in the manifest"
else
  fail "every public Pi handler is declared in the manifest" \
    "public handler exists but is undeclared in manifest: $(printf '%s' "$orphaned_handlers" | tr '\n' ' ')"
fi

# --- guarded tool set --------------------------------------------------------
jq -r '[.hooks[]?.guardedTools[]?] | unique | .[]?' "$MANIFEST" 2>/dev/null | sort -u > "$tmp/manifest_tools"

guard_line="$(grep -E 'GUARDED_TOOL_NAMES[[:space:]]*=' "$EXTENSION" || true)"
if [[ -n "$guard_line" ]]; then
  pass "extension.mjs declares GUARDED_TOOL_NAMES"
  printf '%s\n' "$guard_line" \
    | grep -oE '"[^"]+"' \
    | tr -d '"' \
    | sort -u > "$tmp/extension_tools"

  extra_in_manifest="$(comm -23 "$tmp/manifest_tools" "$tmp/extension_tools")"
  extra_in_extension="$(comm -13 "$tmp/manifest_tools" "$tmp/extension_tools")"

  if [[ -z "$extra_in_manifest" && -z "$extra_in_extension" ]]; then
    pass "manifest guarded-tool list matches GUARDED_TOOL_NAMES exactly"
  else
    detail=""
    if [[ -n "$extra_in_manifest" ]]; then
      detail="manifest declares tool(s) GUARDED_TOOL_NAMES does not: $(printf '%s' "$extra_in_manifest" | tr '\n' ' ')"
    fi
    if [[ -n "$extra_in_extension" ]]; then
      if [[ -n "$detail" ]]; then
        detail="$detail; "
      fi
      detail="${detail}GUARDED_TOOL_NAMES has tool(s) the manifest does not declare: $(printf '%s' "$extra_in_extension" | tr '\n' ' ')"
    fi
    fail "manifest guarded-tool list matches GUARDED_TOOL_NAMES exactly" "$detail"
  fi
else
  fail "extension.mjs declares GUARDED_TOOL_NAMES" "no GUARDED_TOOL_NAMES assignment found in $EXTENSION"
fi

finish
