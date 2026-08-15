---
title: v6.4.5 CLOSE audit — data-flow
date: 2026-08-14
auditor: shepherd:auditor
sprint: v6.4.5
concern: data-flow
mode: close
methodology: superpowers:systematic-debugging (falsify, not confirm) — every finding below is
  grounded in a command run against this checkout at HEAD b57d495, not in a wave report's prose.
prior_class_priors: adaptation registry empty (`shctx adapt report` — "no sprint metrics
  recorded yet"; `shctx adapt priors --lessons` — no rows). No prior `close-data-flow.md`
  exists in any `.shepherd/runs/*` directory (v500, v512-dev0, v514, v516, v517, v641-dev0
  all checked) — framework priors only, first data-flow audit on record for this repo.
---

## Scope reviewed

The guard decision path end to end, on all three harnesses, per the brief:
`content/predicates/*.toml` → `services/cli/shepherd_cli/predicates.py` (`Engine.evaluate`) →
each harness's relay/translator → each harness's own hook-output wire shape → whether the
runtime actually acts on it. Files read in full: `packages/harness-claude/src/{guard,
guard-serve-engine,guard-serve-broker,guard-serve-client}.mjs`, `packages/harness-claude/hooks/
{guard-eval,guard-broker-main}.mjs`, `packages/harness-codex/src/guard.mjs`, `packages/
harness-codex/hooks/hooks.json`, `packages/harness-pi/src/extension.ts`, `services/cli/
shepherd_cli/{predicates.py,commands/guard.py}`, `hooks/hooks.json`, `hooks/scripts/
{coder_git_guard.sh,conductor_write_guard.sh,dispatch_guard.sh,dedup_write_guard.sh,
dups_write_guard.sh}`, `content/predicates/dispatch-scope.toml`, plus the two adapter
READMEs. Commands run: live `bin/shepherd guard eval` / `bin/shepherd guard test`, a `python3`
parse of `hooks/hooks.json`'s full `PreToolUse` array, `grep` across every live
`hooks/scripts/*.sh` for any shared-engine call, `strings` against the installed
`codex-cli 0.147.0` binary, and a live run of `packages/harness-claude/test/
guard-serve-transport.test.mjs` (targeted — no workspace-wide cargo/pytest run, per brief).
9 files read end to end, 2 live CLI probes, 1 binary probe, 1 targeted test run.

## Findings summary

CRITICAL=1, HIGH=2, MEDIUM=2, LOW=0. Verifications (disproved hypotheses)=3.

## Findings

### CRITICAL — the entire shared-engine guard pipeline never receives a live Claude tool call

**Hypothesis:** the new shared-engine guard relay for Claude (`hooks/guard-eval.mjs` →
`src/guard.mjs` → `services/cli/shepherd_cli/predicates.py`) is fully built and tested but was
never wired into the live `hooks/hooks.json`, so on this repo's own dogfooded Claude sessions
it never evaluates a single real `PreToolUse` call.

**Falsification:**
```
$ python3 -c "import json; d=json.load(open('hooks/hooks.json'));
  print([h['command'] for e in d['hooks']['PreToolUse'] for h in e['hooks']
         if 'guard-eval' in h['command']])"
[]
$ grep -ln "shepherd guard\|guard eval\|guard serve\|guard-eval\|guard-serve" hooks/scripts/*.sh
(no output — zero matches across all 32 live guard scripts)
$ echo '{"role":"coder","tool_name":"Bash","tool_input":{"command":"git commit -am x"}}' \
  | bin/shepherd guard eval
{"decision": "deny", "predicate": "git-custody", "rule": "implementer-never-writes-git",
 "halt_code": "CODER-GIT-WRITE", ...}
```
The engine itself is correct and live (third command). The relay code is correct and unit-
tested (`packages/harness-claude/test/guard.test.mjs` spawns `hooks/guard-eval.mjs` directly
and asserts allow/deny/unresolved end to end — which is exactly why this gap was invisible to
every test: the test harness calls the relay script directly, bypassing `hooks.json` entirely,
so it can never detect that nothing in production calls it that way). `packages/
harness-claude/src/guard.mjs`'s own `buildGuardHooksEntry()` (lines 106–116) is the exact
`hooks.json` entry that should exist and does not; its README even states outright "**Is the
relay safe to wire into `hooks/hooks.json` now?** Yes" (line 92) and separately confirms the
gap: "**No full `hooks/hooks.json` emission**... out of this step's file scope to write into
`hooks/` at the repo root regardless" (lines 179–184). Every live write-boundary/git-custody/
dispatch enforcement on Claude today runs through independent legacy bash scripts
(`coder_git_guard.sh`, `conductor_write_guard.sh`, `dispatch_guard.sh`, `lock_guard.sh`,
`plan_proof_guard.sh`) that never read `content/predicates/*.toml` and never call the shared
engine — none of DF-76's fix (build the engine) or the twelve waves of relay/broker/socket work
that followed it has moved the needle on what actually gates a live Claude tool call in this
repo, at close.

**Confidence:** HIGH — structurally verified by direct inspection of the exact file the plugin
loads, not by reading a wave report's claim.

**Why this outranks the brief's "tenth gate" framing:** every one of the nine named
gate-that-cannot-fail defects (DF-17/19/59/62/63/71/72/75/77) is a test that manufactures a
precondition the runtime never supplies — the gate runs, and passes wrongly. This is the
inverse and, on Claude, total: the gate never runs at all. `shepherd guard test` reporting
17/17 and `packages/harness-claude`'s 8/8 both stay green regardless, because neither one
executes the actual live-hook path this finding is about.

### HIGH — `dedup-gate` is unreachable from any live tool call on all three harnesses

**Hypothesis:** `content/predicates/dedup-gate.toml`'s rule set is conformance-tested (via
`shepherd guard test`) but structurally unreachable from a real `PreToolUse`/`tool_call` event
on Claude, Codex, or Pi.

**Falsification:**
```
$ grep -rn "dedup-gate" packages/*/src packages/*/hooks services/cli/shepherd_cli
packages/harness-claude/src/guard.mjs:92-96   (doc comment: "has NO entry here on purpose")
packages/harness-pi/src/extension.ts:29-38    (doc comment: "NAMED GAP")
# packages/harness-codex/src/guard.mjs: zero mentions anywhere
$ grep -c '^\[\[example\]\]' content/predicates/dedup-gate.toml
3
$ bin/shepherd guard test
17/17 examples passed
```
`services/cli/shepherd_cli/predicates.py`'s `Engine._evaluate_tool_call` (the raw-tool-call
shape every relay actually sends) maps only `Write/Edit/apply_patch → write-boundary`,
`Bash → git-custody`, `Agent/Workflow → dispatch-scope` — there is no branch that ever produces
a `dedup-gate` request. All three adapters' own source comments independently confirm this is
known and deliberate, not an oversight in the code itself. But the consequence is real: 3 of
the 17 examples (18%) in the "17/17 examples passed" conformance number that `bin/shepherd
guard test` reports at close are for a check nothing live ever calls. On Claude specifically,
the dedup enforcement that DOES fire live (`hooks/scripts/dedup_write_guard.sh`, regex
symbol-name matching, and `dups_write_guard.sh`, shape-similarity via `shctx dups check`) is a
**third**, wholly independent implementation that never reads `content/predicates/
dedup-gate.toml` at all — the predicate file and its Python "reference implementation /
behavioral oracle" describe a check that is not what runs in production on any harness. Per
the seed's own decision #2 ("A predicate expressed as code in two languages is a defect"),
this is now three implementations of one concept, two of which (Python engine, TOML spec) do
zero live work.

**Confidence:** HIGH.

### HIGH — `dispatch-scope` is unreachable from any live tool call on Codex

**Hypothesis:** the `dispatch-scope` predicate has zero live `PreToolUse` enforcement on the
Codex harness, despite Codex being the one harness (besides Claude, which is covered above)
whose materialized `hooks.json` is real, committed, shipping product — confirmed via
`packages/harness-codex/README.md`'s own account of `bin/apply.mjs materialize()` writing to
the package's own root, i.e. `packages/harness-codex/hooks/hooks.json` is not scaffolding
awaiting a future wiring step the way Claude's parallel package is.

**Falsification:**
```
$ cat packages/harness-codex/hooks/hooks.json
{ "hooks": { "PreToolUse": [ { "matcher": "^(apply_patch|Bash)$", ... } ],
             "PostToolUse": [ { "matcher": "^(spawn_agent|collaborationspawn_agent)$", ... } ] } }
```
`spawn_agent`/`collaborationspawn_agent` — Codex's own dispatch tool — is wired ONLY at
`PostToolUse`, for after-the-fact role tagging (`src/dispatch-record.mjs`); there is no
`PreToolUse` hook on it at all, so a dispatch cannot be pre-flight denied, only tagged once it
has already fired. Independently, even a hypothetical wiring attempt would fail silently:
`predicates.py`'s `_DISPATCH_TOOL_NAMES = frozenset({"Agent", "Workflow"})` are Claude's own
tool names; a shape-(b) request with `tool_name: "spawn_agent"` falls through to
`_unresolved("no (predicate, action) mapping known for tool \`spawn_agent\`", ...)` regardless.
A wrong-tier dispatch on Codex (an implementer dispatching another role; a lane-lead invoking
the plan-author or gate roles) is not pre-flight blocked on that harness today — only
after-the-fact write-boundary/git-custody enforcement (which IS live-wired on Codex, see
Verification below) catches downstream consequences, never the dispatch decision itself.

**Confidence:** HIGH.

### MEDIUM — the shared guard-serve broker caches the predicate/role corpus for its whole process lifetime, with no invalidation on `content/` changes

**Hypothesis:** `bin/shepherd guard serve`'s engine loads `content/predicates/*.toml` and
`content/roles/*.md` exactly once at process start and never reloads; combined with the
broker's idle-timer reset on every request, a broker under sustained guard traffic never
restarts, so a live edit to `content/roles/*.md` or `content/predicates/*.toml` mid-sprint is
silently invisible to it for the rest of its life.

**Falsification:** read `services/cli/shepherd_cli/commands/guard.py::run_serve` — `engine =
_load_engine_or_exit(content_dir)` runs once, before `for raw_line in sys.stdin:`, and is never
called again inside the loop. Read `packages/harness-claude/src/guard-serve-broker.mjs`'s
`armIdleTimer()` — called from the `connection` handler on every accepted socket connection,
clearing and re-arming the 10-minute timer each time, so continuous traffic (sub-10-minute
gaps between guard calls, the realistic case in an active wave) never lets the idle path fire
and recycle the engine. This is not hypothetical staleness risk in the abstract — this exact
sprint edited `content/roles/*.md` mid-run as part of the DF-77 fix chain. It is currently
**latent** on Claude (per the CRITICAL finding above, nothing wires the broker there today) but
**live-reachable on Codex**, whose `hooks/hooks.json` genuinely shares this same broker/engine
process (same `defaultSocketPath(contentDir)` derivation, imported verbatim from
`guard-serve-broker.mjs` into `packages/harness-codex/hooks/scripts/shepherd_guard.mjs`).

**Confidence:** HIGH on the mechanism (read, not inferred); MEDIUM on operational impact this
specific sprint (no evidence a warm broker was actually caught serving stale content mid-run —
this is a construction-level finding, not an observed incident).

### MEDIUM — `dispatch_guard.sh` only partially covers `dispatch-scope.toml`'s dispatcher-tier rules

**Hypothesis:** `content/predicates/dispatch-scope.toml`'s `implementer-roles-never-dispatch`
rule (`deny_if_dispatcher_is_implementer`) has no live analog in Claude's actually-wired guard
(`dispatch_guard.sh`), and the `plan-authorship-and-gating-are-root-tier-exclusive` rule
(keyed on `dispatcher_tier == "lane-lead"`, i.e. *any* conductor) is only partially mirrored by
that script's Check 4, which fires only when its own best-effort `teammate_mode` heuristic
reads 1.

**Falsification:**
```
$ grep -n current_role hooks/scripts/dispatch_guard.sh
(no output — the script never resolves the CALLING role at all)
```
`dispatch_guard.sh` inspects only the dispatch *target*'s `subagent_type` plus structural
markers (`team_name`, `cwd`, prompt tags) — it has no mechanism to know whether the caller
issuing the `Agent`/`Task` call is itself an implementer-tier role, so
`implementer-roles-never-dispatch` cannot be enforced by it in principle. Check 4 (the closest
analog to `plan-authorship-and-gating-are-root-tier-exclusive`) is gated on `[[ "$teammate_mode"
-eq 1 && ... ]]`; a SOLO (non-teammate) conductor dispatching `engineer`/`critic` would not trip
it, a distinction `dispatch-scope.toml`'s rule does not make (it denies on `dispatcher_tier`
alone, regardless of teammate vs. solo topology). This is plausibly mitigated in practice by
tool-grant absence — implementer-tier subagents may simply never be handed the `Agent`/`Task`
tool at all, a structurally different and unverified-by-me enforcement path — so this is
flagged at MEDIUM rather than asserted as a live breach; see Open questions.

**Confidence:** MEDIUM — the code-level gap is HIGH-confidence (directly read); whether it is
exploitable in practice depends on a tool-grant fact I did not verify live.

## Verifications (disproved hypotheses)

1. **"`coder_git_guard.sh` (warn-on-unresolved) and `conductor_write_guard.sh`
   (deny-on-unresolved) disagree in a way that indicates real inconsistency."** FALSIFIED.
   Both scripts' own headers (`coder_git_guard.sh:40-55`, `conductor_write_guard.sh:33-68`)
   independently justify the different posture by naming the different resource and blast
   radius each protects: `current_role()` resolves both "root's own direct git" and "an
   uncorrelated coder" to the same `"unknown"` value (an acknowledged open gap, DF-77 FIX 3),
   so `coder_git_guard.sh` cannot safely hard-deny on it without also blocking root's
   legitimate git; `conductor_write_guard.sh`'s "no direct authorship" rule has no such
   collateral-damage case (a `@worker` dispatch is always the safe alternative), so it denies
   unconditionally. Deliberate, documented, and correct — not a contradiction.

2. **"A guard verdict could be emitted in a shape the runtime silently ignores"** (the brief's
   named DF-75-adjacent risk). FALSIFIED on both harnesses that emit a shape. Claude's flat
   `{"permissionDecision":"deny","message":...}` matches `hooks/scripts/_lib.sh`'s own
   `emit_deny` (ground truth for what this plugin's live runtime already consumes) exactly.
   Codex's nested `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":
   "deny","permissionDecisionReason":...}}` was independently confirmed against the
   **installed** `codex-cli 0.147.0` binary via `strings /opt/homebrew/bin/codex | grep -i
   permissionDecision` — it embeds `PreToolUseHookSpecificOutputWire` with exactly those field
   names, and additionally requires a non-empty `permissionDecisionReason` on a deny (a
   constraint `packages/harness-codex/src/guard.mjs`'s `preToolUseDeny` always satisfies).

3. **"The Claude/Codex shared single-engine-process-behind-a-socket design lets one harness's
   request affect another's verdict, or caches a verdict across requests."** FALSIFIED at the
   per-request level (the corpus-level caching finding above is a separate, real issue).
   `GuardServeEngine.evaluate()`/`#evaluateOne` computes each request fresh from its own
   payload; the `#pending` promise chain only serializes I/O ordering against the single
   child's stdin/stdout, carrying no decision state between calls. Live-ran
   `node packages/harness-claude/test/guard-serve-transport.test.mjs` — all 6 assertions
   passed: engine killed mid-session denies in 1ms (never hangs, never silently allows), a
   stale socket recovers in 113ms, an idle broker self-terminates and unlinks its own socket, an
   engine that never starts fails closed within the bounded `spawnWaitMs`, and warm requests
   average 0.37ms vs. 115ms cold.

## Open questions

- Does any `content/roles/*.md` implementer-tier role (`coder`, `worker`, `discovery`,
  `auditor`) actually receive the `Agent`/`Task` tool grant on Claude at all? If not, the
  MEDIUM `dispatch_guard.sh` coverage gap above is moot in practice (structurally unreachable
  for a different reason than the predicate's own rule). I did not verify Claude's live
  tool-grant table for this; `packages/compiler/src/capabilities.mjs`'s `dispatch` capability
  mapping would be the place to check next.
- Was a live `guard serve` broker ever actually observed serving a stale verdict mid-sprint (as
  opposed to the construction-level staleness risk established above)? No incident evidence
  found either way in the dogfood ledger; this audit did not attempt to reproduce it live
  (would require editing `content/` while a broker is warm, a write op outside this role's
  read-only mandate).
- Is `packages/harness-codex`'s materialized `hooks/hooks.json` actually what a real
  `codex-shepherd` install uses today, or only what this repo's own `bin/apply.mjs` produces
  locally? The README's own account (`materialize()` writes to the package's own root as
  committed files) supports "yes, this is the real shipped artifact," and I treated the HIGH
  dispatch-scope finding accordingly, but I did not independently probe an actual installed
  `codex-shepherd` package to confirm parity.

## Pattern delta

No prior `close-data-flow.md` (or any prior data-flow-concern audit) exists in
`.shepherd/runs/{v500,v512-dev0,v514,v516,v517,v641-dev0}` — this is the first data-flow audit
on record for this repo, so no severity-vs-prior or 3-sprint trend is computable.
**Systemic risk: none evaluable (insufficient history).** Noting for future trend tracking: this
sprint's single largest data-flow finding (CRITICAL — unwired relay) is the same *shape* as
DF-76 (an engine that exists but nothing calls) and DF-75 (a guard that enforces nothing) from
this same sprint's own dogfood ledger — a fix that makes the callee correct without ever
confirming a live caller reaches it. If a future data-flow audit finds a fourth instance of
"built + tested + never wired," that is the systemic pattern to name explicitly.

## Cache telemetry

`shctx query cache-usage --sprint=v6.4.5 --md` returned no output (exit 0, empty stdout) —
telemetry view absent, establishing baseline. Skipped per contract.

## Grade

**B-**

## Grade rationale

No CRITICAL/HIGH finding here reflects a live security breach today — every harness's
*existing* legacy enforcement (Claude's bash guards, Codex's shared-engine write-boundary/
git-custody wiring, Pi's `pi.on('tool_call')` relay) continues to fail closed correctly where
it is actually wired, and the transport/broker layer's failure-mode coverage (dead engine,
dead broker, stale socket, never-started engine) is genuinely tested and genuinely passes live.
The grade is capped below A/A- by the CRITICAL finding under this rubric's own terms: the
sprint's headline, seed-stated deliverable — "guard predicates are data, not duplicated code...
interpreted by exactly ONE evaluator on Claude and Codex" (seed decision #2) — does not hold at
close. On the harness this repo dogfoods itself with, that one evaluator is fully built, fully
unit-tested, explicitly self-certified as "safe to wire," and reaches zero live tool calls.
Two of the four `content/predicates/*.toml` files (`dedup-gate` universally, `dispatch-scope`
on Codex) are unreachable from any live call on the harness(es) that matter for them, while a
green `shepherd guard test 17/17` and green per-package test suites both continue to certify
against that same corpus, giving false confidence at every gate the sprint's own quantitative
summary leans on. This is not a SUBTRACT violation (nothing here was net-negative or dishonest
— the code that exists is correct, and both adapter READMEs disclose the wiring gap in their
own words) and it is not a real-work-test failure (real, substantial work landed — role
resolution, broker lifecycle, wire-shape verification, three harness adapters). It lands at B-,
not lower, because every gap found is honestly disclosed somewhere in the diff's own comments
(this audit corroborated, rather than discovered from nothing, most of the underlying facts —
the CRITICAL finding's novelty is in confirming the wiring gap was never closed by wave 12, not
in discovering an undocumented defect) and because the parts that ARE live (Codex write-
boundary/git-custody, Pi's full four-predicate-minus-one coverage, Claude's legacy bash guards)
demonstrably work under adversarial failure-mode testing. It lands no higher than B- because a
sprint whose named north star is one shared, harness-agnostic guard engine cannot claim that
outcome achieved while the busiest harness in this very repo's own workflow never calls it.

## Output to conductor

```
## AUDITOR REPORT
- deliverable: 21 (status: delivered)
- Concern: data-flow
- Mode: close
- Files reviewed: 9 read in full (+2 hooks.json, +2 READMEs, +1 predicates.toml)
- Findings: CRITICAL=1, HIGH=2, MEDIUM=2, LOW=0
- Verifications (disproved): 3
- Open questions: 3
- GH issues filed: none (read-only mandate; findings recorded as audit_findings rows
  58-65 via `shctx audit insert`, not as new GH issues)
- Grade: B-
- Report path: /Users/jo3/src/fl03/shepherd/.shepherd/runs/v645/reports/close-data-flow.md
- Hot-fix-lane recommendations: 1 (wire packages/harness-claude's guard-eval.mjs into
  hooks/hooks.json's PreToolUse Write|Edit|Bash|Agent|Workflow matchers, run guard.test.mjs's
  live 3-way role-resolution matrix against it, THEN decide whether to retire or keep the
  legacy bash guards as defense-in-depth — do not retire them before the new relay is proven
  live, per this sprint's own DF-77/DF-78 lesson about a step's blast radius outrunning its
  file_scope)
- Sprint-pattern entry: written (see Pattern delta — first data-flow audit on record; flagged
  the "built + tested + never wired" shape as one to watch for recurrence)
- Agent ID + timestamp: shepherd:auditor @ 2026-08-14T05:23:44Z
```
