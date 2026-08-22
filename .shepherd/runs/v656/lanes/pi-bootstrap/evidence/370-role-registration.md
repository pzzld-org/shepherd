# #370 Pi role registration and terminal lifecycle evidence

## Outcome

The staged Pi package contains compiler-owned carrier bytes only in the stage/package:

- 9 canonical prompts: `auditor`, `coder`, `conductor`, `critic`, `discovery`, `engineer`, `planter`, `shepherd`, `worker`
- exactly 7 provider agents: `shepherd:auditor`, `shepherd:coder`, `shepherd:conductor`, `shepherd:critic`, `shepherd:discovery`, `shepherd:engineer`, `shepherd:worker`
- excluded agents: `shepherd:shepherd`, `shepherd:planter`
- `maxSubagentDepth: 2`: `shepherd:conductor`, `shepherd:engineer` only
- model aliases `sonnet` and `haiku`: 0 generated agent frontmatter occurrences
- every generated agent reloads `../src/extension.mjs`

No generated `agents/`, `prompts/`, or `skills/` tree is tracked under `packages/harness-pi/`.

## RED evidence

| Contract | Command / observation | Result |
|---|---|---|
| Pi aliases must inherit | `cargo test -p shepherd-compiler target_final_role_carriers_resolve_models_profiles_and_pi_tools_in_core` | exit 101; expected `None`, received `Some("sonnet")` |
| child native lifecycle | `node packages/harness-pi/test.mjs` | exit 1; child sessions produced root binds and no child start/stop |
| nested extension retention | `python3 scripts/tests/test-generate-pi-agents.py` | exit 1; generated engineer omitted `subagentOnlyExtensions` |
| parent terminal surfaces | `node packages/harness-pi/test.mjs` | exit 1; `tool_result`, `subagent:foreground-complete`, and `subagent:async-complete` observers were absent; `/tmp/v656-370-parent-terminal-red.log` |
| live native readiness shape | fresh no-override Pi smoke | four records remained active; native capability reports omit computed `readiness`, so unadapted component exchange validation rejected the real response |
| live workflow correlation | sanitized real `tool_result` / `async-complete` fields | attached workflow children identify their native child by `workflow.value[].runId`; async results expose child `runId`, explicit `index`, and the session JSONL at `artifactPaths.outputPath`, not the outer carrier run ID |
| exact terminal idempotence | fresh no-override Pi smoke | child-local stop succeeded, but parent exact resolve returned `ERROR: dispatch record is terminal: stopped`; the narrower classifier retained false pending work |
| terminal correlation lockout | `node packages/harness-pi/test.mjs` | exit 1; missing/mismatched evidence blocked guarded mutation, a forged duplicate replaced an exact pending stop, pre-correlation retries were unbounded, and session open omitted `O_NONBLOCK`; `/tmp/v656-370-final-red.log` |
| production generic provider gate | `node packages/harness-pi/test.mjs` | exit 1; absent and malformed `pi.getAllTools()` inventories did not produce the exact mutation block, and inactive registered-provider acceptance was unimplemented; `/tmp/v656-370-final-red.log` |

RED logs and field-shape evidence contain no credentials or prompt bodies.

## Deterministic lifecycle coverage

`packages/harness-pi/test/child-lifecycle.test.mjs` proves:

- attached success plus failed, interrupted, signalled, timed-out, and manually stopped terminal results
- attached workflow child run IDs rather than the outer carrier/tool-call ID
- detached foreground does not close early and closes on `subagent:foreground-complete`
- async out-of-order rows use each explicit child run ID and index; no array-position identity
- duplicate and child-local-first terminal idempotence after exact native proof
- missing and mismatched evidence stays nonblocking; pre-correlation candidates are deduplicated, capped at 64, and discarded after three attempts
- a forged duplicate cannot replace or unblock an exact correlated pending stop
- failed stop remains pending, blocks mutation, and retries only the stored exact stop at safe boundaries
- native mismatch and missing start cannot stop another record
- non-Shepherd plus non-dispatchable `shepherd:shepherd` / `shepherd:planter` rows are ignored
- absent, symlink, directory, oversized, malformed, wrong-header, and invalid-ID session files fail closed
- session files open with `O_RDONLY | O_NONBLOCK | O_NOFOLLOW`, then pass descriptor regular-file and device/inode checks before a bounded first-line read
- malformed/oversized run IDs and missing/negative/fractional/oversized indexes fail closed
- nested ancestry uses only validated `PI_SUBAGENT_PARENT_PATH`; malformed, truncated, self-parent, non-integer, and final-entry mismatch paths fail closed
- actual native capability reports without a serialized `readiness` field are normalized to the typed computed variant before exchange validation
- start failure, terminal handoff failure, success, and shutdown remove process/event listeners
- root and child sessions use `pi.getAllTools()` at `session_start`; configured inactive `subagent` tools pass, while absent, malformed, throwing, and wrong-case inventories block mutation with one exact remediation
- assistant messages close only for `stopReason === "stop"` with no tool call

## GREEN evidence

| Contract | Command | Result |
|---|---|---|
| formatting | `cargo fmt --all -- --check` | exit 0 |
| compiler mapping | `cargo test -p shepherd-compiler` | exit 0; 16 tests |
| native identity core | `cargo test -p shepherd-core --features full --test portable_dispatch` | exit 0; 7 tests |
| typed component | `cargo test -p shepherd-component` | exit 0; 15 tests including doctest |
| staged Pi adapter | `node packages/harness-pi/test.mjs` | exit 0; 6/6 files and 23 Node tests; `/tmp/v656-370-final-node-rerun.log` |
| provider-free fresh Pi write | staged Shepherd package only, no `pi-subagents` | exit 0; Write blocked with exact remediation and no file created; `/tmp/v656-370-absent-provider-proof.log` |
| manifest parity | `bash hooks/tests/test_pi_manifest_drift.sh` | exit 0; 6/6 |
| generator | `python3 scripts/tests/test-generate-pi-agents.py` | exit 0; 3 tests |
| package surface | `bash scripts/tests/test-pi-package-surface.sh` | exit 0; 7/7 |
| package negative controls | `bash scripts/tests/test-pi-package-surface.sh --self-test` | exit 0; 4/4 |
| carrier authority | `bash scripts/tests/test-generated-carrier-authority.sh` | exit 0 |
| gate reachability | `python3 scripts/check-gate-wiring.py` | exit 0; 61 test files reachable |
| compiler package content | `python3 scripts/tests/test-generate-compiler-package-content.py` | exit 0; 3 tests |
| packed portability | `bash scripts/tests/test-packed-plugin-portability.sh` | exit 0 |
| packed bytes/runtime | `bash scripts/test-packed-plugin.sh` | exit 0; staged component and all active adapters exercised; `/tmp/v656-370-final-packed-rerun.log` |
| deterministic eval contracts | `bash services/eval/tests/run.sh` | exit 0; 5/5 |
| whitespace | `git diff --check` | exit 0 |

## Generic provider capability proof

Production readiness uses Pi's documented public `pi.getAllTools()` API. The extension accepts any
configured tool whose name is exactly `subagent`; it never imports `pi-subagents`, calls the legacy
wrapper, or requires the tool to be active. Root and child negative controls cover absent, malformed,
throwing, and wrong-case inventories. The exact block is:

`Pi subagent provider unavailable. Run \`pi install npm:pi-subagents\`, then restart Pi.`

A fresh isolated Pi process loaded only the freshly staged Shepherd package, with no subagent
provider package in settings. Pi attempted a real `write`; the tool result was `isError: true` with
that exact text, no file was created, the process exited 0, and the staged inventory still contained
seven agents. Sanitized proof is `/tmp/v656-370-absent-provider-proof.log`.

## Clean live Pi terminal proof

A fresh `/tmp` Pi config loaded exactly two local packages: installed `pi-subagents` 0.53.0 and the freshly staged Pi package. Its default was `openai-codex/gpt-5.6-sol`. The command supplied no `--model`, child model override, fallback, or retry. The generated agent files contained zero `model:` entries.

The provider inventory listed exactly these seven `shepherd:` roles:

`shepherd:auditor`, `shepherd:coder`, `shepherd:conductor`, `shepherd:critic`, `shepherd:discovery`, `shepherd:engineer`, `shepherd:worker`.

The engineer launched auditor and discovery concurrently, waited for both, then launched critic:

| Role | Started (UTC) | Stopped (UTC) | Native terminal state |
|---|---|---|---|
| `shepherd:engineer` | `2026-08-22T02:32:57.068Z` | `2026-08-22T02:33:24.011Z` | `stopped`, revision 2 |
| `shepherd:auditor` | `2026-08-22T02:33:02.885Z` | `2026-08-22T02:33:05.084Z` | `stopped`, revision 2 |
| `shepherd:discovery` | `2026-08-22T02:33:02.899Z` | `2026-08-22T02:33:05.594Z` | `stopped`, revision 2 |
| `shepherd:critic` | `2026-08-22T02:33:09.613Z` | `2026-08-22T02:33:11.954Z` | `stopped`, revision 2 |

Final output: `ROLES_OK:7 ENGINEER_OK AUDITOR_OK DISCOVERY_OK CRITIC_OK`.

The four records have distinct bounded `pi-subagent-<sha256>` IDs, literal carriers matching their roles, exact child session IDs from validated JSONL headers, `state: stopped`, and `revision: 2`. The live session contains zero terminal tool errors. Sanitized exact proof is `/tmp/v656-370-live-terminal-proof.log`; raw prompts and authentication are excluded.

## Residual risk

An uncatchable hard kill of both a parent and child before either process handles a terminal callback/event can still leave a revision-1 record. Closing that crash-only gap requires durable startup reconciliation or native lease reaping, not another in-process callback. Normal attached, detached, async, failure, signal, duplicate, and child-local-first terminal paths are covered and live-proven.
