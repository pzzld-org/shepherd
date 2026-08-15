# Integration

Shepherd owns deterministic orchestration and governance. A harness owns its
event envelope, process bridge, and host response format. Project skills own
language or domain mechanics. These boundaries are the portability contract.

## The component boundary

```text
Claude hooks   Codex hooks   Pi extension + SubagentProvider
      \\             |                 /
       \\            |                /
        thin host adapters
                 |
   @fl03/component-runtime
                 |
       fl03:shepherd@6.4.5
       Rust WebAssembly component
                 |
   identity, guard, lifecycle, response,
   compiler, registry-facing native contracts
```

The component receives typed records and returns typed records. It does not
inspect a harness's private directory, parse a host's policy file, discover a
process, or write an arbitrary path. Native Rust owns those host operations
behind explicit interfaces.

Project identity is deliberately not supplied by a harness. The one native
CLI derives the primary repository, project ID, active run, and descriptor-safe
write paths from its `ExecutionContext`; linked worktrees resolve through the
primary checkout. The Component then correlates every request fact the adapter
does know, including run when explicitly selected, harness, session, agent,
role, lane, tool call, revision, lease, and resume lineage. For write tools the
guard also compares the host tool target with the native resolved write paths.
This keeps project custody in the native filesystem boundary instead of
letting an adapter assert an arbitrary project ID.

The WIT package is `fl03:shepherd@6.4.5` in
[`crates/component/wit/shepherd.wit`](../crates/component/wit/shepherd.wit).
Generated JavaScript bindings are release artifacts, not a second source of
logic. The adapter packages must remain thin and must not grow policy parsers,
role inference, or filesystem materializers.

## Supported adapters

### Claude Code

`@fl03/harness-claude` translates Claude hook envelopes. It uses the component
for identity, guard decisions, lifecycle plans, response validation, and
canonical emission. Missing or invalid component runtime fails closed. Claude
Code's Agent Teams capability is host functionality, not a Shepherd policy
engine.

The source repository intentionally does not contain generated JavaScript or
Wasm. Claude marketplace GitHub sources can only copy repository content and
cannot select a generated GitHub release ZIP, so v6.4.5 does not claim that a
repository-source marketplace install is runnable. The production artifact is
the complete, bundled `shepherd-claude-plugin-6.4.5.zip` release asset, not a
self-contained runtime: it needs Node.js 20 or newer to host the intentional
WebAssembly Component Model adapter and the native `shepherd` executable on
`PATH` (or an explicit `SHEPHERD_NATIVE_BIN`). Load it for one session with:

```sh
claude --plugin-url \
  https://github.com/FL03/shepherd/releases/download/v6.4.5/shepherd-claude-plugin-6.4.5.zip
```

For checksum-first use, download the adjacent `.sha256` sidecar, verify the ZIP,
and pass the local archive to `claude --plugin-dir`. Both Claude flags are
session-only. The native `shepherd` executable must already resolve from
`PATH`, or `SHEPHERD_NATIVE_BIN` must name it explicitly.

### Codex

`@fl03/harness-codex` translates Codex hook and lifecycle envelopes into the
same typed records. It does not ship an apply/materialize executable and does
not import Claude's private hooks.

### Pi

`@fl03/harness-pi` is a host extension, not a standalone Pi agent runtime. It
requires a `SubagentProvider`-compatible extension, such as `pi-subagents`, to
resolve mutation identity and spawn/resume/stop operations. The provider must
advertise the required methods and readiness. Missing or unready provider
capability fails closed. Pi's contract is documented in
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
tool call, role, lane, or resume source is rejected. Claude and Codex translate
an actual `SubagentStart` carrying `source_agent_id` into typed resume and inject
only the bounded, validated context bundle returned by native Rust.

## Host capability limits

Adapters must report host limitations instead of guessing:

| Host | Shepherd assumption | Degradation |
| --- | --- | --- |
| Claude Code | Hooks and Agent Teams may be available. | If a hook or identity correlation is unavailable, the adapter reports the limitation and preserves its documented fail-closed posture. |
| Codex | Hook envelopes expose native agent identity and lifecycle events. | Missing identity or lifecycle facts produce a blocked or unresolved typed result, never a fabricated role. |
| Pi | A ready `SubagentProvider` is supplied by the host extension. | Missing provider, method, or readiness blocks mutation operations. |

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
bash scripts/tests/test-claude-plugin-release.sh
node packages/scripts/check-package-boundary.mjs
node packages/scripts/check-deps.mjs
```

The packed test must load the installed tarballs, not repository source paths.
The Claude release test separately loads the extracted release ZIP with no
repository runtime or dependency fallback.

## See also

- [Configuration](configuration.md) for the canonical project and user tiers.
- [Customization](customization.md) for doctrines and branch models.
- [Permissions](permissions.md) for host-side authorization.
