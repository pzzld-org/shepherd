---
title: v6.4.6 Seed — the plugin installs, the hooks fire, and the release publishes itself
branch: v6.4.6
base: main
kind: patch-seed
status: ready-for-engineer
date: 2026-08-17
author: planter @ plant-v646-2026-08-17
planter_mesh: .shepherd/runs/v646/mesh.md
prior_close_report: none — no close.md exists anywhere under .shepherd/runs/ (mesh ROW 13)
prior_handoff: .shepherd/runs/v645/handoff.md — read, and superseded on its headline item (mesh ROW 12)
milestone: MISSING — no v6.4.6 milestone exists; milestone 58 is v6.4.5 (10 open), 59 is v6.5.0.
  gitflow.yml would have created it and never ran (mesh ROW 5). Creating it is a W0 step.
open_pr: 304 (v6.4.6 → main, open, not draft)
sprint_dependencies: []
sprint_size: M
sprint_metadata:
  expected_loc_delta: negative
  subtract_note: >-
    This is a repair patch, not a feature patch. Two of the operator's four asks are already
    implemented (mesh ROW 0); a third is 85% implemented. Net-new surface is one config tier
    and one Pi hook manifest. Everything else is deletion, de-duplication, and making an
    existing gate capable of failing. A plan that proposes building a release workflow or a
    model map from scratch has misread the mesh and is a critic-RED escalation.
file_scope:
  exclusive:
    - bin
    - scripts
    - .github/workflows
    - crates/cli/src/cmd/wave_c_bootstrap.rs
    - crates/cli/src/cmd/dispatch.rs
    - crates/core/src/loader.rs
    - hooks
    - packages/harness-pi
  additive:
    - CHANGELOG.md
    - README.md
    - crates/core/src/settings.rs
    - plugins/shepherd
    - .shepherd/shepherd.toml
    - agents
---

# v6.4.6 — stop shipping a plugin that cannot install itself

## A. Patch theme

Every capability this repo has built over v6.4.x is currently unreachable from a clean machine.
The install path documented as primary is broken, the hooks that carry the plugin's behaviour
exit 127 before they run, and a freshly initialized project is structurally incapable of
dispatching. This patch fixes the chain that delivers the product, and fixes nothing else.

The theme is **repair and subtract**. The Rust foundation is written; the release automation is
written; the model map is written. None of it runs. v6.4.6 carries the torch by making what
exists execute, and by deleting the compensating workarounds that accumulated while it did not.

## B. Why this patch

Mesh ROW 14 establishes that everything the operator reported is one failure propagating:

```
create-release-tar.sh uses GNU-tar-only flags
 └─> aarch64-apple-darwin packaging fails (+ Windows dangling-symlink test fails)
      └─> "Publish verified release" is skipped
           └─> every GitHub release carries zero assets
                └─> binstall pkg-url 404s
                     └─> disabled-strategies removed the compile fallback
                          └─> `cargo binstall` hard-fails; only `cargo install` works
                               └─> bin/shepherd is symlinked into ~/.local/bin as a stand-in
                                    └─> it shadows the real ~/.cargo/bin/shepherd, exit 127
                                         └─> every hook in every harness fails
                                              └─> and where a binary DOES run, `shepherd init`
                                                  produced a project with no identity file
```

Each link is reproduced first-hand in the mesh with the exact command and output. The release
gate reported **green** throughout, so none of it ever surfaced as a red build.

## C. Priors and lessons carried forward

1. **The v6.4.5 carry-forward's CRITICAL is resolved — do not re-open it.** `carry-forward.md
   §0` says the guard engine is Python and must be Rust. Re-measured at seed time:
   `crates/core/src/guard/{engine,json,model,parser,tokenizer}.rs` exist, `crates/cli/src/cmd/
   guard.rs` exists, `services/cli` is gone, and 24 tracked `.py` files remain (tooling and
   conformance only, no engine). Carrying it forward would burn the largest lane on finished
   work. (mesh ROW 12)
2. **Gates that cannot fail is the repeating failure class in this repo, and it is now on the
   release path.** Three instances measured this seed: a release run that concludes `success`
   while skipping every job (ROW 5); `hooks/tests/run.sh` executing 6 of 24 test files, where
   the 18 skipped are precisely the tests for the de-registered hooks (ROW 7); and
   `scripts/tests/test-cargo-binstall-local.py`, a binstall test that passes locally while
   binstall is 404-broken in production. Every gate this sprint touches must be made to fail on
   purpose before it is trusted.
3. **Local verification agreed with a false portability claim.** `create-release-tar.sh:44-46`
   asserts its flag set is shared by GNU tar and bsdtar. It is not, and it passes on this
   machine's bsdtar 3.5.3 while failing on the runner's older libarchive. Platform claims get
   verified on the platform, in CI, or they are not verified. (ROW 3)

## D. Engineering decisions (locked)

Changing one of these is a critic-RED escalation, not a sprint-time judgment call.

1. **Do not author a release workflow.** `.github/workflows/gitflow.yml` already implements
   tag → release → version bump → cut next patch branch → draft PR → milestone roll, and
   mod-10 is enforced in two independent places (`gitflow.yml:130-145` and
   `scripts/version-bump.py:86` `successor()`, guarded by a `VersionAuthorityError` at `:80`
   that rejects any minor or patch above 9). The operator's ask is satisfied by making it
   *fire*, not by writing a second one.
2. **Do not author a model map.** `shepherd models resolve <role> --harness <claude|codex|pi>`
   already returns the 9-role × 3-harness table, backed by `ModelsConfig`
   (`crates/core/src/settings.rs:545`) with `[models]` in `.shepherd/shepherd.toml` as the
   project override. The delta is three values and one missing tier (deliverable 8).
3. **`dep:config` owns configuration; `dep:toml` is for non-configuration TOML documents
   only.** Operator rule, restated as policy. `crates/core/src/guard/parser.rs` is the one
   legitimate `toml::` consumer — it parses `content/predicates/*.toml` domain documents with
   `[[rule]]`/`[[example]]` array-of-tables and an open `extra` map surfaced as dynamic
   `GuardValue`, which is a document format, not configuration. The other three call sites are
   configuration logic duplicating what `config` already provides (deliverable 6). No agent
   migrates configuration *toward* `toml`; the direction is one-way.
4. **The wrapper goes; the binary stays.** `bin/shepherd` is a checkout-only convenience that
   became a production failure the moment it was linked onto PATH. Prefer deletion (SUBTRACT)
   over patching its resolution logic. If the plan keeps it, it must never be installable, and
   `scripts/install-shepherd.sh` must refuse to place it on PATH.
5. **`NOFOLLOW` stays.** Refusing to follow symlinks when reading project identity is correct
   security policy and is pinned by `crates/cli/tests/dispatch_cli.rs:232` and
   `crates/cli/tests/wave_f_knowledge.rs:111`. Only the *error classification* changes.
6. **Scaffolding is atomic or it fails.** A `.shepherd/` namespace that has a database but no
   identity is not a degraded state to tolerate; it is the state that produced this sprint. If
   `init` cannot write every required artifact, it must leave nothing behind and say why.
7. **Codex and Pi are first-class, not derived.** Harness fidelity means each of the three
   binds identity, guards tool use, and closes dispatch. A harness that silently defines fewer
   events than another is a regression, not a capability difference (deliverable 5).
8. **Model tiers for this sprint's own execution: sonnet and haiku only.** Operator directive,
   2026-08-17. Plan authorship (engineer) and root are the stated exceptions in the flock map;
   every implementer, auditor, critic, and discovery dispatch runs sonnet or haiku.

## E. Deliverables

Each anchors to a tracked issue or an explicit carry-forward with mesh evidence.

### 1. `cargo binstall shepherd-cli` succeeds on a clean machine — BLOCKER
**Anchors:** mesh ROW 2, ROW 3. **Issue:** none filed; file one.
Four independent defects sit between a merge and a downloadable asset. All four must clear;
fixing any three still yields a zero-asset release.

**1a. macOS arm64 packaging.** `scripts/create-release-tar.sh:47` uses `--owner 0 --group 0`,
under a comment (`:44-46`) asserting that set is shared by GNU tar and bsdtar. GNU tar has
`--owner/--group` and no `--uid/--gid`; older libarchive has the reverse. Run `31895705712`
died on `tar: Option --owner=0 is not supported` on the `macos-14` (arm64) runner.
`4c7c050` then changed `--owner=0` to `--owner 0` — and **no release run has exercised the
macOS packaging path since**, because every subsequent run skipped every job (ROW 5). The fix
is therefore *unverified, not verified*. Treat it as unproven until a macOS runner executes it.
**1b. Windows.** `scripts/tests/test-release-installer-windows.ps1:370` creates a deliberately
dangling symlink; PowerShell 5.1 refuses without `-Force`.
**1c. The asset verifier looks for packages that do not exist.**
`scripts/verify-release-distribution.sh:86-87` extracts
`fl03-{component-runtime,harness-claude,harness-codex,harness-pi}-${version}.tgz`. The actual
published names are `@pzzld/component-runtime`, `@pzzld/pi-claude`, `@pzzld/pi-codex`,
`@pzzld/pi-shepherd`, so `npm pack` (`release.yml:348`) emits `pzzld-pi-claude-6.4.6.tgz` and
friends. **Both the scope prefix and three of the four package names are wrong.** This runs at
`release.yml:483`, inside the publish job — so even a green build fails here.
**1d. crates.io publishing is dead by construction.** `cargo-publish.yml:3-4` triggers on
`push: tags: ["v*.*.*"]`, and `release.yml` pushes the tag using `secrets.GITHUB_TOKEN`.
GitHub does not trigger workflows from `GITHUB_TOKEN`-authored events. The lane can only ever
run via `workflow_dispatch` — which is why crates.io `shepherd-cli 6.4.5` exists with no
GitHub assets behind it.

Then verify `pkg-url` (`crates/cli/Cargo.toml:60`) resolves to a real object with the binary at
the archive root, matching `bin-dir = "{ bin }{ binary-ext }"`.
**Acceptance:** a CI job runs the packaging script on `macos-14` and asserts the archive layout
binstall expects; the asset verifier's expected names are derived from `package.json`, not
hardcoded; `curl -I` on the published v6.4.6 `pkg-url` returns 200; the tag push uses a
credential that can trigger `cargo-publish.yml`.
**Note:** `scripts/tests/test-cargo-binstall-local.py` passes today while binstall is
404-broken in production — it tests a local archive, never the published URL. Prior C2 applies.
**Consider:** #301 (`cargo xtask`) is the operator's own preference for consolidating this
orchestration rather than hand-patching shell. Engineer's call, but adopt-over-rewrite is the
house rule.

### 2. `shepherd` on PATH is the native binary — BLOCKER
**Anchors:** mesh ROW 1. **Issue:** #307.
Delete `bin/shepherd`, or make it structurally uninstallable. `scripts/install-shepherd.sh`
currently defaults to the exact directory the launcher symlink occupies; it must not be
possible for the repo launcher to precede `~/.cargo/bin/shepherd` on PATH.
**Acceptance:** with `~/.local/bin` ahead of `~/.cargo/bin`, `shepherd --version` prints the
native version. `shepherd doctor` detects and reports when the resolved `shepherd` is not the
native binary. The launcher's existing test is wired into a gate that runs.

### 3. A freshly initialized project can dispatch — BLOCKER
**Anchors:** mesh ROW 6. **Issue:** #306.
`initialize_project` (`crates/cli/src/cmd/wave_c_bootstrap.rs:282`) creates the directory tree,
the comment-only `shepherd.toml`, and the migrated registry — and never writes
`project.json`. Confirmed: `scaffolded_at` appears in the entire workspace only in three test
fixtures. The pzzld vault is not corrupted; it is the exact, expected output of `shepherd init
--confirm`, which means **every project this tool has ever created is born unable to
dispatch**. Nothing inserts a `projects` row either.
**Acceptance:** `shepherd init --confirm` in an empty directory produces a namespace where
`shepherd dispatch` and every registry-backed verb succeed. `shepherd doctor` fails — loudly —
on a namespace missing identity, instead of reporting `status: ok`. The init gate test asserts
the complete artifact set, and is shown to fail when identity is removed.

### 4. Errors name the actual failure — BLOCKER
**Anchors:** mesh ROW 6. **Issue:** #306.
`crates/cli/src/cmd/dispatch.rs:186-193` maps every `rustix::fs::open` failure to `"cannot open
project identity {} without following symlinks"`, so a plain `ENOENT` reads as a symlink
refusal. The same phrasing is duplicated at `crates/cli/src/cmd/wave_f_knowledge.rs:963`. This
message cost the operator a full diagnostic pass down the symlink path, which the mesh proves
was never the cause.
Classify by errno: `ENOENT` → "project not scaffolded — run `shepherd init`"; `ELOOP`/NOFOLLOW
→ the security refusal; `EISDIR` → not a regular file.
**Acceptance:** a test asserts each of the three messages from its real errno. The symlink
refusal test still passes unchanged.

### 5. Every harness defines every hook — HIGH
**Anchors:** mesh ROW 7. **Issues:** #290, and the de-registration in `ffd9aea`.
- Codex's shipped manifest (`plugins/shepherd/codex/hooks/hooks.json`) lost `SubagentStart` and
  `SubagentStop` in the Rust-native migration; the superseded node manifest still has them.
  Restore both.
- Pi has **no hook manifest at all** — `packages/harness-pi/shepherd.pi.json` declares only
  `transitions.resume`/`stop`. Pi binds no identity and guards no tool use. Give it parity.
- Seven hook scripts under `hooks/scripts/` are registered nowhere after `ffd9aea` replaced
  them with `crates/cli/src/cmd/claude_hook.rs` (+377 lines). Retire them, or register them.
  Do not leave both.
- `hooks/tests/run.sh` executes 6 of 24 test files; the 18 it skips are the tests for the
  de-registered scripts. Either the tests run or the files go.
- `hooks/scripts/hook_authority_inventory.py` audits only `hooks/hooks.json`, so the shipped
  Codex carrier manifest has never been checked by it.
**Acceptance:** one table, generated not hand-written, showing event × harness × implementation
for all three harnesses, with no blank cells that are not a documented harness limitation. Each
harness's hooks are exercised against a real invocation.

### 6. Configuration parsing belongs to `config` — HIGH
**Anchors:** operator directive 2026-08-17; mesh ROW 0.
Four `toml::` call sites exist in `crates/*/src`. `guard/parser.rs` is legitimate and stays.
The other three are configuration logic:
- `crates/core/src/loader.rs` parses each layer with `toml`, re-serializes it, and hands it to
  `config` to parse **a second time**. Per-layer semantic validation additionally rejects
  configurations that are legal after merge.
- `crates/cli/src/cmd/wave_a_models.rs:285` re-reads and re-parses a config file the
  `ExecutionContext` already parsed.
- `crates/cli/src/cmd/wave_c_bootstrap.rs:324` hand-walks a dotted key over `toml::Value`
  instead of using `config`'s path expressions.
Also: the `config` feature in `crates/core/Cargo.toml:157-161` force-enables `dep:toml`, and
`loader.rs` is the only reason it must.
**Constraint:** comment-preserving migration rewrites are a genuine `toml` use. Keep exactly
those; delete the duplicated merge and validation. Do not break the migration paths pinned by
`crates/cli/tests/migrate_layout.rs` and `crates/registry/tests/layout.rs`.
**Acceptance:** the double-parse is gone, per-layer validation moves post-merge, and the
existing loader and migration tests pass unchanged.

### 7. The release gate can fail — HIGH
**Anchors:** mesh ROW 5.
A push to `main` whose subject does not match the release regex sets `proceed=false`, skips
every job, and concludes **`success`**. `gitflow.yml:26` chains on that conclusion, so the
post-release automation the operator asked for hangs off a signal that is green for a no-op.
Distinguish "not a release commit" (a real skip) from "a release commit that produced nothing"
(a failure). Then confirm the full chain end-to-end on the v6.4.6 merge: tag, release with
assets, version bump, next patch branch, draft PR, milestone roll.
**Acceptance:** a deliberately-broken release commit turns the run red. The v6.4.6 release
carries assets and the v6.4.7 branch and draft PR are cut automatically.

### 8. The model map states the intended tiers — MEDIUM
**Anchors:** mesh ROW 9. **Issue:** #181.
Operator's intent: root and planter and engineer at opus; conductor opus or sonnet; coder,
worker, auditor, critic at sonnet; discovery sonnet or haiku.
Current resolution matches for seven of nine. Deltas: `root` is `inherit-caller` → `inherit`
and must be opus; and there is **no economy tier** in the portable vocabulary
(`crates/core/src/settings.rs:557-570` has only `inherit-caller`, `reasoning-high`,
`standard`), so "discovery on haiku" is currently unexpressible. Add the tier, set the two
values, and reconcile the second copy of this map in `agents/*.md` frontmatter so there is one
authority.
**Acceptance:** `shepherd models show --md` renders the operator's table exactly, for all three
harnesses.

### 9. CHANGELOG and release notes are truthful — BLOCKER for the release itself
**Anchors:** mesh ROW 10.
`CHANGELOG.md` has no `## v6.4.6` section, and `release.yml:437-462` **hard-fails** (`exit 1`)
when notes extraction finds no matching section — so this sprint's release is already
guaranteed to fail before it builds anything. `CHANGELOG.md:7` also still reads `## v6.4.5 —
unreleased` although v6.4.5 tagged and published on 2026-08-15.
`hooks/tests/test_changelog_current.sh` exists to catch exactly this and is one of the 18 tests
`run.sh` never executes.
**Acceptance:** the section exists, v6.4.5 is marked shipped, and the changelog test runs in a
gate that is shown to fail without the section.

### 10. Create the v6.4.6 milestone and reconcile v6.4.5 — LOW
No `v6.4.6` milestone exists (58 is v6.4.5 with 10 open, 59 is v6.5.0) because gitflow never
ran. Several of the 10 open v6.4.5 issues describe work that has since landed (see ROW 12).

## F. Sprint topology

Recommended shape only. The engineer's Stage Graph is binding.

| Lane | Theme | Deliverables | Depends on | Parallel-safe with |
|---|---|---|---|---|
| A | Distribution: packaging, launcher, install | 1, 2 | — | B, C, D |
| B | Identity: scaffolding and error classification | 3, 4 | — | A, C, D |
| C | Harness fidelity: Claude, Codex, Pi hooks | 5 | — | A, B, D |
| D | Config policy and model map | 6, 8 | — | A, B, C |
| E | Release chain end-to-end | 7, 9, 10 | A | — |

Lane E is last by necessity: the release chain cannot be verified until packaging produces
assets. Lanes A–D are file-disjoint per `file_scope`.

## G. Explicitly out of scope

- Authoring any new release workflow or model-map subsystem (decisions D1, D2).
- The 20 open SQL-injection and guard issues (#284–#298). Real, but not on the delivery chain,
  and folding them in makes this the long sprint the operator explicitly asked it not to be.
- Retiring the remaining 24 tracked `.py` files. `scripts/version-bump.py` is load-bearing on
  the release path this sprint must not destabilize; it is the correct target for v6.4.7.
- The `plugins/shepherd` symlink question (mesh ROW 8) beyond **measuring** it. All nine agents,
  all seven skills, and the Claude hook manifest reach outside the declared plugin source. If a
  real marketplace install proves them dangling, that is a blocker and gets escalated; if it
  installs clean, it is a v6.4.7 tidy. Measure first, decide second.

## H. Gates

1. **W0-GATE** — deliverables 1, 2, 3 reproduce as failures before any fix lands. A sprint that
   cannot demonstrate the bug cannot demonstrate the fix.
2. **GATE-CAN-FAIL** — every gate this sprint touches or adds is shown to fail on purpose,
   with the failing output recorded in the lane artifact. Non-negotiable: three inert gates
   were measured at seed time (prior C2).
3. **CLEAN-MACHINE** — `cargo binstall shepherd-cli` and `shepherd init` are exercised in an
   environment with no repo checkout and no pre-existing `~/.local/bin/shepherd`.
4. **HARNESS-PARITY** — the generated event × harness table from deliverable 5 is attached to
   the close report.
5. **RELEASE-CHAIN** — the v6.4.6 merge produces a tag, a release carrying assets, a v6.4.7
   branch, and a draft PR, with no manual step.
