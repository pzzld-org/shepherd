# CODER REPORT — W0-S7 — `packages/` npm workspace skeleton

- Lane: l5-harness
- Skills loaded: code-style (no `typescript.md` ledger exists yet — applied shared
  principles per `code-style/SKILL.md`'s own fallback instruction: "If no file exists
  for the language, apply the shared principles below and note the gap"), typescript
  (`typing` skill's TypeScript surface not invoked — no type-level work in this
  skeleton step; JS/JSON only)

## Files changed

Created (all NEW; nothing pre-existing was modified):

- `/Users/jo3/src/fl03/shepherd/.worktrees/v645-l5-harness/package.json`
- `/Users/jo3/src/fl03/shepherd/.worktrees/v645-l5-harness/packages/compiler/package.json`
- `/Users/jo3/src/fl03/shepherd/.worktrees/v645-l5-harness/packages/compiler/README.md`
- `/Users/jo3/src/fl03/shepherd/.worktrees/v645-l5-harness/packages/compiler/test.mjs`
- `/Users/jo3/src/fl03/shepherd/.worktrees/v645-l5-harness/packages/harness-claude/package.json`
- `/Users/jo3/src/fl03/shepherd/.worktrees/v645-l5-harness/packages/harness-claude/README.md`
- `/Users/jo3/src/fl03/shepherd/.worktrees/v645-l5-harness/packages/harness-claude/test.mjs`
- `/Users/jo3/src/fl03/shepherd/.worktrees/v645-l5-harness/packages/harness-codex/package.json`
- `/Users/jo3/src/fl03/shepherd/.worktrees/v645-l5-harness/packages/harness-codex/README.md`
- `/Users/jo3/src/fl03/shepherd/.worktrees/v645-l5-harness/packages/harness-codex/test.mjs`
- `/Users/jo3/src/fl03/shepherd/.worktrees/v645-l5-harness/packages/harness-pi/package.json`
- `/Users/jo3/src/fl03/shepherd/.worktrees/v645-l5-harness/packages/harness-pi/README.md`
- `/Users/jo3/src/fl03/shepherd/.worktrees/v645-l5-harness/packages/harness-pi/test.mjs`
- `/Users/jo3/src/fl03/shepherd/.worktrees/v645-l5-harness/packages/scripts/check-deps.mjs`

All 14 files sit strictly inside `[FILE-SCOPE]` (`packages/` NEW + root `package.json`
NEW). `crates/**`, `services/cli/**`, `content/**` untouched. `git status --porcelain`
in the worktree confirms only `package.json` and `packages/` are new/untracked from
this lane; two other files (`commands/spawn.md`, `hooks/scripts/session_open.sh`) show
as modified but belong to sibling W0-S2 running concurrently in the same worktree —
not touched by this step.

## LOC delta

+464 / -0 (14 new files, `wc -l`; no cargo/Rust production involved, so the ONE-LOC
`*.rs` rule does not apply to this step — all lines are JSON manifests, Markdown
READMEs, and vanilla `.mjs`). Per-file: `package.json` 18, `compiler/package.json` 14,
`compiler/README.md` 17, `compiler/test.mjs` 15, `harness-claude/package.json` 17,
`harness-claude/README.md` 14, `harness-claude/test.mjs` 13, `harness-codex/package.json`
17, `harness-codex/README.md` 17, `harness-codex/test.mjs` 13, `harness-pi/package.json`
17, `harness-pi/README.md` 21, `harness-pi/test.mjs` 13, `packages/scripts/check-deps.mjs`
258. The estimate in the brief was ~200; actual is 464, driven almost entirely by
`check-deps.mjs` (258 lines) — a self-testing gate script with three rules plus three
synthetic-fixture negative controls plus a positive-control run against the real tree,
sized comparably to the two scripts it was asked to mirror (`scripts/check-workspace.sh`
361 lines, `scripts/check-plugin.sh` 309 lines, both with the same `--self-test`
discipline). This is a measured fact for the dispatcher's LOC governance, not an
adjudication — no deliverable was cut to fit the estimate (LOC-BUDGET-GOVERNANCE stays
the dispatcher's call, not mine).

## Acceptance outputs

All four commands run from the worktree root (`/Users/jo3/src/fl03/shepherd/.worktrees/v645-l5-harness`), verbatim stdout + actual exit code.

### 1. workspaces check

```
$ npm ls --workspaces --json >/dev/null 2>&1 || node -e "
const p=require('./package.json'); if(!p.workspaces) throw new Error('no workspaces');
console.log('workspaces:', p.workspaces.length)"
```
(no stdout — the left side of `||` succeeded)
Exit: 0

Diagnostic note (not part of the pass/fail contract, included for transparency): the
left branch (`npm ls --workspaces --json`) itself exits 0 with no `node_modules`
installed (npm resolves the root manifest and reports workspaces as empty rather than
erroring), so the `||` short-circuits before the `node -e` fallback runs. Confirmed
independently that `packages/*` really is declared:
```
$ node -e "const p=require('./package.json'); if(!p.workspaces) throw new Error('no workspaces'); console.log('workspaces:', p.workspaces.length)"
workspaces: 1
```
Exit: 0

### 2. directory existence

```
$ test -d packages/harness-claude && test -d packages/harness-codex && test -d packages/harness-pi && echo "PASS (all three dirs exist)"
PASS (all three dirs exist)
```
Exit: 0

### 3. dependency-rule gate

```
$ node packages/scripts/check-deps.mjs
checking 4 package(s): @fl03/compiler, @fl03/harness-claude, @fl03/harness-codex, @fl03/harness-pi

  no adapter depends on another adapter        ok
  adapter scoped deps are allowlisted          ok
  compiler does not depend on adapters         ok

ok: all 3 dependency rules hold.
```
Exit: 0

### Extra verification run (not in the brief's acceptance block, run for my own
confidence per the excellence bar — `--self-test` proving the rules are falsifiable,
plus a re-check against the real tree)

```
$ node packages/scripts/check-deps.mjs --self-test
self-test: every rule must be able to fail

  no adapter depends on another adapter        fails as designed
  adapter scoped deps are allowlisted          fails as designed
  compiler does not depend on adapters         fails as designed

ok: every rule is falsifiable.

confirming the real packages/ tree is accepted:
checking 4 package(s): @fl03/compiler, @fl03/harness-claude, @fl03/harness-codex, @fl03/harness-pi

  no adapter depends on another adapter        ok
  adapter scoped deps are allowlisted          ok
  compiler does not depend on adapters         ok

ok: all 3 dependency rules hold.
```
Exit: 0

Also confirmed each package's placeholder test fails as designed (exit 1, throws
`NotImplementedError` citing the Wave-4 step, never a fake issue number) and each
`package.json` parses as valid JSON — `compiler`, `harness-claude`, `harness-codex`,
`harness-pi` all exit 1 on `node packages/<pkg>/test.mjs`.

## Deviations

None from the brief. One clarifying note: `[CONTEXT-INVENTORY]` said to confirm the
Cargo workspace version via `cargo metadata --no-deps`; per this step's own
`[PROTOCOL-REMINDERS]` ("Do NOT run `cargo metadata` either — read the version straight
out of `Cargo.toml` with the Read tool instead") I read `Cargo.toml` directly instead —
`[workspace.package].version = "6.4.5"`, matching every `package.json` version in this
step. `packages/scripts/` (holding `check-deps.mjs`) is a subdirectory of `packages/`
and therefore also matched by the `packages/*` workspace glob; it carries no
`package.json` and npm silently skips it as a workspace member (confirmed empirically —
neither `npm ls --workspaces` nor the acceptance run below flags it), consistent with
`W4-S1`'s own plan reference treating `packages/scripts/*.mjs` as tooling, not a
publishable package.

## Staged GH commands

None — no GitHub interaction in this step (npm-only skeleton, no `gh` writes required
or attempted).

## Notes

Design decisions made while filling in what the brief left open, for the dispatcher and
for whoever writes W4-S1/S3/S4/S5/S6:

- **Root `package.json`** — `"private": true`, `workspaces: ["packages/*"]`, `version`
  pinned to `6.4.5` (read from `Cargo.toml`), plus `engines: { node: ">=20", npm:
  ">=10.3.0" }`. The npm floor documents the `libc`-field constraint W4-S1's own
  `[CONTEXT-INVENTORY]` names (`libc` landed in npm 10.3.0, npm/cli#6914) — harmless
  metadata now, saves W4-S1 from having to add it later.
- **Every sub-package** (`compiler`, `harness-claude`, `harness-codex`, `harness-pi`) —
  `"private": true` (NON-GOALS: do not publish anything this sprint), `version: "6.4.5"`
  matching the Cargo workspace pin (mirrors the pattern already used in `Cargo.toml`'s
  `[workspace.dependencies]`, e.g. `shepherd-core = { ..., version = "6.4.5" }`),
  `"type": "module"` (vanilla ESM, no bundler/transpile step, matching `[USER-STYLE]`).
  Each of the three `harness-*` manifests declares `"dependencies": { "@fl03/compiler":
  "6.4.5" }` — the one real dependency edge the architecture actually calls for (adapters
  consume the compiler's `compile()`); no other dependency exists yet because adapter
  logic is W4's job, not this step's.
- **`packages/scripts/check-deps.mjs`** is the load-bearing deliverable of Action 3.
  Modeled directly on the two Python `--self-test` scripts I read read-only
  (`scripts/check-workspace.sh`, `scripts/check-plugin.sh`): same `RULES` list-of-tuples
  shape, same `label.padEnd(44)` / `ok` / `FAILED` / `::error::` output convention, same
  "self-test builds a synthetic broken fixture in a temp dir per rule, then re-runs the
  real check" structure. Three rules: (1) no `@fl03/harness-*` package may depend on
  another `@fl03/harness-*` package in any dependency field; (2) a `harness-*` package's
  `@fl03/*`-scoped dependencies must be `@fl03/compiler` or match a reserved
  `@fl03/cli-*` platform-binary prefix (not populated until W4-S1 — the allowlist exists
  now so this gate does not need rewriting the day those packages land, and the prefix
  choice follows the `@biomejs/cli-<platform>` precedent D2's report names as the correct
  musl/`libc`-field exemplar, not esbuild); (3) `@fl03/compiler` must never depend back
  on a `harness-*` package. All three are exercised against the real `packages/` tree
  (accepts, 0 violations) and against three independent synthetic negative fixtures
  (each rejects, as designed) via `--self-test`.
- **READMEs** — one paragraph each, sourced from `discovery-d1-harness.md`'s probe-
  confirmed per-harness facts (Codex's two-primitive `[agent_types]` table and
  `max_concurrent_children = 3`, confirmed against the installed `codex-shepherd@1.0.2`
  bundle; Pi's jiti-loaded TS extension, `tool_call` guard signature, and lack of a
  native team primitive; Claude's closed `model:` enum) plus `plan.md`'s W4-S3/S4/S5/S6
  sections for what each package will eventually own, so the stub documents the real
  future shape rather than a generic placeholder.
- **Placeholder tests** — every `test.mjs` throws a local `NotImplementedError` class
  naming the exact future step (`W4-S3`/`S4`/`S5`/`S6`), never a fabricated GH issue
  number, per the brief's explicit instruction. Verified each exits 1.

## INSIGHTS

- kind: nit — `check-features.sh` / `check-workspace.sh` / `check-plugin.sh` all live at
  `scripts/*.sh` despite two of the three being Python (`#!/usr/bin/env python3` under a
  `.sh` name). `check-deps.mjs` follows the honest-extension convention instead
  (`.mjs` for real ESM) since the brief's own acceptance line invokes it via `node
  packages/scripts/check-deps.mjs` rather than as a bare executable — worth deciding,
  when W4-S1 adds more `packages/scripts/*.mjs` tooling, whether the repo wants one
  naming convention or is fine with the split by directory (`scripts/` = shell-named,
  `packages/scripts/` = extension-honest).

- Reporter: shepherd:coder @ 2026-08-13T00:36:07Z
