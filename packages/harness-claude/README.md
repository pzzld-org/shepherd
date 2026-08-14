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

## Guard-layer wiring (`src/guard.mjs`, `src/dispatch-record.mjs`, `hooks/guard-eval.mjs`)

Decision 2 (seed): guard predicates (`content/predicates/*.toml`) are interpreted by exactly
ONE evaluator on Claude and Codex -- the shared engine -- with Pi's TS interpreter as the
only second one. `src/guard.mjs` is therefore deliberately not a predicate interpreter:
`hooks/guard-eval.mjs` is a thin PreToolUse relay that resolves `role` locally, then forwards
the resolved request to `bin/shepherd guard eval` and translates the verdict back into
Claude's own hook-output shape (`{"permissionDecision":"deny","message":"..."}` to block,
silence or `{"additionalContext":"..."}` to allow -- verified against this repo's own live
`hooks/scripts/_lib.sh`'s `emit_deny`/`pass_silent`/`emit_context`). All decision logic
(`buildGuardDecision`, `interpretEngineResult`, `engineUnavailableVerdict`,
`missingRecordWarnedVerdict`, `roleResolutionUnavailableVerdict`) lives in `src/guard.mjs`,
unit tested in `test/guard.test.mjs` with an explicit allow case, an explicit deny case, AND a
live integration case that spawns the real engine (plan.md [ACCEPTANCE]'s cross-adapter
requirement, proven at this adapter's own level since `packages/scripts/predicate-coverage.mjs`
-- the shared cross-adapter enforcer of that line -- belongs to no single adapter's file
scope).

**Role resolution (closes the W10 auditor's HIGH finding).** The relay used to forward
`{...JSON.parse(raw), harness:"claude"}` with no `role` key, ever -- wired into
`hooks/hooks.json` live, that would have hit the engine's missing-role `unresolved` path for
EVERY Write/Edit/Bash/Agent/Workflow call from EVERY role, including root's own git
operations, and denied project-wide. `src/dispatch-record.mjs`'s `resolveRole` closes it with
a three-way split SHAPED like `packages/harness-codex/src/dispatch-record.mjs`'s own (same
three `kind`s), evaluated BEFORE the engine is ever consulted: no marker (root, never
dispatched) -> allow; marker + a resolved dispatch record -> forward `role` to the engine for
a real decision; marker + no record -> WARN loudly and let the call through (`missing-record`
-- see below; this was DENY through an earlier pass at this file, corrected). Unlike Codex,
this adapter does not build a new tagging mechanism -- Claude already has one, shipped by a
sibling step in this same run (DF-77: `hooks/scripts/agent_invocation_tagger.sh` +
`current_role()`, `hooks/scripts/_lib.sh`) -- so `resolveRole` shells out to that real hook
library (one bash subprocess, sourcing `_lib.sh` and calling its own exported
`current_sprint()` / `current_role()` / `resolve_namespace()` verbatim) rather than
re-deriving the `tool_use_id` -> dispatch-record correlation a second time in JS. The one
thing `current_role()` does not resolve on its own -- Claude's `PreToolUse` payload carries no
verified per-caller identity field the way Codex's `agent_id` does, an acknowledged open gap
(DF-77 FIX 3, `_lib.sh`'s own `current_role()` header) -- is only PARTLY broken by ONE narrow,
additional signal `current_role()` never consults: whether this sprint's dispatch dir holds
ANY tagged record at all. That signal answers "has this sprint dispatched anything, ever," not
"did THIS call come from a dispatch" -- it is `true` for the whole remainder of every real
sprint from its first dispatch onward, so it cannot tell root's own call apart from an
untraceable dispatched one; it now shapes the WARNING message only, never the allow/deny
choice (see `src/guard.mjs`'s "MISSING-RECORD POSTURE, CORRECTED"). `test/guard.test.mjs`'s
own integration section proves all three outcomes end to end, through the real relay, the real
`agent_invocation_tagger.sh`, and (for the deny case) the real live engine, against a dispatch
directory SEEDED with several unrelated records first -- the shape of a real sprint, never an
empty sandbox -- never a hand-authored dispatch record or an injected `role` field.

**Is the relay safe to wire into `hooks/hooks.json` now?** Yes -- but that answer changed
since this section was last written, and the change is the whole reason to re-read it: an
earlier pass at this file answered "yes" here on the strength of an integration test whose
FIRST case ran against a freshly-`git init`'d, zero-dispatch-record sandbox -- `hasMarker`
false, `no-marker`, silent allow. That is NOT the shape of a real sprint. Measured against the
REAL repo, with a REAL fresh `tool_use_id` (`toolu_01FRESHCALLxxxxxxxxxx`, the shape this
session actually sends) and this sprint's own, genuinely non-empty
`.shepherd/dispatch/v6.4.5/` (64 tagged records):

```
$ echo '{"session_id":"s1","tool_use_id":"toolu_01FRESHCALLxxxxxxxxxx","tool_name":"Bash","tool_input":{"command":"git status"}}' | node packages/harness-claude/hooks/guard-eval.mjs
$ echo '{"session_id":"s1","tool_use_id":"toolu_01FRESHCALLxxxxxxxxxx","tool_name":"Write","tool_input":{"file_path":"/tmp/x"}}' | node packages/harness-claude/hooks/guard-eval.mjs
```

Before this fix, BOTH denied -- a plain `git status`, a plain `Write`, from a session
indistinguishable from root's own -- 100% of live calls, unconditionally, for the entire
remainder of any sprint that had ever dispatched once. Wiring that version into
`hooks/hooks.json` would have taken down every tool call in the operator's own session, not
just a coder's. After this fix, run against the same real repo, the same real command, the
same fresh id: NEITHER denies (`additionalContext` warns instead, no `permissionDecision`
key) -- verified live above, not in a sandbox. The specific blast radius the W10 auditor
named, AND the "10th instance of the dominant defect class" this later fix closes, are both
now closed against the actual runtime precondition, not a manufactured one.

One caveat, named rather than hidden, and unchanged by this fix: `current_role()`'s own
correlation gap (DF-77 FIX 3) is still open, so this relay still cannot tell "root, mid-sprint"
apart from "an untraceable dispatched call, mid-sprint" -- both resolve to `current_role()`'s
literal `"unknown"`. This adapter's posture for that ambiguity is now WARN-and-allow, matching
`hooks/scripts/coder_git_guard.sh`'s own shipped DF-77 FIX 2 posture for the identical
ambiguity (never deny an unresolved role) -- not a NEW gap this relay introduces, but the
SAME accepted one already shipped elsewhere in this codebase for git writes specifically, now
applied consistently across the wider Write/Edit/Bash/Agent/Workflow matcher this relay
covers. Concretely: an untraceable dispatched call's write is NOT enforced by this relay until
DF-77 FIX 3 lands a real per-call correlation key -- it warns, loudly, naming the gap, and lets
the call through. A genuinely resolved role (the common case -- a coder's dispatch really was
tagged) is unaffected and still reaches the real engine for a real decision, proven above.
Wiring `hooks/hooks.json` itself remains root's call, out of this step's file scope regardless
of this finding.

**Engine exists, LIVE (DF-76 -- this note replaces a prior "named gap" that predates the
engine)**: the engine is `services/cli/shepherd_cli/` (`commands/guard.py` + `predicates.py`),
Python, served through `bin/shepherd guard eval` -- NOT `crates/cli`, which remains a second,
near-empty binary (`crates/cli/src/cmd.rs`'s only variant is `Init`) and was never the CLI
surface this relay shells out to. `bin/shepherd` on this box resolves to the real bash
launcher at the repo root (its own header: "the single canonical entrypoint for the shepherd
CLI"), not `shctx` -- confirmed live: `echo '{"role":"coder","tool_name":"Bash","tool_input":
{"command":"git commit -am x"}}' | bin/shepherd guard eval` returns
`{"decision": "deny", "predicate": "git-custody", "rule": "implementer-never-writes-git",
"halt_code": "CODER-GIT-WRITE", ...}`, exit 0. The relay still fails CLOSED (never a silent
allow) if the engine becomes unreachable for any reason (missing venv, bad stdin, `content/`
not found) -- that path is unit tested via `engineUnavailableVerdict`, not re-verified live
here since it requires deliberately breaking the engine.

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
node packages/harness-claude/test/guard.test.mjs                # allow/deny/unresolved + failure modes + live 3-way role-resolution matrix (populated dispatch dir)
node packages/harness-claude/test/run-state.test.mjs            # canonical JSON, golden byte match
node packages/harness-claude/test/advance-run.mjs <run-id>       # release-gate C.4 (needs a real run.json)
```
