# `@fl03/harness-claude`

The Claude Code adapter translates native hook envelopes into the typed
`fl03:shepherd@6.4.5` Component Model contract. The Rust component owns
identity normalization, guard policy, lifecycle planning, provider facts,
response validation, and canonical emission. Claude hooks only load the
adjacent packaged runtime, translate the hook envelope, and hand a typed
dispatch request to the native transport.

`hooks/guard-eval.mjs` is fail-closed when the component is missing, invalid,
or returns a native identity response for another request. `hooks/dispatch-lifecycle.mjs`
handles SessionStart, SubagentStart, SubagentResume, and SubagentStop through
the component's lifecycle plan. Claude's registered SubagentStart hook is
translated into typed resume when the host supplies `source_agent_id`. Every
native request and response is correlated by the Rust component before host
context is emitted, and capability-blocked starts fail closed. The adapter
exposes no separate materializer or CLI; use `shepherd compile
--target claude --out <absolute-directory>` for descriptor-safe installation.

The generated runtime is staged into `@fl03/component-runtime/runtime` during
release and is never committed. `SHEPHERD_COMPONENT_MODULE` is a test or
embedding override only.

## Release archive

Claude's GitHub marketplace source copies repository bytes. It cannot select a
generated GitHub release asset, so the source checkout is not advertised as an
installable marketplace plugin: it intentionally has no generated component
runtime. The production Claude boundary is the complete, bundled release archive
`shepherd-claude-plugin-6.4.5.zip`; it is not self-contained because Claude
executes its hooks with Node and delegates dispatch to the native CLI.

Hard prerequisites: Node.js 20 or newer, because the adapter intentionally
hosts the WebAssembly Component Model in Node, and the native `shepherd`
executable on `PATH`. `SHEPHERD_NATIVE_BIN` may name that executable explicitly
for an embedded installation.

After meeting those prerequisites, load the release for one Claude session:

```sh
claude --plugin-url \
  https://github.com/FL03/shepherd/releases/download/v6.4.5/shepherd-claude-plugin-6.4.5.zip
```

`--plugin-url` is a session-only Claude Code option. It does not install a
persistent marketplace entry. For checksum-first loading, download the ZIP and
its `.sha256` sidecar, verify them with `sha256sum --check` (or
`shasum -a 256 --check` on macOS), then run:

```sh
claude --plugin-dir ./shepherd-claude-plugin-6.4.5.zip
```

Contributors build the exact same archive without changing the checkout:

```sh
npm ci --ignore-scripts
cargo build --locked --release -p shepherd-component --target wasm32-wasip2
scripts/build-claude-plugin-release.sh /absolute/output/directory
scripts/tests/test-claude-plugin-release.sh
```

The build is reproducible and emits the ZIP plus its SHA-256 sidecar. The test
extracts a clean fixture, verifies the canonical carrier inventory, executes
the real staged guard hook using its adjacent runtime, and runs
`claude plugin validate --strict` when the Claude CLI is available.
