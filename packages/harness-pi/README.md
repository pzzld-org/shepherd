# `@pzzld/pi-shepherd`

The Pi adapter is a thin host extension over `@pzzld/component-runtime`.
Identity normalization, guard evaluation, lifecycle planning, provider
capability validation, and request-to-response exchange validation are implemented once by the
`fl03:shepherd@6.4.9` Rust WebAssembly component.

Pi contributes only its extension API and provider transport. The extension
requires an explicit `SubagentProvider` for lifecycle `spawn`, `resume`, and
`stop`; native `shepherd` bind and resolve requests are the only identity
authority. Every bind, resolve, start, resume, and stop response is correlated
by the Component across its operation, optional run, harness, session, agent,
lane, role, tool-call ID, and operation-specific lifecycle fields before Pi
consumes it. Native `ExecutionContext` owns project and working-directory
facts; the guard separately cross-checks input-derived write paths. The
adapter probes the provider capability envelope before every lifecycle
operation and returns `capability_blocked` without invoking provider lifecycle
methods when the envelope is malformed, degraded, blocked, or absent. It also
fails closed when the component or native root binding is absent. A resume
provider result must use a new agent ID: the supplied ID is the persisted
source identity. If any post-resume publication or exchange validation fails,
the adapter stops that newly returned child; if cleanup also fails, both errors
are retained in an `AggregateError`. Stop publication persists the native
terminal record before provider termination, so a native stop failure leaves
the provider child running for retry. `pi-subagents`-class extensions are
supported through the machine-readable [`shepherd.pi.json`](./shepherd.pi.json)
contract; no shell fallback is used.

The adapter exposes no separate materializer or CLI. Use `shepherd compile
--target pi --out <absolute-directory>` for descriptor-safe installation.

Pi loads the generated component from the adjacent runtime packaged in
`@pzzld/component-runtime/runtime`. `SHEPHERD_COMPONENT_MODULE` is reserved
for tests and controlled embedding. Release staging is performed by
`scripts/stage-component-runtime.sh`; generated `.wasm`, `.js`, and `.d.ts`
files are not committed to the repository.

Node 20 or newer is required. The published runtime is JavaScript; separate
declarations preserve the Pi extension types without runtime type stripping.
Run the adapter gate with:

```sh
node test.mjs
```
