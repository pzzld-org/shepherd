#!/usr/bin/env bash
# Regression harness for the legacy-command disposition and public CLI
# authority checks. The gate itself supplies deliberate broken fixtures.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GATE="$ROOT/scripts/check-cli-authority.py"

python3 "$GATE" --self-test
python3 "$GATE"

# D4 retired the repo-tracked compatibility launcher outright rather than
# patch its resolution bug (it derived its search root from the unresolved
# BASH_SOURCE[0], so a symlinked install silently exited 127 instead of
# falling through PATH). The GATE run above already asserts this at the
# manifest-authority level; assert it again here at the filesystem level,
# matching the retired-root checks immediately below, so the harness catches
# a regression even if the gate script itself weakens.
test ! -e "$ROOT/bin/shepherd"
test ! -e "$ROOT/scripts/tests/test_shepherd_native_launcher.sh"

test ! -e "$ROOT/services/cli"
test ! -e "$ROOT/skills/context/scripts"
if rg -n '"authority"[[:space:]]*:[[:space:]]*"python-legacy"|unsupported_pending_parity' \
  "$ROOT/conformance/cases" "$ROOT/conformance/legacy-command-disposition.json"; then
  printf '%s\n' 'legacy CLI implementation or pending route disposition remains' >&2
  exit 1
fi

test ! -e "$ROOT/bin/shepherd-venv-ensure"
test ! -e "$ROOT/hooks/scripts/session_venv.sh"
test ! -e "$ROOT/hooks/tests/test_cli_venv_selfheal.sh"

# D4 retired $ROOT/bin outright (asserted above). Naming it here anyway made
# ripgrep exit 2 -- "path does not exist" -- and because the call sits inside
# an `if`, `set -e` is suppressed and rc=2 takes the same branch as rc=1
# ("nothing matched"). This sweep reported CLEAN by erroring out, for every
# run since the launcher was retired. Sweep the paths that exist, and fail
# loudly on any rc that is neither 0 (matched) nor 1 (clean).
legacy_paths=("$ROOT/hooks/hooks.json" "$ROOT/hooks/scripts")
for legacy_path in "${legacy_paths[@]}"; do
  test -e "$legacy_path" || {
    printf 'FAIL: legacy-bootstrap sweep names a path that does not exist: %s\n' "$legacy_path" >&2
    exit 1
  }
done
# `rg ...; rc=$?` cannot be used under `set -e`: rc=1 (clean sweep) is a
# FAILING command, so the shell exits before the rc is ever inspected. The
# `|| rc=$?` form is the one that survives, because a failing left-hand side
# of `||` is exempt from `set -e`.
sweep_rc=0
rg -n '(session_venv|shepherd-venv-ensure|poetry)' "${legacy_paths[@]}" || sweep_rc=$?
case "$sweep_rc" in
  0) printf '%s\n' 'legacy interpreter bootstrap remains in an active launcher path' >&2; exit 1 ;;
  1) : ;; # clean
  *) printf 'FAIL: legacy-bootstrap sweep could not run (rg rc=%s)\n' "$sweep_rc" >&2; exit 1 ;;
esac

transport="$ROOT/packages/component-runtime/src/native-transport.mjs"
# The dispatch lifecycle used to live in claude_hook.rs and now lives in the
# harness-NEUTRAL native_hook.rs, which Claude, Codex, and Pi all route
# through; claude_hook.rs is a thin delegator. This gate still asserted the
# three lifecycle symbols against claude_hook.rs and had been failing on that
# refactor -- unnoticed, because nothing ran it. Assert each symbol against
# the file that owns it, and assert the delegation separately, so moving the
# lifecycle again fails here instead of silently.
native_hook="$ROOT/crates/cli/src/cmd/native_hook.rs"
claude_hook="$ROOT/crates/cli/src/cmd/claude_hook.rs"
test -f "$transport"
test -f "$native_hook"
test -f "$claude_hook"
rg -q 'run_native_hook' "$claude_hook" || {
  rc=$?
  printf 'FAIL: claude_hook.rs must delegate to run_native_hook, not reimplement the lifecycle (rg rc=%s)\n' "$rc" >&2
  exit 1
}
# Every registered hook resolves to one of exactly two authorities, and no
# third. This assertion previously required the native shape for EVERY hook,
# which was true only until the seven carrier hook scripts were restored; it
# has been failing since, and nothing ran it to notice. State the real rule
# and name the count, so a manifest that registers zero hooks cannot pass by
# vacuous truth.
python3 - "$ROOT/hooks/hooks.json" "$ROOT" <<'PY'
import json
import pathlib
import sys

manifest = json.loads(pathlib.Path(sys.argv[1]).read_text())
root = pathlib.Path(sys.argv[2])
NATIVE = {"type": "command", "command": "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/shepherd_native.sh", "args": ["claude-hook"]}
PREFIX = "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/"

hooks = [
    hook
    for groups in manifest["hooks"].values()
    for group in groups
    for hook in group["hooks"]
]
if not hooks:
    sys.exit("FAIL: hooks.json registers no hooks at all")

native, scripted, bad = 0, 0, []
for hook in hooks:
    if hook == NATIVE:
        native += 1
        continue
    command = hook.get("command", "")
    if hook.get("type") == "command" and command.startswith(PREFIX):
        # A registration pointing at a script that does not exist is the exact
        # defect that shipped dead for four releases. Resolve it on disk.
        target = root / "hooks" / "scripts" / command[len(PREFIX):]
        if not target.is_file():
            bad.append(f"{command} -> missing {target}")
        else:
            scripted += 1
        continue
    bad.append(json.dumps(hook, sort_keys=True))

if bad:
    sys.exit("FAIL: hook registrations neither native-dispatch nor a resolvable "
             "carrier script:\n  " + "\n  ".join(bad))
print(f"hooks.json: {len(hooks)} registrations checked "
      f"(native={native}, carrier-script={scripted}, unresolvable=0)")
PY
rg -q 'plan_lifecycle' "$native_hook" || { rc=$?; printf 'FAIL: native_hook.rs must reference plan_lifecycle (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -q 'DispatchService::with_context' "$native_hook" || { rc=$?; printf 'FAIL: native_hook.rs must reference DispatchService::with_context (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -q 'GuardValue::from' "$native_hook" || { rc=$?; printf 'FAIL: native_hook.rs must reference GuardValue::from (rg rc=%s)\n' "$rc" >&2; exit 1; }

# Published adapters resolve one native CLI contract: an explicit override
# wins, then SHEPHERD_NATIVE_BIN, PATH, and standard per-user install roots.
# The bare `shepherd` name remains the final host-resolution fallback, and no
# source-checkout repository path may enter the published lifecycle.
rg -q 'SHEPHERD_NATIVE_BIN' "$transport" || { rc=$?; printf 'FAIL: native-transport.mjs must honor SHEPHERD_NATIVE_BIN (rg rc=%s)\n' "$rc" >&2; exit 1; }
rg -q 'return[[:space:]]+"shepherd"' "$transport" || { rc=$?; printf 'FAIL: native-transport.mjs must retain the bare shepherd final fallback (rg rc=%s)\n' "$rc" >&2; exit 1; }
if rg -n 'repositoryRoot|join\([^)]*bin[^)]*shepherd|/bin/shepherd' "$transport"; then
  printf '%s\n' 'published native transport contains a checkout-specific CLI path' >&2
  exit 1
fi
node --test "$ROOT/packages/component-runtime/test/native-transport.test.mjs"

printf '%s\n' 'check-cli-authority: SessionStart retains native dispatch binding without a legacy runtime bootstrap'
printf '%s\n' 'test_cli_authority_gate: all checks passed'
