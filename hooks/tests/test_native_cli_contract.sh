#!/usr/bin/env bash
# Regression contract for the v6.4.5 native CLI hook cutover.
#
# Hooks are host adapters. They may invoke the one installed `shepherd` binary,
# but must not recreate a second `shctx` launcher, prescribe that retired name,
# or shell through the plugin-local compatibility launcher.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fails=0

pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1" >&2; fails=$((fails + 1)); }

expect_executable_absent() {
  local label="$1" pattern="$2" path
  local files=()
  shift 2
  while IFS= read -r path; do
    files+=("$path")
  done < <(find "$@" -type f \( -name '*.sh' -o -name '*.json' \) -print)
  if awk -v needle="$pattern" '
    FNR == 1 { file = FILENAME }
    /^[[:space:]]*#/ { next }
    $0 ~ needle { printf "%s:%d:%s\n", file, FNR, $0; found = 1 }
    END { exit(found ? 0 : 1) }
  ' "${files[@]}" >/dev/null 2>&1; then
    fail "$label"
    awk -v needle="$pattern" '
      /^[[:space:]]*#/ { next }
      $0 ~ needle { printf "%s:%d:%s\n", FILENAME, FNR, $0 }
    ' "${files[@]}" >&2 || true
  else
    pass "$label"
  fi
}

echo "== native hook CLI contract =="

expect_executable_absent \
  "no-retired-shctx-command-or-message-in-executable-hooks" \
  '(shctx[[:space:]]|[[]shctx[]]|shctx[[:space:]]+CLI)' \
  "$ROOT/hooks/scripts" "$ROOT/hooks/hooks.json"
expect_executable_absent \
  "no-plugin-local-bash-launcher-in-hooks" \
  'bash[[:space:]]+.*bin/shepherd' \
  "$ROOT/hooks/scripts" "$ROOT/hooks/hooks.json"
expect_executable_absent \
  "session-start-does-not-install-a-second-cli" \
  'install-shctx-launcher' \
  "$ROOT/hooks/hooks.json"
expect_executable_absent \
  "retired-hooks-are-not-registered" \
  '(coder_git_guard|dups_write_guard|plan_proof_guard|tmux_pane_cleanup|workflow_model_guard)' \
  "$ROOT/hooks/hooks.json"
expect_executable_absent \
  "no-retired-file-based-role-resolution-in-hooks" \
  'current_role' \
  "$ROOT/hooks/scripts"

for command in \
  'dups check --help' \
  'seed --help' \
  'guard eval --help' \
  'plan verify --help' \
  'init --help' \
  'status --help' \
  'doctor --help' \
  'deliverable stalled --help'; do
  if (cd "$ROOT" && cargo run --quiet --locked -p shepherd-cli -- $command >/dev/null 2>&1); then
    pass "native-surface-$command"
  else
    fail "native-surface-$command"
  fi
done

# v6.4.5 deliberately does not statically interpret arbitrary Workflow JS in
# a source-tree shell. The real component/native boundary handles Workflow as
# a typed dispatch request: a script-only payload is unresolved and the Claude
# adapter translates unresolved verdicts to a fail-closed denial; a typed
# target_role reaches the native dispatch predicate normally.
raw_workflow='{"tool_name":"Workflow","role":"shepherd","tool_input":{"script":"const r = await agent(\"x\")"}}'
if raw_out="$(printf '%s' "$raw_workflow" | (cd "$ROOT" && cargo run --quiet --locked -p shepherd-cli -- guard eval) 2>&1)" \
  && printf '%s' "$raw_out" | grep -q '"decision": "unresolved"' \
  && printf '%s' "$raw_out" | grep -q 'cannot determine the dispatch target role'; then
  pass "native-workflow-script-only-unresolved-fail-closed"
else
  fail "native-workflow-script-only-unresolved-fail-closed: ${raw_out:-no output}"
fi

typed_workflow='{"tool_name":"Workflow","role":"shepherd","tool_input":{"target_role":"coder"}}'
if typed_out="$(printf '%s' "$typed_workflow" | (cd "$ROOT" && cargo run --quiet --locked -p shepherd-cli -- guard eval) 2>&1)" \
  && printf '%s' "$typed_out" | grep -q '"decision": "allow"'; then
  pass "native-workflow-typed-target-role-evaluated"
else
  fail "native-workflow-typed-target-role-evaluated: ${typed_out:-no output}"
fi

if [[ "$fails" -eq 0 ]]; then
  printf 'PASS: test_native_cli_contract\n'
  exit 0
fi

printf 'FAIL: test_native_cli_contract (%d)\n' "$fails" >&2
exit 1
