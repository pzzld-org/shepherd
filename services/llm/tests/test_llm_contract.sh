#!/usr/bin/env bash
# Gate: arg/usage contract and error paths — no real claude call.
set -eu -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
LLM="$HERE/../llm.sh"
TMP="$(mktemp -d)"
tree_child=""
cleanup() {
  if [[ -n "$tree_child" ]] && kill -0 "$tree_child" 2>/dev/null; then
    kill -KILL "$tree_child" 2>/dev/null || true
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT

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

# A successful local completion must cancel its timeout watchdog immediately.
# Regression: the watchdog's `sleep` inherited the command-substitution pipe,
# so a fast completion still blocked for the full configured timeout.
FAKE="$TMP/fake-claude"
printf '%s\n' '#!/usr/bin/env bash' 'cat >/dev/null' 'printf '\''{"scores":{}}\n'\''' >"$FAKE"
chmod +x "$FAKE"
started=$SECONDS
out="$(SHEPHERD_LLM_BIN="$FAKE" bash "$LLM" complete --prompt='hi' --timeout=2)"
elapsed=$((SECONDS - started))
[[ "$out" == '{"scores":{}}' ]] || { echo "FAIL: fake completion output: $out"; exit 1; }
(( elapsed < 2 )) || { echo "FAIL: successful completion waited ${elapsed}s for its watchdog"; exit 1; }

# A blocking local process must return the documented timeout status promptly.
BLOCKING="$TMP/blocking-claude"
printf '%s\n' '#!/usr/bin/env bash' 'exec sleep 30' >"$BLOCKING"
chmod +x "$BLOCKING"
started=$SECONDS
rc=0
SHEPHERD_LLM_BIN="$BLOCKING" bash "$LLM" complete --prompt='hi' --timeout=0 \
  >"$TMP/blocking.out" 2>"$TMP/blocking.err" || rc=$?
elapsed=$((SECONDS - started))
[[ "$rc" == 3 ]] || { echo "FAIL: timeout exit: got $rc"; exit 1; }
(( elapsed < 2 )) || { echo "FAIL: timeout was not bounded: ${elapsed}s"; exit 1; }
grep -q 'completion timed out after 0s' "$TMP/blocking.err" || { echo "FAIL: timeout diagnostic"; exit 1; }

# Timeout owns the whole local-Claude process tree, not only the wrapper PID.
TREE="$TMP/tree-claude"
# shellcheck disable=SC2016 # fixture lines must expand in the child shell
printf '%s\n' \
  '#!/usr/bin/env bash' \
  'sleep 30 &' \
  'printf '\''%s\n'\'' "$!" >"${SHEPHERD_LLM_TEST_CHILD_PID_FILE:?}"' \
  'wait' >"$TREE"
chmod +x "$TREE"
started=$SECONDS
rc=0
SHEPHERD_LLM_TEST_CHILD_PID_FILE="$TMP/tree-child.pid" \
  SHEPHERD_LLM_BIN="$TREE" \
  bash "$LLM" complete --prompt='hi' --timeout=1 \
  >"$TMP/tree.out" 2>"$TMP/tree.err" || rc=$?
elapsed=$((SECONDS - started))
[[ "$rc" == 3 ]] || { echo "FAIL: tree timeout exit: got $rc"; exit 1; }
(( elapsed < 3 )) || { echo "FAIL: tree timeout was not bounded: ${elapsed}s"; exit 1; }
[[ -s "$TMP/tree-child.pid" ]] || { echo "FAIL: tree child PID was not recorded"; exit 1; }
tree_child="$(<"$TMP/tree-child.pid")"
if kill -0 "$tree_child" 2>/dev/null; then
  echo "FAIL: timed-out completion left child PID $tree_child alive"
  exit 1
fi
tree_child=""

echo "ok: llm contract"
