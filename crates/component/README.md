# shepherd-component

This crate exports the pure Shepherd guard and content compiler through the
WebAssembly Component Model. The interface is defined in `wit/shepherd.wit`.
The public compiler and guard operations consume the embedded canonical corpus:
hosts choose a canonical target and receive a typed guard verdict or error, but
never pre-parse role/skill metadata, supply a second policy corpus, or provide
source provenance that can disagree with its bytes. The component does not
discover files, inspect a harness, open a registry, or spawn a process.

Build the component core for WASI Preview 2 with:

```console
cargo build -p shepherd-component --target wasm32-wasip2 --release
```

The WIT contract is the stable cross-language boundary. Harness-specific
filesystem and process work remains in native adapters.

## Dispatch contract

`fl03:shepherd@6.4.7` exports one typed dispatch surface in addition to the
canonical compiler and guard operations:

- `normalize-identity` accepts a typed `identity-input` and returns a
  validated `normalized-identity` with a deterministic identity key. The
  `tool-use-id` field is retained for audit correlation and is never included
  in that key.
- `plan-lifecycle` accepts a normalized identity and an optional typed
  `dispatch-binding`, returning a `dispatch-plan` whose request variant is one
  of `bind-root`, `start`, `resolve`, `stop`, or `resume`.
- `evaluate-provider` accepts a typed capability probe and returns a complete
  capability report with `ready`, `degraded`, or `blocked` readiness. Missing
  providers are represented as blocked reports, not as adapter-specific
  guesses.
- `validate-response` validates typed native identity-resolution facts, including role,
  identity completeness, write-scope derivation, capability diff, and tool
  correlation shape.
- `validate-native-response` validates the operation-specific response for
  `bind-root`, `start`, `resolve`, `stop`, and `resume`, including terminal
  state and bounded resume-context invariants.
- `validate-native-exchange` validates the typed request and response together,
  proving that run, harness, session, identity, role, lane, tool call, revision,
  capability probe, lease, and resume source belong to the same operation.

The core owns these rules for Claude, Codex, and Pi. Adapters only decode host
events, populate the WIT records, invoke the component, and translate the
typed result into their host event envelope. There is no generic policy JSON,
source-byte input, or host-provided role/skill parser at this boundary.

## Node runtime contract

The release probe runs `npm ci --ignore-scripts` from the root lockfile, then
uses only `node_modules/.bin/jco` at the locked
`@bytecodealliance/jco@1.28.1`. It never invokes `npm exec` or accesses the
registry at runtime. The probe copies the component and its Node assertion
module to a temporary staging directory before transpilation. Generated
JavaScript, core Wasm, declarations, and the `node_modules` shim symlink stay
there and are deleted on exit. No generated runtime asset belongs in the
repository.

The current component imports these 14 WASI Preview 2 interfaces, which jco
resolves with its locked `@bytecodealliance/preview2-shim` dependency:

- `wasi:cli/environment@0.2.6`
- `wasi:cli/exit@0.2.6`
- `wasi:cli/stderr@0.2.6`
- `wasi:cli/stdin@0.2.6`
- `wasi:cli/stdout@0.2.6`
- `wasi:cli/terminal-input@0.2.6`
- `wasi:cli/terminal-output@0.2.6`
- `wasi:cli/terminal-stderr@0.2.6`
- `wasi:cli/terminal-stdin@0.2.6`
- `wasi:cli/terminal-stdout@0.2.6`
- `wasi:io/error@0.2.6`
- `wasi:io/poll@0.2.6`
- `wasi:io/streams@0.2.6`
- `wasi:random/insecure-seed@0.2.6`

The exact sorted import contract is checked into
`wit/resolved-imports.txt`. Both the local WASM gate and CI diff the imports
extracted by pinned `wasm-tools 1.254.0` against that file. The list reflects
Rust's current WASI Preview 2 runtime surface; it does not grant filesystem or
network authority.

The repository probe is POSIX-only: its Bash harness stages under a POSIX
temporary directory and uses a temporary `node_modules` symlink. That is a
development-gate constraint, not a requirement of the published Component or
Node runtime. The packaged runtime resolves its adjacent dependencies and does
not create this probe symlink on the user's host.
