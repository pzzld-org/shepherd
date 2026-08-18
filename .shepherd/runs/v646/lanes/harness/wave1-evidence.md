# Wave 1 evidence — harness lane, run v646

Base `1f2a398`. Every result below was produced by the CONDUCTOR against the worktree,
not taken from a coder self-report. All four coders returned empty or junk final
messages ("(no action needed)", "(no action taken)", ".", "(repeat of prior message)")
while having done correct work. Trusting those reports would have scored wave 1 as a
total failure. Verification against ground truth is the only reason this is known good.

## W1.1 — D6 role prose scope tokens

Files: `content/roles/engineer.md`, `content/roles/planter.md`. `agents/` untouched.
Status: LANDED, not yet verifiable on the tracked tree, because `agents/` is
intentionally stale (root owns regeneration). The real-tree lint still reports the 4
scope-bound violations; that is expected and resolves when root regenerates.

## W1.2 — D5 conductor lint re-point

File: `hooks/tests/lint_agent_capabilities.sh`.

Violations 5 -> 4 (conductor cleared). No regression in the gate it contradicted:

    $ bash hooks/tests/test_legacy_policy_retirement.sh | grep conductor_write_guard
      PASS  conductor_write_guard.sh is unregistered
      PASS  conductor_write_guard.sh source is deleted

Added `HOOKS_JSON="${SHEPHERD_LINT_HOOKS_JSON:-$REPO_ROOT/hooks/hooks.json}"` (line 47)
mirroring the `SHEPHERD_LINT_AGENTS_DIR` pattern at line 46. This resolved a real
wave-1 disjointness violation: the planned falsification required temporarily editing
`hooks/hooks.json`, a file W1.3 owns and rewrites concurrently. The override makes the
gate falsifiable without touching a file this step does not own.

FAIL-ON-PURPOSE (strip `Write` from the matcher in a temp manifest copy):

    $ SHEPHERD_LINT_HOOKS_JSON=/tmp/.../no-write.json bash hooks/tests/lint_agent_capabilities.sh
      FAIL conductor: no Edit/Write/NotebookEdit/MultiEdit grant is claimed (checked
      above) but hooks.json has no PreToolUse matcher covering both 'Write' and 'Edit'
      as exact tokens — defense-in-depth missing
    lint_agent_capabilities: 5 violation(s)

Tracked `hooks/hooks.json` unmodified by this step.

## W1.3 — D2+D3 re-register seven hooks

Files: `hooks/hooks.json`, `hooks/scripts/hook_authority_inventory.py`.

11 registrations. The 4 native `shepherd claude-hook` adapters preserved exactly;
7 shell hooks restored on their original events. Machine-checked hard rule:

    OK: no native registration on CwdChanged/PreCompact/PostToolUse

(`crates/core/src/dispatch/portable.rs:794` maps non-typed events to
`DispatchPlan::Ignored`, so a native registration there would be an inert no-op.)

Inventory: 8 entries — 2 thin, 6 telemetry, 0 independent, 0 nondeterministic.

FAIL-ON-PURPOSE, both directions, via `--root` against a temp fixture:

    FAIL: missing inventory metadata: hooks/scripts/unclassified.sh          exit=1
    FAIL: hooks/scripts/cwd_changed.sh:50: telemetry_policy_authority        exit=1

This satisfies the team lead's two-way condition AT THE INVENTORY MECHANISM. It does
NOT yet satisfy it at `test_registered_hooks_no_python.sh`, which wave 2 must reframe
to actually consult the classification. Mechanism proven; wiring not yet. The condition
is not reported as met until the reframed test itself fails both ways.

## W1.4 — D8 Pi manifest + drift test

Files: `packages/harness-pi/shepherd.pi.json`, `hooks/tests/test_pi_manifest_drift.sh` (new).

Manifest declares Pi's real in-process mechanism (not Claude's exec form), citing
handler lines. Test passes 6/6 on the real tree, is bash-3.2 safe, is `100755`, and
accepts `SHEPHERD_PI_MANIFEST` / `SHEPHERD_PI_EXTENSION` overrides.

FAIL-ON-PURPOSE, both directions:

    A: manifest declares a guarded tool the extension does not guard
      FAIL  manifest guarded-tool list matches GUARDED_TOOL_NAMES exactly --
            manifest declares tool(s) GUARDED_TOOL_NAMES does not: notebook_edit   exit=1

    B: orphaned handler (tool_call removed from manifest, pi.on("tool_call") remains)
      FAIL  every pi.on(...) handler is declared in the manifest --
            pi.on(...) handler exists but is undeclared in manifest: tool_call     exit=1

Correction to mesh ROW 7 for the close report: "Pi is unguarded" is true of the
MANIFEST and false of the IMPLEMENTATION. `extension.mjs` binds identity at
`session_start` and guards write/edit/bash at `tool_call`, fail-closed on every error
path. Pi lacked a declaration, not enforcement.

## Expected-red, wave 2 input

    test_registered_hooks_no_python.sh   exit=1  AssertionError on the exact command set
    test_registered_hook_authority.sh    exit=1  assert len(inventory["entries"]) == 1
    test_legacy_policy_retirement.sh     exit=1  four-adapter count; strict inventory string

## BLOCKER — gate.sh RED, caused by this lane

    $ python3 scripts/generate-compiler-package-content.py --check
    compiler-package-content: byte drift: SHA256SUMS; byte drift: content/roles/engineer.md;
    byte drift: content/roles/planter.md
    $ bash scripts/gate.sh   -> exit 1

`crates/compiler/build.rs:30` asserts generated compiler package content equals authored
root content. W1.1's `content/roles/` edit made the embedded projection stale, so the
build script panics and the whole workspace fails to compile. `test_native_cli_contract.sh`
is collateral: its `native-surface-*` checks shell out to `cargo run`.

Fix is `python3 scripts/generate-compiler-package-content.py --write`, which writes
`crates/compiler/package-content` — inside `crates/**`, forbidden to this lane.
Escalated to the root session. Distinct from the `agents/` ruling: stale `agents/` only
makes a lint read stale, this stops compilation outright. The config lane hits the same
wall the moment its `content/roles/conductor.md` edit lands.

---

# Wave 2 evidence (partial — W2.1)

## W2.1 — D4 condition (2) now proven AT THE SELF-TEST

File: `hooks/scripts/hook_authority_inventory.py`.

`self_test()` now registers a third fixture hook `hooks/scripts/unclassified.sh`
(line 237/256) that is deliberately absent from the fixture's `METADATA.update({...})`,
and `"missing inventory metadata"` is added to the `required` set.

    $ python3 hooks/scripts/hook_authority_inventory.py --self-test
    hook_authority_inventory: self-test passed          exit=0
    $ python3 hooks/scripts/hook_authority_inventory.py --check
    exit=0

FAIL-ON-PURPOSE (conductor-run, against a /tmp COPY; tracked file untouched):
classify the fixture's `unclassified.sh` so the failure can no longer be emitted —

    $ python3 /tmp/.../inv.py --self-test
    self-test failed to detect: missing inventory metadata
    exit=1

Both halves of the team lead's D4 HARD CONDITION are now proven at the inventory and
its self-test:
  (1) telemetry hook emitting a policy decision  -> `telemetry_policy_authority`
  (2) unclassified shell registration            -> `missing inventory metadata`

STILL OUTSTANDING: the condition names `test_registered_hooks_no_python.sh`. That test
must itself fail both ways, and it must consult the inventory classification
programmatically rather than allowlisting filenames. W2.2 owns that. The condition is
NOT reported as met until the reframed test is verified to bite.

## W2.2 — three pinned tests reframed; D4 HARD CONDITION now FULLY MET

Files: `test_registered_hooks_no_python.sh`, `test_registered_hook_authority.sh`,
`test_legacy_policy_retirement.sh`. All three exit 0 against the W1.3 tree.

The reframed `test_registered_hooks_no_python.sh` CONSULTS THE INVENTORY
PROGRAMMATICALLY — it is not a filename allowlist. Line 71:

    [sys.executable, audit_path, "--root", audit_root, "--json"],

and reads `classification` back out. Its own header records why: "A version that
merely allowlisted filenames would look correct and prove nothing."

FAIL-ON-PURPOSE, conductor-run, both against /tmp copies (tracked tree untouched):

    (a) register a raw Node policy command
        FAIL  registered hook manifest launches Node (policy must never resolve through Node)
        FAIL  every non-native registration is classified thin/telemetry by hook_authority_inventory.py
        exit=2

    (b) register an UNCLASSIFIED shell script
        FAIL  every non-native registration is classified thin/telemetry by hook_authority_inventory.py
        exit=1

The team lead's D4 HARD CONDITION is satisfied at the named test, both ways. D2/D3
stands; the retire-all-seven fallback is formally dead and was never entered.

`test_legacy_policy_retirement.sh` keeps its exact-set property: the native-adapter
count is now scoped to `.command == "shepherd" and .args == ["claude-hook"] | length == 4`,
so the 4 native adapters are still pinned exactly while the 7 shell registrations are
accounted for separately by classification. Its `retired=()` array is untouched, and
`conductor_write_guard.sh` still passes both "unregistered" and "source is deleted".

Suite state after wave 2:

    test_registered_hooks_no_python.sh   exit=0
    test_registered_hook_authority.sh    exit=0
    test_legacy_policy_retirement.sh     exit=0
    test_exec_bits.sh                    exit=0
    test_pi_manifest_drift.sh            exit=0
    lint_agent_capabilities.sh           exit=1  (4 scope-bound violations; clears when
                                                  the root session regenerates `agents/`)
