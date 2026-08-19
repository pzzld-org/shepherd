#!/usr/bin/env bash
# The request the JS transport emits must be ACCEPTED by the real native CLI.
#
# WHY THIS EXISTS.
#
# Every dispatch request the component-backed transport produced was rejected by
# `shepherd dispatch` -- bind-root, start, resolve, stop and resume alike --
# because `planToNativeDispatch` never stamped the wire envelope. Each request
# type in crates/core/src/dispatch/portable.rs declares `pub schema: String` and
# is `#[serde(deny_unknown_fields)]`, and crates/cli/src/dispatch_service.rs
# validates it against exactly one constant. The WIT record deliberately omits
# it (the component owns semantics, the transport owns framing), and nothing
# filled the gap.
#
# The Pi adapter therefore could not bind a session and had a non-functional
# guard. It went unnoticed because the extension was never loaded at all --
# `@pzzld/pi-shepherd` shipped with no `pi` key, so none of this code ran.
#
# What existed and did not catch it: packages/component-runtime/test/
# native-transport.test.mjs asserts only how the BINARY NAME is resolved
# (SHEPHERD_NATIVE_BIN override, PATH fallback). Nothing ever fed a real request
# to a real CLI and looked at the answer. Two green tests, zero coverage of the
# thing that was broken.
#
# THE ASSERTION. For each operation, the CLI must NOT reject the request as
# malformed or schema-mismatched. It may legitimately refuse for a business
# reason -- "no executing shepherd run exists" is the expected answer in a
# scratch project -- and that is a PASS here: the wire contract held and the
# request reached the logic behind it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

fails=0
checks=0
pass() { checks=$((checks + 1)); printf '  PASS  %s\n' "$1"; }
fail() { checks=$((checks + 1)); printf '  FAIL  %s\n' "$1" >&2; fails=$((fails + 1)); }

SHEPHERD_BIN="${SHEPHERD_NATIVE_BIN:-}"
if [[ -z "$SHEPHERD_BIN" ]]; then
  for candidate in "$ROOT/target/debug/shepherd" "$ROOT/target/release/shepherd"; do
    [[ -x "$candidate" ]] && SHEPHERD_BIN="$candidate" && break
  done
fi
if [[ -z "$SHEPHERD_BIN" ]]; then
  SHEPHERD_BIN="$(command -v shepherd || true)"
fi
if [[ -z "$SHEPHERD_BIN" ]]; then
  # A stated skip, never a silent pass: without a binary this proves nothing.
  printf '  SKIP  no shepherd binary (build it or set SHEPHERD_NATIVE_BIN)\n'
  printf '0/0 passed (skipped)\n'
  exit 0
fi

# The wire envelope, read from the Rust constant rather than duplicated here.
# A literal in this file would be a second source of truth that drifts exactly
# like the one this gate exists to catch.
EXPECTED_SCHEMA="$(rg -o 'const REQUEST_SCHEMA: &str = "([^"]+)"' -r '$1' \
  "$ROOT/crates/cli/src/dispatch_service.rs" | head -1)"
if [[ -z "$EXPECTED_SCHEMA" ]]; then
  fail "could not read REQUEST_SCHEMA from crates/cli/src/dispatch_service.rs"
  printf '%s/%s passed\n' "$((checks - fails))" "$checks"
  exit "$fails"
fi

# ...and the JS side must agree with it, statically, before anything runs.
JS_SCHEMA="$(rg -o 'DISPATCH_REQUEST_SCHEMA = "([^"]+)"' -r '$1' \
  "$ROOT/packages/component-runtime/src/index.mjs" | head -1)"
if [[ "$JS_SCHEMA" == "$EXPECTED_SCHEMA" ]]; then
  pass "transport and CLI agree on the wire schema ($EXPECTED_SCHEMA)"
else
  fail "wire schema disagreement: transport=${JS_SCHEMA:-<none>} cli=$EXPECTED_SCHEMA"
fi

# A scratch git repository, so the CLI gets past repository resolution and
# actually parses the request. Nothing here mutates the real project.
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
git -C "$scratch" init --quiet
git -C "$scratch" commit --quiet --allow-empty -m init
# SCAFFOLD IT. Without `.shepherd/project.json` the CLI refuses at the
# project-scaffold check BEFORE it ever reads stdin, so every probe below would
# "pass" without the request being parsed at all -- a gate that proves nothing
# while reporting green. The first draft of this file did exactly that.
if ! (cd "$scratch" && "$SHEPHERD_BIN" init --confirm >/dev/null 2>&1); then
  fail "could not scaffold the scratch project; probes would not reach JSON parsing"
  printf '%s/%s passed\n' "$((checks - fails))" "$checks"
  exit "$fails"
fi
# Prove the precondition actually holds rather than assuming init succeeded.
if [[ ! -f "$scratch/.shepherd/project.json" ]]; then
  fail "scratch project reports scaffolded but .shepherd/project.json is absent"
  printf '%s/%s passed\n' "$((checks - fails))" "$checks"
  exit "$fails"
fi

# One representative request per operation, each carrying the envelope the
# transport now stamps.
probe() { # probe <operation> <json>
  local operation="$1" request="$2" output rc
  set +e
  output="$(cd "$scratch" && printf '%s\n' "$request" | "$SHEPHERD_BIN" dispatch "$operation" 2>&1)"
  rc=$?
  set -e
  # These two are wire-contract failures and must never happen.
  if grep -q 'must be one valid RFC 8259 JSON value' <<<"$output"; then
    fail "$operation: CLI rejected the transport's request as malformed JSON"
    return
  fi
  if grep -qE 'does not match the dispatch schema|unsupported schema|unknown field|missing field' <<<"$output"; then
    fail "$operation: schema mismatch -- ${output}"
    return
  fi
  if grep -q 'project not scaffolded' <<<"$output"; then
    fail "$operation: CLI stopped at the scaffold check, so the request was never parsed"
    return
  fi
  pass "$operation: request accepted by the CLI (rc=$rc, reached business logic)"
}

probe bind-root "{\"schema\":\"$EXPECTED_SCHEMA\",\"harness\":\"pi\",\"session_id\":\"wire-probe\",\"role_carrier\":\"shepherd:shepherd\",\"mode\":\"execution\",\"lease_ms\":86400000}"
probe resolve "{\"schema\":\"$EXPECTED_SCHEMA\",\"harness\":\"pi\",\"session_id\":\"wire-probe\",\"tool_call_id\":\"probe-1\",\"tool_name\":\"write\"}"

# FALSIFICATION. Strip the envelope and the CLI must refuse -- otherwise this
# gate would pass against a transport that stopped stamping it, which is the
# entire defect.
stripped="{\"harness\":\"pi\",\"session_id\":\"wire-probe\",\"role_carrier\":\"shepherd:shepherd\",\"mode\":\"execution\",\"lease_ms\":86400000}"
set +e
stripped_output="$(cd "$scratch" && printf '%s\n' "$stripped" | "$SHEPHERD_BIN" dispatch bind-root 2>&1)"
set -e
if grep -qE 'does not match the dispatch schema|missing field' <<<"$stripped_output"; then
  pass "falsification: a request without the wire envelope is refused, and says why"
else
  fail "falsification: a request WITHOUT the schema envelope was not refused -- got: ${stripped_output}"
fi

# The CLI must also tell these two cases apart. Collapsing them is what made a
# missing field read as a syntax error and cost a day of looking for a JSON bug.
set +e
garbage_output="$(cd "$scratch" && printf 'not json at all\n' | "$SHEPHERD_BIN" dispatch bind-root 2>&1)"
set -e
if grep -q 'must be one valid RFC 8259 JSON value' <<<"$garbage_output"; then
  pass "genuinely malformed input is still reported as malformed JSON"
else
  fail "malformed input no longer reports a JSON syntax error: ${garbage_output}"
fi

printf '%s/%s passed\n' "$((checks - fails))" "$checks"
exit "$fails"
