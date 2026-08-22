# #370 Pi role registration and terminal lifecycle evidence

## Outcome

The staged Pi package contains compiler-owned carrier bytes only in the stage/package:

- 9 canonical prompts: `auditor`, `coder`, `conductor`, `critic`, `discovery`, `engineer`, `planter`, `shepherd`, `worker`
- exactly 7 provider agents: `shepherd:auditor`, `shepherd:coder`, `shepherd:conductor`, `shepherd:critic`, `shepherd:discovery`, `shepherd:engineer`, `shepherd:worker`
- excluded agents: `shepherd:shepherd`, `shepherd:planter`
- carrier transport: all 7 generated agents include `subagent` and `maxSubagentDepth: 2`
- canonical dispatch authority: compiled `critic` and `worker` capabilities omit `dispatch`; compiled `conductor` and `engineer` capabilities include it
- authored `model_hint` survives compiler, Component, WIT, and generated JSON role boundaries
- project-neutral conductor and engineer carriers use the impossible `model: model-required/model-required` sentinel because their portable hint is `reasoning-high`
- every other project-neutral non-inherit carrier uses the same impossible sentinel
- model aliases `sonnet` and `haiku`: 0 generated Pi agent frontmatter occurrences
- dogfood resolution: root, engineer, and conductor use Sol:xhigh; ordinary roles use Luna:max
- every generated agent reloads `../src/extension.mjs`

No generated `agents/`, `prompts/`, or `skills/` tree is tracked under `packages/harness-pi/`.

## RED evidence

| Contract | Command / observation | Result |
|---|---|---|
| emitted portable hint | `cargo test -p shepherd-compiler --test compile target_final_role_carriers_resolve_models_profiles_and_pi_tools_in_core` | exit 101; `EmittedRole` had no `model_hint` field |
| closed Pi target config | `cargo test -p shepherd-core --features config,serde,std --test loader pi_model_targets_are_closed_and_loaded_by_the_canonical_schema` | exit 101; `ShepherdConfig` had no `model_targets` field |
| Component hint boundary | `cargo test -p shepherd-component --test component canonical_compilation_binds_the_host_to_a_canonical_target_profile` | exit 101; WIT `emitted-role` had no `model-hint` |
| configured Pi target | `cargo test -p shepherd-cli --test wave_a_models_cli models_resolve_pi_uses_the_configured_concrete_target_map` | exit 101; resolver returned portable `reasoning-high`, not configured Sol |
| carrier sentinel | `python3 scripts/tests/test-generate-pi-agents.py` | exit 1; ordinary carrier omitted `model-required/model-required` |
| required thinking suffix | core loader and CLI resolver regressions | RED accepted a model without effort and remediation named only `provider/model` |
| child native lifecycle | `node packages/harness-pi/test.mjs` | exit 1; child sessions produced root binds and no child start/stop |
| nested extension retention | `python3 scripts/tests/test-generate-pi-agents.py` | exit 1; generated engineer omitted `subagentOnlyExtensions` |
| parent terminal surfaces | `node packages/harness-pi/test.mjs` | exit 1; `tool_result`, `subagent:foreground-complete`, and `subagent:async-complete` observers were absent; `/tmp/v656-370-parent-terminal-red.log` |
| live native readiness shape | fresh no-override Pi smoke | four records remained active; native capability reports omit computed `readiness`, so unadapted component exchange validation rejected the real response |
| previous live root-resume token | Pi `--continue` emitted `session_start` with the persisted native session ID | **FALSE**; Rust `bind_root` returned `dispatch record already exists`, so that resumed root could not call `subagent`. This rejected proof is retained; corrected proof appears below. |
| live workflow correlation | sanitized real `tool_result` / `async-complete` fields | attached workflow children identify their native child by `workflow.value[].runId`; async results expose child `runId`, explicit `index`, and the session JSONL at `artifactPaths.outputPath`, not the outer carrier run ID |
| exact terminal idempotence | fresh no-override Pi smoke | child-local stop succeeded, but parent exact resolve returned `ERROR: dispatch record is terminal: stopped`; the narrower classifier retained false pending work |
| terminal correlation lockout | `node packages/harness-pi/test.mjs` | exit 1; missing/mismatched evidence blocked guarded mutation, a forged duplicate replaced an exact pending stop, pre-correlation retries were unbounded, and session open omitted `O_NONBLOCK`; `/tmp/v656-370-final-red.log` |
| production generic provider gate | `node packages/harness-pi/test.mjs` | exit 1; absent and malformed `pi.getAllTools()` inventories did not produce the exact mutation block, and inactive registered-provider acceptance was unimplemented; `/tmp/v656-370-final-red.log` |
| depth-only safe carrier | fresh persisted root -> `shepherd:worker` on `pi-subagents` 0.53/0.54 | `maxSubagentDepth: 2` alone did not register the provider extension in the worker; the worker could not exercise a policy-owned no-dispatch block. Carrier frontmatter must include the `subagent` transport even when canonical role capabilities omit `dispatch`. |

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
- generated critic and worker carriers register `subagent` at depth 2 while their canonical compiled capabilities omit `dispatch`
- valid managed worker Write remains allowed; managed worker and critic `subagent` calls receive the exact no-dispatch block before provider/native execution
- managed engineer and conductor are the negative controls: their canonical capabilities contain `dispatch`, so the no-dispatch reason does not block them
- assistant messages close only for `stopReason === "stop"` with no tool call

## GREEN evidence

| Contract | Command | Result |
|---|---|---|
| formatting | `cargo fmt --all -- --check` | exit 0 |
| compiler mapping | `cargo test -p shepherd-compiler` | exit 0; portable hint emitted and Pi inherit mapping typed |
| native identity core | `cargo test -p shepherd-core --features full --test portable_dispatch` | exit 0; 7 tests |
| typed component | `cargo test -p shepherd-component` | exit 0; 15 tests including doctest |
| staged Pi adapter | `env -u SHEPHERD_COMPONENT_MODULE node packages/harness-pi/test.mjs` | exit 0; 6/6 files and 28 Node tests |
| managed child provenance | real fixture-backed managed child `session_start` | native `start` request has exact `capability_source: "pi-child-environment"` |
| corrected process resume | persisted workflow and exact retained conductor | workflow `32a0d8e6-ff3e-4eff-972c-91fbacc6cfb5` and revive `6f6e5e11-145e-4718-a79d-5911ef3941b1` reached `complete`; retained output marker exact |
| fresh safe carrier | persisted root -> `shepherd:worker` with staged Shepherd plus `pi-subagents` 0.54.0 | worker Write created the exact 29-byte marker; worker `subagent` returned the exact no-dispatch block; only one child session existed, so no critic started; `/tmp/v656-370-safe-carrier/live-proof-summary.log` |
| provider-free fresh Pi write | same staged Shepherd package, no `pi-subagents` | exit 0; Write blocked with exact remediation and no file created; `/tmp/v656-370-safe-carrier/live-proof-summary.log` |
| manifest parity | `bash hooks/tests/test_pi_manifest_drift.sh` | exit 0; 6/6 |
| generator | `python3 scripts/tests/test-generate-pi-agents.py` | exit 0; 3 tests |
| package surface | `bash scripts/tests/test-pi-package-surface.sh` | exit 0; 7/7 |
| package negative controls | `bash scripts/tests/test-pi-package-surface.sh --self-test` | exit 0; 4/4 |
| carrier authority | `bash scripts/tests/test-generated-carrier-authority.sh` | exit 0 |
| gate reachability | `python3 scripts/check-gate-wiring.py` | exit 0; 62 test files reachable |
| compiler package content | `python3 scripts/tests/test-generate-compiler-package-content.py` | exit 0; 3 tests |
| packed portability | `bash scripts/tests/test-packed-plugin-portability.sh` | exit 0 |
| packed bytes/runtime | `bash scripts/test-packed-plugin.sh` | exit 0; staged component and all active adapters exercised; packed carrier assertions require transport plus depth 2 for all seven while staged canonical critic/worker capabilities omit `dispatch` and engineer/conductor capabilities include it |
| package boundary | `node packages/scripts/check-package-boundary.mjs` | exit 0; four package dry-runs passed with no workspace-only distribution edges |
| deterministic eval contracts | `bash services/eval/tests/run.sh` | exit 0; 5/5 |
| concrete Pi model routing | fresh staged package and three isolated Pi roots | omitted model failed before child execution; Luna:max worker succeeded; Sol:xhigh conductor dispatched Luna:max worker and auditor; all four native records stopped at revision 2; `/tmp/v656-model-safety-live.Mq8FwE/live-proof-summary.log` |
| installed CLI dogfood config | `shepherd config show` plus role-specific `shepherd models resolve ... --harness pi` calls | exit 0 after installing the new CLI; root/engineer/conductor return Sol:xhigh and worker/auditor/discovery return Luna:max |
| whitespace | `git diff --check` | exit 0 |

## Corrected conductor resume proof

Root gates and Rust tests passed before installing `shepherd-cli` 6.5.6. Using the original
`TMPDIR`, persisted async workflow `32a0d8e6-ff3e-4eff-972c-91fbacc6cfb5` reported `State complete`;
its main `shepherd:conductor` also completed. After process resume, exact retained child
`b5fa268e-74a4-4198-8c55-5e6473873e5b` was revived as clean run
`6f6e5e11-145e-4718-a79d-5911ef3941b1`. The revive reached `complete` without tools or rerun and
retained exact output `REVIVED_OK CONDUCTOR_OK NO_DISPATCH_OK WORKER_OK AUDIT_OK`.

The original acceptance conductor, worker, and auditor native records are all `stopped`, revision 2.
No critic child exists. The acceptance marker
`.shepherd/runs/v656/lanes/pi-bootstrap/evidence/370-conductor-acceptance.md` has exact bytes
`ACCEPTANCE_WORKER_OK\n`. Proof:
`/tmp/v656-conductor-acceptance.log`, `/tmp/v656-conductor-acceptance-resume-dir-fixed.log`,
`/tmp/v656-conductor-acceptance-revive-clean.log`, and their referenced session artifacts.

## Generic provider capability proof

Production readiness uses Pi's documented public `pi.getAllTools()` API. The extension accepts any
configured tool whose name is exactly `subagent`; it never imports `pi-subagents`, calls the legacy
wrapper, or requires the tool to be active. Generated carriers include the transport tool because
`pi-subagents` 0.53/0.54 loads its child extension only when that tool is present; transport presence
does not alter the Component's canonical capabilities. Root and child negative controls cover absent,
malformed, throwing, and wrong-case inventories. The exact block is:

`Pi subagent provider unavailable. Run \`pi install npm:pi-subagents\`, then restart Pi.`

A fresh isolated Pi process loaded only the freshly staged Shepherd package, with no subagent
provider package in settings. Pi attempted a real `write`; the tool result was `isError: true` with
that exact text, no file was created, and the process exited 0. Sanitized proof is
`/tmp/v656-370-safe-carrier/live-proof-summary.log`.

## Fresh safe-carrier live proof

A fresh `/tmp` Pi configuration loaded exactly two local packages: installed `pi-subagents` 0.54.0
and the freshly staged Pi package. The generated carrier gave all seven children the `subagent`
transport and `maxSubagentDepth: 2`; the staged compiler manifest independently proved worker and
critic canonical capabilities omit `dispatch`, while conductor and engineer include it.

A persisted root launched exactly one `shepherd:worker` in the assigned detached worktree. The
worker's real `Write` completed with `isError: false` and created
`.shepherd/runs/v656/safe-carrier-worker-marker.txt` with exact bytes
`SAFE_CARRIER_WORKER_WRITE_OK\n`. Its next real `subagent` call returned `isError: true` with exact
text `Pi Component role worker no-dispatch contract blocks subagent`. The session tree contained
one child `session.jsonl`, the worker only; no critic child was created.

The same staged Shepherd package was then loaded without the provider. A root `Write` returned the
unchanged exact provider remediation and created no marker. Deterministic sanitized proof is
`/tmp/v656-370-safe-carrier/live-proof-summary.log`; carrier details are in
`/tmp/v656-370-safe-carrier/carrier-proof.log`.

## Concrete model-routing live proof

A fresh staged package used the new `shepherd.compiled-tree/3` manifest and generated all
seven project-neutral agent carriers. The direct `shepherd:worker` carrier contains
`model: model-required/model-required`; invoking it without a per-run model failed with
`Unknown subagent model 'model-required/model-required' in the active Pi model registry.`
The provider created no child session.

An explicit `openai-codex/gpt-5.6-luna:max` worker then returned
`LUNA_MAX_WORKER_OK`. A separate `openai-codex/gpt-5.6-sol:xhigh` conductor returned
`SOL_XHIGH_CONDUCTOR_OK` after dispatching only an explicit Luna:max worker and Luna:max
auditor. Child session JSONL metadata records Luna plus `max` for all three leaves and Sol
plus `xhigh` for the conductor. No Spark, Terra, Fable, or Sol leaf appears. The four exact
native records are `stopped`, revision 2. Sanitized deterministic proof is
`/tmp/v656-model-safety-live.Mq8FwE/live-proof-summary.log`.

## Luna max blocker-audit follow-up

The three blocker reproductions were captured before implementation:

- `requested_harnesses_load_project_model_overrides_for_resolve_and_show` returned
  `inherit` for Claude instead of the project override's `haiku`.
- `explicit_harness_config_is_validated_under_the_requested_harness` rejected
  `.shepherd/shepherd.claude.toml` as noncanonical because model inspection forced Pi.
- `no_target_preserves_the_environment_harness_for_config_selection` returned the
  default instead of the environment-selected Claude override.
- `malformed_repository_never_falls_back_to_context_free_defaults` proved a broken
  repository was incorrectly treated as a context-free directory before the fallback
  was restricted to paths with no `.git` marker.
- `test_rejects_non_inherit_manifest_models_without_partial_output` accepted `sonnet`,
  `haiku`, and `provider/model:max` on a schema-3 worker and exited 0.
- `empty_document_materializes_the_canonical_defaults` returned `inherit-caller` for
  engineer/conductor instead of `reasoning-high`; live content had the same drift.

The corrected loader runs for every requested harness, preserves the environment harness
when no target is requested, and falls back to typed defaults only for a context-free call
with no explicit config. The Pi generator now rejects any non-inherit manifest model with
exact error `dispatchable role worker non-inherit hint standard must emit model null, got
'<value>'`; `inherit-caller` still requires compiler-emitted `inherit`. Engineer and
conductor defaults and authored hints are `reasoning-high`. The dogfood `[models]`
overrides were removed, and installed `models show --harness pi --json` reports all four
reasoning roles as `source: default` while resolving them to Sol:xhigh.

`cargo fmt`, workspace default/full checks, workspace default/full clippy with warnings
denied, workspace tests, Component tests, CLI tests, six Pi package files/28 Node tests,
compiler/package/content projection checks, packed distribution, packed portability,
fast gate, and full gate passed. The Pi bootstrap live eval passed at 90/20 without changing its threshold. The unrelated
cargo-native-distribution good fixture remains explicit debt at 82/100 and was not changed
in this lane.

A second fresh stage proves all seven dispatchable carriers now use
`model-required/model-required`, including engineer and conductor. Omitted worker launch
failed before a child session. Explicit Luna:max worker succeeded. A Sol:xhigh conductor
dispatched only Luna:max worker/auditor children. Exact session metadata and four native
`stopped`, revision-2 records are summarized at
`/tmp/v656-model-routing-final.QO73FQ/live-proof-summary.log`.

## Residual risk

An uncatchable hard kill of both a parent and child before either process handles a terminal callback/event can still leave a revision-1 record. Closing that crash-only gap requires durable startup reconciliation or native lease reaping, not another in-process callback. Normal attached, detached, async, failure, signal, duplicate, and child-local-first terminal paths are covered and live-proven.

## Final deterministic acceptance

- Full conformance replay: `110/110`, with checksum `739234eb74a35fc437dc5f0f17b1dbf667244a9833d7784f9a9afc9085cdd94e` verified.
- Deterministic eval contracts: `5/5`; Pi bootstrap live eval `90/20`; unrelated cargo-native-distribution debt remains `82/100` and unchanged.
- Full repository gate: green in 42 seconds; formatting and `git diff --check` passed.
- Final Luna:max blocker audit: `ACCEPT`, with no remaining BLOCKER/HIGH findings.
- Live model proof: Sol:xhigh conductor, Luna:max worker/auditor, omitted model failed before child execution, and 4/4 native records stopped at revision 2.
