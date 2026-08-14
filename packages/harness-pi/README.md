# @fl03/harness-pi

`packages/harness-pi` is the adapter over `@fl03/compiler`'s `pi` emission target for the
`@earendil-works/pi-coding-agent` CLI. It has four responsibilities:

1. **Materialize** (`src/materialize.mjs`, `bin/materialize.mjs`) -- write `compile('pi')`'s
   `EmittedTree` onto disk: `prompts/*.md` (Pi's native per-file slash-command mechanism,
   filename -> `/name`, one per role -- Pi has no other file-declared-role format) and
   `skills/*/SKILL.md`. `compile()` itself never writes (`packages/compiler`'s own contract);
   this package is where the concrete write happens. There is no hardcoded default output
   directory anywhere in this package -- `--out` is a required CLI flag, never a guess at a
   real `~/.pi/agent/` or project `.pi/` install path, so running this adapter can never
   silently overwrite an operator's live Pi configuration.
2. **Resolve** (`src/models.mjs`, `src/tools.mjs`) -- close the two columns
   `content/RECONCILIATION.md` leaves as pointers for a later-wave Pi adapter: `model_hint`
   (`standard`|`reasoning-high`|`inherit-caller`) -> Pi's `--model <bare-id>` subprocess flag,
   and each role's abstract `capabilities` list -> Pi's `--tools` **replacing** allowlist
   (confirmed against the installed `@earendil-works/pi-coding-agent@0.84.1` binary's own
   tool registry, `allToolNames = new Set(["read","bash","edit","write","grep","find","ls"])`
   -- not `--help` text alone).
3. **Dispatch** (`src/dispatch.mjs`) -- Pi has no native per-role dispatch primitive
   (`discovery-d1-harness.md`: "absent as file-declared roles; a role = a CLI invocation").
   `setModel()` is session-global, so per-role model pinning costs one `pi` subprocess per
   role, never a frontmatter flag. This module builds that subprocess's `argv`/`env`; it
   never spawns one.
4. **Guard** (`src/predicates.mjs`, `src/guard.ts`, `src/extension.ts`) -- a jiti-loaded
   TypeScript extension, default-exported as `(pi: ExtensionAPI) => void`, registering
   `pi.on('tool_call', ...)`. Pi has no `hooks.json` module at all ("hooks do not exist as a
   module, they are extensions" -- `discovery-d1-harness.md`'s Pi probe), so this is a
   genuine second interpreter of `content/predicates/*.toml`, not a file copy, kept in
   lockstep with the spec by replaying its own `[[example]]` corpus directly
   (`test/guard-predicates.test.mjs`) rather than a hand-copied fixture list.

## `--tools` is a REPLACING allowlist

Confirmed against the installed binary's `pi --help` and its CLI source
(`args.ts`: "Comma-separated allowlist of tool names to enable... Only the named tools are
enabled"). `src/tools.mjs`'s `resolvePiTools(capabilities)` always returns a role's **full**
desired set -- never "built-ins minus a few" -- and separately reports which capabilities
have no Pi tool at all (`PI_UNSUPPORTED_CAPABILITIES`), so a gap is visible, not silently
dropped.

## The guard layer is a genuine port, not a file copy

`src/guard.ts` evaluates every rule in `content/predicates/{dedup-gate,dispatch-scope,
git-custody,write-boundary}.toml` against a concrete `(role, action, context)` tuple.
`src/extension.ts` wires three of the four into `pi.on('tool_call', ...)`, resolving role
identity from `SHEPHERD_ROLE` (and declared write scope from `SHEPHERD_SCOPE`) -- the same
two dispatch-envelope field names `skills/bridge/SKILL.md` already defines for cross-harness
handoffs, reused here rather than a second env-var convention. It **fails closed**: an
unidentified session (`SHEPHERD_ROLE` unset) gets no write/git/dispatch capability through
this guard, never every capability by default.

**Named gap -- `dedup-gate` is implemented and tested against its full corpus, but NOT wired
into a `tool_call` handler.** A dedup-gate verdict needs a resolved *symbol name* plus a
registry hit (`shctx query dedup-check --name=<symbol>`), and the `write`/`edit` `tool_call`
event Pi actually delivers (`{path, content}` / `{path, edits[]}`) carries neither.
Extracting "the one new public symbol this write introduces" from raw file content is
language-aware static analysis this guard layer does not perform. Emitting a handler that
always allows (or always denies) here would look complete while enforcing nothing -- naming
the gap is the honest result.

**No native team/subagent primitive.** Pi ships no spawn/parallel-agent primitive at all
(`discovery-harness-portability.md` §3: "No native spawn primitive... confirmed by the
complete `extensions.md` event catalog... containing no spawn/team/parallel-agent event").
The only implementation is the third-party `@tintinweb/pi-subagents` extension, described by
its own README as "early release status." This package does **not** depend on it
(`test/team-primitive-absent.test.mjs` asserts `package.json` never gains that dependency) --
multi-agent dispatch is declared absent for Pi rather than emulated on unvetted third-party
code, matching this step's `[NON-GOALS]`.

## Model pinning: bare ids, not Claude's `[1m]` annotation

`src/models.mjs` maps `model_hint` to the same Claude-side slug
`skills/context/references/model-map.md`'s `[models]` table already uses
(`reasoning-high` -> `opus[1m]`, `standard` -> `sonnet`), then strips the extended-context
annotation: Pi's `--model <pattern>` flag takes a bare provider model id/pattern
(`"provider/id"` and optional `":<thinking>"`), not Claude's `[1m]` context-window toggle.
`root`/`shepherd` (`model_hint: inherit-caller`) is never spawned as its own subprocess by
this adapter -- root IS the already-running session, matching `model-map.md`'s own "`root`
is advisory" note.

## Node version

`src/extension.ts`, `src/guard.ts`, and `src/pi-types.ts` are TypeScript, loaded directly by
Node's own type-stripping (no build step, matching how Pi itself loads extensions via jiti).
Unflagged type-stripping is Node's default from 23.6.0; `npm test` here passes
`--experimental-strip-types` explicitly (`package.json`'s `test` script) so the suite also
runs correctly back to Node 22.6.0, where the feature exists behind that flag. This is a
deliberate divergence from the workspace root's and sibling packages' `"node": ">=20"` floor
-- `packages/harness-pi/package.json` declares `">=22.6.0"`.

## CLI

```
node packages/harness-pi/bin/materialize.mjs --out=<dir> [--check] [--list]
```

`--check` materializes twice into the same `--out` and asserts the second pass produced
byte-identical files on disk -- the filesystem-level analogue of `compile()`'s own
`--check`. `--list` prints every path `compile('pi')` would emit and writes nothing.

Implemented in Wave 4 (W4-S6).
