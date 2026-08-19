# `@pzzld/pi-codex`

The Codex adapter translates native hook envelopes into the typed
`fl03:shepherd@6.5.3` Component Model contract. The Rust component owns
identity normalization, guard policy, lifecycle planning, provider facts,
response validation, and canonical emission. Codex hooks only load the
adjacent packaged runtime, translate the hook envelope, and hand a typed
dispatch request to the native transport.

`hooks/scripts/shepherd_guard.mjs` handles PreToolUse and lifecycle events,
failing closed when the component is missing, invalid, or returns a native
identity response for another request. Codex's registered SubagentStart hook
is translated into typed resume when the host supplies `source_agent_id`.
Every native request and response is correlated by the Rust component before
host context is emitted, and capability-blocked starts fail closed. The
adapter exposes no separate apply executable; use
`shepherd compile --target codex --out <absolute-directory>` for descriptor-safe
installation.

The generated runtime is staged into `@pzzld/component-runtime/runtime` during
release and is never committed. `SHEPHERD_COMPONENT_MODULE` is a test or
embedding override only.
