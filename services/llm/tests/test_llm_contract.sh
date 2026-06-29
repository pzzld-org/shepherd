#!/usr/bin/env bash
# Gate: arg/usage contract and error paths — no real claude call.
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
LLM="$HERE/../llm.sh"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

# unknown subcommand → exit 2
rc=0; bash "$LLM" frobnicate >/dev/null 2>&1 || rc=$?
[[ "$rc" == 2 ]] || { echo "FAIL: unknown subcommand exit: got $rc"; exit 1; }

# unknown flag → exit 2
rc=0; SHEPHERD_LLM_MOCK_TEXT=x bash "$LLM" complete --bogus >/dev/null 2>&1 || rc=$?
[[ "$rc" == 2 ]] || { echo "FAIL: unknown flag exit: got $rc"; exit 1; }

# non-integer timeout → exit 2 (validated before any call)
rc=0; SHEPHERD_LLM_MOCK_TEXT=x bash "$LLM" complete --timeout=abc >/dev/null 2>&1 || rc=$?
[[ "$rc" == 2 ]] || { echo "FAIL: bad timeout exit: got $rc"; exit 1; }

# help works and names the contract
out="$(bash "$LLM" help)"
grep -q "route a model call through the LOCAL Claude Code" <<<"$out" || { echo "FAIL: help text"; exit 1; }

# missing claude binary on a real (non-mock) call → exit 4, not a hang
rc=0; SHEPHERD_LLM_BIN="$TMP/nope" bash "$LLM" complete --prompt='hi' --timeout=5 >/dev/null 2>&1 || rc=$?
[[ "$rc" == 4 ]] || { echo "FAIL: missing-binary exit: got $rc"; exit 1; }

# missing --prompt-file → exit 2
rc=0; bash "$LLM" complete --prompt-file="$TMP/absent" >/dev/null 2>&1 || rc=$?
[[ "$rc" == 2 ]] || { echo "FAIL: missing prompt-file exit: got $rc"; exit 1; }

echo "ok: llm contract"
