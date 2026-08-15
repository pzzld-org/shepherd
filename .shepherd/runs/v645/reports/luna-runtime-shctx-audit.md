# Runtime/public `shctx` reference audit

This audit was run after deleting `services/cli/**` and
`skills/context/scripts/**`. Historical run reports, changelog entries,
conformance expected bytes, and the retirement manifest are not included as
live references.

## Must be rewritten by the owning root/docs pass

These files are current prompts or current reference doctrine and still tell a
harness to invoke the deleted CLI:

- `commands/start.md:39` uses `shctx config init`.
- `commands/ctx.md:18-35` is entirely a pass-through surface for `shctx`.
- `commands/focus.md:10,25,30,61,69,76` invokes `shctx loop ...`.
- `commands/loop.md:32,59,63,66,73,77,84` invokes `shctx loop` and `shctx dedup`.
- `skills/harness/references/workflow-templates.md:141,152,158-163,226,254,260`
  uses `shctx graph` and `shctx plan` as the workflow compiler.
- `skills/harness/references/loop-templates.md:66,92` uses `shctx loop` and
  `shctx discovery`.
- `skills/shepherd/references/invariant-matrix.md:113,115-116,121,124,126-127`
  describes `shctx` as the live CLI and names deleted helpers/tests.
- `skills/shepherd/references/flock.md:33,64,76,112,132,143,161,175-177`
  directs agents to `shctx graph`, `issues`, `adapt`, `discovery`, `worktree`,
  `register`, `signal`, and `cleanup`.
- `skills/shepherd/references/pipeline.md:17,21,60,70,131,190` directs the
  conductor to `shctx` graph, seed, plan, dedup, and sprint routes.
- `skills/shepherd/references/seed-template.md:214` names the deleted
  `skills/context/scripts/cmd_seed.sh` implementation.
- `commands/spawn.md:54-55,59,221,322,331,341,357,384,392,401,404-405,
  438-439,451,454,478,502` still directs the operator to `shctx` config,
  init, priors, models, teammate, seed, loop, dashboard, and signal routes.
- `skills/context/references/{model-map,naming-conventions,schema,profiles}.md`
  still present the deleted `shctx` command as the live context API. The
  examples `skills/context/examples/inject-coder.md:1,3,12,61` and
  `journal-entry.md:9,21,27` do the same.
- `skills/shepherd/references/escalation.md:50`,
  `operating-philosophy.md:83,93`, `wave-routine.md:32`, and
  `spawn-flags.md:149-183` also contain current operator instructions using
  the retired name.
- `services/README.md:17`, `services/eval/README.md:36,79`, and
  `services/llm/README.md:37` describe `shctx eval` as an active service
  integration. `services/eval/evals/cases/reflection_good.txt:1` is an eval
  fixture and may remain evidence, but the README references are live docs.

## Current hook/runtime compatibility residue

These are not all direct command executions, but they are active code paths
that still expose or classify the retired name and need an owner decision:

- `hooks/scripts/_lib.sh:8,38,66,71,79,201-208,259-308,325,331,348` retains
  `shctx_config_files`, `shctx_harness`, `shctx_repo_root`, `shctx_db_path`,
  `shctx_artifacts_root`, and comments that define them as a shctx runtime.
- `hooks/scripts/session_open.sh:163` reads the old `announce_shctx_path`
  configuration key.
- `hooks/scripts/conductor_write_guard.sh:9,84-86,211-213` still describes
  the deny-list and exemptions using `shctx` (the actual write regex is
  already named `SHEPHERD_WRITE_PATTERN`).
- `hooks/scripts/bash_guard.sh:100-103`, `lock_guard.sh:24`,
  `coordinate_drive_guard.sh:138`, `dispatch_guard.sh:388-389`,
  `teammate_git_guard.sh:50`, `teammate_heartbeat.sh:5-65`, and
  `subagent_telemetry.sh:264-273` contain active-hook comments/contracts
  naming the retired runtime. Most are comments, but they can misdirect
  future maintenance.
- `services/eval/eval.sh:16,24` describes its integration as `shctx eval`;
  the executable itself is a standalone evaluator, so this is documentation
  residue rather than a second CLI invocation.

## Dangling old test surfaces

The entire `skills/context/tests/**` suite still assigns `SHCTX` to the
deleted dispatcher or executes deleted `cmd_*.sh` files. Representative exact
references include:

- `skills/context/tests/_setup.sh:15-32` defines the old test helpers.
- `skills/context/tests/test_dispatch.sh:4-6`, `test_cmd_teammate.sh:17-29`,
  `test_cmd_seed.sh:11`, `test_cmd_report.sh:17`, and
  `test_cmd_deliverable.sh:14` directly name deleted files.
- The same `SHCTX="$SHCTX_SKILL_ROOT/scripts/shctx"` pattern remains in
  `test_{adapt,canonical_types_filter,close_lane,config,doctor,dups,eval,
  export,flag_aliases,graph_compile,graph_next,handoff,init,inject,lint,
  lock,mem,migrate,models_resolve,query,refresh_artifacts,refresh_github,
  refresh_symbols,release,search,sprint_pipelines,status,staged_handoff,
  style,sync,worktree_create_batch}.sh`.
- `hooks/tests/test_exec_bits.sh:33`, `test_v636_wiring.sh:69-71`,
  `test_v639_wiring.sh:54,66,81-82`, `test_v630_wiring.sh:88-107`,
  `test_engineer_self_contained.sh:85-87`, `test_v644_wiring.sh:200`,
  `test_pause_retired.sh:38,62`, and `test_sql_escaping.sh:19,68-80,181-255`
  assert deleted paths or invoke the old dispatcher. These tests must be
  retired or rewritten against the Rust CLI before the full hook suite can be
  green.

## Evidence-only references

The following are intentionally retained as migration evidence and do not
execute the old CLI: `conformance/legacy-command-disposition.json`,
`conformance/cases/**/case.json` descriptions, `conformance/cases/**/expected/**`
old-byte fixtures, `scripts/check-cli-authority.py` resurrection self-tests,
`services/eval/evals/cases/plugin_distribution_bad.txt`, and historical
`.shepherd/runs/**` reports/changelog entries.

## Rust-owned user-facing residue

Root must fix these outside this lane because they are Rust-owned CLI output
or settings contracts:

- `crates/cli/src/cmd/wave_a_models.rs:33-34,174` emits `shctx models` usage,
  footer, and validation text.
- `crates/cli/src/cmd/wave_b1_mem.rs:14,278,319,337,345,369` emits `shctx
  mem` usage, removal output, and the `run 'shctx init'` remediation.
- `crates/cli/src/cmd/wave_b1_status_handoff.rs:123` emits `run 'shctx init'`.
- `crates/core/src/settings.rs:355,367` still exposes and defaults the
  `announce_shctx_path` setting. This is a schema/API compatibility decision,
  not a comment-only rename.
- `crates/cli/tests/wave_a_models_cli.rs:124` and
  `crates/cli/tests/wave_b1_mem_cli.rs:103,127` freeze the old user-facing
  strings and must move with the Rust output change.

Rust registry migration comments under `crates/registry/src/migrate/**` and
embedded migration comments under `skills/context/schema/migrations/**` still
name historical shctx writers. They do not emit or invoke the command and can
remain as historical schema provenance unless the root documentation gate
requires a zero-string policy.
