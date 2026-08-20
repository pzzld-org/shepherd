# `@pzzld/component-runtime`

This package is the only JavaScript boundary for the generated
`fl03:shepherd@6.5.5` WebAssembly Component Model bindings. A release places
the generated ESM module, declarations, and adjacent core Wasm under
`runtime/`; `SHEPHERD_COMPONENT_MODULE` is an explicit test/embedding
override. It exposes only
typed identity, lifecycle, provider, response, guard, and canonical emission
calls.

Every native lifecycle and identity result crosses the typed
`validateNativeExchange` boundary with its original planned request. Schema
validation alone is insufficient because a valid response for another run,
session, agent, tool call, or resume source must fail closed.

The runtime does not accept a host-provided project identity. The adjacent
native `shepherd` process derives project and active-run custody from its
descriptor-safe execution context; the Component validates the typed exchange
facts available to the adapter. This split prevents a language adapter from
redirecting an otherwise valid exchange to an arbitrary project.

The package never parses policy files, invokes npm, searches the registry, or
falls back to the retired JavaScript compiler and guard implementations. A
missing or incomplete component fails closed with a machine-readable error.

This package does not own filesystem writes and exposes no second CLI. The
component returns a typed `emitted-tree` to language hosts; the official
descriptor-safe materializer is the canonical native command:

```sh
shepherd compile --target <claude|codex|pi> --out <absolute-directory>
shepherd compile --target <claude|codex|pi> --out <absolute-directory> --check
```

Stage a release runtime without modifying the repository:

```sh
SHEPHERD_COMPONENT_NODE_ROOT=/path/to/locked-node-root \
  scripts/stage-component-runtime.sh /tmp/shepherd-release-stage
```
