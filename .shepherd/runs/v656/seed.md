---
title: v6.5.6 Seed — prove the plugin lifecycle under every supported harness
branch: v6.5.6
base: main
kind: sprint-seed
status: ready-for-engineer
date: 2026-08-22
author: planter @ pi-sol-v656
planter_mesh: .shepherd/runs/v656/mesh.md
prior_close_report: .shepherd/runs/v651/close.md
prior_reliability_close: .shepherd/runs/v646/close.md
tracking_issue: 374
milestone: MISSING — create v6.5.6 and attach #374 plus PR #372
open_pr: 372 (v6.5.6 → main, OPEN, draft, merge state CLEAN)
sprint_dependencies: []
sprint_size: M
sprint_metadata:
  expected_loc_delta: non-positive
  subtract_note: >-
    v6.4.6 already closed installation, PATH shadowing, fresh identity, hook declaration
    parity, configuration authority, and release-gate falsifiability. v6.5.6 must prove those
    outcomes still hold, not rebuild them. Reuse the Rust core, Component Model boundary,
    config crate, existing package fixtures, and existing hook carriers. A new parser, wrapper,
    artifact subsystem, shell policy parser, or harness-specific policy authority is critic RED.
file_scope:
  exclusive:
    - packages/harness-pi
    - packages/harness-claude
    - packages/harness-codex
    - packages/component-runtime
    - crates/core
    - crates/cli
    - crates/component
    - hooks
    - content/predicates
    - scripts
    - .github
    - .claude/settings.json
    - docs
    - Cargo.toml
    - Cargo.lock
    - package.json
    - package-lock.json
    - .gitignore
    - services/eval/evals
  additive:
    - README.md
    - CHANGELOG.md
    - SECURITY.md # NEW
---

# v6.5.6 — one native policy core, three truthful harnesses

## A. Mandatory first handoff message

State verbatim:

> This is a shepherd plugin reliability pass for `FL03/shepherd@v6.5.6`; hook reliability is in scope.

Then record exact branch, HEAD, clean worktree, native Cargo CLI path, `shepherd doctor` output,
tracked version-authority equality, dependency baseline, and artifact custody before any work.
All active versions remain `6.5.6`; no bump is needed. Any later dependency or authority change
lands in the same reviewed commit path as the behavior requiring it.

## B. Hard-stop preconditions

- Branch must be exactly `v6.5.6`; worktree must be clean before dispatch.
- `shepherd doctor` must exit 0 and resolve `/Users/jo3/.cargo/bin/shepherd` as native.
- `/Users/jo3/vaults/pzzld` and `/Users/jo3/Documents/vaults/pzzld` must resolve to the same
  project, with a regular `.shepherd/project.json` readable through the no-follow path.
- This exact class is fatal and its full output is recorded:
  `cannot open project identity /Users/jo3/Documents/vaults/pzzld/.shepherd/project.json without following symlinks: No such file or directory (os error 2)`.
- The live Pi `call_*|fc_*` rejection reproduced in `mesh.md` is the first execution blocker.
  Planning may proceed; implementation work must begin with #368 and prove normal Pi writes work.
- No Cargo install probe runs until identity, hook, and active-run checks pass.
- No production publish, merge, tag, release, or permission change occurs without operator confirmation.

## C. Locked engineering decisions

1. The Rust CLI and Component Model remain the only policy authority. Adapters translate.
2. `config` owns general configuration parsing. `toml` is allowed only for the existing typed,
   non-configuration guard predicate documents unless a gate proves another narrow object need.
3. Unknown shell effects fail closed. Do not build an ad hoc shell-language parser.
4. Build and package outputs remain ignored or externally staged. Do not create a tracked
   `build-artifacts/` tree or restore a repo launcher.
5. v6.4.6 claims are regression hypotheses. A green current reproduction means no code change.
6. Every fix ships with one deterministic regression test and one periodic eval that would have
   caught the defect. Acceptance proves the intended cases ran and includes a negative control.
7. PR #372 remains draft until all P0/P1 evidence is reviewed on the exact integration commit.

## D. Deliverables

### Pi accepts native tool-call IDs without weakening identity

**Priority:** CRITICAL
**GH:** #368

Normalize standard Pi/OpenAI `call_*` and `fc_*` tool-call identifiers at the adapter boundary.
Do not relax project, run, lane, role, dispatch, or session identifier validation. Reproduce the
planting-session failure before the fix, then prove structured Write/Edit and guard calls complete
through Pi afterward. Add adversarial malformed identifiers and cross-field confusion cases.

### Pi exposes the complete closed flock

**Priority:** CRITICAL
**GH:** #370

Register exactly `shepherd`, `planter`, `engineer`, `conductor`, `critic`, `coder`, `auditor`,
`discovery`, and `worker` through the Pi subagent provider. Preserve the literal requested role,
tier resolution, lane, bounded scope, acceptance, and report path end to end. Do not invent aliases
or a tenth role. Prove each role dispatches or is correctly denied by capability policy.

### Dispatch records and write guards tell the truth

**Priority:** HIGH
**GH:** #320, #334

Record actual lane and bounded write scope; represent read-only as explicitly non-writable, never
`["**"]`. Apply equivalent least-authority policy to structured writes, patches, and shell-capable
paths. Missing or empty Bash command input cannot allow. Where arbitrary shell effects cannot be
proven, fail closed with an actionable reason. Test identical effects across every mutation carrier.

### First run and legacy config produce actionable transitions

**Priority:** HIGH
**GH:** #367, #369

A clean project gets an explicit `plant → spawn` transition, and a legacy `paths.reports` project
either receives bounded compatibility or one reversible migration action. General parsing stays in
`config`; no handwritten merge or parallel TOML configuration path. Prove clean, legacy, partial,
and interrupted states without overwriting identity or canonical registry rows.

### Active version and organization identity are singular

**Priority:** HIGH
**GH:** #351, #326

Expose one compatibility marker across source, native CLI, package cache, and all adapters. Replace
remaining FL03 runtime/install URLs with canonical `pzzld-org` locations while preserving historical
records. Cold source install, metadata-only Binstall, and normal harness install must report the exact
candidate version with no checkout or stale PATH entry involved.

### Gate evidence records execution, not substrings

**Priority:** HIGH
**GH:** #374

Separate command text observed, gate process invoked, and gate completed successfully. Comments,
`echo`, `printf`, quoted strings, concatenation, aliases, wrappers, missing commands, and failing
gates cannot mint successful verification provenance. Reuse structured lifecycle events or mark the
claim unverified. Remove superseded substring authority after parity is proven.

### Hook behavior is proven across Claude, Codex, and Pi

**Priority:** HIGH
**GH:** #374

Generate an event × harness matrix for identity, session open/close, dispatch start/stop, guard
allow/deny/unresolved, report completion, compaction, and failures. Test behavior, not declaration
strings. Each supported cell records input, native result, adapter translation, durable artifact, and
negative control. Unsupported host capabilities are explicit limitations, never fabricated parity.
The clean consumer proof completes role → dispatch → guard → report on all three harnesses.

### Dependency and contributor posture are release-owned

**Priority:** HIGH
**GH:** #374

Classify npm and Cargo findings by production/dev closure, reachability, affected package, fixed
version, and shipped artifact. Remove, upgrade, or time-bound every reachable production high or
critical. Add deterministic unwaived-finding policy and missing update coverage without making
registry uptime trusted. Remove shared bypass permissions, unrestricted shell grants, and prompt
suppression from `.claude/settings.json`; document the minimum dogfood posture in `SECURITY.md`.

### Release state and artifact custody close cleanly

**Priority:** MEDIUM
**GH:** #374

Create milestone `v6.5.6`, attach #374 and PR #372, and keep the PR draft. Prove no build artifact,
repo launcher, generated package, or mutable release legal payload is tracked. Fix the authority
scanner's ignored `.pi/` false positive without excluding tracked source. Existing release staging,
archive inventory, checksums, and legal-payload gates remain the mechanism.

## E. Explicitly out of scope

- Rebuilding Cargo Binstall metadata, release workflows, hook manifests, or config precedence when
  current regression probes pass.
- Adding a parser, framework, config authority, artifact service, or harness-local policy engine.
- Reopening historical v6.4.6 issues without a current failing reproduction.
- Publishing or merging #372 during implementation.
- Formal verification or unsupported-host parity claims.

## F. Required evidence and gates

1. **PREFLIGHT:** exact branch/HEAD, clean tree, native CLI, doctor, identity, version, dependency,
   and artifact checks are durable before dispatch.
2. **P0-FIRST:** #368 red/green proof and normal Pi tool execution pass before other implementation.
3. **GATE-CAN-FAIL:** every changed gate has a recorded negative control and zero-test discovery fails.
4. **CLEAN-CONSUMER:** isolated homes with no checkout or stale PATH prove both Cargo install paths.
5. **HARNESS-SEMANTICS:** 3/3 complete lifecycle flows and 100% declared supported matrix cells pass.
6. **LEAST-AUTHORITY:** read-only, bounded-write, shell-unknown, missing-input, and sibling-lane cases pass.
7. **CONFIG-AUTHORITY:** general config behavior has zero direct `toml::` parsing; the predicate object
   exception stays documented and tested.
8. **TEST + EVAL:** each fixed defect has a deterministic regression and a periodic eval case.
9. **SUBTRACT:** superseded wrappers, carriers, substring proofs, and unsafe defaults are deleted.
10. **INTEGRATION:** fast/full Rust, Node, hook, component, package, archive, supply-chain, Linux, and
    Windows gates pass against one exact commit; PR #372 remains draft pending review.

## G. Measurable exit

- Pi performs normal writes and exposes 9/9 roles with literal identity.
- Claude, Codex, and Pi each complete one clean role → dispatch → guard → report lifecycle.
- All supported hook matrix cells pass behaviorally; limitations are explicit.
- Cold `cargo install` and metadata-only `cargo binstall` report `6.5.6` without repo state.
- Zero vacuous write scopes, substring-only gate proofs, tracked build outputs, repo launchers,
  unsafe shared defaults, unowned config parsers, or unwaived reachable production highs/criticals.
- Every issue closure links failing-before and passing-after evidence from the exact integration SHA.
- `.shepherd/runs/v656/seed.md` remains the single handoff; close emits one restart command set.

## H. Sizing recommendation

This is a medium reliability sprint because the defects are independent but the authorities already
exist. The plan should maximize file-disjoint work after #368 clears Pi dispatch, reuse installed
dependencies, and bias every partition toward deletion. Sequencing belongs to the engineer.
