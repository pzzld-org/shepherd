# `@pzzld/pi-shepherd`

The Pi adapter is a thin host extension over `@pzzld/component-runtime`.
Identity normalization, guard evaluation, lifecycle planning, provider
capability validation, and request-to-response exchange validation are implemented once by the
`fl03:shepherd@6.5.6` Rust WebAssembly component.

Pi contributes only its extension API and provider transport. At every root or
child `session_start`, after tools are registered, the production extension
calls Pi's public `pi.getAllTools()` API. Any compatible registered subagent
system is accepted when the configured tool metadata contains a tool named
exactly `subagent`. The probe intentionally does not use `getActiveTools()`. Every generated child
carrier includes `subagent` as a transport-registration tool and sets
`maxSubagentDepth: 2`, including roles that cannot dispatch. The Component's
compiled canonical role capabilities remain the policy authority: a managed child
whose canonical capabilities omit `dispatch` receives the exact no-dispatch block
before provider execution. A missing or malformed tool inventory leaves the
session readable but blocks Write, Edit, and Bash with one remediation:

```text
Pi subagent provider unavailable. Run `pi install npm:pi-subagents`, then restart Pi.
```

`pi install npm:pi-subagents` is the supported install or upgrade path for the
reference provider. Shepherd neither imports nor depends on that package.
Native `shepherd` bind and resolve requests remain the only identity authority.
Every bind, resolve, start, resume, and stop response is correlated by the
Component across its operation, optional run, harness, session, agent, lane,
role, tool-call ID, and operation-specific lifecycle fields before Pi consumes
it. Native `ExecutionContext` owns project and working-directory facts; the
guard separately cross-checks input-derived write paths. The lower-level
embedding adapter retains typed capability-envelope checks for direct provider
lifecycle calls. Production readiness uses only Pi's configured tool registry.
The machine-readable contract is
[`shepherd.pi.json`](./shepherd.pi.json); no shell fallback is used.

## Install

```sh
pi install npm:pi-subagents
pi install npm:@pzzld/pi-shepherd
```

Pi discovers everything this package contributes from the `pi` key in
`package.json`: `extensions`, `skills`, `prompts`, and `subagents.agents`. With
that declaration absent Pi loads no Shepherd agent definitions even when the
role prompts are present.

The nine skills, nine role prompts, and seven dispatchable agent definitions are
**generated**, not committed. The Rust compiler is their only authority, and a hand-copied
tree in this package would be a second, inevitably stale one -- `scripts/tests/test-generated-carrier-authority.sh`
fails if `skills/`, `prompts/`, or `agents/` appears in the repository. Release staging runs
`scripts/stage-pi-carrier.sh`, which invokes `shepherd compile --target pi` into
the staged package immediately before `npm pack`, so the published tarball
carries the carrier and the repository does not.

The published carrier is project-neutral. An `inherit-caller` role carries
`model: inherit`. Every other role carries `model: model-required/model-required`,
a generic intentionally impossible sentinel that prevents direct provider launch from
falling back to a parent or global default. Supported dispatch passes the exact concrete
`provider/model:thinking` result of `shepherd models resolve ROLE --harness pi` as a
per-run model override; the reference provider gives that override precedence.

Each generated agent explicitly reloads `src/extension.mjs` in nested children, registers the
`subagent` transport tool, and sets `maxSubagentDepth: 2`. Transport registration does not grant
dispatch authority. Before normal mutation guarding, the extension blocks a managed child's
`subagent` call unless that child's already-resolved Component canonical capabilities contain
`dispatch`; it does not infer a role from prompts, environment policy flags, or an adapter-owned
role list. The extension recognizes only `PI_SUBAGENT_CHILD=1` sessions with a compiler-emitted
dispatchable `shepherd:<role>` carrier. It derives bounded child identities from explicit provider
run/index fields and derives nested parents only from a validated `PI_SUBAGENT_PARENT_PATH`;
missing or mismatched ancestry fails closed.

Child-local terminal callbacks remain an early best effort. Each parent process also observes its
immediate descendants through Pi's public `tool_result`, `subagent:foreground-complete`, and
`subagent:async-complete` surfaces. Untrusted rows first enter a deduplicated queue capped at 64
candidates and three native correlation attempts each. That queue never blocks mutation. A row
moves to the mutation-blocking stop-pending set only after its explicit child run, index,
compiler-approved carrier, regular non-symlink session JSONL, exact session header, component
resolve plan, native exchange, and exact run/agent/carrier/session/role validation all succeed.
Session files are opened read-only, nonblocking, without following symlinks, and checked by
file type plus device/inode before the bounded first line is read. Once correlated, failed stops
remain blocking and retry only the exact stored stop at later safe boundaries; duplicate or forged
evidence cannot replace it. `subagent:async-started` is never terminal authority.

To materialize the same tree yourself against a checkout, use `shepherd compile
--target pi --out <absolute-directory>`; the adapter exposes no separate
materializer or CLI.

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
