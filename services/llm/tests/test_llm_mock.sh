#!/usr/bin/env bash
# Gate: complete returns the mock payload verbatim, from file and inline, and
# never touches the claude binary (proved by pointing SHEPHERD_LLM_BIN at a
# command that would fail loudly if invoked).
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
LLM="$HERE/../llm.sh"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

# A binary that, if ever called, makes the test fail unmistakably.
export SHEPHERD_LLM_BIN="$TMP/should-never-run"
printf '#!/bin/sh\necho REAL_CLAUDE_WAS_CALLED >&2; exit 99\n' > "$SHEPHERD_LLM_BIN"
chmod +x "$SHEPHERD_LLM_BIN"

# --- mock from file ---
printf '{"scores":{"x":4}}\n' > "$TMP/mock.json"
out="$(SHEPHERD_LLM_MOCK="$TMP/mock.json" bash "$LLM" complete --prompt='ignored')"
[[ "$out" == '{"scores":{"x":4}}' ]] || { echo "FAIL: file mock payload: got '$out'"; exit 1; }

# --- mock from inline text ---
out="$(SHEPHERD_LLM_MOCK_TEXT='HELLO_MOCK' bash "$LLM" complete < /dev/null)"
[[ "$out" == 'HELLO_MOCK' ]] || { echo "FAIL: inline mock payload: got '$out'"; exit 1; }

# --- mock short-circuits before needing a prompt at all ---
out="$(SHEPHERD_LLM_MOCK="$TMP/mock.json" bash "$LLM" complete < /dev/null)"
[[ "$out" == '{"scores":{"x":4}}' ]] || { echo "FAIL: mock without prompt: got '$out'"; exit 1; }

# --- ping reports mock mode (no binary probe) ---
out="$(SHEPHERD_LLM_MOCK="$TMP/mock.json" bash "$LLM" ping)"
grep -q "MOCK mode active" <<<"$out" || { echo "FAIL: ping mock: got '$out'"; exit 1; }

echo "ok: llm mock"
