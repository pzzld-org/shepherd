# @fl03/harness-claude

The Claude Code adapter over `@fl03/compiler`'s `claude` emission target. Implemented in
Wave 4 (`W4-S4`). Thin by design ([USER-STYLE]): the only real logic this package owns is
what is genuinely per-harness -- `model_hint` resolution, disk materialization, and the
PreToolUse guard relay -- everything else (parsing `content/`, sorting, hashing, frontmatter
grammar) is imported from `@fl03/compiler`, never re-implemented.

## Pipeline

```
compile("claude")          @fl03/compiler -- roles + skills, model_hint UNRESOLVED
  -> finalizeClaudeTree()  src/finalize.mjs -- resolves model_hint -> model: via src/model.mjs
  -> materialize(tree, targetDir)   src/materialize.mjs -- writes the tree to disk
```

`finalizeClaudeTree` and `materialize` are pure/side-effecting in exactly the way their
names suggest: the former is a deterministic transform (reproducibility proven in
`test/reproducibility.test.mjs`, mirroring `packages/compiler/test/reproducibility.test.mjs`
one level up the pipeline); the latter never assumes a target directory -- it is always
caller-supplied, so nothing in this package's own test suite writes outside a throwaway temp
dir. Materializing onto the LIVE `agents/`/`skills/` tree at the repo root is a future
step's job, not this one's -- `packages/harness-claude/` is this step's entire file scope.

## Model resolution (`src/model.mjs`)

`content/roles/*.md`'s `model_hint` is carried through `compile("claude")` unresolved (that
resolution is adapter work, per `discovery-d1-harness.md`'s Core-vs-adapter split). The
table is a transcription off the currently committed `agents/*.md`, not a guess --
`test/model.test.mjs` checks all 9 roles against the live files:

| `model_hint` | `model:` | roles |
|---|---|---|
| `standard` | `sonnet` | auditor, coder, conductor, critic, discovery, worker |
| `reasoning-high` | `opus[1m]` | engineer, planter |
| `inherit-caller` | `inherit` | shepherd (root) |

`opus[1m]` and `inherit` are both legal values in the live tree today, wider than the
`sonnet\|opus\|haiku\|fable` enum plan.md's own context inventory names as closed -- this
adapter matches the tree that is actually deployed, not the simplified description of it.

## Declared ceilings (`src/ceilings.mjs`)

Claude's two real `Workflow`-tool dispatch caps (`skills/harness/SKILL.md` `## Workflow
tool`: "~16 concurrent agents; 1,000 total dispatches per run"), declared as constants
rather than discovered at runtime -- the same discipline `packages/harness-codex`'s
`max_concurrent_children = 3` and `packages/harness-pi`'s absent-team-primitive declaration
apply to their own harnesses.

## Guard-layer wiring (`src/guard.mjs`, `hooks/guard-eval.mjs`)

Decision 2 (seed): guard predicates (`content/predicates/*.toml`) are interpreted by exactly
ONE evaluator on Claude and Codex -- the shared Rust engine -- with Pi's TS interpreter as
the only second one. `src/guard.mjs` is therefore deliberately not a predicate interpreter:
`hooks/guard-eval.mjs` is a thin PreToolUse relay that forwards the hook payload to
`bin/shepherd guard eval` and translates the verdict back into Claude's own hook-output
shape (`{"permissionDecision":"deny","message":"..."}` to block, silence to allow -- verified
against this repo's own live `hooks/scripts/_lib.sh`). All decision logic
(`interpretEngineResult`, `engineUnavailableVerdict`) lives in `src/guard.mjs`, unit tested
in `test/guard.test.mjs` with an explicit allow case and an explicit deny case (plan.md
[ACCEPTANCE]'s cross-adapter requirement, proven at this adapter's own level since
`packages/scripts/predicate-coverage.mjs` -- the shared cross-adapter enforcer of that line
-- belongs to no single adapter's file scope).

**Named gap, not silently degraded:** `crates/cli` exposes no `guard eval` subcommand as of
this adapter's base commit (`crates/cli/src/cmd.rs`'s only variant is `Init`) -- the "shared
Rust engine" plan.md's Action 2 names has no CLI surface yet, and `crates/**` is outside this
step's file scope to build one. `src/guard.mjs`'s module doc comment declares the exact
contract that engine needs to satisfy (stdin JSON in, `{"decision":"allow"|"deny",...}` on
stdout, exit 0 for a successful evaluation either way) so the relay has a concrete target,
and fails CLOSED (never a silent allow) when that engine is unreachable -- confirmed live
against the actual `bin/shepherd` launcher on this box, which currently resolves to `shctx`
(a different, pre-existing tool) rather than the Rust binary; `bin/shepherd guard eval`
correctly surfaces as `guard engine unavailable, failing closed: exit 1: ERROR: unknown
subcommand: guard`, not a hang or a false allow.

## Run-state interop (`src/run-state.mjs`, `test/advance-run.mjs`) -- release-gate C.4

`test/advance-run.mjs <run-id>` is release-gate criterion C.4's JS half:

```bash
./target/release/shepherd run init c4probe &&
  node packages/harness-claude/test/advance-run.mjs c4probe &&
  ./target/release/shepherd run show c4probe | grep -q '"status"'
```

`src/run-state.mjs`'s `toCanonicalJson` is a byte-exact JS port of
`crates/core/src/run/canonical.rs` (recursively sorted keys, 2-space indent, ASCII-only with
`\uXXXX` escaping including astral surrogate pairs) -- `test/run-state.test.mjs` proves the
byte match against the REAL, Rust-written `.shepherd/runs/v645/run.json` on disk, not a
synthetic fixture. `advanceRunState` moves `status` one step through the closed lifecycle
(`planted -> planned -> executing -> closing -> closed`, idempotent at `closed`) and stamps
`updated_at`; every other field -- named by the schema or not -- round-trips unchanged, which
is what makes "no migration step" true by construction rather than by care (the exact #247
regression class `crates/core/src/run.rs`'s own module doc names).

## Known divergences from the hand-maintained tree (`test/finalize.test.mjs`)

This step's dispatch brief: "diff your emission against [agents/, commands/, skills/, and
hooks/] and report every divergence... which one it is matters." `test/finalize.test.mjs` is
that diff, pinned as a deterministic, self-updating test rather than a one-off read. Current
state, all 9 roles:

- **Intentional additions** (content gap closed, not opened): every compiled role file gains
  `dispatchable`, `write_eligible`, `write_scope` -- new machine-readable write-boundary
  facts `agents/*.md` never carried. This is the whole point of the `content/` migration.
- **Content gap** (hand-maintained field with no `content/roles/*.md` source): `color`,
  `description`, and (`conductor`/`engineer`/`planter`/`shepherd` only) `effort`. Fabricating
  values for these would be inventing data `content/` does not provide -- flagged for a
  follow-up `content/roles/*.md` schema step, not fabricated here.
- **Compiler-layer findings** (out of this step's file scope --
  `packages/compiler/src/capabilities.mjs` -- to fix): `capabilitiesToClaudeTools` currently
  over-grants relative to every hand-maintained role, never under-grants (`test/finalize.test.mjs`
  pins the exact extra set per role so a NEW, unaccounted-for one fails the test):
  - `NotebookRead` granted universally by the `read` capability, though only `discovery`'s
    hand-maintained grant actually carries it.
  - `LSP` granted to `auditor` via `code-intelligence`, absent from `agents/auditor.md`
    entirely (a CHANGELOG entry shows `discovery` carried `LSP` once, years ago; nothing
    live carries it today).
  - `Workflow` granted to `planter` via `dispatch` (which maps to `[Agent, Workflow]`),
    though `agents/planter.md` grants only `Agent` -- every OTHER `dispatch`-capable role
    (conductor, engineer, shepherd) does carry `Workflow` by hand, so this is planter-specific
    and unexplained anywhere in its own prompt body.
  - `Edit` granted to `worker` via `write` (which maps to `[Write, Edit]`), though
    `agents/worker.md` grants only `Write` -- consistent with
    `content/roles/worker.md`'s own `write_scope` ("`*.md` deliverables only... never
    source"), a Write/Edit distinction the capability table does not carry.
- **No `commands/*.md` in the compiled tree at all.** `content/` has no `content/commands/`
  source tree (W0-S8 never created one; `content/RECONCILIATION.md` row 3 treats the
  command wrapper as contributing zero facts `content/roles/planter.md` doesn't already
  carry). The live `commands/` directory (7 files) has no compiled counterpart -- a real,
  named content gap, not something this adapter can close without a `content/commands/`
  source existing first.
- **No full `hooks/hooks.json` emission.** This adapter emits the guard-predicate PreToolUse
  entry (`buildGuardHooksEntry`) only. The live `hooks/hooks.json`'s many OTHER matchers
  (`SessionStart` bootstrapping, `teammate_heartbeat.sh`, `worktree_teardown_guard.sh`, and
  so on) are shepherd-operational concerns with no `content/predicates/*.toml` source --
  reconciling them is a separate, larger effort than "wire the guard layer," and out of this
  step's file scope to write into `hooks/` at the repo root regardless.

## Tests

```bash
node packages/harness-claude/test.mjs                          # every test/*.test.mjs
node packages/harness-claude/test/reproducibility.test.mjs      # byte-identical across 2 calls
node packages/harness-claude/test/model.test.mjs                # model_hint -> model:, vs agents/*.md
node packages/harness-claude/test/finalize.test.mjs             # the pinned hand-tree diff
node packages/harness-claude/test/materialize.test.mjs          # disk write, temp dir only
node packages/harness-claude/test/guard.test.mjs                # allow + deny + 2 failure modes
node packages/harness-claude/test/run-state.test.mjs            # canonical JSON, golden byte match
node packages/harness-claude/test/advance-run.mjs <run-id>       # release-gate C.4 (needs a real run.json)
```
