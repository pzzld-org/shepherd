#!/usr/bin/env bash
# A remediation string must name a command the operator can actually run.
#
# v6.5.0 shipped five user-facing messages that told the operator to run a
# bare `shepherd init`. That command is gated behind `--confirm`, so every one
# of them exits 2 and scaffolds nothing: the messages whose job is unblocking
# a cold project sent the operator in a circle. `shepherd doctor` carried the
# correct wording the whole time, which makes this drift rather than an
# unknown, and drift is what a lint is for.
#
# The scan itself lives in hooks/scripts/remediation_flag_lint.py (deriving
# the gated-subcommand map from the CLI's own refusal text). This file proves
# two things about it: the repo is clean, and the lint can still see a real
# regression.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LINT="$ROOT/hooks/scripts/remediation_flag_lint.py"
fails=0
checks=0

fail() { checks=$((checks + 1)); printf '  FAIL  %s\n' "$1" >&2; fails=$((fails + 1)); }
pass() { checks=$((checks + 1)); printf '  PASS  %s\n' "$1"; }

if [[ ! -f "$LINT" ]]; then
  fail "lint script is missing: $LINT"
  printf '%s/%s passed\n' "$((checks - fails))" "$checks"
  exit "$fails"
fi

if summary="$(python3 "$LINT" --root "$ROOT" 2>&1)"; then
  pass "every remediation naming a gated subcommand carries its authorization flag (${summary})"
else
  fail "every remediation naming a gated subcommand carries its authorization flag: ${summary}"
fi

# Falsification. A lint nobody has watched fail is a lint nobody knows works,
# so rebuild the exact v6.5.0 defect in a fixture and require a non-zero exit.
FIXTURE="$(mktemp -d)"
trap 'rm -rf "$FIXTURE"' EXIT
mkdir -p "$FIXTURE/crates/cli/src/cmd"

cat >"$FIXTURE/crates/cli/src/cmd/gate.rs" <<'GATE'
fn gate(confirm: bool) -> Result<(), CliError> {
    if !confirm {
        return Err(CliError::message_with_code(
            "init is mutating; re-run with --confirm",
            2,
        ));
    }
    Ok(())
}
GATE

cat >"$FIXTURE/crates/cli/src/cmd/regression.rs" <<'REGRESSION'
fn not_found_message(path: &Path) -> String {
    format!("project not scaffolded — run `shepherd init`: {}", path.display())
}
REGRESSION

if python3 "$LINT" --root "$FIXTURE" >/dev/null 2>&1; then
  fail "falsification: the reintroduced v6.5.0 wording was NOT detected (the scan is blind)"
else
  pass "falsification: the reintroduced v6.5.0 wording is detected"
fi

# The gate map must come from the refusal text, not a hard-coded list. A
# fixture with a remediation but no refusal text has nothing to derive from,
# and must fail loudly rather than pass by finding zero gates to check.
EMPTY="$(mktemp -d)"
trap 'rm -rf "$FIXTURE" "$EMPTY"' EXIT
mkdir -p "$EMPTY/crates/cli/src/cmd"
cat >"$EMPTY/crates/cli/src/cmd/regression.rs" <<'ORPHAN'
fn message() -> String {
    format!("project not scaffolded — run `shepherd init`")
}
ORPHAN

if python3 "$LINT" --root "$EMPTY" >/dev/null 2>&1; then
  fail "gate-map drift: deriving zero gated subcommands reported success"
else
  pass "gate-map drift: deriving zero gated subcommands fails loudly"
fi

printf '%s/%s passed\n' "$((checks - fails))" "$checks"
exit "$fails"
