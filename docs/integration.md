# Integration

Shepherd owns deterministic orchestration and governance. A harness owns its
event envelope, process bridge, and host response format. Project skills own
language or domain mechanics. These boundaries are the portability contract.

## The component boundary

```text
Claude hooks → shepherd claude-hook → native Rust core ─────┐
Codex hooks  → shepherd codex-hook  → native Rust core ─────┤
                                                             │
Pi extension → thin host adapter → @pzzld/component-runtime  │
                                  → fl03:shepherd@6.5.6     │
                                           WebAssembly component
                                                             │
                        identity, guard, lifecycle, response,
                        compiler, registry-facing typed Rust contracts
```

Claude and Codex marketplace hooks bypass the Component Model and invoke the
native Rust core directly. The npm Codex adapter and Pi adapter send typed
records through the Component and receive typed records in return. Neither path inspects a
harness's private directory, parses a host policy file, discovers a process,
or writes an arbitrary path; Native Rust owns those host operations behind
explicit interfaces.

Project identity is deliberately not supplied by a harness. The one native
CLI derives the primary repository, project ID, active run, and descriptor-safe
write paths from its `ExecutionContext`; linked worktrees resolve through the
primary checkout. The Component then correlates every request fact the adapter
does know, including run when explicitly selected, harness, session, agent,
role, lane, tool call, revision, lease, and resume lineage. For write tools the
guard also compares the host tool target with the native resolved write paths.
This keeps project custody in the native filesystem boundary instead of
letting an adapter assert an arbitrary project ID.

The WIT package is `fl03:shepherd@6.5.6` in
[`crates/component/wit/shepherd.wit`](../crates/component/wit/shepherd.wit).
Generated JavaScript bindings are release artifacts, not a second source of
logic. The adapter packages must remain thin and must not grow policy parsers,
role inference, or filesystem materializers.

## Supported adapters

### Claude Code

The normal Claude marketplace plugin invokes the native `shepherd claude-hook`
command directly. That one Rust command owns identity normalization, lifecycle
planning and persistence, and guard evaluation. Missing identity, lifecycle,
or project facts fail closed at PreToolUse. Claude Code's Agent Teams capability
is host functionality, not a Shepherd policy engine.

Install the native `shepherd` executable on `PATH`, then install the plugin
normally from the GitHub marketplace source:

```sh
claude plugin marketplace add FL03/shepherd
claude plugin install shepherd@shepherd --scope user
```

The catalog uses Claude's normal relative `./plugins/shepherd` source entry.
That thin carrier holds a byte-identical projection of the canonical manifest
and links to canonical hooks, agents, and skills, which Claude dereferences
into its installed cache. There is no plugin ZIP, generated JavaScript runtime,
Node prerequisite, duplicate authored plugin content, or session-only loader
in the supported Claude installation path.

### Codex

The normal repository marketplace invokes `shepherd codex-hook` directly for
`SessionStart` and guarded `PreToolUse`. It does not register Codex's native
subagent lifecycle events: the host envelope does not provide a trusted
correlation from the parent spawn request to the child session identity. The
CLI reports those events as unsupported rather than fabricating a dispatch.
Its `.codex-plugin/plugin.json` selects a byte-gated regular-file projection
because Codex does not copy source symlinks. Install it with:

```sh
codex plugin marketplace add FL03/shepherd --ref v6.5.6
codex plugin add shepherd@shepherd
```

The cache contains no Node, npm, Wasm, or source-checkout dependency.
`@pzzld/codex-shepherd` remains the Component-backed npm embedding adapter; it
does not own this marketplace path or import Claude's private hooks.

### Pi

`@pzzld/pi-shepherd` is a host extension, not a standalone Pi agent runtime. At
root and child `session_start`, it calls Pi's public `pi.getAllTools()` API and
accepts any compatible registered subagent system whose configured tool name is
exactly `subagent`. It checks all configured tools, not only active tools. Every
generated child carrier includes that transport tool and `maxSubagentDepth: 2`
so the provider registers below root. This does not grant dispatch authority:
managed children may execute `subagent` only when their Component-compiled
canonical capabilities contain `dispatch`. An absent or malformed tool inventory leaves
reads available but blocks Write, Edit, and Bash with:
`Pi subagent provider unavailable. Run \`pi install npm:pi-subagents\`, then restart Pi.`
The extension does not import or depend on `pi-subagents`; that command is the
supported install or upgrade path for the reference provider. Pi's contract is
documented in
[`packages/harness-pi/shepherd.pi.json`](../packages/harness-pi/shepherd.pi.json).

## Install generated adapter trees

The native CLI is the only writer:

```sh
shepherd compile --target claude --out /absolute/path/to/claude
shepherd compile --target codex --out /absolute/path/to/codex
shepherd compile --target pi --out /absolute/path/to/pi
```

The component returns an in-memory emitted tree. JavaScript packages do not
write that tree and no adapter exposes a second CLI. `--check` verifies a
previously materialized tree without changing it. Materialization is
descriptor-safe, ownership-aware, and atomic.

## Compose project skills

Project-specific skills remain configuration, not forks of Shepherd. Add them
to the canonical `.shepherd/shepherd.toml`:

```toml
[skills]
mandatory = ["code-style"]

[skills.by_domain]
rust = ["rust"]
wasm = ["webassembly"]
payments = ["payments"]

[skills.detection]
rust = ["**/*.rs"]
wasm = ["**/*.wit", "**/component/**"]
payments = ["**/payments/**"]
```

The native compiler validates the authored role, skill, reference, doctrine,
and command budgets. Keep each skill focused. Put long explanations in a
reference and load that reference only for the lanes that need it.

Project doctrines belong to the project, not to the Shepherd package. Keep
them under a project-owned path and reference that path from configuration.
Do not edit the compiled adapter tree to add a doctrine; regenerate from the
single source tree.

## Shared identity, memory, and resume

Cross-harness coordination uses the same facts regardless of the host:

- typed normalized identity and a deterministic identity key;
- typed dispatch binding, start, stop, and resume records;
- run-scoped `dispatch/`, `reports/`, `audits/`, lane plans, and handoffs;
- structured cross-run context in `.shepherd/ctx` and the native registry;
- immutable cross-run documentation in the flat `.shepherd/docs/` root.

An adapter may translate an event, but it may not create a second role map,
guard corpus, run ledger, or context store. Resume reads the canonical run
artifacts and verifies identity before accepting a continuation. The Component
validates every native request and response as one typed exchange before an
adapter consumes it. A valid-schema response for another run, session, agent,
tool call, role, lane, or resume source is rejected. Claude translates an
actual `SubagentStart` carrying `source_agent_id` into typed resume and injects
only the bounded, validated context bundle returned by native Rust. Codex's
regular marketplace carrier does not register subagent lifecycle hooks until
the host exposes a trusted correlation contract.

## Gate provenance

The Bash `PostToolUse` carrier is telemetry, not gate authority. It may emit the
normal `bash_post` hook event and a worktree-cwd warning, but it does not read
`tool_input.command` or `tool_response` to claim that a configured gate ran. It
also does not infer execution or success from the outer Bash status. There is no
command-text gate ledger.

Command text is an observation only. Comments, `echo`, `printf`, quoted text,
concatenation, aliases, wrappers, missing commands, and failing gates remain
unverified from this hook. The hook does not parse shell syntax. A wrapper can
mention a command without invoking it, and a process can be invoked without
passing.

Gate state is distinguishable only from a wave-owned execution artifact.
These states are mutually exclusive and ordered by explicit evidence, not by
text observed by this hook:

| State | Required artifact evidence |
| --- | --- |
| Unverified | No valid invocation record exists for the gate identity; an orphan result is ignored or rejected |
| Invoked | The latest valid attempt has an invocation record but no matching result record |
| Failed | The latest valid attempt has an invocation record plus its matching non-zero result |
| Passed | The latest valid attempt has an invocation record plus its matching zero result |

### Attempt correlation and retry resolution

The gate identity is the tuple `run`, `wave`, `lane`, and `gate`.
`scripts/gate-artifact.py` assigns every invocation a unique `attempt_id`,
appends that invocation before starting the process, and appends its matching
result only after the process returns. The invocation append order is the
attempt order. A retry gets a new `attempt_id` and never overwrites prior
records. Unknown, cross-gate, contradictory, and duplicate results fail closed.

State resolution selects the last valid invocation, not file mtime or the last
result record. A retry with no result is therefore `Invoked`, even when an older
attempt passed. A matching non-zero result is `Failed`; zero is `Passed`. A
delayed result for an older attempt cannot revive a stale pass.

### Wave-owned writer and reader

Run a gate through the writer from the repository root:

```sh
python3 scripts/gate-artifact.py \
  --run v656 --wave w1 --lane gate-provenance --gate hooks \
  run -- bash hooks/tests/run.sh
```

Read the same artifact without executing a process:

```sh
python3 scripts/gate-artifact.py \
  --run v656 --wave w1 --lane gate-provenance --gate hooks \
  status -- bash hooks/tests/run.sh
```

The derived artifact path is
`.shepherd/runs/<run>/lanes/<lane>/evidence/gates/<wave>-<gate>.jsonl`.
`run` preserves the gate process exit code. `status` returns 0 for `Passed`, 1
for `Failed`, 3 for `Unverified`, 4 for `Invoked`, and 2 for malformed,
mismatched, or command-mismatched evidence. The reader requires the expected
command after `--`; a successful `true` process cannot certify the declared
hooks gate. The script location owns the repository root regardless of caller
cwd. Descriptor-relative no-follow traversal rejects symlinked parents and
files, an exclusive artifact lock linearizes readers with retries, every append
writes the complete payload, and every accepted JSONL record ends in a newline.
Records and artifacts are bounded. `scripts/tests/test-gate-artifact.py` proves
invocation precedes execution, command binding, result correlation, exit
preservation, concurrent latest-invocation retry semantics, complete newline
framing, repository-root ownership, malformed evidence refusal, and symlink
refusal. The fast gate executes this suite and `services/eval/tests/run.sh`; the
wiring checker discovers both service and repository test runners.

The ordinary `hooks-YYYY-MM-DD.jsonl` event proves only that the host adapter
completed its own telemetry path. It is not evidence for any gate state.

## Host capability limits

Adapters must report host limitations instead of guessing:

| Host | Shepherd assumption | Degradation |
| --- | --- | --- |
| Claude Code | Hooks and Agent Teams may be available. | If a hook or identity correlation is unavailable, the adapter reports the limitation and preserves its documented fail-closed posture. |
| Codex | The regular marketplace carrier supports SessionStart and guarded PreToolUse. | Native subagent lifecycle hooks are not registered because the host does not expose a trusted spawn-to-child correlation; direct lifecycle inputs are rejected, never fabricated into a role. |
| Pi | `pi.getAllTools()` reports a configured tool named exactly `subagent`; child carriers register that transport at depth 2. | Missing or malformed configured-tool metadata blocks Write, Edit, and Bash while reads remain available. Component canonical capabilities independently block no-dispatch children before provider execution. |

Host-specific limits belong in adapter diagnostics and run evidence. They do
not change the Component Model contract.

## Verification

Run package tests from the repository root after `npm ci --ignore-scripts`:

```sh
node packages/harness-claude/test.mjs
node packages/harness-codex/test.mjs
(cd packages/harness-pi && node test.mjs)
node --test packages/component-runtime/test/*.test.mjs
```

The durable integration checks are:

```sh
bash scripts/test-component-node.sh
bash scripts/test-packed-plugin.sh
bash scripts/tests/test-claude-marketplace.sh
node packages/scripts/check-package-boundary.mjs
node packages/scripts/check-deps.mjs
```

The packed test must load the installed tarballs, not repository source paths.
The Claude marketplace test strictly validates a dereferenced carrier fixture,
installs the actual thin carrier in an isolated home/configuration, confirms
the cache contains no escaping symlinks or Node/npm artifacts, and invokes its
native hook contract.

## See also

- [Configuration](configuration.md) for the canonical project and user tiers.
- [Customization](customization.md) for doctrines and branch models.
- [Permissions](permissions.md) for host-side authorization.
