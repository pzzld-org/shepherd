---
title: v6.4.6 close report — the plugin could not run its own sprint
run: v646
branch: v6.4.6
base: main
status: closed
date: 2026-08-17
author: root @ session-1535f7a2
---

# v6.4.6 — close report

## A. The headline is not in the seed

The seed's thesis was that every capability v6.4.x built is unreachable from a clean machine.
That was true, and lanes A–E address it. But the largest finding of this sprint came from
**running the sprint through the plugin itself**, and it was not on the deliverable list:

> Shepherd's guard system was not enforcing. The dispatch ledger was empty on every harness,
> so no tool call could be attributed to a role, and not one rule in `dispatch-scope` had
> ever fired. The nine-role flock was enforced by prose.

Six defects of one class were found and fixed, each surfacing as a guard refusal aimed at the
caller while the actual fault was in shepherd's own plumbing. All six are regression-tested,
and every test was confirmed red against the previous code before being accepted.

| # | Defect | Effect before fix |
|---|---|---|
| 1 | `PreToolUse` denied on every error | one unusable run namespace disabled `Write\|Edit\|Bash\|Agent\|Workflow` — the entire repair surface |
| 2 | `Workflow` required a field it cannot carry | every workflow call refused |
| 3 | carrier form compared against bare role ids | every in-flock dispatch refused as off-flock |
| 4 | host tool envelope not forwarded to the resolver | every root-session `Write`/`Edit` denied for "no validated write paths" |
| 5 | `agent_type` required on tool events | every dispatched agent's tool call unresolvable |
| 6 | `SubagentStart` required a block no host sends | **the dispatch ledger was empty on every harness** |

Measured after: a conductor may dispatch a coder, is REFUSED dispatching an engineer
(wrong-tier), and a coder is REFUSED dispatching anything (implementers never dispatch).
Those are the flock's own rules enforcing for the first time. 34 agents were recorded and
role-attributed during this sprint's own execution.

## B. A regression this sprint introduced — and closed

Recorded in full as carry-forward item 0a. Stated here because a close report that buries it
is worthless.

`05a977a` allowed a `Workflow` call with no resolvable target. The justification written at
the time — "each spawned agent is guarded at `SubagentStart`, where its role is known" — was
asserted and never verified, **and it is false**. `SubagentStart` records an agent; it does
not evaluate dispatch-scope.

Consequence: two target-keyed rules are bypassable by payload shape. A conductor denied
`WRONG-TIER-DISPATCH` when it declares `target_role: engineer` is ALLOWED when it writes the
same dispatch as a script string, and `closed-flock-only` falls the same way for any role.
`implementer-roles-never-dispatch` is unaffected and is genuinely stronger than before.

**Closed at `828edbe`** on the operator's instruction. A lane lead must now DECLARE the roles
it dispatches; root and implementers are unchanged, so `Workflow` stays usable and only the
evasion is shut. Measured: `conductor + script naming engineer` now denies with
`WRONG-TIER-DISPATCH` where it previously allowed, `conductor + target_role: coder` still
allows, and `Agent` with no target is still unresolved.

`hooks/tests/test_native_cli_contract.sh` was RED and correctly red throughout. The harness
lane refused three times to edit it to assert `allow`, which is the only reason the bypass
was visible at all.

## C. What the sprint learned about its own discipline

The seed's thesis is "gates that cannot fail". Turning that on the sprint's own instruments
produced four rules, all from the lanes:

1. **A gate is not proven by a red test. The test must be shown to RUN, then shown to go
   red.** `test result: ok. 0 passed` survives every did-it-go-red check ever devised.
   Found when a lane's gate for its own primary acceptance criterion had never executed.
2. **Every gate states how many things it checked, and fails when that number is zero.**
   The pattern already existed here (`test_exec_bits.sh` fails with `no path-invoked scripts
   matched — pathspec drift?`) and had simply never been generalized.
3. **Falsification runs against a `/tmp` copy** — stated INSIDE the requirement, not beside
   it. Told only "prove it can fail", an agent reaches for `git checkout` on a live file
   every time. The requirement was underspecified, and the agent was not wrong to infer it.
4. **A stale artifact does not fail loudly. It produces a plausible wrong answer,
   attributable to someone else's work.** Three incidents, each mis-attributed on first
   reading — to a flaky agent, to brief defects, and finally to a coder appearing to ship the
   exact anti-pattern its brief had banned.

The gate itself was the largest instance: `cargo test --workspace` ran **3 of 126**
`shepherd-core` tests, including **none of the guard engine's 66**, because Cargo silently
omits targets whose `required-features` are unmet. Fixed in `04c500a`.

## D. Deliverable status

| # | Deliverable | Status |
|---|---|---|
| 1 | `cargo binstall` reaches a real asset | **CLOSED** — tar detection, PowerShell `-Force`, derived package names, crates.io precedence |
| 2 | `shepherd` on PATH is the native binary | **CLOSED** — `bin/shepherd` deleted; installer heals dangling, refuses live |
| 3 | a fresh project can dispatch | **CLOSED** — `init --confirm` writes identity and one matching `projects` row atomically; `doctor` fails loudly without it; verified live at integration |
| 4 | errors name the actual failure | **CLOSED** — 2 of 2 misleading sites fixed, subject-aware by errno, NOFOLLOW untouched |
| 5 | every harness defines every hook | **CLOSED** — `run.sh` 27/27; Pi manifest; generated parity table |
| 6 | configuration parsing belongs to `config` | **CLOSED** — one `toml::` consumer tree-wide, and it is the intended one |
| 7 | the release gate can fail | **CLOSED** — full truth table; a skip-everything run no longer concludes success |
| 8 | the model map states the intended tiers | **CLOSED** — `models show --md` renders the operator's corrected table |
| 9 | CHANGELOG and release notes are truthful | **CLOSED** — section present, v6.4.5 dated; the seed's premise was stale |
| 10 | v6.4.6 milestone, v6.4.5 reconciled | **CLOSED** — milestone existed; 10 stale issues verified and closed with evidence, zero open |

## D2. Gates this sprint made able to fail

Every one below was inert or absent when the sprint started, and each was shown red on
purpose before being trusted.

| Gate | Was | Now |
|---|---|---|
| feature-gated Rust targets | 3 of 126 core tests ran; guard engine's 66 never did | wired into `gate.sh`, 130 more tests execute |
| `test-release-package-names.sh` | correct, falsifiable, referenced by nothing | wired into `gate.sh fast` |
| `test-release-archive-layout.sh` | correct, falsifiable, referenced by nothing | wired into `gate.sh fast` |
| `test-release-tar-portability.sh` | stub modelled a tar that cannot exist | models GNU and old-libarchive; fails under both |
| `lint_agent_capabilities.sh` | deleted in v6.4.5 while red | restored, its 5 violations fixed, reports OK |
| `hooks/tests/run.sh` | executed 6 of 24 test files | 27 of 27 |
| `rule_msrv_is_consistent` | nothing checked the three files agreed | added, falsifiable |
| `test_cli_authority_gate.sh` | orphan; and its scanner went inert when `bin/` was deleted | in progress |
| live-symlink refusal | no regression test; suite stayed green when sabotaged | in progress |

## E. Lane evidence

Per-lane plans, W0 reproductions, falsification records and handoffs are under
`.shepherd/runs/v646/lanes/<lane>/`. The harness-parity table required by gate H4 is at
`.shepherd/runs/v646/harness-parity.md`.

## F. Carry-forward

`.shepherd/runs/v646/carry-forward.md` — ten items, led by the regression in section B.
v6.4.5's carry-forward existed on disk but was never tracked, which is why its CRITICAL item
had to be rediscovered; the ignore rule is fixed and this one is committed.
