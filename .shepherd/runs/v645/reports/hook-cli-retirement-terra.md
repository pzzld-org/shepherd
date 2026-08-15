# v6.4.5 hook CLI retirement and self-review

## Outcome

The source hook registry has one public CLI contract: installed native
`shepherd`. It contains no `shctx` launcher, no
`services/cli` path, no plugin-local `bin/shepherd` shell
launcher, no Python fallback, and no `type: agent` policy hook.

The retired launcher installer and its test are absent:
`scripts/install-shctx-launcher.sh` and
`scripts/tests/test_shctx_launcher.sh`.

## Retired source authority

The following legacy policy/state scripts are both deleted and asserted
unregistered by `test_legacy_policy_retirement.sh`:

~~~text
session_open.sh                 focus_rehydrate.sh
bash_guard.sh                   teammate_git_guard.sh
worktree_teardown_guard.sh      release_trigger_guard.sh
conductor_write_guard.sh        lock_guard.sh
dedup_write_guard.sh            dispatch_guard.sh
teammate_idle.sh                coordinate_drive_guard.sh
deliverable_check.sh            close_finalize_check.sh
user_prompt_submit.sh           teammate_heartbeat.sh
worktree_lifecycle.sh           hotfix_vehicle_guard.sh
workflow_model_guard.sh
~~~

Additional obsolete source/test surface is removed: the legacy dups,
plan-proof, coder-git, agent-invocation, session-venv, tmux-cleanup, and
workflow Python scanner paths, plus their retired hook tests.

This is an intentional semantic retirement, not pretend enforcement. The
unmatched capabilities are no longer registered:

- Session orientation/adaptation and prompt-tier markers.
- Shell parsing for arbitrary Bash, Git custody, lock, dedup, dispatch
  payload/ownership, and worktree teardown.
- Stop-time coordinate, deliverable, close-finalize, heartbeat, idle, and
  lifecycle mutation policies.
- Hotfix cardinality and plan-proof lifecycle policies.
- Raw JavaScript Workflow model parsing. v6.4.5 accepts only a typed Workflow
  dispatch target through the native component; unresolved raw Workflow input
  remains fail-closed under the component guard.

Future Rust/core work must expose a typed command or component contract before
one of these semantics can return. No shell hook claims to enforce any of them.

## Remaining shell behavior

The only shells still registered are thin adapters or telemetry:

- `seed_preflight_check.sh` invokes native seed verification and is
  the sole shell PreToolUse policy adapter.
- Insight, discovery, Bash-post, CwdChanged, and SubagentStop hooks record
  non-blocking evidence under the active
  `.shepherd/runs/<run>/events/...` path.
- PreCompact writes its snapshot under
  `.shepherd/runs/<run>/snapshots/...`. It no longer creates the
  orphaned rehydration marker. Its optional SQLite reads are read-only.

Every retained shell requires an executing strict `run.json` owner
before it writes. It does not recreate retired top-level
`cache`, `logs`, `memory`, `snapshots`,
`tmp`, `insights`, or `discoveries` roots.

## TDD and gate evidence

RED then GREEN:

1. `test_compaction_run_scope.sh` failed because
   `precompact_snapshot.sh` wrote
   `fixtures/rehydrate-pending.<session>`. The source marker and
   fixture creation were removed; the test now passes while retaining the
   run-scoped snapshot assertion.
2. `test_run_scoped_hook_state.sh` failed for each dormant helper
   (`shepherd_mcp_available`, `safe_dispatch_id`, and
   `session_tier_marker`). The unreferenced helpers were removed;
   the test now passes.

Green gates:

~~~text
bash hooks/tests/run.sh
# PASS: 16 adapter regressions

python3 -m py_compile hooks/scripts/hook_authority_inventory.py
python3 hooks/scripts/hook_authority_inventory.py --self-test
python3 hooks/scripts/hook_authority_inventory.py --check
python3 hooks/scripts/hook_authority_inventory.py --strict
# PASS: 3 thin, 6 telemetry, 0 independent, 0 nondeterministic

python3 scripts/check-plugin.py
# PASS: all 8 plugin contract rules hold
~~~

The executable-source scan for retired CLI/config/root patterns returned no
findings.

## Live dogfood condition

The direct read-only command below did **not** reach the native binary in this
already-running session:

~~~text
target/debug/shepherd migrate --layout v5 --scope project --dry-run
~~~

It was intercepted before execution by
`PRIMARY-RELAY-REQUIRED: invoke the exact codex-shepherd-primary sentinel.`
That relay is absent from the current source registry and is covered by the
retirement regression, so this is evidence of an already-loaded legacy
hook/cache. It is not a passing native migration gate and must be rechecked
after the host reloads the released hook registry. No source test or
source-level gate remains blocked.

The physical `.shepherd/logs/hooks/2026-08-15.jsonl` observed in
this live session is zero bytes. Root owns its final removal after all tool
activity because the loaded legacy hook can recreate it. It contains no
recoverable content.
