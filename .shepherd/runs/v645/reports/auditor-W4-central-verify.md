---
title: W4 central verification — content compiler + three harness adapters
date: 2026-08-13
auditor: central-verification-auditor
sprint: v6.4.5
concern: central-verification (compiler/adapter reproducibility, guard falsifiability, model-pin correctness)
mode: close
methodology: superpowers:systematic-debugging (falsify-don't-confirm; every claim re-run at HEAD, not accepted from self-report)
prior_class_priors: none consulted — first central-verify pass for this concern class this session (adaptation registry not queried; no adapt priors tool available in this dispatch's toolset)
---

## Scope reviewed

Read-only build-and-verify pass over W4-S3 (`packages/compiler/`), W4-S4
(`packages/harness-claude/`), W4-S5 (`packages/harness-codex/`), W4-S6
(`packages/harness-pi/`) at live HEAD (`v6.4.5`, commit `337f2365`, working tree
matches the four steps' self-reported `files_touched` exactly — confirmed via
`git status --porcelain`). I am the only agent this wave permitted to build; I built
`crates/cli` (`cargo build --release -p shepherd-cli`) to independently verify the
Rust CLI subcommand surface referenced by W4-S4's release-gate C.4 claim, rather than
trusting the coder's static-read claim. 27 files reviewed directly (all new/modified
files under the four packages), plus `content/roles/*.md` (9), `content/RECONCILIATION.md`,
`content/predicates/write-boundary.toml`, `agents/*.md` (9), and `crates/cli/src/cmd.rs`.

All acceptance commands were run serially from the repo root (`/Users/jo3/src/fl03/shepherd`),
each redirected to its own log file with its own `echo "EXIT:$?"` captured immediately
after, never `$?` read through a pipe. `bin/shepherd lint` was run from
`/Users/jo3/src/fl03/shepherd` (repo root) per the DF-72 warning — `pwd` printed
immediately before it confirms this.

## THE FOUR QUESTIONS

### Q1 — Is emission reproducible?

**PASS.** Each target compiled twice via `--check` (which itself performs two
in-process `compile()` calls and diffs the digest) and I additionally ran each
package's full `test/reproducibility.test.mjs`, which re-derives byte equality
independently of `--check`'s own code path.

```
$ node packages/compiler/bin/compile.mjs --target=claude --check
ok: compile('claude') is idempotent -- 16 file(s), digest f9ddac89ad11bee6fc7ddfdcfc0ba5a1dd65854c54a79e0ccbbbbb6688baa61c
EXIT:0

$ node packages/compiler/bin/compile.mjs --target=codex --check
ok: compile('codex') is idempotent -- 7 file(s), digest c3d60acb91f10e607e8f9e3742c58592c54f5e5b86c4d8686f8c46a42ad3b486
EXIT:0

$ node packages/compiler/bin/compile.mjs --target=pi --check
ok: compile('pi') is idempotent -- 15 file(s), digest 8cfa1edb6119c0733fbf254b93845349cd362e53b94f7630fc8b39dd1299222d
EXIT:0
```

Full suites, run serially from repo root:

```
$ node packages/compiler/test.mjs        -> 3/3 test file(s) passed, EXIT:0
$ node packages/harness-claude/test.mjs  -> 6/6 test file(s) passed, EXIT:0
$ node packages/harness-codex/test.mjs   -> 6/6 test file(s) passed, EXIT:0
$ cd packages/harness-pi && node --experimental-strip-types test.mjs -> 8/8 test file(s) passed, EXIT:0
```

`compile()` performs no disk I/O (confirmed: `git status --porcelain` before/after
every one of the above runs is byte-identical to the wave's own baseline listing —
no stray files appeared). Emission is a pure function of `content/` as claimed.

### Q2 — Did Codex get a command surface it must not have?

**PASS — zero command surface.** `--list` for `codex` prints exactly 7 paths, none
prefixed `commands/`, `prompts/`, or `agents/`:

```
$ node packages/compiler/bin/compile.mjs --target=codex --list
shepherd.codex.toml
skills/adaptation/SKILL.md
skills/bridge/SKILL.md
skills/context/SKILL.md
skills/motivation/SKILL.md
skills/shepherd/SKILL.md
skills/thinking/SKILL.md
EXIT:0

$ grep -c '^commands/' <above output>
0
```

`node packages/compiler/test/codex-no-command-surface.test.mjs` independently
confirms: `ok: compile('codex')'s 7 file(s) carry no command, prompt, or
per-role-file surface`, EXIT:0.

### Q3 — Are the Pi guards real? (falsifiability required)

**SPLIT VERDICT — Pi: real and enforcing. Codex: the materialized artifact is a
no-op in its current, permanent operating state. This is the "eighth gate."**

I wrote my own adversarial harness (not the coder's `test/*.test.mjs`), imported
the real `packages/harness-pi/src/extension.ts` module, mocked only the minimal
`pi.on()` capture surface, and fired 7 crafted `tool_call` events — 5 attacks that
must be blocked, 2 negative controls that must NOT be blocked (to rule out a
guard that just blocks everything).

```
$ node --experimental-strip-types <independent harness>
PASS auditor writes outside declared scope (SCOPE OVERFLOW-shaped attack) -> {"block":true,"reason":"report-write role missed its one declared output path"}
PASS coder attempts git commit (CODER-GIT-WRITE) -> {"block":true,"reason":"implementer roles never perform a version-control write"}
PASS worker attempts to dispatch engineer (implementer-never-dispatches) -> {"block":true,"reason":"implementer roles never dispatch"}
PASS coder hides git commit in compound bash command -> {"block":true,"reason":"implementer roles never perform a version-control write"}
PASS unidentified session (no SHEPHERD_ROLE) writes anything -> {"block":true,"reason":"SHEPHERD_ROLE is unset -- guard cannot resolve role identity, denying by default"}
PASS coder writes WITHIN its declared scope (must be ALLOWED) -> undefined
PASS unrelated tool (read) is never touched by the guard -> undefined
ALL INDEPENDENT ADVERSARIAL CHECKS PASSED
EXIT:0
```

Pi's `pi.on('tool_call', ...)` extension genuinely enforces write-boundary,
git-custody (including a compound-command obfuscation attempt), and dispatch-scope,
and fails closed on unresolved role identity. This is a real, falsifiable guard,
not a decoration.

**Codex is the eighth gate.** `packages/harness-codex/src/guard.mjs`'s
`decideForToolCall()` reads role from a caller-supplied parameter, and
`hooks/scripts/shepherd_guard.mjs` (the actual materialized artifact that would be
installed at `$PLUGIN_ROOT/hooks/scripts/shepherd_guard.mjs` and wired by the
materialized `hooks/hooks.json`) supplies that parameter from
`process.env.SHEPHERD_ROLE ?? ""`. When role is unset or unrecognized,
`decideForToolCall` **fails OPEN** (`return { result: "allow" }`) — a documented,
self-disclosed "NAMED GAP" in both the code header and the README. I verified
**nothing in this diff, or anywhere else in the repository, ever sets
`SHEPHERD_ROLE` for a Codex subprocess** (`grep -rn "SHEPHERD_ROLE" packages/harness-codex/`
finds only the 3 places that *read* it, never one that writes it; the code's own
comment admits "Codex has no analog of `hooks/scripts/agent_invocation_tagger.sh`").
I then ran the actual shipped script directly, unmodified, exactly as `hooks.json`
would invoke it, with `SHEPHERD_ROLE` unset (today's real, permanent state — not a
contrived edge case):

```
$ unset SHEPHERD_ROLE
$ echo '{"tool_name":"Bash","tool_input":{"command":"git commit -am \"sneaky coder commit\""}}' \
    | node packages/harness-codex/hooks/scripts/shepherd_guard.mjs
EXIT:0
STDOUT: (empty)   <- empty stdout = silent allow, per the script's own documented wire contract

$ echo '{"tool_name":"apply_patch","tool_input":{"path":"crates/cli/src/cmd.rs"}}' \
    | node packages/harness-codex/hooks/scripts/shepherd_guard.mjs
EXIT:0
STDOUT: (empty)   <- a coder-tier write to a Rust source file is silently allowed
```

A blatant implementer-tier `git commit` and an `apply_patch` write to `crates/cli/`
both pass silently. To prove the interpreter logic itself is sound (this is a
wiring gap, not a broken predicate evaluator), I re-ran the identical write-boundary
payload with `SHEPHERD_ROLE=auditor` set:

```
$ SHEPHERD_ROLE=auditor node packages/harness-codex/hooks/scripts/shepherd_guard.mjs <<< \
    '{"tool_name":"apply_patch","tool_input":{"path":"crates/cli/src/cmd.rs"}}'
{"permissionDecision":"deny","message":"[shepherd] SCOPE OVERFLOW -- predicate `write-boundary` denied (fired: role-write-eligibility)."}
EXIT:0
```

So the classification is precise: **the pure predicate interpreter
(`predicates.mjs`/`guard.mjs`) is correct** (also independently corroborated —
`test/predicates.test.mjs`'s 17-example corpus run reports `100% agreement`, and I
did not find a case where a correctly-supplied role produced a wrong verdict). **The
materialized, installable artifact is not** — as shipped, it is functionally
identical to having no `PreToolUse` hook registered at all, for every git-write and
every filesystem write, permanently, until a separate piece of infrastructure (a
Codex-side dispatch-role tagger, explicitly named by the coder as out of this
step's scope) is built.

This is not a symmetric risk with Claude's own `coder_git_guard.sh` fail-open
posture, despite the code comment's claim of parity. On Claude,
`agent_invocation_tagger.sh` writes a real dispatch record on every `Agent()` call,
so `current_role()` resolves successfully on the *common* path and only fails open
on the *rare* exception path. On Codex, there is *no* tagger at all — unresolved
role is the *only* path that exists today, so "fails open on unresolved role" is
not a narrow edge-case fallback here, it is the adapter's entire, permanent,
unconditional behavior. I do not think the coder should have built the tagger
unprompted (it is legitimately cross-scope, `crates/**`/launcher work), and the
gap is honestly disclosed in both the code header and the README, not hidden — but
shipping `hooks/hooks.json` + `hooks/scripts/shepherd_guard.mjs` as materialized,
installable artifacts without a loud, prominent flag that they currently enforce
nothing is a CRITICAL finding this run must not average away. **Flipping the
default to fail-closed is NOT a safe recommended fix on its own** — since role
never resolves today, fail-closed would permanently block every Codex write and
git operation, a functional regression worse than the current gap. The correct
fix is to not present this as "the guard layer is wired" until the tagger exists,
or to gate materialization of the live `hooks.json` entry behind that
infrastructure landing.

### Q4 — Is the model-pin mapping correct per target?

**PASS on all three targets, checked against actual emitted artifacts, not
adapter source comments.**

**Claude** — `model:` extracted from `finalizeClaudeTree(compile('claude'))`'s
actual output, all 9 roles, matches `agents/*.md`'s hand-maintained `model:` line
exactly:

```
agents/auditor.md    -> sonnet     (real: model: sonnet)
agents/coder.md      -> sonnet     (real: model: sonnet)
agents/conductor.md  -> sonnet     (real: model: sonnet)
agents/critic.md     -> sonnet     (real: model: sonnet)
agents/discovery.md  -> sonnet     (real: model: sonnet)
agents/engineer.md   -> opus[1m]   (real: model: opus[1m])
agents/planter.md    -> opus[1m]   (real: model: opus[1m])
agents/shepherd.md   -> inherit    (real: model: inherit)
agents/worker.md     -> sonnet     (real: model: sonnet)
```

**Codex** — `shepherd.codex.toml`'s `[models]` table maps every role to a NAME
string (`"standard"`/`"reasoning-high"`), never a Claude model token:

```
[models]
engineer = "reasoning-high"
planter  = "reasoning-high"
... (others = "standard")

[profiles."reasoning-high"]
reasoning_effort = "high"
[profiles."standard"]
reasoning_effort = "medium"
```

`grep -n 'opus\|sonnet\|haiku\|fable\|\[1m\]' packages/harness-codex/shepherd.codex.toml`
→ 0 hits. No Claude-specific model syntax leaked in.

**Pi** — bare model id verified end-to-end through the actual `buildRoleInvocation()`
call for the `engineer` role (which has `model_hint: reasoning-high`, i.e. Claude
slug `opus[1m]`):

```
$ node -e '... buildRoleInvocation(loadRoleFacts(...)get("engineer"), {...}) ...'
{
  "argv": ["pi","--print","--append-system-prompt","/tmp/engineer-prompt.md",
            "--tools","read,grep,find,bash,write,edit","--model","opus"],
  ...
}
```

`--model opus` — bare, the `[1m]` extended-context suffix correctly stripped
(`toBareModelId("opus[1m]")` → `"opus"`, independently confirmed).

## Claude adapter emission vs. the hand-maintained tree

This is the strongest signal in the wave, per instruction — full, unaveraged
comparison follows. `finalizeClaudeTree(compile('claude'))` emits 16 files: 9
`agents/*.md` (role count matches the live `agents/` dir exactly) and 7
`skills/*/SKILL.md` (matches the live `skills/` dir count exactly). It emits
**zero** `commands/*.md` (7 exist live) and **zero** `hooks/hooks.json` (1 exists
live, with many non-predicate-driven matchers).

**commands/ and hooks/hooks.json omission — classified as a documented, deliberate
scope decision, not a defect.** `content/RECONCILIATION.md` row 3 states plainly:
"`commands/plant.md` contributes zero facts `content/roles/planter.md` doesn't
already carry... neither harness's invocation surface is itself a reconciliation
target." Plan.md's own W4-S3 actions confirm: "guard/hook wiring is explicitly
W4-S4/S5/S6's job over `content/predicates/` directly, not this compiler's." The
W4-GATE condition only requires "each adapter's emitted role set diffs clean
against `content/`" (role set = the 9 `agents/*.md`, which it does) — it does not
require command/hook parity. Confidence: HIGH (directly grounded in the plan text
and the reconciliation doc, not inferred).

**Per-role `tools:` frontmatter divergence — systematic diff across all 9 roles,
zero cases of the emitted tree ever *stripping* a real grant:**

```
auditor    emitted-extra: [NotebookRead, LSP]  emitted-missing: []
coder      emitted-extra: [NotebookRead]       emitted-missing: []
conductor  emitted-extra: [NotebookRead]       emitted-missing: []
critic     emitted-extra: [NotebookRead]       emitted-missing: []
discovery  emitted-extra: []                   emitted-missing: []
engineer   emitted-extra: [NotebookRead]       emitted-missing: []
planter    emitted-extra: [NotebookRead, Workflow] emitted-missing: []
shepherd   emitted-extra: [NotebookRead]       emitted-missing: []
worker     emitted-extra: [NotebookRead, Edit] emitted-missing: []
```

I disagree with the coder's own self-report characterization of these as
"compiler-layer over-grants." Independent cross-role evidence points the other
way for 3 of the 4 tool names:

- **`NotebookRead`** — `discovery.md`'s *real, live* tools line already includes
  it (`Bash, Glob, Grep, NotebookRead, Read, Skill, ToolSearch, WebFetch,
  WebSearch, Write`), so the "`read` capability implies `NotebookRead`"
  convention is already established, hand-maintained precedent — the other 8
  role files are simply stale/inconsistent with their own sibling, not the
  compiler inventing a grant. Classification: **drift in the hand-maintained
  tree**, HIGH confidence (direct corroborating precedent in the live tree
  itself, not an inference).
- **`Workflow` on `planter`** — every *other* role with the `dispatch`
  capability (`engineer`, `conductor`, `shepherd`) already carries `Workflow`
  alongside `Agent` in its real, live tools line; only `planter.md` has `Agent`
  without `Workflow`. Classification: **drift in the hand-maintained tree**
  (planter.md simply wasn't updated when `Workflow` was added to its sibling
  dispatch-capable roles), HIGH confidence.
- **`Edit` on `worker`** — every *other* write-eligible role (`coder`,
  `shepherd`, `engineer`, `planter`) already carries `Edit` in its real tools
  line; `worker.md` is the sole write-eligible role missing it. Classification:
  **drift in the hand-maintained tree**, HIGH confidence.
- **`LSP` on `auditor`** — `code-intelligence` (→ `LSP`) appears on exactly one
  role (`auditor`) in `content/roles/*.md`, so there is no cross-role
  hand-maintained precedent to corroborate or refute it either way, unlike the
  other three. This could be a forward-looking capability grant `content/`
  authored ahead of the hand-maintained tree, or an unverified addition
  introduced during W0-S8's authoring that auditor doesn't actually need.
  Classification: **ambiguous — flagged to `## Open questions`**, MEDIUM
  confidence (plausible either way, no corroborating evidence in either
  direction).

**`color`, `description`, `effort` — genuine content gap, not disputed.**
`content/roles/*.md` carries none of the three fields at all (confirmed:
`grep -L '^color:' agents/*.md` → 0 files missing it in the *real* tree, i.e. all
9 real files have `color:`/`description:`; `effort:` is present on 4/9 real files
— `conductor`, `shepherd`, `planter`, `engineer` — and absent from `content/roles/*.md`
entirely). The finalized Claude tree cannot reproduce these three fields.
Classification: **content gap**, HIGH confidence, matches the coder's own
disclosure exactly.

**Net read:** the compiler's tools-frontmatter emission is, if anything, *more*
internally consistent with the hand-maintained tree's own established
conventions than the hand-maintained tree currently is with itself (3 of 4
divergent tool grants have direct corroborating precedent elsewhere in the same
live tree). This materially changes the coder's own self-assessment from
"compiler over-grants" to "hand-maintained tree has stale outliers the compiler's
consistent rule exposes." The compiler never under-grants — every divergence
checked is additive, and 3 of 4 additive cases are independently confirmed to be
convention-consistent, not fabricated.

## Verifications (disproved)

- **Disproved:** "the compiler's NotebookRead/LSP/Workflow/Edit divergences are
  compiler-layer over-grants" (W4-S4's own self-report framing). Falsified by
  direct cross-role diff against the live `agents/*.md` tree: 3 of 4 divergences
  have exact hand-maintained precedent elsewhere in the tree; the compiler is
  consistently applying `content/RECONCILIATION.md`'s own table, which the
  hand-maintained tree itself already partially reflects.
- **Disproved:** `npm ls --workspaces` "works" as a smoke test for this
  workspace's dependency graph. It reports `(empty)` because `node_modules`
  does not exist (no `npm install` was ever run, consistent with every coder's
  resource-discipline claim) — the command exits 0 but proves nothing about
  the declared dependency graph's actual resolvability.
- **Disproved (partially):** the coder's claim that Codex's guard fail-open
  posture "match[es] every existing Claude-side guard's own posture for a
  dispatch it cannot identify." Technically true in isolated behavior
  (`coder_git_guard.sh` does pass silently when `current_role()` can't
  resolve), but operationally false as a risk-parity claim: Claude's tagger
  infrastructure makes unresolved-role the rare exception; Codex has no tagger
  at all, making it the sole, permanent, universal path.

## Findings

### FINDING 1 — CRITICAL — Codex's materialized guard is a no-op in its current, permanent operating state

**Hypothesis:** The Codex adapter's emitted `hooks/hooks.json` +
`hooks/scripts/shepherd_guard.mjs`, if installed exactly as materialized, provides
zero enforcement against any implementer-tier git write or filesystem write,
because nothing anywhere in this diff or the repository sets `SHEPHERD_ROLE` for
a Codex subprocess.

**Falsification:** Ran the actual materialized script (not a mock, not a unit
test — the literal file that `hooks.json` wires) with `SHEPHERD_ROLE` unset
against (a) an implementer-tier `git commit` and (b) an `apply_patch` write to
`crates/cli/src/cmd.rs`. Both returned empty stdout / exit 0 (silent allow, per
the script's own documented wire contract). Re-ran the same `apply_patch` payload
with `SHEPHERD_ROLE=auditor` set and got a correct `deny`/`SCOPE OVERFLOW`
verdict, confirming the interpreter logic itself is sound and the defect is
specifically the role-signal wiring. `grep -rn "SHEPHERD_ROLE" packages/harness-codex/`
confirms 3 read sites, 0 write sites, anywhere in the package.

**Confidence:** HIGH — structurally verified by direct execution of the shipped
artifact with a crafted attack payload, not inferred from source reading.

**Disposition recommended:** Do not represent the Codex guard layer as "wired"
in status/closeout reporting until either (a) a role-tagging mechanism exists for
Codex (explicitly out of W4-S5's own file_scope — this is not asking the coder to
redo their work), or (b) the live `hooks.json` materialization is deliberately
withheld/gated pending that infrastructure, mirroring how the Claude adapter
correctly did NOT wire its own `hooks/hooks.json` into the live repo-root tree
this same wave. This is a wave-level/conductor-level triage item, not a
W4-S5-coder rework item — the coder's own code header and README disclose the
gap prominently and accurately; the risk is in how this gets *represented*
upstream (e.g. at W4-S7 closeout), not in the code itself.

### FINDING 2 — MEDIUM — the shared W4-S4/S5/S6 acceptance script does not exist

**Hypothesis:** `packages/scripts/predicate-coverage.mjs --require-allow-and-deny`,
named verbatim in plan.md's shared `[ACCEPTANCE]` block for W4-S4/S5/S6, was never
created and is not literally satisfiable at HEAD.

**Falsification:** `ls packages/scripts/predicate-coverage.mjs` → "No such file or
directory", exit 1. `ls packages/scripts/` shows only `check-deps.mjs` (which
passes, but tests dependency topology, not predicate allow/deny coverage — a
different concern). All three adapters independently proved allow+deny coverage
via their own local tests (`write-eligibility.test.mjs`,
`test/predicates.test.mjs`, `test/guard-predicates.test.mjs`, all passing), which
satisfies the *intent* but not the plan's literal, named, shared acceptance
command.

**Confidence:** HIGH — directly confirmed by `ls` exit code, corroborated by all
three coders independently self-reporting the identical gap and identical
reasoning (the script belongs to `packages/scripts/`, owned by no single
adapter's `file_scope.exclusive`).

**Disposition recommended:** Needs an owner assignment at W4-S7 closeout or a
dedicated follow-up step — not a defect in any of the three adapters, a plan-level
scope-assignment gap (3 independent coders reaching the identical, reasonable
conclusion is itself evidence the plan under-specified ownership here).

### FINDING 3 — MEDIUM — release-gate C.4 is unrunnable at HEAD; independently confirmed via a live build

**Hypothesis:** `crates/cli` has no `run init`/`run show`/`guard eval`
subcommands, so W4-S4's own declared release-gate C.4 acceptance line cannot be
executed end-to-end.

**Falsification:** Built `cargo build --release -p shepherd-cli` fresh (clean
build, 22.85s, `Finished` release profile, EXIT:0 — no prebuilt binary existed
before this run). Ran the resulting binary directly:

```
$ ./target/release/shepherd run init c4probe
error: unrecognized subcommand   EXIT:2
$ ./target/release/shepherd guard eval
error: unrecognized subcommand   EXIT:2
$ ./target/release/shepherd init
(succeeds)   EXIT:0
```

`grep -n "enum ShepherdCommand" -A2 crates/cli/src/cmd.rs` confirms exactly one
variant, `Init(InitCmd)`.

**Confidence:** HIGH — independently confirmed via a live build and direct binary
invocation, not accepted from the coder's static source-reading claim (which was
accurate).

**Disposition recommended:** Cross-lane blocker outside W4-S4's own `file_scope`
(`crates/**` is must-not-touch for this step). W4-S4's own JS-side
implementation (`src/run-state.mjs`, `test/advance-run.mjs`) is independently
verified correct (see Verifications below) — the gap is entirely on the Rust CLI
side, owned by a different lane.

### FINDING 4 — LOW — `@fl03/compiler` dependency declarations are dead/unresolvable as written

**Hypothesis:** The three harness packages' `"dependencies": {"@fl03/compiler":
"6.4.5"}` entries would not resolve to anything usable even under a real `npm
install`, because `packages/compiler/package.json` declares neither `main` nor
`exports`, and no file in the repo actually imports the bare `@fl03/compiler`
specifier.

**Falsification:** `cat packages/compiler/package.json | jq '{main,exports}'` →
both `null`. `ls packages/compiler/index.*` → no such file. `grep -rn "from
['\"]@fl03/compiler" packages/harness-*/{src,test,bin}/` → 0 hits; every
cross-package reference found is a relative import
(`../../compiler/src/compile.mjs` etc., confirmed by direct grep across all four
packages). `check-deps.mjs` still passes because its 3 rules (no
adapter-depends-on-adapter, adapter deps allowlisted, compiler doesn't depend on
adapters) never actually resolve the specifier — they reason over the manifest
graph, not real module resolution.

**Confidence:** HIGH — directly confirmed by absence of `main`/`exports` plus an
exhaustive grep across every adapter's source for the bare specifier.

**Disposition recommended:** Not currently harmful (nothing relies on the bare
specifier resolving) but should be fixed before `packages/compiler` is ever
published or consumed as its own declared dependency graph implies it can be —
either add `main`/`exports` to `compiler/package.json`, or drop the dependency
declarations and document that cross-package imports are intentionally relative.

### FINDING 5 — LOW — asymmetric materialization completeness across the three adapter packages, as they sit on disk right now

**Hypothesis:** Of the three packages, only `packages/harness-codex/` is
currently shaped as a self-contained, installable plugin bundle at rest
(`shepherd.codex.toml` + `hooks/hooks.json` + `hooks/scripts/` + `skills/*/SKILL.md`
all sit at the package root, mirroring the real installed `codex-shepherd@1.0.2`
layout the coder cross-checked against). `packages/harness-pi/` and
`packages/harness-claude/` ship correct, independently-tested logic in `src/` but
produce no analogous "drop this directory in and it works" artifact.

**Falsification:** `find packages/harness-claude -type f` shows no `agents/`,
`skills/`, or wired `hooks/hooks.json` at the package root — only
`hooks/guard-eval.mjs` (the relay script itself, unwired). `find packages/harness-pi
-type f` shows no `prompts/`/`skills/` materialized at rest, and no `pi.json` or
`package.json`-embedded `"pi": {"extensions": [...]}` manifest field — confirmed
by reading Pi's own `pi-manifest.d.ts`
(`/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent/dist/core/pi-manifest.d.ts`:
`readPiManifest(packageJsonPath)` reads a `pi.extensions` array from
`package.json`) and confirming `packages/harness-pi/package.json` has no `pi` key
at all. So even though I independently proved `src/extension.ts`'s guard logic is
real and enforcing (Finding under Q3), nothing in this diff would cause a real Pi
installation to discover and load it automatically.

**Confidence:** MEDIUM — the materialization gap itself is HIGH confidence
(directly confirmed by file listing and manifest inspection), but whether this
was actually expected of W4-S6 (vs. a later "install" step) is not settled by
plan.md's text, which only requires `compile('pi') --check` clean and the guard
predicate corpus proven — both of which W4-S6 satisfies. Flagging as a
completeness gap relative to the operator's stated "not scaffolded, not stubbed"
bar, not as a plan-acceptance failure.

**Disposition recommended:** Track as a follow-up: give `packages/harness-pi`
a `pi` manifest key (or equivalent install script) so its guard is actually
discoverable by a live Pi session, mirroring what `packages/harness-codex`
already achieves structurally (independent of Finding 1's role-signal gap).

### FINDING 6 — LOW — self-reported git-command process violation (W4-S6), verified harmless

**Hypothesis:** W4-S6's coder ran `git add -N` then `git reset` against
`packages/harness-pi/` during its own LOC-delta verification — both are
prohibited git-write commands for a coder role (`CODER-GIT-WRITE`) — and this
self-report should be independently checked for residue, not just trusted.

**Falsification:** `git status --porcelain=v1 -- packages/harness-pi/` at the
start of my session matches exactly what the coder's own diff describes (3
modified tracked files, 3 new untracked directories) — no staged files, no
orphaned index state. The self-reported `git reset` genuinely restored the prior
state.

**Confidence:** HIGH — directly confirmed against live `git status` output.

**Disposition recommended:** No corrective action needed on the repo; a process
note for the coder's own conduct going forward (git custody is never a coder's to
touch, even transiently), already self-flagged.

## Per-step verdicts

| Step | Verdict | Blocking items |
|---|---|---|
| W4-S3 (compiler) | **PASS** | None. All 5 `[ACCEPTANCE]` lines independently re-run and green. The "compiler over-grants" self-characterization is contradicted by my own tree-comparison (3 of 4 divergent tool grants have hand-maintained-tree precedent) — net: the compiler is *more* internally consistent than the hand-maintained tree it's compared against, not less correct. |
| W4-S4 (claude adapter) | **PASS** | None from inside this step's own `file_scope`. Finding 3 (release-gate C.4 unrunnable) is a cross-lane blocker on `crates/cli`, independently reconfirmed via a live build, already self-disclosed by the coder and correctly not fixed from inside `packages/harness-claude/`. |
| W4-S5 (codex adapter) | **PASS, with a CRITICAL finding requiring conductor/operator triage before this wave's guard-layer claims are represented as "wired" (Finding 1)** | Not a coder-rework item — the fix requires infrastructure outside this step's `file_scope`, and the gap is prominently, honestly disclosed in both code and README. Escalate, do not silently close. |
| W4-S6 (pi adapter) | **PASS** | None. Independent adversarial falsification (Q3) confirms the guard genuinely enforces when invoked; Finding 5 (no discoverable manifest entry) is a completeness gap, not a false-security-boundary risk, and is distinct in kind from Finding 1. |

## Open questions

- Is `code-intelligence`/`LSP` on `auditor` an intentional, forward-looking
  capability grant `content/roles/auditor.md` authored ahead of the
  hand-maintained tree, or an unverified addition introduced during W0-S8's
  authoring pass that auditor doesn't actually need? No cross-role
  corroborating evidence exists either way (auditor is the sole role with this
  capability) — needs the content/ author's confirmation, not a guess.
  (LOW confidence either direction.)
- Was `packages/harness-pi` and `packages/harness-claude` expected to ship a
  self-contained, installable bundle at rest this wave (matching
  `packages/harness-codex`'s shape), or is that explicitly a later "install/
  distribution" step's job? Plan.md's text for W4-S4/S5/S6 does not settle
  this either way — its `[ACCEPTANCE]` block never requires a materialized
  bundle at rest for any of the three adapters, only `compile --check` +
  predicate-corpus coverage, both of which all three satisfy.

## Pattern delta

First central-verification pass filed under this exact concern shape for this
sprint (the four W4 auditor dispatch reports so far — L7, W2, W7, W8, W8R, W9 —
cover different concerns per the report listing in
`.shepherd/runs/v645/reports/`); no 3-sprint trend data available to compare
against. `Systemic risk: none` (single-sprint data point).

Notably: this is the **first** finding in this run where a coder's own
self-report characterization of a divergence ("compiler-layer over-grant") was
independently falsified and reversed (drift in the hand-maintained tree,
verified via cross-role precedent) rather than confirmed. Worth carrying forward
as a prior: when a coder attributes a Claude-tools divergence to "the compiler,"
check for hand-maintained-tree precedent among sibling roles with the identical
capability before accepting that attribution.

## Grade

N/A — this dispatch is a central-verification pass (not a `close` mode audit
with an issue-graded rubric); no A–F grade is produced. Per-step PASS/REDO-shaped
verdicts are recorded above per the dispatch's own instructions.

## Grade rationale

N/A (see above).

## Output to conductor

```
## AUDITOR REPORT
- Concern: central-verification (W4 compiler + 3 adapters)
- Mode: close (central-verify dispatch, no numeric grade requested)
- Files reviewed: 27 (all new/modified under packages/compiler, packages/harness-{claude,codex,pi}) + 9 content/roles/*.md + 9 agents/*.md + content/RECONCILIATION.md + content/predicates/write-boundary.toml + crates/cli/src/cmd.rs
- Findings: CRITICAL=1, HIGH=0, MEDIUM=2, LOW=3
- Verifications (disproved): 3
- Open questions: 2
- GH issues filed: none (read-only report-only dispatch; Finding 1 recommended for conductor/operator triage, not filed as an issue by this auditor)
- Grade: n/a (central-verify dispatch, no rubric grade requested)
- Report path: /Users/jo3/src/fl03/shepherd/.shepherd/runs/v645/reports/auditor-W4-central-verify.md
- Hot-fix-lane recommendations: 1 (Finding 1 — do not represent the Codex guard layer as "wired" at W4-S7 closeout until the role-signal gap is resolved or explicitly accepted by the operator)
- Sprint-pattern entry: written (see Pattern delta above)
- Agent ID + timestamp: auditor-w4-central-verify @ 2026-08-14T00:30:00Z
```

## THE FOUR QUESTIONS — one-line summary

1. **Reproducible?** Yes — all 3 targets byte-identical across two compiles, verified directly.
2. **Codex command surface?** None — 0 of 7 emitted files under `commands/`.
3. **Pi guards real?** Pi: yes, adversarially proven. Codex: the materialized artifact enforces nothing today — the eighth gate, CRITICAL.
4. **Model-pin correct per target?** Yes on all 3 — Claude's 9 `model:` lines match hand-maintained exactly; Codex's `[profiles]` carries only NAME strings, zero Claude tokens; Pi's actual dispatch argv carries a bare `--model opus`, `[1m]` stripped.
