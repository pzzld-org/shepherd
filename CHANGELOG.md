# shepherd — changelog

Per-version history for the `shepherd` plugin (this repo). Format loosely based on [Keep a Changelog](https://keepachangelog.com/); follows [Semantic Versioning](https://semver.org/).

---

## v6.5.2 — unreleased

### Fixed — the Pi adapter has never been loadable by Pi

**`@pzzld/pi-shepherd` shipped with no `pi` key in `package.json`, for its entire
history.** Pi discovers everything a package contributes from that one key:

```json
"pi": { "extensions": [...], "skills": ["./skills"], "prompts": ["./prompts"] }
```

With it absent, Pi loaded **nothing** — not the nine skills, not the nine role
prompts, and not `src/extension.mjs`, which means the lifecycle hooks, the guard,
and native dispatch never ran either. The package installed cleanly and was
completely inert. `/shepherd:shepherd` resolved to nothing in the Pi TUI while
every other installed package listed its skills normally. Confirmed absent in
every commit that has ever touched that manifest.

This was never a content problem. `shepherd compile --target pi` has always
emitted exactly the shape Pi wants — `skills/<name>/SKILL.md` and
`prompts/<role>.md`, 19 files. Nothing put that output inside the package, and
nothing declared it.

Measured before and after, by resource count in Pi's own resolver:

| | Resources Pi registers |
| --- | --- |
| before | **86** (shepherd contributes 0) |
| after | **105** (shepherd contributes 19) |

19 = 9 skills + 9 role prompts + 1 extension.

The fix is three parts:

- `packages/harness-pi/package.json` declares `pi.extensions`, `pi.skills`,
  `pi.prompts`, the `pi-package` keyword, and a `files` list that actually packs
  the generated directories. A `pi` key naming `./skills` while `files` omits it
  is inert in the same way and harder to see, so the gate checks both.
- `scripts/stage-pi-carrier.sh` compiles the carrier into the **staged** package
  immediately before `npm pack`. It is not committed:
  `test-generated-carrier-authority.sh` fails if `packages/harness-pi/skills`
  appears in the repository, and that gate is correct — a hand-copied generated
  tree is a second, inevitably stale authority. The staging script states its
  counts and fails on zero, and cross-checks them against `content/skills`
  (minus `portability: claude-only`) and `content/roles` rather than hardcoding.
- `scripts/tests/test-pi-package-surface.sh` asserts the declaration, wired into
  `gate.sh`, falsifiable in three directions: a correct manifest passes, a
  manifest with no `pi` key fails (the exact shipped defect), and a
  declared-but-unpacked carrier fails.

**Why it went unnoticed for so long.** No gate ever asked what Pi ships.
`check-plugin.py` derives its roots from the Claude and Codex shipping manifests
only, so "Claude 10 skills, Codex 9, Pi 0" was not an assertion anywhere. The
v6.5.1 sprint audited gates extensively and did not catch this, because it
checked whether existing gates worked rather than whether the cross-harness
claim was true. Verifying the three harnesses are actually at parity was the
sprint's headline goal and it was never tested end to end.

## v6.5.1 — 2026-08-19

**Five remediation messages named a command that refuses to run.** `shepherd init` is gated
behind `--confirm` because it mutates: it mints `.shepherd/project.json`, the registry, and
the `projects` row. Five user-facing messages nonetheless printed a bare `shepherd init`, so
an operator on a cold project copied the remediation, got exit 2, and landed exactly where
they started. `shepherd doctor` carried the correct wording the entire time, which makes this
drift between call sites rather than a missing decision.

### Fixed

- **The remediation is runnable as printed.** `cmd/dispatch.rs`, `cmd/wave_b1_mem.rs`,
  `cmd/wave_b1_status_handoff.rs`, `cmd/wave_e_coordination.rs`, and
  `cmd/wave_g_coordination.rs` now name `shepherd init --confirm`. `cmd/wave_c_bootstrap.rs`
  already did; that inconsistency is what made the defect legible.
- **The gated-flag coupling cannot drift back.** `hooks/scripts/remediation_flag_lint.py`
  derives the gated-subcommand map from the CLI's own refusal text (`X is mutating; re-run
  with --FLAG`) and rejects any message, skill, or agent line naming a gated subcommand
  without its flag. A hard-coded list would stop covering a subcommand the day one is added,
  so there is no list. Falsified three ways in `hooks/tests/test_remediation_flags.sh`:
  a fixture reintroducing the exact v6.5.0 wording turns it red, a fixture with no refusal
  text turns it red rather than passing on zero coverage, and it caught a live violation in
  this change's own `SKILL.md` draft on first run.
- **The regression tests assert the flag, not the prefix.** `dispatch_cli.rs` and the
  `cmd/dispatch.rs` unit test previously accepted `run \`shepherd init\``, which is precisely
  the broken string. Both now require `--confirm`; reverting the source turns them red.

- **Carrier drift was a CI-only failure.** Editing `skills/shepherd/SKILL.md` silently broke
  `plugins/shepherd/codex/skills/shepherd/SKILL.md`, which `scripts/check-plugin.py` requires
  to be byte-identical. That script ran in `.github/workflows/rust.yml` and nowhere else, so
  the local gate lane was green while the cross-harness projection was broken, and the author
  learned about it from a red CI job twenty minutes later. `hooks/tests/test_plugin_contract.sh`
  now runs it in the gate lane (0.45s, both the plain scan and `--self-test`), and falsifies
  itself by drifting a scratch carrier and requiring a non-zero exit.

- **The root role answered to two names and only one of them worked.** `shepherd models
  resolve shepherd` printed `unknown role: shepherd` and exited 2 while `shepherd models
  resolve root` printed `opus[1m]` and exited 0, because two crates each hardcoded their own
  vocabulary: `crates/cli/src/cmd/wave_a_models.rs` `const ROLES` says `root`, and
  `crates/core/src/guard/engine.rs` `role_tier` says `shepherd` with no `root` arm at all.
  `content/`, `agents/`, `skills/` and the `shepherd:shepherd` subagent type all spell the
  role `shepherd`. `root` is canonical on the `models` surface and `shepherd` is a
  documented INPUT alias resolving to it, in that direction and not the reverse: `root` is
  the literal `[models]` TOML key operators write (`ModelsConfig::root`,
  `crates/core/src/settings.rs:546`), and `docs/configuration.md`'s default table is
  cross-checked against that field name by `scripts/check-workspace.sh`'s
  `rule_model_defaults_match_the_docs`, so renaming would ripple into `crates/core` and
  `docs/`, both outside this change's scope. `ROLES` stays 9 entries and `models show` never
  grows a `shepherd` row; the alias is input-only. The `unknown role` text is now built from
  `ROLES` and `ROLE_ALIASES` instead of being hand-typed a third time, and a unit test
  iterates both consts against the USAGE string rather than checking today's nine literal
  names, so adding a role or an alias without updating the usage text turns it red.

- **`shepherd seed verify` HARD-failed this project's own seeds.**
  `shepherd seed verify .shepherd/runs/v646/seed.md` exited 1 on `footprint 393 lines > cap
  200 (kind=patch-seed)` and on `file_scope path does not resolve and is not marked (NEW):
  bin`, where `bin` is a directory v6.4.6's own decision D4 deleted after that seed was
  written: the gate was validating a historical artifact against the live tree. Two written
  rules now bound that. First, an unresolved `file_scope` path degrades to a warning only
  when the seed's run has closed, and "closed" requires both a sibling `close.md` and the
  path shape `runs/<id>/seed.md`; every other seed keeps today's HARD failure byte-identical.
  Second, the declared `kind` selects the smell threshold, not the ceiling: 400 lines is the
  HARD ceiling for every seed whatever its label, so relabelling a seed down buys no slack,
  and a `patch-seed` over 200 lines now gets a warning naming the mislabel. Neither
  `SPRINT_FOOTPRINT_CAP` nor `PATCH_FOOTPRINT_CAP` changed value; the v6.4.6 carry-forward
  required that no number move. The path-shape half is the safety property:
  `hooks/scripts/seed_preflight_check.sh` runs the live SEED-GATE against a bare
  `mktemp -t shep-seed.XXXXXX` file in `$TMPDIR`, so a sibling-`close.md` test alone would
  let any stray `close.md` in `$TMPDIR` silently downgrade that gate for every seed a
  planter writes; the temp copy is never named `seed.md` and never sits inside a
  `runs/<id>/` directory, which makes the hook structurally immune. Rejected: a
  frontmatter-date comparison (the verdict would change with the calendar) and resolving
  paths against the commit the seed names (`base: main` is a moving ref, and the hook's
  temp-dir copy has no commit at all). v646 now exits 0 with 2 warnings and v651 exits 0
  with 1 warning, while v645, historical but with no `close.md` on disk, keeps both of its
  unresolved-path HARD failures byte-for-byte: "historical" is not a bypass, "closed" is a
  fact on disk. A relaxation is only distinguishable from a disabled check by what still
  fails, so forcing the path-shape predicate to return `true` turns exactly one test red
  (`close_md_beside_a_non_run_shaped_seed_path_does_not_relax_anything`), a closed run's
  seed carrying a `TODO:` marker still HARD-fails, and a 401-line seed is HARD over the
  ceiling whether it is labelled `sprint-seed` or `patch-seed`.

- **80 shell assertions that could not say what they enforced, and 10 that could not fail.**
  A bare `rg -q` prints nothing, so `set -e` killed the script and named no requirement.
  Worse, **bash 3.2 does not honour `set -e` for a failing `[[ ]]`** and macOS cannot ship
  newer, so ten assertions were inert on the platform where development happens. That class
  had already hidden a false count in `test-release-workflow.sh` since v6.4.6, invisible
  until `gate.sh fast` was wired into Linux CI. All 80 now name their requirement, and
  `hooks/tests/lint_shell_assertions.sh` bans both forms.
  Three sites in `hooks/scripts/_lib.sh` were **deliberately left alone**: they are the final
  expression of predicate functions, where the exit status is the boolean result, and guarding
  them would hard-exit on the negative branch — `quiet_warnings` defaults to false, so every
  hook would have died whenever an operator had not opted in. The lint carries that exclusion.
  Every conversion is append-only: the original command byte-identical plus a guard, verified
  mechanically at 80 conversions and 0 violations.

- **A gate wired to nothing had been red for three refactors, and no one could tell.**
  `scripts/tests/test_cli_authority_gate.sh` was correct, falsifiable, and referenced by
  no runner, no workflow, and no suite. Running it for the first time found three
  independent failures it had accumulated undisturbed. Its legacy-bootstrap sweep named
  `$ROOT/bin`, a directory D4 **retired** — ripgrep exits 2 on a missing path, and because
  the call sat inside an `if`, `set -e` was suppressed and rc=2 took the same branch as
  rc=1, so the sweep reported clean *by erroring out*, every run since the launcher was
  removed. Its `hooks.json` assertion demanded the native dispatch shape for **every** hook,
  which stopped being true the moment the seven carrier hook scripts were restored. And
  three lifecycle assertions still pointed at `claude_hook.rs` after the lifecycle moved to
  the harness-neutral `native_hook.rs`. All three repaired, and the manifest rule now states
  what is actually true — every registration is either native dispatch or a carrier script
  that **resolves on disk** — printing its count (11 checked: native=4, carrier-script=7,
  unresolvable=0) so a manifest registering zero hooks cannot pass by vacuous truth.

- **The unwired-gate class is now structurally unreachable.** This was its fourth
  occurrence; `hooks/tests/run.sh` had it once with a hand-maintained array covering 6 of
  27 files, leaving 21 tests unrun. `scripts/check-gate-wiring.py` asserts every test file
  is reachable from a runner, computing reachability transitively to a fixed point and
  treating glob discovery as first-class wiring — so the fix for the original defect is not
  penalised by the checker that prevents its recurrence. Prose is excluded from the evidence
  set: a CHANGELOG mention is a reference to a test, not an execution of one. The checker
  laundered its own finding twice before it worked — its docstring names the file it was
  written to catch (and `.py` is not prose), and a `.shepherd/` lane worklist names it too.
  A checker must never be its own evidence. Six self-test cases, both directions.

- **An exact version pin on a third-party CLI, masking three defects behind it.**
  `test-codex-marketplace.sh` asserted `== "codex-cli 0.147.0"`, so Codex shipping 0.148.0
  turned it red with nothing in this repository having regressed — and the reflex fix, bumping
  the literal, teaches that the gate is noise. It is now a **floor**. Converting it let the
  assertions *after* it run for the first time in a while, and all three were wrong: the
  install-path check compared two string spellings of one directory (macOS `$TMPDIR` ends in
  a slash, and `/var` is a symlink to `/private/var`) instead of resolving them; the skill
  count was hardcoded at 7 when the carrier ships 9, `plant` having been restored this
  sprint, and is now **derived** from `content/skills` minus `portability: claude-only`; and
  the success line hardcoded the very version it had just stopped asserting.

### Changed — the release pipeline is three workflows, not one

`release.yml` inlined the entire build, which made every release asset reachable through
exactly one event: a patch branch merging into `main`. There was no way to rebuild a target
without cutting a version, and no way to exercise packaging on a branch. The file went from
719 lines to 387.

- `cargo-build.yml` owns every asset. Four trigger classes — `workflow_call`,
  `workflow_dispatch`, `repository_dispatch`, and a tag push — plus a `scope` input
  (`all` | `native` | `component`) for partial runs. One `resolve` job decides the version
  and the checkout ref once, and everything else consumes them.
- `cargo-publish.yml` owns crates.io, reachable the same four ways. Its `workflow_dispatch`
  block had a malformed `jobs:` key nested under it; that is repaired.
- `release.yml` keeps metadata, the two `uses:` calls, and tag and release custody.

`publish-crates` still needs the whole build to succeed first. That ordering is not
cosmetic: publication once ran as its own push-triggered workflow, raced the asset builds,
and won — two consecutive patch versions were burned with crates uploaded, a native target
failing minutes later, and no tag. A crates.io version is not reissuable, so a failed asset
build must cost a re-run, never a version.

`repository_dispatch` `client_payload` is authored by whoever sends it and is grantable
**without** `contents: write`, so both new workflows resolve the checkout ref through a
fail-closed allowlist passed via `env:`, never spliced into a shell command.

**The gates followed the jobs.** `test-release-workflow.sh` asserted 47 asset properties
against `release.yml`; every one was retargeted to `cargo-build.yml`, none dropped or
softened. Its checkout assertion counted `ref: ${{ github.sha }}` occurrences and reported
"4 of 2" after the split, because `release.yml` now also passes that SHA as an *input* — it
asserts the real property per file instead. New assertions cover the split itself:
`release.yml` must delegate via `uses:` **and** must not redefine the jobs it delegated, and
must forward `CARGO_REGISTRY_TOKEN` explicitly, because `workflow_call` does not inherit
secrets.

- **`actionlint` now runs on every workflow.** Reusable-workflow wiring — a `workflow_call`
  input the caller never passes, a required secret the caller omits, a `needs:` naming a job
  that moved — parses as valid YAML and fails only at dispatch time. It is wired into
  `gate.sh` (with a **stated** SKIP when absent locally, never a silent no-op) and into CI
  pinned through `taiki-e/install-action`. It immediately found `SHIFT=patch` in
  `gitflow.yml`, where `patch` is also a real binary; fixed by quoting rather than suppressed.

### Documentation

- **`QUICKSTART.md` is new**: install, initialize, and run a first sprint, with the
  `plant` → `spawn` → `start` arc explained in terms of what each moves the run *from* and
  *to*. Every command in it was executed before it was written.
- The README carried three stale facts, all corrected: the native command surface was dated
  to `v6.4.5`, release archives were still attributed to `release.yml`, and the Claude plugin
  was described as having "four Claude hooks" when it registers 11 across 7 lifecycle events
  (4 native dispatch, 7 carrier scripts).
- **`docs/cargo-distribution.md` described a pipeline that no longer existed**, and
  had for some time. It claimed `cargo-publish.yml` triggers on
  `push: branches: [main, master]`, citing `cargo-publish.yml:3-5` — that trigger
  was already gone — and that the two workflows are "independent Actions runs
  triggered by the same push, not chained with `needs:`", which stopped being true
  when publication moved into `release.yml`. Rewritten to what exists, including
  the trigger table and the reason there is deliberately **no** `push` trigger: a
  push-triggered run has no `needs:` edge to the asset build, which is precisely
  how publication once raced the build and burned two patch versions. The first
  draft of that table listed a push row that does not exist, which is the same
  defect being fixed, caught before commit.
- The README never documented the **skill surface** at all — the ten `/shepherd:*` entry
  points that are the plugin's actual user-facing contract, and whose disappearance started
  this sprint. It now does, including why `plant` and `spawn` are two skills rather than one
  command with a flag: `plant` is role adoption for the session already running, `spawn`
  picks up from the seed under a different profile.

### Fixed — the root skill had no entry condition

`skills/spawn` and `skills/start` both open with `## Preconditions` stated as commands.
`skills/shepherd`, the contract you load first and the only one reached on a cold project,
had none. An agent invoking it against an unscaffolded namespace got a sprint contract with
no way to satisfy it and no sanctioned bootstrap step, leaving the hook's stderr as the only
signal. It now declares the same precondition shape: `shepherd doctor` must report a
dispatchable namespace, and scaffolding stays the operator's decision — root surfaces
`shepherd init --confirm` and halts rather than mutating a namespace as a side effect of
loading a contract.

## v6.5.0 — 2026-08-18

**The release automation ran correctly all the way to `git push` and died there.** The first
fully green release pipeline in the project's history published crates, cut the tag, and
uploaded 32 assets. Its post-publication handoff then computed the successor, cut the branch,
committed the bump, and was refused:

```
! [remote rejected] v6.5.0 -> v6.5.0 (refusing to allow a GitHub App to create or
  update workflow `.github/workflows/rust-wasm.yml` without `workflows` permission)
```

### Fixed

- **A workflow file was a version authority, and no token can push that.** `rust-wasm.yml`
  hard-coded the WIT export string, so `version-bump.py` rewrote it every release and the
  push became a workflow update. There is no permission to grant: `workflows` is **not in the
  `GITHUB_TOKEN` permission vocabulary at all**, so adding it to the `permissions:` block
  would be a syntax error, not a fix. The step now derives the version from `Cargo.toml`, the
  single source of truth, and the authority is retired — 53 authorities down to 52, and no
  workflow file carries a version literal.
- **The coupling cannot come back.** `check-github-actions.py` gained a rule that rejects any
  workflow line containing the workspace version, naming the dead end in the message.
  Falsified two ways: reintroducing the literal turns the checker red, and deleting the rule
  turns its own suite red. `test-version-bump.py` now carries a derived workflow in its
  fixture and asserts the bump leaves it byte-identical; pinning that fixture to the current
  version turns the test red.

### Fixed — Windows is a supported platform, not a shipped stub (#321)

**392 tests run: 392 passed.** The Windows suite is green on both feature sets. It went
94 failures, 35, 20, 12, 6, 3, 0 — every step a real cross-platform defect, none of them a
test that needed relaxing.

The Windows binary this repository builds, packages, and publishes could not create
`.shepherd/`, could not bind a session, and could not store a run. Five families of
`#[cfg(not(unix))]` twins were `Err("... unavailable on this platform")`, and the first Windows
test run in the project's history reported `384 tests run: 290 passed, 94 failed`. Every one is
now implemented.

- **`crate::safe_fs`** is the new shared primitive layer for non-unix targets, and its module
  docs state exactly what it does and does not guarantee rather than implying parity with the
  descriptor-anchored unix side. Opens pass `FILE_FLAG_OPEN_REPARSE_POINT`, so a leaf that is
  or becomes a link yields the link itself and never an attacker's target; every ancestor is
  checked with `symlink_metadata`; publication is `CREATE_NEW` plus `CreateHardLinkW`, the same
  two refusals unix gets from `O_EXCL` and `linkat`. The residual gap — an ancestor swapped
  between its check and its use — is written down in the module rather than discovered later.
- **Implemented:** `wave_c_bootstrap` (all five, so `init` works), the whole `dispatch_store`
  ledger (so the hooks work, for Claude Code, Codex, and Pi alike), `dispatch_scope`
  containment, `compile`'s generated-tree check and materialize, `wave_d_planning` artifacts,
  `wave_b1_status_handoff` run states and handoffs, and `resume_context`. Each returns the SAME
  error variants and messages as its unix twin, because callers and fixtures branch on them.
- **The directory fsync is now a paired platform decision.** `run/atomic.rs` opened the parent
  directory to `sync_all()` it; on Windows `std::fs::File::open` does not set
  `FILE_FLAG_BACKUP_SEMANTICS`, so every store failed with `Access is denied. (os error 5)`.
  The non-unix arm does nothing and says why: NTFS journals the rename, so there is no
  unflushed directory entry the way there is on POSIX. A stated difference, not a swallowed
  error.
- **`windows-latest` is now a permanent CI axis**, not a dispatch option, so this cannot
  regress unobserved. `.cargo/config.toml` and `scripts/setup.sh` add a local
  `x86_64-pc-windows-gnu` cross-check so the Windows half type-checks in seconds instead of a
  six-minute round trip.
- **`safe_fs` ships its own suite**: no-clobber publishes once and leaves no temporary,
  `replace_atomic` overwrites where no-clobber refuses, an over-limit read fails instead of
  truncating, absence and wrong-type stay distinguishable, `ensure_directory` reports only what
  it created, children are sorted and split by kind, removal is idempotent, and a real symlink
  is refused rather than followed.

- **The defects Windows found that had nothing to do with the stubs.** `reject_symlink_path`
  stat'ed the bare drive prefix, so every run command died with
  `ERROR: inspect \\?\C:: Incorrect function.` The layout manifest rendered OS-native
  separators into a durable, sorted, compared artifact, so the same migration produced a
  different manifest on each platform — and once the sources were canonical, the deepest-first
  removal ordering counted `MAIN_SEPARATOR` and collapsed to zero, removing parents before
  their children. `normalize_relative` refused every absolute Windows path because a backslash
  is a smuggling attempt on unix and the separator there. Path identity needed
  `canonical_identity`, because Windows spells one directory three ways —
  `\\?\C:\Users\runneradmin`, `C:\Users\runneradmin`, and `C:\Users\RUNNER~1`.
- **Three tests held a live SQLite connection across their fixture removal.** Windows cannot
  delete a directory containing an open handle; unix unlinks an open file happily, which is
  why no amount of retrying would ever have helped. The teardown helper names the surviving
  files now, which is what turned that from a guess into a diagnosis.

### Changed — the model tier map

The team leads no longer pin a tier. A sprint spawned at the reasoning tier gets leads at that
tier; a sprint spawned cheaply gets cheap leads.

| Roles | Hint | Claude / Codex / Pi |
|---|---|---|
| root, planter | `reasoning-high` | `opus[1m]` / `reasoning-high` / `opus` |
| engineer, conductor | `inherit-caller` | `inherit` / `inherit-caller` |
| critic, coder, auditor, worker | `standard` | `sonnet` / `standard` |
| discovery | `economy` | `haiku` / `economy` at low effort |

`discovery` is the widest fan-out role in the flock, so it reaches for the economy tier that
all three harness profiles already defined and nothing had ever used. All nine stay overridable
through `[models]`.

**This was not safe to change on its own.** `compiler.rs` built the Codex `[agent_types]` table
by skipping any role whose `model_hint` was `inherit-caller`, a proxy for "not dispatchable"
that was wrong in both directions: `planter` is `dispatchable: false` and Codex had been
advertising the role that holds `ask-operator` as spawnable, while any lead adopting
`inherit-caller` would have silently vanished from the table. It keys on `dispatchable` now.

### Changed — organization identity

Identity fields renamed to `pzzld-org` ahead of the repository transfer. Every remaining `FL03`
string resolves something — the binstall `pkg-url`, both installers' release bases, the README
curl one-liner, the marketplace `add` lines — and GitHub's permanent post-transfer redirect
makes `FL03` correct in both states while `pzzld-org` 404s until the move lands. #326 flips them
afterwards.

### Notes

- The fixture pins a synthetic `9.9.9`, never the live release. A fixture pinned to the real
  version would make the test file a version authority, which is the exact coupling the rule
  under test exists to prevent.

---

## v6.4.9 — 2026-08-18

**A Windows checkout rewrote the LICENSE and the release found out last.** Every asset built,
every crate published, and only then did the publication gate compare the LICENSE inside the
Windows zip against the repository copy and refuse to publish. The bytes differed by 201 CR
characters and nothing else. Because the published crates pin that exact commit, the release
could not be re-cut from a fix — the assets had to be lifted out of the failed run's artifacts
and attached to the tag by hand.

### Fixed

- **Line endings are pinned at the repository, not hoped for.** GitHub's Windows runners check
  out with `core.autocrlf=true`. `stage-distribution-legal.sh` copies `LICENSE` verbatim into
  all 16 assets and `verify-release-distribution.sh` compares every extracted copy against the
  repository file, so a rewritten checkout guarantees a failure that only the last job can see.
  `.gitattributes` now pins `* text=auto eol=lf` (no tracked file carried a CR byte, so this
  changes no content — `git add --renormalize .` is a no-op), with the existing
  `THIRD_PARTY_LICENSES/*.txt binary` override still winning for the hash-named upstream texts.
- **The packaging runner refuses a rewritten checkout.** `stage-distribution-legal.sh` fails on
  a `LICENSE` containing CR bytes, before it copies anything. The job that would have produced
  the divergence is the job that stops, instead of five build jobs and a crates.io publication
  succeeding first.
- **Both gates are falsified in the suite.** `test-release-distribution-license.sh` asserts
  `git check-attr eol -- LICENSE` reports `lf`, proves that assertion can observe the
  `unspecified` state by running the same query against a scratch repository with no
  `.gitattributes`, drives the staging script with a CRLF fixture and requires the CR refusal,
  and then drives it with an LF fixture and requires the staged copy to appear.

- **The Windows test build was broken under `-D warnings`, and nothing could see it.**
  `rust.yml`'s `test` job is the only one whose runner is selectable, and three of its run
  steps never declared a shell, so on `windows-latest` GitHub ran them through PowerShell and
  `cargo nextest run ... \` died at parse time before a single test executed
  (`ParserError: D:\a\_temp\<id>.ps1:3`). The advertised escape hatch for proving
  cross-platform behaviour could not prove anything. With `shell: bash` on all three, the
  suite ran on Windows for the first time and immediately failed on three real defects:
  `read_project_id` and `ReadSubject`/`read_regular_nofollow` imported unconditionally into
  test modules whose only callers are `#[cfg(unix)]`, and an `expect(dead_code)` on
  `ReadSubject::open_label` gated `not(unix)` when a non-unix **lib test** build does use it,
  making the expectation unfulfilled -- which `-D warnings` rejects exactly as hard as the
  dead code it was written to tolerate. The gate is now `all(not(unix), not(test))`.
  A fourth followed in the integration suite: `invoke_with_path` in
  `wave_e_coordination.rs`, whose only caller is a `#[cfg(unix)]` test that puts a stub `kill`
  on PATH. All four are the same shape -- an item declared unconditionally whose every caller
  is unix-gated -- and all four were invisible to every unix machine and to every release
  build, which builds the lib rather than the test targets.

### Fixed — Codex users were shipped a Claude-only skill

`plugins/shepherd/codex/skills/harness/` shipped in every Codex install since v6.4.5. Its own
authored frontmatter says `portability: claude-only` and its content is Agent Teams, Dynamic
Workflows, and `ToolSearch` — none of which exist on Codex. The compiler has always excluded
it correctly; three separate gates demanded it be there.

- `generate-codex-carrier.py` projected from `skills/`, the **Claude** carrier, so its drift
  check compared the Claude tree against a copy of the Claude tree and was green throughout.
  It now filters `portability: claude-only`, read from `content/skills/` because the compiler
  STRIPS that key out of what it emits — the projection source cannot answer the question
  about itself.
- `check-plugin.py` required the Codex inventory to equal the Claude inventory exactly, and
  `test-codex-marketplace.sh` asserted the same. Both encoded the defect as a requirement.
  Both now exclude claude-only skills, and the marketplace test additionally refuses to pass
  if no skill is marked claude-only, so the filter can never quietly become a no-op.
- The full gate gained the AUTHORITATIVE check the other three cannot be: the committed
  carrier is diffed against a real `compile --target codex`. A projector and a carrier
  agreeing with each other proves nothing when both are wrong.

All four are falsified: restoring `harness/` to the carrier turns each red, and byte-drifting
a carrier file turns the projector red.

### Found, not fixed

- **The shipped Windows binary cannot initialize a project or durably store a run.** With the
  suite finally able to run on `windows-latest`, it did — and reported
  `384 tests run: 290 passed, 94 failed`. Two stubs account for all of it:
  `wave_c_bootstrap.rs` pairs every descriptor-safe mutation with a `#[cfg(not(unix))]` twin
  that returns `descriptor-safe bootstrap mutation is unavailable on this platform` (five of
  them), so `shepherd init` fails and every hook test cascades from it; and
  `crates/core/src/run/atomic.rs:135` opens the parent directory to `sync_all()` it, which
  Windows refuses with `Access is denied. (os error 5)` because `std::fs::File::open` does not
  set `FILE_FLAG_BACKUP_SEMANTICS`. Filed as #321 — it is a decision (implement the Windows
  primitives, or stop shipping the Windows asset), not a patch.

### Notes

- `cargo binstall shepherd-cli` and `scripts/install-shepherd.sh` were both exercised against
  the published v6.4.8 release on `aarch64-apple-darwin` and resolve, download, verify, and
  install `shepherd-cli 6.4.8`.

---

## v6.4.8 — 2026-08-18

**Stop burning a version every time a native target fails.** v6.4.6 and v6.4.7 both
published their crates to crates.io and then failed to produce a GitHub release, because
crate publication raced the asset builds and won. A published version cannot be reissued, so
each failure cost a version number rather than a re-run.

### Fixed

- **Crate publication is gated on the assets existing.** `cargo-publish.yml` triggered on
  push-to-main independently of `release.yml`, so it uploaded to crates.io in parallel with
  the native and component builds. Publication now happens INSIDE `release.yml`, in a
  `publish-crates` job that needs every asset job, and the tag still waits on it — so the
  documented ordering (assets verified, crates published, tag cut, release published) is
  enforced by the job graph rather than by hope. `cargo-publish.yml` remains as the
  operator-dispatched recovery path.
- **Windows builds.** `-D warnings` rejected two unused items on non-unix: `ReadSubject::open_label`,
  rendered only by the unix-only errno classifier, and the `IdentityLookup` variants, which
  the non-unix reader refuses before constructing. Both are now `expect(dead_code)` under
  `cfg(not(unix))`, which still fails loudly if either becomes reachable.
- **A release gate that counted instead of testing.** The release-workflow contract asserted
  exactly five checkouts pin `github.sha`; adding the publish job made six and turned it red
  while the property it cares about held. It now asserts that EVERY checkout pins the release
  commit.
- **The README's stated toolchain** sat at 1.96.0 through a 1.97.0 bump, because nothing read
  it. `check-workspace.sh` now checks the prose claim alongside `Cargo.toml`, `clippy.toml`,
  and `rust-toolchain.toml`.

### Changed

- The README states where binaries actually come from: the binstall `pkg-url`, the
  archive-root layout CI asserts on a real macOS runner, why `quick-install` and `compile`
  are disabled, and that no build artifact is stored in the repository.

## v6.4.7 — 2026-08-18

**The release chain fired end to end for the first time and surfaced what only a real run
could. v6.4.6's crates published to crates.io; the GitHub release did not complete. This
patch fixes the three defects that stopped it and bumps the version, because 6.4.6 is spent.**

### Fixed

- **Windows builds.** Two unconditional reaches into unix-only code, both introduced by the
  v6.4.6 identity work and invisible on macOS. `wave_f_knowledge.rs` imported
  `classify_nofollow_open_error` — `#[cfg(unix)]`, because it maps a `rustix::io::Errno` —
  from an unconditional `use`. `wave_c_bootstrap.rs` called `descriptor::read_relative_nofollow`
  directly from two unconditional functions, bypassing the paired-free-function idiom every
  other mutation in that file follows. Both now go through `#[cfg(unix)]`/`#[cfg(not(unix))]`
  pairs, with `IdentityLookup` named outside the unix-only module so callers compile
  everywhere. The second site was found only by sweeping for the pattern after fixing the
  first: the compiler reports one error at a time, and the class had two.
- **The pinned WASI import surface.** Stale since v6.4.5. The toolchain bump to 1.97.0 moved
  wasip2 imports `0.2.6` → `0.2.12` and added `wasi:clocks/monotonic-clock`, so the component
  imports 15 interfaces where 14 were pinned. `Cargo.lock` moved by exactly one line and
  carries no `wasi` entry, so this is the toolchain rather than a dependency. The gate was
  right to catch it.
- **A sixth pin of the generated tree's identity**, in `packages/scripts/test-component-node.mjs`,
  holding pre-sprint digests and file counts for all three targets.

### Changed

- **The component validation step names what it found.** It was a chain of `grep -Fq` and bare
  `test`, so a failure printed NOTHING and the step died with only `exit code 1`; diagnosing it
  took a log dive. Each check now reports its finding, the import count is DERIVED from the
  pinned file rather than hardcoded, and a changed import surface is reported as a capability
  change with the exact regeneration command.

## v6.4.6 — 2026-08-18

**The patch that makes the previous five reachable. Every capability v6.4.x built is currently unreachable from a clean machine: the install path documented as primary is broken, the hooks that carry the plugin's behaviour exit 127 before they run, and a freshly initialized project is structurally incapable of dispatching. Seed and evidence: `.shepherd/runs/v646/seed.md`, `.shepherd/runs/v646/mesh.md`.**

### Fixed — the plugin could not run its own sprint

Dogfooding v6.4.6 through the plugin surfaced six defects of one class: a fault in
shepherd's own plumbing surfacing as a guard refusal aimed at the caller. Each disabled a
core capability, and no gate caught any of them.

- **A broken run no longer disables the tools that repair it.** `PreToolUse` returned `deny`
  for every error, and `hooks/hooks.json` matches `Write|Edit|Bash|Agent|Workflow`, so one
  unusable run namespace left a session structurally unable to fix the state that was
  failing. Guard verdicts and infrastructure faults are now separated structurally: no usable
  run namespace surfaces and allows; a healthy run with an unbound session still denies;
  guard-integrity failure stays fail-closed, with an unconditional exemption for a bare
  `shepherd` command so the one thing that repairs the state can never be refused by it.
- **`Workflow` is usable.** It was refused for a `subagent_type` it structurally cannot carry
  — its agents are spawned inside the script. The `dispatch-scope` rule applies to those
  agents, not to the call. Tier rules still bite: an implementer cannot fan out through it.
- **Dispatching a role works.** `deny_if_target_outside_flock` compared the plugin carrier
  form (`shepherd:conductor`) against role ids (`conductor`), refusing every in-flock
  dispatch as off-flock.
- **A root session can write.** Only a dispatched subagent's envelope carries a
  `shepherd_dispatch` block, so the tool name never reached the resolver, no write path was
  derived, and every `Write` and `Edit` was denied for "no validated write paths" — the scope
  check never had a path to check.
- **A subagent tool call resolves.** Identity normalization demanded `agent_type` on every
  event, but a host declares it once at start and resends only `agent_id` per tool call.
- **Dispatched agents are recorded, so role guards can fire at all.** `SubagentStart` required
  a `shepherd_dispatch` block no host can attach, so the dispatch ledger was empty on every
  harness, no tool call could be attributed to a role, and not one rule in `dispatch-scope`
  could ever fire — the nine-role flock was enforced by prose. Bindings are now synthesized
  from what the host does send. An agent shepherd never recorded is surfaced and allowed; a
  record that disagrees still refuses.
- **`PostToolUse` no longer runs a pre-flight guard after the fact**, and a refusal can no
  longer mislabel itself as an event it is not.

### Added

- **`spawn` and `start`.** The documented primary execution path, `/shepherd:spawn`, resolved
  to "Unknown skill" — it had never been built. `spawn` advances planted to planned by
  dispatching one engineer that orients through a composite wave of auditors and discovery
  agents before authoring the plan. `start` is the opposite shape: a direct conductor
  dispatch with no root fan-out.

### Changed

- **GitHub Actions are referenced by floating major version tag, not commit SHA.** A major tag
  inherits an action's own minor and patch fixes; a SHA pin cannot. `actions-lock.json`
  remains the provenance record and the gate checks the workflow's major against it.
  Pre-1.0 actions still pin exactly, because `v0` is not a compatibility channel.
- **Three CI gates that had stopped blocking merges now block again**: clippy never ran on a
  freshly opened PR or on push to main; the only `wasm32-unknown-unknown` cross-compile was
  skipped on pull requests; and `wasm-tools` was installed unversioned, orphaning
  `WASM_TOOLS_VERSION`.
- **clippy is no longer silently under-linting.** `clippy.toml` declared `msrv 1.91.0` while
  the workspace and toolchain are `1.97.0`, suppressing every modernization lint stabilized
  in between. Nothing checked the three files agreed; `check-workspace.sh` now does.
- **Lane evidence is tracked.** `.shepherd/runs/**` made W0 reproductions, handoffs, and
  reproduction scripts uncommittable, so evidence the gates require could not reach the
  release record.

### Planned

- **`cargo binstall shepherd-cli` works.** Four independent defects sit between a merge and a downloadable asset: macOS arm64 packaging uses GNU-tar-only flags, the Windows installer test cannot create its deliberately-dangling symlink, the asset verifier looks for `fl03-*` npm tarballs that were renamed to `@pzzld/*`, and `cargo-publish.yml` can never be triggered because the tag is pushed with `GITHUB_TOKEN`. Fixing any three still yields a zero-asset release.
- **`shepherd` on PATH is the native binary.** The tracked `bin/shepherd` launcher, symlinked into `~/.local/bin`, shadows the cargo-installed binary and exits 127 — which is what turns every hook in every harness into a failure (#307).
- **A freshly initialized project can dispatch.** `shepherd init --confirm` never writes `.shepherd/project.json` and never inserts a `projects` row, so every project this tool has created is born unable to dispatch, while `doctor` reports `status: ok` (#306).
- **Errors name the actual failure.** A plain `ENOENT` on the project identity is reported as a symlink refusal, which misdirects every diagnosis down a path the evidence rules out.
- **Every harness defines every hook.** Codex lost `SubagentStart`/`SubagentStop` in the Rust-native migration; Pi has no hook manifest at all.
- **Configuration parsing belongs to `config`.** The loader parses each layer with `toml`, re-serializes it, and hands it to `config` to parse a second time.
- **The release gate can fail.** A push to `main` that skips every job currently concludes `success`, and the post-release gitflow automation chains off that signal.

## v6.4.5 — 2026-08-15

**The first sprint run as a genuine dogfood, and the plugin's own failures became most of the work. Root drove `/shepherd:spawn` on this repo with two lanes and roughly twenty coders; forty defects surfaced against the framework itself, nine of them became Wave-0 steps that were never in the seed, and the single most expensive one killed ten coders for ~610k tokens before a line was written. Four separate mechanisms turned out to look like verification and not be: a wiring test that greps prose, a `[gates.extra]` block that never executes, an acceptance predicate that passes vacuously, and a version-match test left red across a release. The through-line of every fix below is the same — prove the check can fail.**

### Release recovery and publication

- **Claude distribution and hooks now ship from the repository source.** The normal persistent Claude marketplace install from repository source is verified; native `shepherd claude-hook` covers all four Claude events, with `PreToolUse` and `SubagentStop` fail-closed. The Claude ZIP runtime was removed.
- **Release publication is limited to verified assets, the tag, and publication.** The gitflow workflow owns the post-publication `vNEXT` branch, version bump, PR, and milestone. Fresh-runner recovery gates cover `wasm-tools`, Windows `cfg`, and GNU libc 2.17 compatibility.

### Fixed — the toolchain stops lying

- **`lint` counts violations, not violation kinds.** It reported six stale run directories and printed `FAIL (1 violation(s))`. `scripts/check-plugin.sh` is renamed to `.py` — it was always Python wearing a shell extension, which is misleading to anyone grepping for bash; `gate.sh` and `.github/workflows/rust.yml` follow. That rename had three reference sites across two lanes' scopes and one owned by nobody, and no structural check found any of them.
- **`doctor` stops prescribing commands that do not exist.** Three of its five warnings said `→ fix: run 'shctx refresh --scope=issues'` (likewise `prs`, `releases`), and `refresh` rejects all three — only `symbols` and `artifacts` are accepted. The `artifacts` zone also read a freshness column nothing stamps, so it reported `never refreshed` immediately after a successful refresh. Both fixed against the live registry.
- **Model slugs are translated by the engine, not by each dispatcher.** `shctx models resolve engineer` returned `opus[1m]`, which the dispatch tool's closed enum rejects, so every Opus-tier dispatch silently rewrote the slug at the call site. `models resolve --harness` now owns the 9-role × 3-harness table; no-flag output stays byte-identical by construction.
- **A clean clone can spawn.** The registry DB is gitignored by design and nothing scaffolded it, so a fresh checkout sat permanently un-bootstrapped: `doctor` failed closed with no automatic remedy and every spawn-critical verb depended on the missing DB. `session_open.sh` self-heals and spawn gains Preflight Check 4b, both scaffold-then-proceed. Verified against a real clone, `doctor` 2-fail → 0-fail with no hand-run `init`.

### Fixed — verification that verifies

- **`test_v644_wiring.sh` asserts behaviour, not prose.** It "verified" #268, #269 and #270 with `need <file> "<string>"` greps over documentation. It could not see that **#270 is still broken** (measured 5/5 this run) because the text describing the fix was present, and presence was all it checked. All 24 assertions are now real invocations or explicit `UNVERIFIABLE-IN-TEST` citations naming why. On its first run the rewritten test **failed**, correctly: `agents/shepherd.md:158` sends root to `shctx plan amend`, which errors `unknown subcommand` — the bash surface lacks it while the Python CLI implements it.
- **The three grep-based boundary gates get genuine negative controls.** `boundaries.yml` claimed negative-control verification in a *comment* — a one-time manual check, with no committed fixture. `.github/scripts/boundary-selftest.sh` now proves each gate's exact regex rejects a deliberately-broken fixture and accepts the real tree, and runs ahead of the gates so a broken gate is caught before it silently no-ops.
- **The Stage Graph gets a checker, because the same defect class was caught three times by hand.** `scripts/check-stage-graph.py` runs six invariants — dangling targets, stranding edges, unbacked predicates, same-predecessor AND-joins, reachability, terminal-reachability — each with a deliberately-broken fixture proving it can fail. Its `--self-test` is the pattern, explicitly not the grep-for-prose one. Two of the three prior catches were a critic finding a deadlock and then the engineer's own generalisation missing a third of it.
- **A recorded critic proof cannot be silently invalidated.** `record-critique` succeeds, the plan stays an ordinary file, and nothing warns at record time or edit time — so the author invalidates the attestation and reports the gate green in good faith, twice, and only a later reader running `verify` finds out. `plan_proof_guard.sh` refuses a write to a plan whose sibling proof verifies clean, and deliberately does **not** auto-re-record: that would forge an attestation the critic never made.

### Added — the harness-agnostic substrate

- **`content/` is the single source.** Nine harness-neutral role files, seven skill digests, four declarative guard predicates, and a reconciliation ledger. Every role carries `write_eligible` as a first-class fact rather than an unenforced convention — required because Codex `explorer` roles cannot write files at all, so a compiler emitting from tool-grants alone produces a broken adapter.
- **A conformance oracle frozen from the Python CLI (#281).** 15 cases across `core` and `guard-cli`, green on both, with a committed corpus checksum and a `NORMALIZATION.md` pinning timestamps, UUIDs, absolute paths, locale, JSON key order and `sqlite_master` ordering. The `guard-cli` suite exists because locked decision 3 was measured **false**: five CLI shellouts across four guard scripts, three of which touch DB state *exclusively* through the CLI, so their exact stdout, exit codes and JSON shape are compatibility surface. No golden fixtures existed anywhere beforehand — this is from zero, with 1,583 pytest assertions as the only prior specification.
- **`packages/` npm workspace** with three harness adapters, a compiler stub, and `check-deps.mjs` — a dependency-direction gate carrying three synthetic negative fixtures.
- **Role capability becomes probed, not declared.** `agents/engineer.md:7` grants `Workflow`, `Glob` and `Grep`; the spawned engineer could see none of the three. Frontmatter `tools:` does not survive to runtime, so `lint_agent_capabilities.sh` — which pinned tokens in the *text* of a file — proved nothing. It now records declared-versus-observed per dispatch and detects the delta, with a `--self-test` that fabricates one.

### Fixed — dispatch doctrine matches the platform that ships

- `commands/spawn.md` described teammates as created by a "native teammate-spawn" distinct from the `Agent` tool. On Claude Code 2.1.229 that distinction is gone: `Agent` carries a `name`, `team_name` is documented as ignored, and the session has a single implicit team. `skills/harness/SKILL.md` now records the flat-roster constraint, task-tree-owner notification routing, and the frontmatter-non-authoritative fact.
- **`[mcp].<svc>` becomes a probe, not a promise.** `shepherd_mcp_available` gates on config *and* a TTL-cached runtime probe, emitting the sanctioned `[WARN] MCP <svc> unavailable — using <cli>` degrade automatically.

### Added — one guard engine, and the adapters stop reimplementing it

- **`shepherd guard eval | test | explain`.** Three harness adapters all relayed guard evaluation to `shepherd guard eval` — a command no plan step built and that did not exist. Each step verified its own relay was emitted correctly; nobody owned the callee, so nothing failed. The engine now exists (`services/cli/shepherd_cli/predicates.py`), reads `content/predicates/*.toml` through stdlib `tomllib` for zero new dependencies, and returns one of three verdicts: `allow`, `deny`, or `unresolved`. That third verdict is load-bearing — a guard that cannot identify the acting role must neither silently allow nor blanket-deny, and each adapter picks its own posture for it, loudly.
- **`guard test` replays the 17 `[[example]]` cases as a conformance corpus** and exits non-zero on zero examples loaded. The corpus contains deny cases, so a broken engine cannot show green — verified by mutating the single line every verdict returns through and watching 9 of 17 go red.
- **`shepherd run claim` (#286).** `run init` correctly refuses an existing canonical run with exit 5 and there was no third door, so a second harness could not resume one — blocking a live `FL03/axiom` `v039-dev1` recovery with five lanes mid-flight. `run claim` is read-only against `run.json` (asserted by byte comparison, not by absence of an error), idempotent, and fails closed on a malformed or higher-schema run.

### Fixed — codex-shepherd stops being decoration

- **The Codex guard was a permanent no-op.** `decideForToolCall` opened with `if (!role) return { result: "allow" }`, and `role` came from a `SHEPHERD_ROLE` environment variable that nothing sets for a Codex subprocess. Every branch fell through to allow, on every call, forever. Its test suite was green because the tests set the variable themselves — the runtime never would. It would have installed as a security boundary and enforced nothing.
- **The obvious fix was wrong and the auditor said so.** Flipping the default to fail-closed alone would have permanently denied every Codex write, because role still never resolves. Role resolution landed first: `dispatch-record.mjs` intercepts `spawn_agent` and keys on the real `agent_id` wire field, with a three-way split — no marker means the root session and allows; marker plus record evaluates for real; marker with no record denies loudly. That third case was the silent allow.
- **The wire format was also wrong.** Codex's `PreToolUse` output is a nested `hookSpecificOutput` object, not the flat `{permissionDecision}` shape this adapter emitted. A correct deny would have been silently ignored — the same "enforces nothing while looking healthy" failure, one layer below the role bug. Corroborated three independent ways: the installed bundle's `hooks/protocol.py`, `strings` on the `codex` binary, and that bundle's own gate tests.
- **Codex's local interpreter and TOML reader are deleted** (`predicates.mjs`, `toml-lite.mjs`, and their tests): −208 lines net for that collapse.
- **pi-shepherd deliberately did *not* collapse.** `shepherd guard eval` measured 0.67–0.84 s per call and Pi's `pi.on('tool_call', …)` handler runs synchronously, in-process, on every tool call. The step halted with the measurement rather than shipping a stall or pretending the collapse happened. Pi's enforcement — which an auditor independently falsified as genuinely working, including a compound-command obfuscation attempt — is untouched.

### Fixed — three more gates that could not fail

- **`dispatch_guard.sh` failed OPEN on malformed JSON (#284)**, disabling all 8 checks at once with the script still exiting 0 and looking healthy. Now denies with an explicit halt code naming the payload, with malformed-input fixtures asserting the DENY.
- **SQL quote-escaping, hand-rolled wrong three times (#285).** `cmd_adapt.sh:101` and `cmd_loop.sh:101` used a bash expansion that does not double a single quote, on free-text fields, next to a sibling script in the same directory carrying a correct `esc()`. The regression tests assert the value **round-trips into the row** — asserting exit 0 is what let this survive, since these paths do not fail on a bad write.
- **`shepherd lint` false-passed from a subdirectory**, finding zero files and exiting 0. It now prints the resolved root and file count on every run and exits non-zero on a zero-file lint: "I linted nothing" is not a pass.
- **`workflows/*.js` `meta` blocks get a literal-purity gate** with the negative control recovered from the commit that actually broke this way, plus a false-positive guard for punctuation inside description strings.

### Fixed — the guard that had never denied anything

- **`coder_git_guard.sh` has never denied a single call in this repository** (#287). 63 of 63 live dispatch records carried `agent_role: "unknown"`, because `agent_invocation_tagger.sh:83` derived the role by grepping the dispatch *prompt* for a `# @<role>` header — while `skills/shepherd/SKILL.md §Dispatch law` mandates "put the brief in `prompt`, NEVER inline-embed the agent body." The header lives in `agents/<role>.md`, loaded via `subagent_type`, so by law it was never in the prompt. The guard's only role signal was a string the doctrine forbids being there. It now resolves from `tool_input.subagent_type`, which is mandatory on every dispatch and separately enforced by `dispatch_guard.sh`.
- **The failure path did not fail open, it PROMOTED.** `current_role()` returned `conductor` for any unresolvable id — a tier holding lane commit and lane-branch push rights that `coder` does not. An unidentified caller was granted *more* authority than an identified one. It returns `unknown` now, and a git write under an unknown role warns loudly rather than passing silently; deny was measured unsafe, because root's own git operations resolve to the same `unknown` value.
- **The correlation key is documented as unsolved rather than guessed.** `tool_use_id` provably cannot work (a later call's id is a fresh tool-use block, never the dispatching `Agent()` call's) and neither can `session_id` (shared identically across an entire dispatch tree). `agent_id` is the evidenced candidate; a live capture attempt inside a dispatch harness failed and the step said so instead of shipping a guess.
- `test_coder_git_guard.sh` passed for the entire life of this defect. It is rebuilt around one assertion: a dispatch tagged `shepherd:coder` running `git commit` is DENIED, end to end, through the real hook with a real record.

### Changed — one evaluator, and the CLI stops paying for itself

- **`shepherd guard serve`** — 0.034 ms/request warm against 450–535 ms per `guard eval`. The step measured where the time actually went before building, and most of it was not guards: `bin/shepherd` re-resolved the venv via `poetry env info` on *every* invocation (270–315 ms), and `shepherd_cli/commands/__init__.py` eagerly imported `teammate`, dragging Tortoise ORM and Pydantic into every CLI call regardless of subcommand (~116 ms). Both predate this work and tax every hook, guard and `shctx` call in the plugin.
- **pi-shepherd's second interpreter is gone** (−242 lines). `guard.ts` and `predicates.mjs` deleted; the relay reaches the shared engine through a long-lived server. All three adapters now evaluate through one implementation, with a conformance gate that goes red on any divergence — verified 4-for-4 red on a single mutation.
- **`plan amend` and `plan lane-drift`** (#268, #269). `lane-drift` found 19 divergences on its first run against this sprint's own lanes; 17 turned out to be conductors ledgering progress into their own lane plan, which the operator explicitly authorized, so #288 tracks separating the contract from the ledger rather than editing the evidence to make the check pass.

### Known-broken, measured this run and not yet fixed

- **`teammate_idle.sh` calls a subcommand that does not exist.** `bin/shepherd teammate heartbeat` exits 2 on every invocation; the Python group exposes only `liveness`, `status`, `state`. `2>/dev/null || true` hides it. With the PreToolUse hook matching on a `session_id` root cannot supply, **both** liveness-stamping paths are dead — while the same script's `UPDATE … status='idle'` works, making `idle` a one-way latch. Frozen as a golden oracle case.
- **`shepherd plan extract --run` is rejected outright**, so no invocation produces run-scoped graph state and `plan topology`/`validate` are unavailable. #278 describes the flag as undocumented; here it does not exist.
- **`[gates.extra]` is never executed** — `gate.sh` is a warn-only close ledger, not a runner. Registering a check there does not make it block.
- **Four version sources, three answers**: `plugin.json` 6.4.5, `Cargo.toml` 6.4.5, `shepherd_cli.__version__` 6.4.4, `README.md` v6.4.2. `test_version_match_emits_no_row` exists to assert they agree and has been red since before this sprint.

---

## v6.4.4 — 2026-08-06

**The artifact schema stops contradicting itself. `.shepherd/` had two knowledge silos with the wrong one gitignored, run-scoped audits and reports piling into the cross-run `docs/` tree while the run-scoped directories sat empty, and a `runs/` folder holding spec-shaped directories that `lint` could not see. Plus the five issues that landed with it: an unprovisioned CLI venv that blocked every spawn, a preflight that refused on the session's own team file, no sanctioned way for root to re-gate a plan it correctly fixed, two unlinked sources of truth per lane, and a completion notification that never arrives.**

### Fixed — layout

- **`.shepherd/memory/` is RETIRED; `ctx/` is the one knowledge silo, `cache/` the one disposable-state dir.** `memory/` existed only for `memory/snapshots/precompact-*.json`, appeared in no `[paths]` key and no schema table, and was gitignored to keep that churn out of `git status`. Two plausible destinations with the wrong one ignored: `FL03/axiom`'s `.shepherd/memory/` holds three hand-authored markdown files (carry-forwards, feedback), none tracked, while its `ctx/` holds the failure-patterns and dedup ledgers. Snapshots move to `cache/snapshots/`; `shepherd migrate --layout v4` drains `memory/` (snapshots → `cache/`, `*.md` → `ctx/`); `shepherd lint` FAILs if it reappears; neither `.gitignore` ignores it any more — ignoring it is what made it a silent sink.
- **Run-scoped reports, audits and handoffs live in `{run_dir}`, not `docs/`.** The schema has listed `{run_dir}/reports/` and `{run_dir}/audits/` since v6.4.1 and `run init` scaffolds both, but every writer — `auditor.md`, `discovery.md`, `worker.md`, `planter.md`, `flock.md`, and `lock_guard.sh`'s two write-path regexes — was still pinned to `{paths.reports}` with a `<date>-` prefix. `FL03/axiom`: 1548 files in `.shepherd/docs/reports/`, one run directory. All three layers now name the run-scoped path and the guard DENIES the legacy target with a message naming the correct one. `handoff create` writes `{run_dir}/handoff.md`, deriving the run from the same `[branching]` pattern `run init` uses.
- **`runs/` holds runs, and `lint` can finally see when it doesn't.** `lint` reported ok on a `runs/` tree where all six entries were wrong: two were date-topic SPEC names and none carried a `run.json`. Same bug — the canonical check enumerated `list_runs`, which indexes by `run.json`, so the misnamed directories (the ones no `run init` ever created) were the ones it could never see. Both checks now enumerate directories; a directory under `runs/` without `run.json` is a new FAIL; and `run rename`/`run canonicalize` accept an unregistered directory, closing a loop where such a directory could be neither registered (`run init` refuses a non-canonical id) nor renamed.
- **`[paths].plans`/`[paths].reports` are documented LEGACY read-only keys**, and `[ledger].carry_forward_file` moves off the emptied `{paths.plans}` to `{paths.docs}`. New: `naming-conventions.md §One knowledge silo` and `§The docs/ vs {run_dir} boundary`.

### Fixed — issues

- **#266 — `bin/shepherd` never execs into an unprovisioned venv.** `poetry env info --executable` CREATES a venv when none exists, so a fresh upgrade built an empty one and ran the CLI inside it: every command dying with `ModuleNotFoundError: No module named 'typer'`. It never healed, because `shepherd-venv-ensure` gated on `[ -d "$VENV_DIR" ]` — venv EXISTS, not venv WORKS — and its stamp survives plugin updates. On `/shepherd:spawn`'s critical path, where the natural workaround is the cache-hostile hand-assembled boot prompt #243 exists to prevent. Both scripts now share a filesystem-only `venv_provisioned` probe; the wrapper self-heals once then refuses with the exact recovery command; new `doctor` `cli/venv` check moves discovery before a spawn.
- **#267 — spawn Check 3 tests for a foreign team, not a non-empty directory.** The harness initializes a lead-only team file for the current session at startup, which satisfied "non-empty with `members[]`", so Check 3 refused on a clean session. The team directory id has no string relationship to the session id, so the operator cannot recognize their own team, runs `/shepherd:cleanup`, and every later spawn dies with `team file not found` — five at once, in the report. New `scripts/team-preflight.sh` computes it; `cleanup.md` gains hard prohibitions against touching `~/.claude/teams/` at all.
- **#268 — `shctx plan amend`, root's sanctioned mid-sprint correction.** Root holds adjudication authority and lanes route plan defects TO root, so correcting an approved plan is a designed inflow — but doing so made `plan verify` go `CRITIC-PROOF-STALE` with only bad options left. `amend` re-ties the proof and appends an append-only `amendments[]` record, so the ledger reads *critiqued, then amended by root for reason R*. Refuses an unchanged plan; refuses when no proof exists.
- **#269 — `shctx plan lane-drift`, and the helper-script paths.** A lane's brief renders from `vars.json` while the conductor owns `plan.md`; same content, no link, so corrections silently missed the artifact dispatch renders from. Measured twice: an inverted step title survived corrections by both root and the conductor, and a broken precondition survived in all five lanes' `vars.json` after three of five conductors fixed their own `plan.md`. `lane-drift` diffs the pair and is a wave-boundary gate; the conductor is now told `vars.json` exists. Separately, 25 doctrine sites cited the plugin's helper scripts as bare relative paths, which resolve against the CONSUMER project — so `scripts/df-guard.sh --min=12` measured nothing while reading as though it passed. All now carry `${CLAUDE_PLUGIN_ROOT}`.
- **#270 — the `Agent()` completion notification is absent, not late.** Measured 3/3 across two lanes and three coders: the notification queue never once reported a finished agent. `conductor.md §Defensive poll` upgrades from "may misroute" to "treat it as absent", makes worktree state (`git status --porcelain` / `diff --shortstat`) the ground-truth probe for a coder, and records `SendMessage`'s `had no active task` reply as a confirmed completion signal.

### Fixed — release hygiene

- Completes the v6.4.4 version bump the release automation left half-done: `services/cli/pyproject.toml` and `shepherd_cli.__version__` were still `6.4.3`, which `doctor` reports as a cli/plugin mismatch.

### Tests

New: `hooks/tests/test_lock_guard_write_path.sh` (11), `test_cli_venv_selfheal.sh` (8), `test_team_preflight.sh` (11), `test_v644_wiring.sh`; 6 `plan amend` + 7 `plan lane-drift` + 4 `lint` unregistered-run + 5 `run` naming + 4 `doctor` cli/venv + 5 `handoff` run-scoped + 5 `migrate --layout v4` + 4 `prune` snapshot cases; 2 precompact drain and 1 rehydrate no-shadow case. `test_usage_bash_parity` becomes directional (the Python CLI is a documented superset of the retired bash layer); the v6.2.5 wiring guard now asserts the INVERSE for the `memory/` ignore rules via a new `deny` helper.

---

## v6.4.3 — 2026-08-05

**The fan-out vehicle becomes SUBSTRATE-conditional. `Workflow` is denied inside an Agent-tool subagent and is NOT denied inside an Agent-Teams teammate — and `@conductor`/`@engineer` under `/shepherd:spawn` are teammates, so the denial never applied to them. Alongside it, the auditor verdict ledger gets code for the first time: a canonical root-owned path, a worktree-divergence check, and the step-to-verdict join that turns a missing audit from invisible into red.**

### Changed

- **The Workflow doctrine conflated *subagent* with *teammate* (#263).** #220 recorded a REAL platform message — `"Workflow is not available inside subagents"` (CC 2.1.212) — and then generalized it one word too far. It is true for an **Agent-tool subagent**. It is false for an **Agent-Teams teammate**. The plugin collapsed both into "any spawned role", and every downstream doc inherited the error. `@conductor` and `@engineer` under `/shepherd:spawn` are teammates, not subagents; the denial never applied to them.

  Measured, not quoted: two genuine teammate sessions in the `FL03/axiom` corpus — classified as teammates only by a RENDERED `<teammate-message>` boot brief, since a naive grep misfiles every root session that merely *reads* `commands/spawn.md` — made three `Workflow` calls between them on **CC 2.1.210**, two patches BELOW the 2.1.212 our own doctrine cited as the version that denies them. All three returned `Workflow launched in background` with their own `subagents/workflows/wf_*` transcript dirs. Zero denials anywhere in the corpus; the only `is_error` on any `Workflow` call is a JavaScript parse error. The denial and the working calls are not in tension — they describe two different constructs.

  The corrected rule, with `commands/spawn.md:73` promoted to canonical in `skills/harness/SKILL.md §Workflow tool` and everything else derived from it:

  | substrate | vehicle |
  |---|---|
  | Agent-Teams teammate (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`, native teammate-spawn) | `Workflow` works — fan out via a compiled Dynamic Workflow |
  | Agent-tool subagent, *including* a "teammate" spawned when the substrate is absent | `Workflow` genuinely denied — in-context `Agent()` is correct and the ONLY option, not a downgrade |

  The cost of the conflation, live: in `/shepherd:spawn v0.3.9-dev.1` with the substrate up and `Workflow` available to it, root explicitly instructed its `@engineer` teammate to run the `@critic` gate as a Dynamic Workflow. It dispatched via `Agent()` instead, because `engineer.md:65` said the tool was denied to it. **The body prose outranked both the live grant and a direct root instruction** — that is the whole defect in one observation. Before that, the same doctrine was read as authority over the operator's stated design and reversed a correct engineer dispatch four times, once instructing the engineer to skip its own `@critic`, which would have failed root's own `shctx plan verify` with `CRITIC-PROOF-MISSING`.

  Re-cut across `agents/conductor.md` (§Lane walk, §DISPATCH MODE, §Defensive poll, the hotfix ladder, the WAVE-COMPLETE payload, §Halt codes), `agents/engineer.md §Self-contained mode`, `agents/auditor.md §Dispatch-substrate`, `skills/harness/SKILL.md §Workflow tool` + `§Tool presence`, `workflow-templates.md`, `pipeline.md §Lane law` + `§Combo waves` + `§Hotfix ladder`, `wave-routine.md`, `flock.md`, `invariant-matrix.md` rows 3/24/28, `escalation.md`, `commands/spawn.md`, and the rendered `boot-prompt.md.j2`. The literal `"not available inside subagents"` message is RETAINED throughout as a true fact about subagents — it was never wrong, only misapplied.

  What deliberately did NOT change: `pipeline.md §Lane law`'s statement that a team lead hand-driving its OWN lane fan-out is CORRECT and never flaggable. Who drives did not change. Only the vehicle claim was wrong, and only for the substrate-live case.

- **`WORKFLOW-VEHICLE-PROBE` — confirm your substrate before the first fan-out (#263).** Read your own visible tool list for the literal token `Workflow`. Present → you are on a live teammate substrate, compile a Dynamic Workflow. Absent → you are an Agent-tool subagent, and in-context `Agent()` is simply correct there. `WORKFLOW-SELFCHECK-TOOLSEARCH` is **retained under its original name**: the prohibition is correct guidance, and only its stated reason needed replacing. `ToolSearch` searches the deferred-tool registry only, so a null on the native `Workflow` tool is a **false negative by construction** — it establishes nothing, neither presence nor absence, and is not evidence of "discovery-invisibility".

- **#251 is resolved, not deferred (#263).** Its "invisible to discovery" measurement was taken with `ToolSearch` against native tools (a guaranteed null) AND from a generic workflow-spawned subagent — the one construct where the denial is genuinely real. Both halves are invalid for a teammate, so there is no discovery-vs-invocation ambiguity left to chase. `ScheduleWakeup`'s status in a genuine teammate session is a *different* question, genuinely unmeasured, and stays honestly open in `conductor.md §Temporal self-motivation` — no longer coupled to `Workflow`'s status.

- **The wave-review auditor's grading is re-cut with it (#263).** `agents/auditor.md §Dispatch-substrate` — the section name was right all along — graded `workflow_tool: absent` + `fanout: in-context` as EXPECTED at the teammate tier and a compiled teammate Workflow as `PRIMITIVE-INVERSION`, which is backwards on a live substrate. Now: a teammate on a LIVE substrate reporting `workflow_tool: "present"` / `fanout: "workflow"` is the expected, correct case; a role on a live substrate that hand-rolled in-context anyway is the finding; and a role on a SUBAGENT substrate reporting `fanout: "in-context"` grades PASS, because that is the only option there. The trace records the substrate so the grader can tell the two apart.

- **The #255 pin law widens with the vehicle, rather than relaxing (#263).** More tiers authoring `agent()` calls means more places the model law can be silently bypassed, so the inversion restates it in the same passage everywhere it lands: `Workflow`'s `agent()` does NOT consult `shepherd.toml [models]`, so `model:` must be pinned literally on every call (default sonnet) AND `agentType: "shepherd:<role>"` must name a closed-flock role, authored through the `flockAgent()` wrapper. `DISPATCH-MODEL-UNPINNED` / `DISPATCH-MISSING-SUBAGENT-TYPE` / `WORKFLOW-OFF-FLOCK` widen their "refused by" reach from root to root + conductor + engineer. Inverting a vehicle must not trade one halt code for another.

- **The wiring tests that defended the old law are superseded, not deleted (#263).** `test_v636_wiring.sh` (#207) and `test_v639_wiring.sh` (#220) string-pinned the retired doctrine across six legs — "not available inside subagents", "presence controls the OFFER", `PERMANENT mode`, `DRIVER-CONDITIONAL`, "denied to you", and the auditor grading `workflow_tool: absent` as EXPECTED and CORRECT. That is a large part of why #263 cost what it did: #233 shipped the grant into both team-lead frontmatters, the bodies kept saying the opposite, and the tests defended the bodies, so the contradiction was load-bearing in three places at once. Both blocks now point at the new `hooks/tests/test_v643_wiring.sh` (28 legs), which pins the inverted law over the same files plus the surfaces #220 never covered: the auditor's grading rubric, the downgrade record, and the widened #255 pin reach. One leg deliberately asserts that #251 stays OPEN — a body re-asserting either failure mode as settled fact would reintroduce exactly the confident-but-unverified claim this release removes.

### New

- **The auditor verdict ledger gets code, for the first time (#261, #262).** `auditor-verdicts.txt` appeared NOWHERE in this repo before v6.4.3 — it was a field convention that live sprints relied on and the plugin never codified. That is precisely why both issues were possible: an uncodified path has no custody rule to violate and no parser to be wrong about. A new `shepherd_cli/verdicts.py` owns the deterministic core as pure functions (parse, enumerate, resolve, join, compare) with `commands/run.py` a thin wrapper over it — the CLAUDE.md latent-vs-deterministic split, since the join is same-input-same-output and must never be prose an agent re-derives.

- **`shepherd run wave verify <run>` — the join nothing performed (#262).** Reading `auditor-verdicts.txt` top to bottom shows what IS there; it structurally cannot show what is MISSING. Only a join against the step list can. At the end of a three-wave four-lane sprint one lane had ZERO wave-3 verdict lines and a step was reported CLOSED to the operator; the review behind it was genuinely thorough (a reproduced mutation, a byte-identical restore verified) which is exactly why nobody went looking for the missing paperwork — thoroughness is the disguise. `run wave verify` enumerates every `W-L-S` from the lane plans, joins against the ledger, and reports `NO-VERDICT`, `UNRESOLVED-VERDICT` (last verdict REDO/FAIL), `ORPHAN-VERDICT` (a verdict for a step in no lane plan — the reverse direction, and also real: a step id was minted in the task list and written into no plan), and `MALFORMED-ROW`. Exit 6 on findings, matching `run wave pending`'s existing mechanical-stop idiom.

  Two parsing rules are transcribed from implementations that shipped confidently wrong, and each has a test named for its failure: the verdict is read as a **positional** field, never grepped as `PASS|REDO|FAIL` anywhere on the line (a real PASS row's prose read "REDO iter 2 cleared"), and the **LAST** matching row wins, never the first (a cleared REDO→PASS loop is the normal shape, and first-wins reports it as still failing). Sub-step suffixes (`w2-s1g2`, `w2-s1b`) resolve against their parent step; a bare `w3` subsumes every step of that lane in that wave.

- **`shepherd run ledger path|check` — the ledger is one logical file with N+1 physical copies (#261).** `{run_dir}/auditor-verdicts.txt` is replicated into every lane worktree, and nothing in the path, the filename, or the file distinguishes them. A lane that appended to its own copy — the obvious path relative to where it was working — was invisible to the boundary gate, which greps root's copy; three sibling lanes wrote to the absolute path and were fine, which is habit, not a mechanism. The destructive half is worse and fired for real: root's copy held 43 rows, the lane's held 39, and merging that branch conflicts on the ledger with any lane-favouring resolution deleting another lane's entire wave audit trail. Silent, on a routine merge, with nothing downstream re-deriving acceptance.

  `run ledger path` prints the absolute primary-checkout path (the verb agents use instead of composing a relative one); `run ledger check` compares rows between the primary and every linked worktree and exits 7 on any row a worktree holds that the primary lacks. It deliberately does NOT flag a worktree merely BEHIND the primary — that is every lane's normal state between merges, and a check that fires on it gets ignored within the hour. Both directions are tested. `resolve_repo_root()`'s existing `--git-common-dir` resolution (#221/#231) already pointed the CLI at the primary checkout; that half is now pinned by a test rather than assumed.

- **`.gitattributes` union-merge for the ledger, scaffolded by `shepherd init` (#261).** `.shepherd/runs/*/auditor-verdicts.txt merge=union` — a git BUILT-IN driver, no `.gitconfig` setup. Verified directly: two lanes appending different rows merge to a file containing both, with no conflict and no lost row. This alone would have prevented the destructive half of the incident.

- **`scripts/install-shctx-launcher.sh` — a publisher-agnostic `shctx` PATH launcher (#235).** The reported launcher globbed `cache/fl03/shepherd/*` only, so it resolved a dead 6.3.3 and never saw the actively-loaded 6.3.9 under `cache/pzzld/`. Every `shctx` call fleet-wide — root, six lane conductors, and the hooks — routed to the stale binary for days, and the fallout (bogus per-worktree DBs, "unknown subcommand" on verbs the docs promised) was misdiagnosed across two separate sprints before the launcher was suspected. The installed launcher globs EVERY publisher and picks the highest version by the **version path segment**, ordered numerically — explicitly not a full-path lexicographic sort, which happens to give the right answer today only because `pzzld` sorts above `fl03`, and would silently invert on the next publisher rename. `$CLAUDE_PLUGIN_ROOT` still wins when set, since that is the harness naming the plugin it actually loaded; a broken `CLAUDE_PLUGIN_ROOT` fails loudly rather than silently falling back to the scan. 19 tests, including the `fl03/6.3.3` vs `pzzld/6.3.9` regression verbatim and a `6.4.9` vs `6.4.10` case that also pins the premise (a plain sort gets it backwards).

- **No agent frontmatter names a provider-specific MCP token any more — 129 of them dropped (#110, enforced).** `skills/shepherd/SKILL.md §Provider-agnostic discovery` has said since #110 that the `mcp__plugin_*` entries in a `tools:` line were "the default-provider OFFER, not a hard dependency" — while 129 such tokens shipped across eight agent definitions and `commands/start.md`. The doctrine and the manifest disagreed, and the manifest is what the platform reads.

  Every one of those tokens named ONE server's ONE naming scheme, and shepherd can guarantee none of them: the same GitHub capability is `mcp__github__*` natively and `mcp__MCP_DOCKER__*` behind a Docker MCP gateway — which is how the operator's own GitHub access is actually routed, so the shipped tokens named a server that did not exist on the machine writing them. A token naming an unconnected server is dead weight at best; read as a dependency it binds the plugin to a toolset the installing user may simply not have.

  All 129 are gone. Every role that touches a service grants `ToolSearch` instead and discovers the capability at runtime; `agents/conductor.md`'s one direct-write reference (`mcp__plugin_github_github__issue_write`, named in prose as the mechanism) now names the CAPABILITY and the discovery call instead of a token. This is the same hint-don't-bind discipline `@engineer`'s optional `superpowers:*` skills already used — name what you need, let the runtime resolve it.

  Mechanically enforced rather than left to prose: `lint_agent_capabilities.sh` gains a categorical check that fails on ANY `mcp__*` token in ANY agent frontmatter, plus a companion check that a service-touching role stripped of tokens still grants `ToolSearch` (a role with neither has no way to reach a service at all). Verified to have teeth by re-adding a token to a scratch copy and confirming the lint fails. That subsumes the old GH #74/#84 per-verb MCP sweeps for MCP verbs specifically — a role carrying no MCP token cannot carry a destructive one — and those checks stay for the non-MCP verbs and as belt-and-braces. `test_v630_wiring.sh`'s #185 leg, which string-pinned `mcp__plugin_github_github__add_issue_comment` in `worker.md`, is superseded the same way the #220 legs were: what #185 actually cared about is that the worker can write to GitHub and degrades to the sanctioned CLI, and those two legs were always the load-bearing half.

### Changed (enforcement)

- **`dispatch_guard.sh` Check 6 defaults ON (#263).** The check that flags a teammate hand-rolling an in-context fan-out already existed — opt-in and default OFF, on the reasoning that the behavior was correct at that tier and the reminder was per-step noise. Under #263 the behavior it flags is a real finding, so the default flips; `[hooks].flag_handrolled_fanout = false` silences it. Its message also cited `dispatch-cascade.md §IV-bis`, a doc path that no longer exists anywhere in the repo, now repointed at the live doctrine. It stays a non-blocking reminder, deliberately: a per-call `PreToolUse` hook cannot see a whole batch, cannot tell a probed-and-recorded downgrade from a silent one, and never sees a compiled Workflow's own internal `agent()` calls at all — so it names what to check rather than claiming to have caught anything.

- **`lint_agent_capabilities.sh` and `test_lead_workflow_tool.sh` stop calling the teammate grant "inert".** Both already MANDATED `Workflow` on all three leads (#233) and their logic is unchanged and still correct — only their header comments described the teammate grants as inert-at-runtime forward-compat placeholders, which is precisely the reading #263 retires.

### Changed (structure)

- **The run layout is SCAFFOLDED, not emergent.** `skills/context/references/naming-conventions.md §Run layout` has fixed the per-run directory shape since v6.4.1 — `lanes/`, `graph/`, `dispatch/`, `reports/`, `audits/` — but `run init` only ever created `lanes/`. The rest materialized as a side effect of activity, so "does this run have a `reports/`" answered *did this sprint dispatch a read-only role*, not *is this a run*. A layout that appears only when used is a layout nothing downstream can rely on, and the repo's own tracked runs show the drift: some carry only `plan.md`, some only `seed.md`.

  `shepherd run init` now scaffolds every canonical subdirectory, so a run has its final shape from the moment it exists. `RUN_SUBDIRS` and `RUN_TRACKED_FILES` in `shepherd_cli.models_run` are the single source of truth that the scaffold, the verifier, and the naming-conventions table all read — the code and the doc cannot drift apart.

- **`shepherd run layout <run> [--repair] [--json]` — verify the shape.** Read-only by default so it is safe against a live sprint: prints per-directory `ok`/`missing` plus which durable artifacts are present, exit 6 on drift (the mechanical stop, matching `wave pending` and `wave verify`), exit 5 on a missing run. `--repair` creates what is missing and nothing else, idempotently, touching directories only and never files.

- **The planter owns run-dir creation, and the run carries forward.** `commands/plant.md` already said the planter creates the run dir first; `agents/planter.md` did not, so the step lived in one file and was followed by neither. It is now Step 1-bis in the planter body: `shepherd run init {run}` before any artifact write, `{run}` derived from `[branching].sprint_slug_pattern` and never hand-typed, with the full layout in place before the seed lands. The same `{run_dir}` carries into the `/shepherd:spawn` session untouched — same slug, same paths, no re-derivation and no second directory.

- **`runs/` is deliberately not gitignored wholesale, and now says so.** The durable/disposable split was implemented in `.gitignore` and described in the layout table, but nothing stated the intent, which reads as an oversight to anyone auditing the ignore rules. A run's seed, plan, and lane plans ARE the project's plans and belong in history; only the disposable state around them does not.

- **`docs/` is user-facing documentation only.** Four historical design specs sat in `docs/specs/` while thirteen others lived in `.shepherd/docs/specs/` — two homes for one kind of artifact, and the naming conventions already say cross-run docs belong under `{paths.docs}` (which resolves to `.shepherd/docs`). The four moved; `docs/` is now exactly the five documents a plugin *user* reads. The one wiring test citing a moved path was updated with it.

- **`test_description_budget.sh` — the lazy-load budget gets teeth.** `skills/harness/SKILL.md §Lazy-load economics` caps frontmatter `description` at 200 characters because it is the only text every session pays for whether or not the file is ever used. That was doctrine with no check, and two had already drifted over (`commands/start.md` at 206, `skills/bridge/SKILL.md` at 309). Both trimmed; a new gate measures all 23 agent/command/skill descriptions. Note for anyone extending it: the key regex must allow `-`, since `argument-hint:` is a real key on most commands and a naive `^\w+:` runs straight past it and measures three fields as one.

- **Both plugin manifests named the pre-v6.4.2 config location.** `plugin.json` and `marketplace.json` still told a new user to configure via `.claude/shepherd.toml`, as did three places in the README — the one string a prospective user reads before installing anything, pointing at the location v6.4.2 moved away from.

### Fixed

- **`shepherd worktree gc --all` silently skipped worktrees committed in the current second.** `--all` was encoded as `--older-than=0`, which leaves `threshold == now` while the prune test is `ts < threshold` (STRICTLY older) — so whether a just-finished worktree got collected depended on whether the wall clock ticked between its last commit and the `gc` call. The worktrees `--all` exists to collect are precisely the sub-second-old ones a lane teardown just released, and because the failure is a clock race it reproduced only sometimes, which is worse than a consistent bug. `--all` and `--older-than=0` now both mean NO age floor and resolve identically (two spellings of one intent behaving differently would be its own trap); every other `--older-than=N` path keeps its arithmetic unchanged, and the `threshold 0h` summary line is byte-identical.
- **`doctor` could not see a NEWER plugin installed under a different publisher (#235, second half).** Section 8 compares the running CLI against `plugin.json` at `CLAUDE_PLUGIN_ROOT` — but the reported incident was that `CLAUDE_PLUGIN_ROOT` ITSELF pointed at a dead `fl03/6.3.3` while the actively-loaded `pzzld/6.3.9` sat one directory over, and nothing anywhere reported the discrepancy. Every `shctx` call fleet-wide (root, six lane conductors, the hooks) routed to the stale binary for days; the resulting unknown-subcommand errors and stray per-worktree DBs were misdiagnosed across two separate sprints. A new section 8b walks up to the `cache/` root, globs EVERY publisher's shepherd installs, and warns when any is newer than the one in use. Version comparison is segment-wise numeric, so `6.4.10` sorts above `6.4.9` — a plain string sort gets that backwards, and a full-path lexicographic sort would pick `pzzld` over `fl03` for entirely the wrong reason (right answer today, wrong one after any publisher rename). Conditional like section 8: silent when the env is unset, the layout is not a plugin cache, or the running install is already highest.
- **The v6.4.3 version bump left the CLI behind.** `plugin.json` moved to 6.4.3 while `services/cli/pyproject.toml` and `shepherd_cli.__version__` stayed at 6.4.2, so `doctor`'s own section-8 check warned `running CLI 6.4.2 != plugin 6.4.3` on every invocation and the suite's `test_version_match_emits_no_row` failed. Both bumped; the check that caught it was working exactly as designed.

## v6.4.2 — 2026-08-03

**The v6.4.1 readiness audit closes out: the RunState schema that rejected every live run.json is fixed, three more silent-mutation/staleness gaps in the CLI are closed, the user-level `~/.shepherd` tier gets its missing bootstrap verb, and five doctrine gaps the audit's own execution exposed — Workflow's second dispatch spelling, fan-out with no resource counterweight, an MCP-write liveness term, a cross-implementation lane-plan contract, and a mis-documented boot field — are closed in the written law.**

### New

- **Config resolves across three LAYERS, so a user default, a project binding, a per-harness knob, and a machine-local override each have exactly one home.** Within a layer `local` beats `<harness>` beats base; across layers project beats user: `<workdir>/shepherd.local.toml` (ultimate override, gitignored) -> `<workdir>/shepherd.<harness>.toml` (TRACKED) -> `<workdir>/shepherd.toml` (TRACKED, canonical) -> the unchanged `.claude/` pair -> `~/.shepherd/shepherd{.local,.<harness>,}.toml` (cross-project DEFAULTS) -> `$XDG_CONFIG_HOME/shepherd.toml`. `<harness>` is the ACTIVE harness only (`SHEPHERD_HARNESS`, else Claude Code's own markers, else `CODEX_HOME`; absent when undetected) — a codex knob never takes effect under Claude Code. The deliberate ordering call: the legacy `.claude/` tiers are PROJECT files, so they outrank the whole user layer — were it the other way, merely creating `~/.shepherd/shepherd.toml` would silently override every project still bound through `.claude/`. Harness files are tracked because a harness knob is a property of the project; `*.local.toml` is not, and the scaffolded `.shepherd/.gitignore` encodes exactly that. Derived in one place per language (`config._config_tiers`; `shctx_config_files` in BOTH `_lib.sh` files), cross-checked byte-identical. See `docs/configuration.md §Resolution`.
- **`shepherd config validate` refuses credentials and env-var references in files git TRACKS.** `shepherd.toml` and `shepherd.<harness>.toml` are committed, so they carry only portable knobs; anything machine-specific or secret belongs in the gitignored `shepherd.local.toml`. Credential-shaped keys (`*_secret`, `*token*`, `api_key`, ...), literal credential shapes (`ghp_`, `sk-`, `AKIA`, PEM headers), and `$VAR`/`${VAR}` references — which shepherd never expands anyway — are reported against the tracked file with the fix named. The gate applies to tracked tiers ONLY: the identical content passes in `*.local.toml`, since that is where it is supposed to live. Findings never echo the offending value back, so the check cannot leak a secret into a CI transcript.
- **Config tiers are named, not positional.** The chain grew 5 -> 9 and silently broke two callers that indexed it: `config show` sliced `[:4]`, and `doctor` mapped tier-to-label by position and reported `<workdir>/shepherd.toml` as the "legacy-local" tier. Tiers now carry `(label, path, scope)`; callers filter and label by name, so the next tier added cannot leave one behind.
- **The `shepherd.toml` precedence chain moves out of `.claude/` — a harness-neutral config location.** `.claude/` is owned by ONE harness (Claude Code); shepherd's own bridge contract (`skills/bridge/SKILL.md`) requires implementations to coordinate "exclusively through the project-visible artifact schema... never harness internals," yet a project's *entire* shepherd binding lived inside a competing harness's config directory — `codex-shepherd`, or any future implementation, had to reach into `.claude/` just to discover a repo uses shepherd at all. Two new tiers now lead the chain, `<workdir>/shepherd.local.toml` and `<workdir>/shepherd.toml` (canonical, resolved through the same namespace resolver every other command uses — never a hardcoded `.shepherd`), ahead of the unchanged `.claude/shepherd.local.toml` → `.claude/shepherd.toml` → `$XDG_CONFIG_HOME/shepherd.toml` chain. Purely additive: a project that never adds a `<workdir>/` config sees zero behavior change, and `.claude/shepherd.toml` keeps resolving forever. `shctx config path`/`config init` now target the canonical tier; `shctx config migrate [--dry-run]` moves an existing `.claude/shepherd.toml` onto it (idempotent, never clobbers an existing destination); `is_shepherd_project()` reflects either canonical location. See `docs/configuration.md §Resolution`.
- **`shepherd config validate [--json]` — schema validation with did-you-mean, per-tier.** Unknown keys and unknown `[section]`s used to fall back silently (a typo was simply ignored, the default applied with no signal). Every existing precedence-tier file now validates separately against the `shepherd.toml` pydantic schema — never the merged config — so an issue is reported against the exact file and `[section].key` it came from, never misattributed to a tier sitting lower in the chain. Unknown keys/sections get a `difflib` did-you-mean; a wrong type names the allowed set directly. Exit 0 clean (including when no tier files exist); `--json` for tooling.
- **`shepherd init` becomes the single seamless bootstrap.** Previously an operator ran `shepherd init` then separately `shepherd config init` to get a fully configured project; that hand-off is now gone. `shepherd init` scaffolds the namespace tree, creates `shepherd.db` and applies pending migrations, registers the project, scaffolds the canonical `shepherd.toml`, and runs a closing `doctor` pass — one command, idempotent end to end, with a closing bootstrap summary stating created-vs-already-present for each step. `--no-config`/`--no-doctor` opt out of the new steps individually (`--no-config --no-doctor` together reproduce the exact pre-v6.4.2 on-disk effect); `--user` opts IN to also bootstrapping `~/.shepherd` (the one new step that touches `$HOME`). See `docs/configuration.md §Bootstrap`, `docs/integration.md §Getting started`.
- **Run ids are now mechanized canonical — no harness suffix, no ordinal, ever.** The rule was already written (`naming-conventions.md §Run identity`: `{run}` == the sprint/patch slug the configured pattern produces, never invented ad hoc) but never enforced — a live run in `FL03/axiom` is directoried as `v039-dev0-codex-01`, three unauthorized tokens appended to the canonical `v039-dev0`. This matters because the bridge contract arbitrates custody through ONE `run.json` per run; a harness- or ordinal-suffixed directory silently forks the run into parallel, uncoordinated implementations instead of one shared ledger, defeating the entire mechanism. Now enforced: `shepherd run init` refuses a non-canonical id at creation (naming the canonical one instead), `shepherd run canonicalize` migrates an existing violation onto the canonical path, and `shctx lint` WARNs on every non-canonical run directory it finds. `skills/bridge/SKILL.md` gains a `## Run id canonicality` section beside the #252 content-vs-path contract table.
- **`[project].harnesses` — declarative multi-harness metadata.** A new `shepherd.toml` key listing which shepherd implementations are known to operate in a repo, e.g. `harnesses = ["claude-code", "codex"]`. Purely declarative: a machine-readable anchor for the bridge contract so an implementation can tell "no other harness is configured here" from "a sibling is declared and may hold custody" before it inspects `run.json` — shepherd does not coordinate harnesses automatically and no feature reads it for dispatch yet. See `docs/configuration.md §[project]`, `skills/bridge/SKILL.md`.
- **`shepherd home` — the missing bootstrap verb for the user-level tier (#254).** `~/.shepherd/{profiles,templates}/` (the cross-project style/template tier `resolve_user_home()`'s own docstring called "need not exist") had no command that ever created it — an operator who wanted one Rust style profile shared across every project had to know the undocumented path shape and `mkdir -p` it by hand. `shepherd home init` seeds it from the bundled default; `shepherd home which` renders the same profile/template resolution chain `style show`/`render` pick a winner from, so tier resolution is inspectable instead of implicit. `doctor` gains a ninth check reporting whether `~/.shepherd` exists (INFO, not a failure — the tier stays optional) and which tier each project-declared profile resolves from.

### Fixed

- **CRITICAL: `shepherd run` read 0% of existing `run.json` files, taking the #242 boundary-merge ledger down on every live sprint (#247).** The new pydantic `RunState` was a brand-new minimal schema with `extra="forbid"` and no migration path from anything a prior CLI or a codex-shepherd run had written — field renames (`run_id`→`run`), shape changes (dict-keyed `lanes`→list), and 27 rejected extra top-level fields turned "corrupt run.json" into the reported error for files with no data loss at all. Fixed with an explicit, unit-tested `normalize_run_document()` (handles every renamed/reshaped field), `RunState`/`LaneState` switched to `extra="allow"` so a CLI write can no longer silently drop a field a sibling shepherd implementation wrote, a new `shepherd run migrate [--all]` verb, and the error wording corrected to name the schema mismatch instead of implying corruption.
- **`shepherd dash` GRAPH section presented a closed, wrong-sprint graph as the live one, with no staleness signal (#248).** `.shepherd/graph/state.json` is a legacy non-run-scoped path never tied to the active run; `dash` read it unconditionally. Now compares the file's recorded `sprint` against the active run and prints a staleness/mismatch banner in place of the numbers when they disagree, and notes when graph state isn't being written run-scoped at all.
- **`dash --help` and `migrate --help` executed the command instead of printing help (#249).** Both live among the 25 command modules that disable Click's `--help` interception for bash parity, and neither had its own `-h`/`--help` short-circuit — `migrate --help` fell through to the real schema-migration branch. Both now check for the flag before any DB open or filesystem write; `models.py`/`panes.py`, also named in the issue, were confirmed already correct via eager callbacks and are unchanged.
- **`status`, `audit`, and `style show`/`list` silently migrated the project DB schema despite presenting as read-only (#250).** All four opened the DB through `db.lifespan()`, which calls `ensure_migrated()` unconditionally; `doctor`/`lint` were the only commands that didn't. Callers that want a true read-only open now pass `lifespan(db_path, migrate=False)`, paired with a new `schema_is_current()` precheck (its own short-lived connection, the identical `MAX(version)`/`COUNT(*)` comparison `ensure_migrated`'s fast path already runs) so a caller opting out of self-heal refuses loudly on a stale schema instead of surfacing a confusing missing-column crash.
- **`git_custody` was documented as an `INVOCATION-CONTEXT` field but rendered under `INHERITED CONTEXT`, one block too early (#253).** `agents/conductor.md`'s boot Check 1 lists `git_custody` among the fields it verifies inside the `INVOCATION-CONTEXT:` block; the canonical `boot-prompt.md.j2` template rendered it earlier, outside that block, so a conductor running Check 1 literally would never find it. Moved the template's `git_custody` line into the `INVOCATION-CONTEXT:` block to match the doctrine it's checked against.
- **Dispatch law didn't cover `Workflow`'s `agent()` spelling — a workflow script could fan out agents carrying none of the flock contract with nothing objecting (#255).** `skills/shepherd/SKILL.md §Dispatch law` was written against `Agent(subagent_type:)` only; `Workflow agent({agentType})` is the same dispatch, under a different option name, and the doctrine never named it — a field incident fanned out 16 agents with both options omitted on every call, so all 16 ran as generic subagents (no role body, no code-style skills, no model pin — all inherited opus over the mandated sonnet) and nothing in tooling caught it. The dispatch law now states both spellings are one law (`DISPATCH-MISSING-SUBAGENT-TYPE` either way), that `Workflow agent()` does NOT consult `shepherd.toml [models]` so `model` must be pinned on every call (`DISPATCH-MODEL-UNPINNED`), a new `WORKFLOW-OFF-FLOCK` halt code in the dispatch-law table, and the sanctioned `flockAgent()` guarded-wrapper authoring pattern.
- **Fan-out doctrine had no counterweight — a dispatcher following it correctly could take the machine down (#256).** Measured on a 16 GB box: a verify phase of 12 agents each independently invoking the project's build for the same gate drove free memory to 16 MB and swap to 8.6/9.2 GB before the kernel SIGKILLed a *teammate's* build mid-run — the OS picked the victim, and it picked useful work, not the excess fan-out. `skills/shepherd/SKILL.md` gains a `## Fan-out counterweight` section immediately beside the fan-out doctrine it balances: file-disjointness authorizes concurrent writes, not concurrent builds; fan out fixes, verify once centrally; a resource preflight (declared peak memory/disk ÷ headroom = concurrency cap, with the Rust `codegen-units`-understates-concurrency trap named explicitly); watch swap-free over disk-free (swap is the leading indicator, disk the lagging one); and a killed build is the dispatcher's own largest allocator, never left to the OS. Landed alongside in code: `services/cli/tests/run.sh` now defaults to parallel test workers (`-n auto`, ~3.7x measured) with `SHEPHERD_TEST_JOBS` to cap them, so the suite's own gate doesn't repeat the incident against itself.
- **MCP-over-CLI had no liveness term — a tool that hangs for 30 minutes is "available" by the old contract's test (#257).** Measured: a GitHub-MCP issue-comment write timed out at 1824s, retried, timed out again at 1804s, while `gh issue comment` posted instantly — an hour lost to a tool "available" by the discovery-only reading the whole time. The contract now defines availability as bounded latency, not presence: an MCP write unreturned past a 120s budget is UNAVAILABLE for contract purposes and the sanctioned CLI fallback applies without counting as a violation; the existing `[WARN] MCP unavailable` line now records elapsed time so a hang and a clean absence are distinguishable in a close report; one retry then commit to the fallback for the rest of the dispatch, never per-call re-probing; and bulk ledger writes (a sprint close's many comments) are CLI-first outright given the aggregate hang risk.
- **Boot Check 3 assumed lane-plan sections a cross-implementation run doesn't write (#252).** A codex-shepherd-authored run materializes a real file at every `lanes/{lane}/plan.md` path but as a thin pointer doc — no `## Steps`, no `## Lane acceptance`, no `## Deviations` — so a claude-shepherd conductor booting onto it was told to check off steps that don't exist. `agents/conductor.md` Check 3 now self-heals: a lane plan missing those sections gets them materialized from the master plan's `## Lane projection` before the first dispatch (logged as the conductor's own first `## Deviations` entry); a master plan with no `## Lane projection` to reconstruct from halts `LANE-PLAN-UNRECOVERABLE` rather than inventing steps. `skills/bridge/SKILL.md` gains the distinction the bridge lacked: a table naming which cross-implementation artifacts carry a required **content** shape versus which are merely **path**-compatible.
- **The "Workflow denied in subagents" claim was re-verified on CC 2.1.220 and found imprecise: the tool is invisible to discovery, not denied at invocation (#251).** From a generic workflow-spawned subagent, `Workflow` is absent from the tool roster entirely — not inline, not in the deferred-tool list, no `ToolSearch` match by exact name or keyword — and `Agent`/`ScheduleWakeup` are absent the same way (`SendMessage` loads fine). "Denied at invocation" and "invisible to discovery" are different states with different remediations, and a v6.4.0 grant that "goes live automatically if the platform lifts the denial" cannot, in fact, self-activate an invisible tool. `agents/conductor.md` §Lane walk and this file's own v6.4.0 entry (below) are corrected to say so, with the untested case — a role-launched `shepherd:conductor`/`shepherd:engineer` session rather than a generic subagent, and whether `ScheduleWakeup` survives in a genuine teammate session — recorded as an open question rather than papered over.

## v6.4.1 — 2026-08-03

**The robustness release: the canonical Python CLI completes (all seven remaining bash commands ported), one Jinja2 template engine, one standard `.shepherd/runs/{run}/` artifact layout, and a planning contract refined with internalized planning discipline.** This is the release `d0c9462` bumped the version for and #239 scoped; the bump shipped ahead of the work, and this entry documents what landed under it. Board triage closed 19 stale shipped-but-open issues before a line changed; the sprint plan lives at `.shepherd/runs/v641-dev0/plan.md` (the first artifact in the new layout).

### New

- **`shepherd render` — the ONE template engine (#244/#243/#181).** Jinja2 (`StrictUndefined`, `trim_blocks`, `lstrip_blocks`, sorted-key `tojson`) behind `shepherd_cli/render.py`, replacing five placeholder dialects (awk `gsub`, Python `str.replace`, bash interpolation, two latent `{curly}` conventions). Template resolution: project `.shepherd/templates/` → user `~/.shepherd/templates/` → bundled package data. `--out --manifest` writes a timestamp-free lineage sidecar (template/vars/output sha256), mirroring the graph-compile manifest precedent. Bundled templates: `handoff.md.j2`, `boot-prompt.md.j2` (stable blocks FIRST, per-lane vars LAST — the #243 prefix-cache fix), `lane-plan.md.j2`, `seed.md.j2`, `plan.md.j2`.
- **`shepherd run` — CLI-owned run state.** `.shepherd/runs/{run}/run.json` is schema-validated (pydantic) and atomically written (tempfile → fsync → replace), never latent-space-authored. `run init|show|list|set|lane add|lane set` plus the **#242 boundary-merge ledger**: `run wave accept <lane> --commit <sha>` / `run wave merged <lane>` / `run wave pending` (exit 6 while accepted-but-unmerged lanes remain — the mechanical wave-gate stop).
- **Run-scoped artifact layout.** Every run-scoped artifact lives under `.shepherd/runs/{run}/`: `seed.md`, `mesh.md`, `plan.md`, `phase0.md`, `close.md`, `handoff.md`, conductor-owned `lanes/{lane}/plan.md`, ephemeral `graph/ dispatch/ reports/ audits/`. Durable knowledge is git-tracked; run state is gitignored (the codex-shepherd split). `shepherd migrate --layout v3` relocates legacy `docs/plans/*.{seed,plan}.md` and `styles/*.md` (idempotent, `git mv`-aware, collision-safe) — this repo migrated itself with it.
- **Profiles (operator directive).** `.shepherd/styles/<lang>.md` becomes `.shepherd/profiles/<profile>/style.md` — a directory per profile so user-specific instructions live alongside the language standard. Four-tier resolution: project profiles → legacy styles → user `~/.shepherd/profiles/` → bundled. `~/.shepherd` is the user-level home (`SHEPHERD_HOME` override), the planned site of a future #239 global DB (no `global.db` code, migration, or spec exists yet — see #254).
- **The last 7 bash commands ported** (#239): `adapt`, `inject`, `plan`, `graph`, `loop`, `panes`, `release` land as native Typer modules with migrated test suites, alongside their bash originals. All SQL parameterized (#234 class eliminated); `graph next` cursor regression pinned (#225); `teammate register-lead` ported with the #241 UNIQUE retrofit. **Correction (2026-08-13, v6.4.5 audit):** this entry originally also claimed `skills/context/scripts/` "retires behind `bin/shepherd`" with `shctx` staying as "a thin exec alias." Both halves were false, then and now: `skills/context/scripts/shctx` is, and remains, a standalone bash dispatcher (`cmd_*.sh` under it) that never calls `bin/shepherd`, so it cannot be an alias to it. The 7 commands above were ported to native Python IN ADDITION to the bash originals, not instead of them — the `shctx`→`bin/shepherd` shim cutover that would actually retire `cmd_*.sh` was explicitly deferred at v6.4.0 (see "Deferred to v6.4.1" below) and never landed; `bin/shepherd` still falls back to bash `shctx` for the commands the Python CLI doesn't own outright.

### Fixed

- **Worktree root resolution in the Python CLI (#221/#231).** `resolution.resolve_repo_root()` now resolves via `git rev-parse --git-common-dir` (mirroring the bash fix), so a conductor lane in a linked worktree binds the MAIN checkout's registry instead of scaffolding a divorced per-worktree DB; `in_subworktree()` feeds doctor. Regression tests build a real repo + worktree.
- **Test-suite portability.** `services/cli/tests/conftest.py` hardcoded the author's absolute repo path (`/home/user/shepherd`) — the whole suite failed to collect from any other clone. Now derived from `__file__`.
- **`eval list` flag-parity test de-flaked.** The byte-compare straddled a second boundary on the rendered `Ns ago` age; ages are normalized before comparison.
- **Identity-gated Stop hooks (#232/#228) + liveness scoping (#229).** The coordinate-drive guard fires on positive session identity (registered lead, no teammate marker) instead of registry inference; heartbeats no longer stamp other sessions' rows; reboot-stale ghosts drop out of the live set.
- **Gate-skipping enforcement (#59).** `doctor` reports gate-invocation coverage (including `[gates.extra]`) from a deterministic per-session ledger; `close_finalize_check.sh` surfaces unrun extra gates at close.

### Changed

- **Planning contract refined (no new skills, nothing forced).** The engineer's plan discipline is internalized (superpowers skills load only IF INSTALLED, never a grade-cap): per-step `Interfaces: Consumes/Produces` contracts, a banned-placeholder law, a pre-critic self-review walk (seed coverage / placeholder scan / symbol consistency). Lane plans materialize as files — root renders `runs/{run}/lanes/{lane}/plan.md` from the lane projection; the **conductor owns its lane plan** (checkbox tracking, append-only `## Deviations`, acceptance results) as its ONE write exemption. Boot prompts are rendered (`shepherd render boot-prompt.md.j2`) with the lane-plan PATH instead of a pasted brief slice, and carry a structured `git_custody: root|lane` field the profile must obey (#230). Spawn preflight Check 1 verifies the Agent-Teams substrate instead of advising (#220).
- **`.shepherd/` is the only project-visible namespace.** This repo's own dogfood config and artifacts migrated off `.artifacts/` (resolvers still honor legacy trees). `skills/context/references/naming-conventions.md` is the canonical artifact schema: exact-path table, ownership table, identifier grammar, git split.
- **Eval rubrics.** `seed.rubric.json` gains a `no_placeholders` dimension; new `plan.rubric.json` grades seed coverage, buildability, interface contracts, and placeholders at the wave-review bar.

## v6.4.0 — 2026-07-21

**Hardening + the CLI consolidates onto a single canonical Python surface.** The command-line interface moves onto the `shepherd` Python CLI (`services/cli`), retiring the loose `shctx` shell layer behind one entrypoint so future buildouts get consistency, real libraries, and community tooling. A user-wide `~/.shepherd` home, self-containment fixes, teammate engagement loops, and the dev.5–7 issue batch land alongside. (Sprint in progress; sections appended as work lands.)

### New

- **`bin/shepherd` is the single canonical CLI entrypoint (item 3).** A thin wrapper that resolves `${CLAUDE_PLUGIN_ROOT}`, prefers `poetry -C services/cli run shepherd`, and falls back to `python3 -m shepherd_cli` when poetry is absent — the same self-contained pattern the `myfi` plugin proved. The Python package (`shepherd_cli`) becomes the sole owner of CLI logic; the `cmd_*.sh` shell scripts are retired behind it (parity-gated; port in progress).
- **Auto-venv under `~/.shepherd` (item 1).** `bin/shepherd-venv-ensure` bootstraps the `services/cli` poetry venv idempotently (stamp-diff on `pyproject.toml`; re-installs when the venv is missing) with the stamp under `${CLAUDE_PLUGIN_DATA:-$HOME/.shepherd/plugin-data}` so it survives a plugin update. A new `SessionStart` hook (`hooks/scripts/session_venv.sh`) keeps it fresh — gated on a shepherd project, fail-open.

### Docs

- **README calls out `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` (item 6).** A prominent Install note plus two FAQ rows: the execution path runs entirely through Agent-Teams teammate-conductors, which are experimental and off by default; without the variable `/shepherd:spawn` cannot spawn a teammate. README version reference corrected 6.3.3 → 6.4.0.

### Changed

- **`services/cli` version 6.3.7 → 6.4.0**, description updated to name it the canonical CLI rather than a surface "coexisting with bash shctx".
- **`Workflow` ships in-tree on both teammate leads — `@engineer` + `@conductor` (#233).** Reverses the v6.3.9/#220 tier partition per operator decision: the manual 6.3.8 grant that 6.3.9 stripped is now canonical, so a release never clobbers it again. The grant is INERT at runtime today — Workflow is still denied inside a subagent (CC 2.1.212), so the executing fan-out stays in-context `Agent()`; the agent bodies keep that honest. `lint_agent_capabilities.sh` now mandates Workflow on all three leads (`LEAD_MANDATED_WORKFLOW="shepherd engineer conductor"`), `test_lead_workflow_tool.sh` is rewritten to pin it (stripping it from any lead fails), and `test_v636`/`test_v638` wiring reconciled. **Correction (2026-08-03, #251):** this entry originally also claimed the grant "goes live automatically if the platform lifts the denial." A later measurement (CC 2.1.220, from a generic workflow-spawned subagent) found `Workflow` is not merely denied-at-invocation but INVISIBLE TO DISCOVERY — absent from the tool roster entirely, same as `Agent`/`ScheduleWakeup` from that vantage point. An invisible tool cannot "go live automatically": nothing re-adds it to a roster on its own, so a future platform change needs its own detection mechanism, not an assumption baked into this grant. See `agents/conductor.md` §Lane walk for the current, honestly-hedged wording (the role-launched `shepherd:conductor` case itself remains untested).
- **Conductor + root shepherd actively run focus + motivation + improvement loops (#236).** The conductor gains temporal self-motivation: a `ScheduleWakeup` grant plus a ground-truth-probe rule so a lost completion notification no longer strands it idle (no root babysits a teammate, and `/goal`/`/loop` are lead-only). Its §Lane walk now runs its own FOCUS-LOOP to the final WAVE-GATE and cites `adapt priors`. Root's standing operating mode — FOCUS-LOOP + drive contract + close-time `shctx adapt roll` — is made explicit in `skills/shepherd/SKILL.md`.
- **Self-containment: MCP is provider-agnostic (item 5b / #110).** Shepherd no longer hard-assumes the `mcp__plugin_github_github__*` namespace. Every flock agent that touches GitHub/Sentry/Supabase now grants `ToolSearch` (engineer, auditor, discovery, coder, worker join conductor/planter), and the dispatch contract (`skills/shepherd/SKILL.md §Principles`) discovers a service's tools at runtime by capability — a native `mcp__github__*`, Composio, or a Docker-gateway `mcp__MCP_DOCKER__*` namespace all resolve — with `gh`/`psql` CLI as the sanctioned fallback. A `ToolSearch` that returns nothing for a service is treated as a disconnected/absent provider (#110): degrade to the CLI fallback and emit `[WARN] MCP <svc> unavailable`, never a silent tool failure. The `mcp__plugin_*` frontmatter entries stay as the default-provider offer, not a dependency.

### Fixed

- **`shctx teammate heartbeat` no longer breaks on an apostrophe in `--note`/`--phase`/`--tool` (#234).** The heartbeat write path interpolated user text unescaped (`NULLIF('$note','')`), so a conductor engagement note like `reconciling lane-config's plan steps` threw `unrecognized token` and the heartbeat silently failed — directly undermining the #236 engagement telemetry it was meant to record. Routed `name`, `note`, `phase`, `tool`, and the tmux pane id through the existing `esc` helper (single-quote doubling), matching the `safe_*`/`_txt` escaping every other write path already used. Regression pinned in `skills/context/tests/test_cmd_teammate.sh`. (The `loop focus upsert` path #234 also named already escapes via `_txt`; the heartbeat path was the remaining live gap.)

### Deferred to v6.4.1 (tracked in #239)

The flagship "retire the shell scripts" work is committed as v6.4.1 deliverables, not dropped: porting the last 7 bash commands (`inject plan graph adapt loop release panes`, ~3,300 lines) to native Python with parity, bundling the schema as package data, the `shctx`→`bin/shepherd` shim cutover that retires `cmd_*.sh`, and the `~/.shepherd` cross-project `global.db` + evolvable user-wide styles/doctrines + `shepherd sync`. None of it blocks a live sprint — `bin/shepherd` already drives all 40 commands today through the shim; the parity port is completeness work that must not be rushed into a broken command.

## v6.3.9 — 2026-07-18

**The six token-costing bugs the dev.6 shepherd session filed after v6.3.8 shipped (#220–#225) are closed as the patch's pillars: three real code fixes (shctx worktree-DB race, `graph next` crash, a concurrent-session Stop-loop) and a teammate-tier doctrine reconciliation grounded in the current Claude Code harness (Workflow is denied inside subagents; conductors commit AND push their own lane).**

### Fixed

- **`shctx` no longer binds a stray empty per-worktree DB under concurrent `/shepherd:spawn` lanes (#221).** `skills/context/scripts/_lib.sh:shctx_repo_root` resolved the project root via `git rev-parse --show-toplevel`, which returns the CURRENT worktree's root — so from a linked worktree (every concurrent conductor lane) config and the registry DB scoped per-worktree. Because the namespace dir (`.shepherd`/`.artifacts`) is a git-TRACKED subtree it exists in every worktree checkout while the DB is gitignored, so `resolve_workdir` picked the worktree-local namespace, `shctx_db_path` targeted a never-created DB there, and the first query auto-vivified a 0-byte, schema-less `shepherd.db` (`shctx_ensure_migrated`'s fast path bails on a DB with no `schema_versions` row) — the field "`no such table: focus` / `no such table: teammates`". Fixed at the single resolution point: `shctx_repo_root` now resolves the MAIN worktree via `git rev-parse --git-common-dir` (which points at the shared `.git` even from a linked worktree), mirroring the proven `hooks/scripts/_lib.sh:sprint_root` pattern; every downstream resolver (`resolve_workdir`, `shctx_db_path`, `cfg_get`, `shctx config path`, `cmd_doctor.sh`, …) inherits it. New `shctx_in_subworktree` helper + a `shctx doctor` check that WARNs on a stray per-worktree DB and confirms the shared-root scoping. Test: `skills/context/tests/test_worktree_root_resolution.sh` (real linked worktree → repo root + DB path + config all resolve to main).

- **`shctx graph next` no longer throws `AttributeError: 'str' object has no attribute 'get'` (#225).** Stage-Graph `agents:` entries are meant to be mappings (`{role, count}`), but nothing enforced it: the natural YAML shorthand `agents: [engineer]` (a bare string) passed `plan extract` and `plan validate` clean and detonated three commands later at `a.get("role")` in `cmd_graph.sh`. Closed at the boundary AND the crash sites: `cmd_plan.sh` `_cmd_extract` normalizes every entry when state.json is written (string → `{role, count:1}`; a mapping without a `role`, or any other shape, hard-fails at extract with a clear message), `_cmd_validate` gains check #5 so `validate` stops reporting OK for a malformed plan, and the four downstream readers (`graph next`/`compile`/`diagram`, `plan topology`) each guard `isinstance(a, dict)` as defense-in-depth for a hand-edited state.json. Test: `skills/context/tests/test_graph_next.sh` (shorthand extracts + renders `@engineer`; a genuinely malformed entry is rejected).

- **`coordinate_drive_guard.sh` nudges only the recorded spawn LEAD, never a concurrent bystander session (#223).** The Stop guard exempted registered TEAMMATES (#197) but never asked whether the stopping session is the LEAD that owns the live team — so a second, unrelated session sharing the per-repo DB read the same `v_teammates_live` counts and got the `[coordinate-active-drive]` block every turn-end, with a "drain the work" instruction it had no teammates to act on (and text that could drive a wrong-session `git worktree remove`). The DB had no concept of a lead. Fix: new `spawn_leads` table (migration `0021_spawn_lead.sql`), `shctx teammate register-lead` (wired into `commands/spawn.md`, stamping root's own `{main_chat_session_id}` at spawn), and a conservative guard gate that exits 0 only when a DIFFERENT session is the recorded lead of a live team AND the stopping session leads none (`MY_LEAD=0 AND OTHER_LEAD>0`) — when no lead is recorded (pre-#223 DB, or `register-lead` not called) the guard preserves its pre-#223 behavior rather than silently no-op'ing a genuine lazy-root stop. Test: `hooks/tests/test_coordinate_drive_guard.sh` gains bystander-exempt + lead-still-blocks cases; all prior BLOCK cases pass unchanged (no `spawn_leads` rows → `OTHER_LEAD=0`).

- **The teammate-conductor / self-contained-engineer doctrine is reconciled with the real Claude Code harness: `Workflow` is denied inside subagents, so in-context `Agent()` fan-out is the first-class teammate mode (#220).** Verified against `code.claude.com/docs` (CC 2.1.212): the `Workflow` tool is a TOP-LEVEL-SESSION primitive — hard-denied inside any spawned subagent/teammate regardless of `tools:` frontmatter (presence controls the OFFER, not runtime permission); Agent Teams do not nest (teammates cannot spawn teammates) and the main session is the fixed lead; teammates CAN spawn nested subagents via `Agent()`. So doctrine that told a teammate-conductor/engineer to "compile gate-free fan-out into a Dynamic Workflow" (v6.3.5/#207 premise) was unsatisfiable one tier down and burned cycles on a denied call or a mis-report. The platform fact is now canonical in `skills/harness/SKILL.md §Workflow tool`; `agents/conductor.md` (§DISPATCH MODE, replacing the WORKFLOW SELF-CHECK) + `agents/engineer.md` fan out in-context via `Agent()` as the unconditional first-class mode; `wave-routine.md`/`pipeline.md`/`workflow-templates.md` are driver-conditional (root compiles, teammate dispatches in-context); `agents/auditor.md §Dispatch-substrate` grades a teammate's `workflow_tool: absent`/`fanout: in-context` as EXPECTED and CORRECT (the inverse — a teammate claiming a compiled Workflow — is the anomaly). The v6.3.5/#207 grant is PARTITIONED, not deleted: root (`shepherd`) still GRANTS `Workflow` (it drives `/shepherd:start`), the teammate leads DROP the now-inert grant, and `lint_agent_capabilities.sh` pins BOTH halves (`LEAD_MANDATED_WORKFLOW="shepherd"` + a `WORKFLOW_TEAMMATE_DENIED` inverse); `test_lead_workflow_tool.sh` proves root-strip fails and teammate-add fails.

- **The conductor commit-custody contradiction is resolved to ONE model: a conductor commits AND pushes its OWN lane branch (#222).** `commands/spawn.md`'s boot-brief listed `git commit`/`git push` under `TEAMMATE-GIT-WRITE`, directly contradicting `agents/conductor.md` ("Commits are yours") and both mechanical guards (`teammate_git_guard.sh` explicitly ALLOWED in-worktree commits; `coder_git_guard.sh` bakes in "the conductor stages+commits your reported files"). Per operator direction, a conductor is a detached manager that commits AND pushes its lane after implementation + adversarial-review waves, then hands root a clean, final product; only cross-lane integration onto the shared dev branch stays root's. `teammate_git_guard.sh` now allows `git push` (blocking only `merge`/`rebase`/`cherry-pick` + `worktree add/remove/prune`), `spawn.md:124` is corrected to match, and `agents/conductor.md` §WAVE-COMPLETE gains a self-enforcing `git_custody` attestation (`committed`, `commit_shas`, `pushed`, `worktree_clean`) that `escalation.md`'s `WAVE-COMPLETE-UNVERIFIED` cross-checks before root's own `git log`. Test: `test_teammate_git_guard.sh` flips the push case to PASS.

- **A misrouted in-context `Agent()` sub-dispatch completion no longer strands a conductor for hours (#224).** Documented Agent-tool nesting behavior: a subagent a teammate-conductor dispatches can report completion to the session that owns the whole task tree (root), not to the conductor — the field cost was a REDO coder's full report sitting unseen 2h+ while its conductor held WAVE-COMPLETE on "no notification yet." `agents/conductor.md` gains a Defensive-poll rule (past the step's expected runtime, actively `TaskGet`/read the dispatched agent's output instead of blocking on a notification that may have misrouted; bounded backoff, then escalate), and `agents/shepherd.md` gains a Coordinate-loop RELAY step (a completion for a lane root did not itself dispatch is relayed VERBATIM to the owning conductor the same wake, matched via the `shctx teammate` registry + a new `Lane:` line on the WORKER/CODER report).

### Housekeeping

- New/updated tests wired into `hooks/tests/run.sh` and the context suite: `test_worktree_root_resolution.sh` (#221), `test_graph_next.sh` (#225), extended `test_coordinate_drive_guard.sh` (#223) + `test_teammate_git_guard.sh` (#222) + `test_lead_workflow_tool.sh` (#220 grant-partition, rewritten) + `test_v636_wiring.sh`/`test_v638_wiring.sh` (reconciled to the #220 partition), and a new `test_v639_wiring.sh` pinning every cross-file leg of #220–#225. `invariant-matrix.md` rows 3 + 24 updated for the #220 partition; new rows 28–33 record the six invariants.

- **Custody-model decision recorded (Confusion-Protocol resolution).** #222's literal ask was to excise conductor commit language and attest a "dirty worktree" (Model B, root harvests everything). Investigation found both mechanical git guards + `conductor.md` + `coder.md` all implement Model A (conductor commits its lane; root integrates cross-lane); reverting to Model B would gut two mature enforcement hooks and break `WAVE-COMPLETE-UNVERIFIED`'s git-log verification. Operator confirmed Model A, extended so the conductor also PUSHES its own lane branch. The one dissenting line (`spawn.md:124`) was corrected to the enforced model.

- **Concern flagged (`DONE_WITH_CONCERNS`):** `skills/harness/references/workflow-templates.md §Model pin` (untouched) states a compiled segment runs via `node <segment>.workflow.js` as "a Bash invocation, not the Workflow tool" — outside `workflow_model_guard.sh`'s `PreToolUse(Workflow)` reach. If literally true, the compiled-script execution path never invokes the native `Workflow` tool, which sits awkwardly next to #220's "Workflow tool denied in subagents" as the mechanism a teammate is blocked by. The v6.3.9 doctrine (teammate NEVER produces an executed script; it dispatches in-context via `Agent()`) is correct regardless, but the `shctx graph compile` execution-mechanism plumbing deserves a definitive answer in a follow-up.

## v6.3.8 — 2026-07-17

**The single-root-dispatcher "waves of dynamic workflows" routine is codified once and driven two ways, and its wave-gate facts move out of latent space into three deterministic scripts.**

### New

- **`/shepherd:start` returns as the codified root-drives-workflows execution mode (#217).** The per-wave routine — `pipeline()` over file-disjoint `@coder`+`@auditor` step pairs (redo cap 3), a hard-rule preamble on every brief, and a serial root gate (`journal-status` → `loc-count` → cross-step disjointness → workspace gate → append-only MSD ledger + wave commit) — is defined once in `skills/shepherd/references/wave-routine.md`. Two drivers: root runs it directly via the thin, execution-only `commands/start.md` (also the zero-drift fallback when Agent Teams are unavailable), and a `@conductor` runs it abbreviated per-lane (`agents/conductor.md §Lane walk`), differing only in scope and git-integration authority. `agents/shepherd.md`, `commands/spawn.md`, and the Dispatch law (`skills/shepherd/SKILL.md` + `agents/shepherd.md` prohibitions #2/#12 + the side-effect boundary) are reconciled so the direct-drive mode is a first-class path: root may dispatch `@coder` and commit source ONLY in this mode, where it runs the same wave gate a conductor would.

- **Three deterministic wave-gate scripts (`scripts/`) replace latent-space computation.**
  - **`loc-count.py` (#216)** — net production Rust LOC of the working tree vs a base ref: added-minus-removed `.rs` lines outside brace-matched `#[cfg(test)]` / `#[cfg(all(test, …))]` spans, `tests/` directories skipped, `#[cfg(not(test))]` counted as production, untracked new files plus file deletions and renames handled (the gate runs before the wave commit). The brace matcher is comment- and string/char/raw-string-literal-aware.
  - **`journal-status.sh` (#213)** — deterministic wave-return from a Dynamic-Workflow `journal.jsonl` (`steps / returned / pass / redo / pending`; exit 3 absent, 4 pending, 0 done). The dispatcher records the `runId` + journal path in the plan frontmatter (survives `/compact`); the journal watchdog is canonical, the harness task registry is not.
  - **`df-guard.sh` (#214)** — `--min=12` disk-pressure precheck before any cargo. The four disk rules (df precheck, shared coder→auditor `CARGO_TARGET_DIR`, delete-on-final-PASS, no concurrent workspace gate) are baked into `agents/coder.md`, `agents/auditor.md`, `pipeline.md §Gates`, and the wave routine.

### Fixed

- **Root (`agents/shepherd.md`) grants `Workflow`.** Root's WORKFLOW SELF-CHECK mandates compiling Dynamic Workflows and `/shepherd:start` drives them directly, but the grant was missing — root could not drive a wave. `lint_agent_capabilities.sh` `LEAD_MANDATED_WORKFLOW` now includes `shepherd`, and the self-check prose is reconciled (`present` is the guaranteed path).

- **`@critic` grants `Bash`.** Its Step 0.5 runs `shctx deliverable promise` / `audit insert`, but `critic`'s tools were `Glob, Grep, Read, Skill`, so every verdict deliverable stalled. `bash_guard.sh` Check 3 now scopes critic (and discovery) to read-only: source and filesystem mutation via shell are blocked, `shctx` passes. A read-only-role Bash-presence lint block pins it.

- **`agents/coder.md` states the ONE-LOC rule verbatim (#215):** every production `*.rs` line counts, `tests/` files and `cfg(test)` bodies do not; any budget/scope/governance interpretation is a `LOC-BUDGET-GOVERNANCE` escalation to the dispatcher, never local adjudication; dropping a mandated deliverable is never a valid LOC remedy.

### Housekeeping

- New tests: `test_loc_count.sh`, `test_journal_status.sh`, `test_df_guard.sh`, `test_readonly_bash_guard.sh`, `test_v638_wiring.sh`; `test_exec_bits.sh` extended to `scripts/`; all wired into `hooks/tests/run.sh`. `skills/shepherd/references/invariant-matrix.md` rows 25–27 record the new invariants.

## v6.3.7 — 2026-07-16

**Finish the #206 job v6.3.6 only patched: the generic mailbox is gone, replaced by a dedicated cross-session `signal` channel — and the native `shepherd` CLI grows from one command group to five.**

### Fixed

- **The redundant `shctx mailbox` surface is removed; a dedicated cross-session `signal` channel replaces its one real use (#206).** v6.3.6 narrowed the phantom-unread symptom (excluding `kind='seed-ready'` from the drive guard's count) but left the generic mailbox — and its confusion — in place. The root cause was a single generic inbox straddling two unrelated jobs: intra-session teammate↔lead coordination (which the harness already owns via the native `SendMessage` queue — root's canonical inbox) and cross-session handoff between two independent operator sessions. This splits them by scope. **Intra-session** stays entirely on native `SendMessage`; the `coordinate_drive_guard.sh` Stop hook no longer reads any mail table at all (a Stop hook cannot see the native queue in SQLite, so it must not try) and keys purely on idle teammates — the phantom-unread desync is now structurally impossible, not merely filtered. **Cross-session** gets a purpose-built, deliberately narrow channel: `shctx signal send/poll [--consume]` over a new `session_signals` table (migration `0020_drop_mailbox.sql`, which drops the `mailbox` table + `v_mailbox_unread_per_recipient` view and creates `session_signals`). It carries no read/ack tri-state — just a one-shot `consumed_at` — and nothing "drains" it, so it can never manufacture an unread count. The `--staged` plant→spawn `seed-ready` handoff is repointed onto it (`agents/planter.md`, `skills/shepherd/references/spawn-flags.md`, `commands/spawn.md`), and the doctrine is explicit that the committed seed file — not the signal — is the source of truth. Doctrine updated across `flock.md`, `escalation.md`, `motivation/SKILL.md`, `loop-templates.md`, `configuration.md`, `context/SKILL.md`, and `schema.md`. Tests: `cmd_mailbox` test deleted; new `test_cmd_signal.sh`; `test_staged_handoff.sh` rewritten onto the signal channel (and asserting the mailbox subcommand no longer resolves); `test_coordinate_drive_guard.sh` rewritten (no mail table, idle-only triggering); `test_v636_wiring.sh` §206 flipped to assert full removal. Context suite 48/48, hook suite green.

### New — the native `shepherd` CLI grows from one command group to thirty-three (#198 continuation)

- **Thirty-two new natively-ported Typer command groups join `teammate`:** `signal`, `mem`, `deliverable`, `status`, `lock`, `sprint`, `models`, `query`, `style`, `report`, `search`, `export`, `lint`, `seed`, `config`, `sync`, `dash`, `insights`, `dups`, `handoff`, `ready`, `discovery`, `audit`, `eval`, `doctor`, `migrate`, `init`, `close-lane`, `issues`, `worktree`, `refresh`, and `prune` (was: one group, everything else shimmed to bash). Each mirrors its `shctx cmd_*.sh` twin with bash parity (same subcommands, flags, output shape, exit codes, ordering, and no-subcommand behavior) over the SAME sqlite registry, under the established coexistence contract — Tortoise models MIRROR the canonical SQL schema (never `generate_schemas`), the schema self-heals like #200, and un-ported subcommands still shim to bash `shctx`, so `shepherd` remains a working superset on day one. Highlights: `signal` is cross-tool interoperable with the bash channel (a signal sent by either is polled by either); `sprint` mirrors bash's orchestration by shelling to sibling scripts via `find_bash_shctx`; `lock` uses raw parameterized SQL for `locks_history` (closing the string-interpolation hole the bash `'$SESS'` interpolation carries); `models` is pure-config (tomllib, no DB); `search` ports FTS5 MATCH via raw SQL; `seed verify` is a pure-text pre-flight gate; `sync` mirrors bash's refresh pipeline by shelling to sibling scripts. Each batch was produced by a **Dynamic-Workflow wave** — the shepherd plugin dogfooding its own fan-out substrate to build itself, one disjoint-file agent per group, with the orchestrator reviewing every port, resolving model/table collisions, and greening the suite (fixing the wave-authored tests' own bugs the suite surfaced — a trailing-newline assertion, a `MAX(refreshed_at)` staleness expectation, and a `help_option_names=[]` gap where three groups let Click steal `--help` from their bash-usage handler). `dash` is a read-only composition that reuses six existing models and shells to `cmd_graph.sh` for its graph section; `insights`/`discovery` read on-disk JSON records; `audit` runs a lint→doctor→status pipeline; `doctor` ports the diagnostic sections natively; `eval` mirrors `eval_runs`. Where a table already had a read-scoped model (`discovery_findings`, `audit_findings`), the write paths use raw parameterized SQL rather than redeclaring the table (the collision rule). Wave 6 added the operator-selected "valuable" remainder: `migrate`/`init` (narrated schema/scaffold, raw sqlite3 so the "applying NNNN" lines survive — `db.lifespan`'s self-heal is silent), `close-lane`/`issues`/`worktree`/`refresh` (DB writes + faithful subprocess drives of git/gh/sibling stages), and `prune` (destructive GC ported with its safety contract intact: dry-run default, `--confirm` required, snapshot-before-delete, table-guarded deletes). CLI package bumped 6.3.3 → 6.3.7; full CLI suite 1079 passed (was 30, teammate-only). **Deliberately left on the bash shim** (operator decision — a native port would re-implement a large bash state machine or merely re-shell-out): the workflow state machines `graph`/`adapt`/`loop`/`plan`/`release`, plus `inject` (context assembly) and `panes` (tmux). They keep working today via the passthrough shim.

### Housekeeping

- **Closed #207 with evidence — the lead-`Workflow` grant fix from v6.3.5/v6.3.6 is verified in-tree.** `agents/conductor.md` and `agents/engineer.md` both grant `Workflow`; `hooks/tests/test_lead_workflow_tool.sh` (the strip-and-reintroduce guard) and the `lint_agent_capabilities.sh` `LEAD_MANDATED_WORKFLOW` block are green, so the mandated Dynamic-Workflow fan-out path is reachable and can't silently regress. No code change needed in v6.3.7 beyond confirming the guard.

## v6.3.6 — 2026-07-16

**Pin the #207 `Workflow`-tool grant so it can never silently regress, kill the #206 phantom-unread Stop loop, and repair the changelog gap that hid all of it.**

### Fixed

- **A team lead can no longer silently lose the `Workflow` tool its own fan-out doctrine mandates (#207 — regression guard).** The v6.3.5 one-line frontmatter fix was correct but unguarded: nothing stopped a future edit from dropping `Workflow` again and returning every `@conductor`/`@engineer` to the slow in-context `Agent()` fallback. Closed structurally with three agreeing layers. (1) **Authoring-time** — `hooks/tests/lint_agent_capabilities.sh` gains a `LEAD_MANDATED_WORKFLOW` block asserting both leads grant `Workflow` (the inverse of the existing tool-*claim*-consistency check), with a dedicated strip-and-reintroduce test `hooks/tests/test_lead_workflow_tool.sh` (each lead exercised independently) wired into the suite. (2) **Runtime** — `agents/auditor.md` §Dispatch-substrate no longer grades a `workflow_tool: absent` trace as unconditionally correct; post-#207 an unexplained `absent` is a regression signal, so the wave-review gate agrees with the static lint. (3) **Doctrine + docs** — `agents/conductor.md` §WORKFLOW SELF-CHECK reconciled (`present` is the guaranteed path; `absent` now means a genuine runtime denial worth noting, not the routine spawn state it was through v6.3.4), and `skills/shepherd/references/invariant-matrix.md` row 24 records the lint+test pair. `hooks/tests/test_v636_wiring.sh` pins all three legs so none drifts back independently. Hook suite 65/65 → 67/67.
- **`coordinate_drive_guard.sh` stopped phantom-blocking root's Stop on a stale `seed-ready` mailbox row (#206).** The Stop guard counted "lead-bound unread" as any unread `mailbox` row whose recipient isn't a current teammate. But since v6.2.8 escalations moved off the mailbox onto the native SendMessage queue (root's real inbox), leaving the `--staged` plant→spawn `seed-ready` handoff as the mailbox's ONLY sender. That row is addressed to a `shepherd-spawn-<slug>` inbox drained by its own dedicated `mailbox recv --mark-read` wait-gate poll — never by root's coordinate loop — and an abandoned `--staged` run (STAGED-TIMEOUT, crash, or `--staged` simply never used) leaves it `read_at IS NULL` forever. Because the namespace DB is shared per repo, every UNRELATED coordinate session then miscounted it as "N unread message(s) addressed to you" and re-fired the drive block indefinitely (the per-session runaway cap only masks 2 blocks per session, so it recurred every fresh session — the field "4 unread over an empty inbox, twice"). Fix: exclude `kind = 'seed-ready'` from the unread count; general lead-bound unread signalling is preserved. Two regression cases added to `test_coordinate_drive_guard.sh` (a seed-ready row never blocks; a genuine lead-bound unread alongside it still does). Wholesale mailbox removal (the issue's alternative ask) stays out of scope: `--staged` cross-session handoff has no SendMessage equivalent (SendMessage is single-team-scoped; plant and spawn are separate sessions).
- **Reconstructed the missing v6.3.4 and v6.3.5 changelog entries, and closed the gap that let them ship undocumented.** Both were tagged releases (#204, #205) with no `CHANGELOG.md` entry — and v6.3.5 was the #207 `Workflow`-tool fix itself, so the single most consequential recent fix went unrecorded. Root cause: `.github/workflows/release.yml` silently fell back to GitHub auto-generated notes when a `## v<version>` section was missing. That fallback now emits a loud `::warning::` GitHub Actions annotation, and a new `hooks/tests/test_changelog_current.sh` gate fails the hook suite whenever `CHANGELOG.md` lacks an entry for the current `plugin.json` version — so a version bump can never again ship without its changelog entry. The reconstructed v6.3.4 / v6.3.5 entries are below.

### Housekeeping

- **Closed #152 and #154 with evidence — both were fixed in v6.3.2 but left open** (the v6.3.2 housekeeping pass closed 21 other resolved issues and missed these two, though both are named in the same entry's §Fixed). #154 (the `close_finalize_check.sh` deferred-merge re-block loop) has both fail-open escapes present and covered: the `[close].finalize_hold` operator hold (`close_finalize_check.sh:90-92`) and the per-`(session,slug,HEAD-sha)` runaway bound (`:94-106`); `test_close_finalize_check.sh` 15/15. #152 is fully present too — part 1 (root git-verifies a `WAVE-COMPLETE` claim: `agents/shepherd.md:192-204` + `WAVE-COMPLETE-UNVERIFIED` in `escalation.md`, pinned by `test_flock_output_review.sh`), and part 2 (branch discipline) was subsumed by the stronger #187 `coder_git_guard.sh` blanket coder-git deny (v6.3.0 — cwd-independent, proven by `test_coder_git_guard.sh`'s cross-worktree case) plus the pre-existing conductor cwd-pin doctrine (`flock.md` §Ban 1 / `bash_guard.sh`).

## v6.3.5 — 2026-07-15

**Team leads (`@engineer`, `@conductor`) finally carry the `Workflow` tool their fan-out doctrine mandates (#207).**

### Fixed

- **`@engineer` and `@conductor` could not take the Dynamic-Workflow fan-out path their own doctrine calls the default (#207).** Both leads run at `[spawn].lead_effort = ultracode`, where compiling gate-free fan-out into a Dynamic Workflow is "the default, not the exception" (`agents/conductor.md` §WORKFLOW SELF-CHECK) — but `Workflow` was absent from their `tools:` frontmatter, so the mandated self-check hit its "Absent → in-context `Agent(...)`" branch on every spawn and every conductor/engineer silently fell back to the slow, sequential-ish in-context fan-out (no out-of-context compilation, no concurrent segment execution). Field evidence: all three v0.3.8-dev.3 Wave-1 conductors reported `workflow_tool: absent / fanout: in-context-fallback`; Wave 1 (3 file-disjoint lanes) took ~3h wall-clock. Added `Workflow` to the `tools:` allowlist of both `agents/conductor.md` and `agents/engineer.md`. (This entry was reconstructed in v6.3.6, which also adds the regression guard that keeps the grant from silently regressing again.)

## v6.3.4 — 2026-07-15

**Marketplace manifest identity fix + version-string sync (#204) — no agent/hook/skill/CLI behavior changed.**

### Fixed

- **`.claude-plugin/marketplace.json` top-level `name` was `"fl03"`, inconsistent with the plugin's own identity (`"shepherd"` everywhere else, including `plugin.json` and the marketplace's own `plugins[0].name`).** Corrected to `"shepherd"`; `repository` gained the explicit `.git` suffix (`…/shepherd` → `…/shepherd.git`), the top-level `version` was promoted next to `repository`/`homepage`, and the plugin entry's fields were normalized (`homepage` added, field order regrouped).

### Changed

- Bumped the plugin version 6.3.3 → 6.3.4 across `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `skills/context/SKILL.md`, and `skills/shepherd/SKILL.md` so the marketplace manifest and skill `version:` frontmatter track the plugin. No agent, hook, skill, or CLI runtime behavior changed (confirmed via `git show 6611530 --stat`). (Entry reconstructed in v6.3.6 — omitted at release time; see v6.3.6 §Fixed.)

## v6.3.3 — 2026-07-15

**State-subsystem hardening — the `declared_state` feature the field broke on first run — plus the packaged `shepherd` CLI begins; the toolkit feature is retired.**

### Fixed

- **`shctx teammate liveness` / `shctx panes` crashed with `no such column: declared_state` on a behind DB (#200).** `shctx init` seeded only `0001_init.sql`; migrations were applied by a SEPARATE `shctx migrate`, so a DB from an older plugin (or one left half-applied by the 0017 abort) lagged the code and the 0019 `declared_state` query errored (tests passed because the harness applies every migration file directly). Closed structurally: `_lib.sh` gains `shctx_apply_pending_migrations` (the gap-fill loop, now the single source shared with `cmd_migrate.sh`) + `shctx_ensure_migrated` (a cheap behind-check that auto-applies when the schema lags — concurrency-tolerant, fail-soft). `init` now migrates to HEAD (the source of the drift); `teammate`/`panes` call `ensure_migrated` before any `declared_state` read and degrade to a timing-only verdict when healing is impossible (read-only/locked DB, mirroring `coordinate_drive_guard.sh`); `doctor`'s pending-migration check is now GAP-aware. Tests: new `test_schema_self_heal.sh` (behind DB heals + degrades), extended `test_migrate.sh`. Context suite 48/48.

### New — automatic teammate liveness (#193)

- **`hooks/scripts/teammate_heartbeat.sh` — PreToolUse auto-stamp.** Non-conductor teammates (the self-contained `@engineer`) never called `shctx teammate heartbeat`, so `last_seen_at` froze at `spawned_at` and liveness read `presumed-crashed` while the teammate ran a multi-minute fan-out. The 0019 `declared_state` read-verdict was a half-fix — it needs a MANUAL declaration. Now every tool call stamps `last_seen_at` for the current teammate (booting→active): liveness is trustworthy for every role for free, no self-report, and a new role can't forget it. Observational (never blocks a tool), fail-open, `[hooks].teammate_heartbeat = on|off`. Test: `test_teammate_heartbeat.sh` (7 cases). Hook suite 65/65.

### New — the packaged `shepherd` CLI begins (#198)

- **`services/cli/` — Python + Poetry (Tortoise ORM / Pydantic / Typer).** A typed, session/pid-scoped data-access layer over the registry — the clean home for the scoping the bash scripts re-patch at every call site. First group ported: `teammate liveness/status/state`. Liveness is SCOPED-by-construction to the active session's team, excluding prior-session ghosts — the #195 fix, demonstrated. Tortoise models MIRROR the canonical SQL schema (coexistence: SQL migrations stay authoritative, never `generate_schemas`); the CLI self-heals the schema like #200. Un-ported subcommands shim to bash `shctx`, so `shepherd` is a working superset on day one. Deterministic feature → 30 pytest gate tests (incl. a real bash-vs-Python verdict-parity gate) are the proof; no LLM eval. Bash `shctx` is unchanged. Later increments migrate the surface group-by-group and rename the entrypoint.

### Changed

- **Task list demoted to a best-effort mirror; the registry is authoritative for wave-gating.** The harness Task list fails often enough that wave progression must not depend on it. Doctrine (`skills/shepherd/references/pipeline.md`, `agents/{conductor,shepherd}.md`, `skills/harness/SKILL.md`): the registry (`shctx graph`/focus) is the system of record for lane/wave state; a `Task*` failure degrades to the registry and NEVER blocks progression.
- **Team leads spawn at `ultracode` (#198 direction).** `[spawn].lead_effort` (default `ultracode`) is injected into `@engineer`/`@conductor` boot briefs, so the effort level itself makes Dynamic-Workflow fan-out the default — no brief-context spent nagging for it. `conductor` frontmatter `thinking: high → max`. The blanket "sprints MUST NOT run under `/effort ultracode`" in `workflow-templates.md` is reconciled: leads run ultracode for per-segment fan-out, but orchestration SHAPE stays the critic-gated graph's, and a whole sprint compiled into one workflow is still forbidden regardless of effort.

### Removed — the toolkit feature

- **Dropped the `toolkit` registry wholesale** (forgotten, net-negative surface, per operator directive): `cmd_toolkit.sh`, `commands/toolkit.md`, `hooks/scripts/toolkit_surface.sh`, `hooks/scripts/capability_discovery.sh` (its only consumer), the three `[TOOLKIT]` inject blocks in `cmd_inject.sh`, `references/toolkit.{md,schema.json}`, the `[discovery].auto_capabilities` toggle, and every doctrine / doc / config reference. `shctx toolkit` and `/shepherd:toolkit` are gone; tests `test_toolkit.sh` / `test_toolkit_surface.sh` / `test_capability_discovery.sh` removed. Net-negative LOC.

## v6.3.2 — 2026-07-14

**Cleanup + bug-hunt pass, and an explicit teammate `declared_state` that ends the false-positive liveness cancellations the axiom run kept surfacing.**

### Fixed

- **`close_finalize_check.sh` re-blocked every turn-end forever when a merge was deferred (#154).** The Stop hook fires `decision:block` whenever a sprint's close report is committed but the dev branch is still on origin — but when the dev→patch merge is DELIBERATELY deferred (operator-gated), both signals stay positive indefinitely, so it re-blocked on every turn-end (field: every ~15-30s for hours, an unbreakable loop). Added two fail-open escapes: an explicit `[close].finalize_hold = "true"` operator hold, and a runaway bound per `(session, slug, HEAD-sha)` that fails open after 2 nudges on the same committed state (mirrors `coordinate_drive_guard.sh`'s #114 idiom) — a new commit changes HEAD, so a genuine new close report still re-warns once. Tests: `test_close_finalize_check.sh` 15/15.
- **Root now git-verifies a `WAVE-COMPLETE` claim before releasing the gate (#152).** A lane conductor could send `WAVE-COMPLETE — self-gate GREEN` while its branch and worktree HEAD were both still at the base commit (zero commits, zero diff) and root accepted it on the field-only contract. `agents/shepherd.md` §WAVE-COMPLETE contract now treats the payload as a request to VERIFY: root runs `git -C <lane-worktree> log <BASE-COMMIT-EXPECTED>..HEAD` and refuses the wave with the new `WAVE-COMPLETE-UNVERIFIED` halt code (registered in `escalation.md`) on an empty result. Pinned by `test_flock_output_review.sh`.
- **`0017_focus_lane.sql` broke every fresh install.** The migration dropped `focus` and renamed `focus_new → focus` while the `v_focus_current` view (from `0013`) still referenced the old table; on SQLite ≥ 3.25.0 `ALTER TABLE … RENAME` re-parses every view, so the rename aborted with `error in view v_focus_current: no such table: main.focus`. Under `cmd_migrate.sh`'s `set -e` the whole migrate aborted at `0017`, so a fresh `shctx init && migrate` landed half-migrated (`focus` stuck as `focus_new`, `0018` never applied) — which in turn failed `test_dups_write_guard.sh` and `test_session_adaptation.sh`. Reordered to drop the dependent view before the rebuild and recreate it after the rename, matching `0016_mailbox_kind_relax.sql`; existing v17 DBs are untouched (migrations are version-gated). Hook suite 61/63 → 63/63.

### New — explicit teammate `declared_state` (#193 / #194 / #195 / #98 / #197)

- **`teammates.declared_state` (migration `0019`).** One column a teammate (or its lead) declares from a fixed enum — `init | in-progress | error | complete | idle` — that wins over the `last_seen_at` timing heuristic. The `status` column conflated lifecycle with a `presumed-crashed` verdict no writer ever set, and it false-positives now that #93 retired the per-tool heartbeat: a healthy teammate crosses the 5-min stale window and reads crashed while actively running. `NULL` = undeclared → exact pre-`0019` behavior (backward compatible; `v_teammates_live` is `SELECT t.*` so it surfaces the column with no view edit).
- **`shctx teammate state <name> [--set=<s>]`** declares/reads it; **`shctx teammate heartbeat --state=<s>`** stamps `last_seen_at` and declares in one call. Both validate the enum (`TEAMMATE-STATE-INVALID`).
- **`liveness` / `panes` verdict** respects the declaration: `in-progress` is never `presumed-crashed` regardless of the gap (#193); `error` surfaces as the escalation signal the stalled conductor never sent (#98); `complete` is terminal; `idle` explicit; `init` is a transient boot marker that still falls through to timing (a stale boot stays a crash candidate).
- **`shctx teammate prune --crashed` (#194)** matches that DERIVED verdict — an undeclared/`init` row still `booting`/`active` past the stale window — instead of the `status='crashed'` literal no writer sets (so it used to prune 0). Adds `--stale-mins`.
- **`coordinate_drive_guard.sh` is now root-only (#197).** It exits early on any session that is itself a registered teammate (mirroring `teammate_git_guard.sh`'s `session_id` detection), so a self-contained `@engineer` is never trapped running root's "drain the work first" loop and silently degrading its plan. Its live/idle counts also drop `complete` teammates and undeclared stale ghosts (#195), so prior-session rows stop inflating the count and false-blocking a legitimate root halt.
- Wiring: `commands/spawn.md` (declare at register / `LANE-COMPLETE` / HALT), `agents/conductor.md` §Orient, `agents/engineer.md` step (7). Tests: `skills/context/tests/test_cmd_teammate.sh` + `hooks/tests/test_coordinate_drive_guard.sh` extended. Hook suite 63/63, context suite 48/48.

### Housekeeping

- **Issue-ledger cleanup.** Triaged every open non-feature issue against the tree and closed 21 that were already resolved in shipped releases but never closed (#61, #86, #88, #98, #100, #102, #108, #111, #113, #120, #123, #157, #169, #172, #180, #183, #184, #185, #186, #187, #192), each with a cited close comment. #59, #110, #112 stay open as genuine features (each needs a net-new enforcement subsystem).
- **Filed #198** — tracking issue for a next-sprint Python + Poetry CLI with direct session/pid-scoped DB access, and the `shctx` → `shepherd` rename. Buildout deliberately deferred.

## v6.3.1 — 2026-07-08

**Conductor owns git directly — retire the @worker-for-two-git-commands waste (operator follow-up to #187).**

### Changed

- **`conductor_write_guard.sh` — git carve-back.** The v6.2.7 "conductor read+dispatch only" model routed EVERY git-write through `@worker`, so the conductor spawned a worker just to run a routine commit — wasteful. Coders/workers own no git (#187), so the conductor now commits its lane's coder output DIRECTLY (`git -C <worktree>`); `@worker` is reserved for a BULK git batch only. The guard's deny-list drops `GIT_WRITE_PATTERN`/`GIT_WORKTREE_WRITE_PATTERN` — it still blocks artifact Edit/Write, non-git FS mutation (`rm`/`mv`/`sed -i`/redirect), and mutating `shctx` state verbs (`CONDUCTOR-WRITE-DENIED`). Cross-lane INTEGRATION onto the dev branch stays root-exclusive for a teammate-conductor via `teammate_git_guard.sh` (unchanged); root/solo has full git.
- **`agents/conductor.md`** updated to match (header, §Lane walk seam + commit-custody, §Hard prohibitions #1/#3/#8, §Halt codes, divergence table): commits are the conductor's, direct; the retired `CONDUCTOR-GIT-WRITE-DENIED` code is folded into `CONDUCTOR-WRITE-DENIED`. `test_conductor_write_guard.sh` flips the git cases to PASS and pins FS/`shctx` under `CONDUCTOR-WRITE-DENIED`. Full hook suite 63/63.

## v6.3.0 — 2026-07-08

**Field-hardening sprint from the axiom dev.8 run: the flock substrate now enforces its own contracts instead of trusting prose (#181, #183–#187).**

### New — `hooks/scripts/coder_git_guard.sh` (#187)

- **`PreToolUse(Bash)` @coder git-write guard.** Git custody is never the coder's: coders write files under `[WORKTREE].Path`, list them in the CODER REPORT, and the conductor stages+commits that output only after the wave-review returns PASS. The deeper reason coders own no git — a `REDO` verdict re-runs the named coder over the SAME files, so keeping output uncommitted means nothing to unwind (field incident: coders self-committed twice in axiom dev.8; pathspec-less commits in a SHARED lane worktree swept siblings' uncommitted files). Deny-by-default: every git subcommand except a read-only allowlist (`status`/`diff`/`log`/`show`/`rev-parse`/…) is blocked. python3 `shlex` extracts the effective subcommand past git global options (`git -C x commit` → `commit`); a write-verb deny-list is the fallback when python3 is absent. Halt code `CODER-GIT-WRITE`. Doctrine updated across `agents/coder.md` (Step 5 → no-git hand-off), `skills/shepherd/references/flock.md` §@coder/§Write boundaries/§Mandatory verification, `agents/conductor.md` §Lane walk (PASS-gated commit custody), `escalation.md`. Tests: `test_coder_git_guard.sh` (20 cases).

### Fixed

- **Teammate registration + TeammateIdle routing (#183).** Named-Agent teammates were never mechanically registered (prose-only step, no auto-register hook, and the CONDUCTOR-ONLY gate refused the self-contained `@engineer` teammate), so the `teammates` table stayed empty — `shctx teammate liveness` returned nothing and every `TeammateIdle` fired unmatched, flooding the lead with noise that masked real stalls. `cmd_teammate.sh` register now accepts conductor + engineer and is an idempotent upsert on `(project_id, team_name, teammate_name)`; `commands/spawn.md` wires root-side registration into the spawn path before the liveness poll; `teammate_idle.sh` matches by name across identity fields and suppresses the "no row matched" warning when no spawn is live. Tests: `test_teammate_idle.sh` (7), updated `test_cmd_teammate_conductor_only.sh`.
- **Conductor boot hard-halt on brief SHAPE (#184).** A `BOOT-FORMAT: lead-attested` marker (placed by the lead beside `ROOT-SESSION-NAME`) relaxes the boot checks from header-shape to a SUBSTANCE check of the required facts, so a lead-authored non-canonical brief carrying every fact no longer raises `TEAMMATE-BOOT-MALFORMED`. The `dispatcher` check is never relaxed; unmarked briefs keep the strict shape check. `agents/conductor.md` §Boot verification, `commands/spawn.md`, `escalation.md`.
- **@worker GH-write contract (#185).** Added `add_issue_comment` to `agents/worker.md` (`issue_write` already covered close/update/milestone/label). The MCP-over-CLI doctrine (`worker.md`, `skills/shepherd/SKILL.md` §Principles) now conditions the MCP preference on MCP availability and sanctions the `gh`/`psql` CLI as the explicit write fallback when the MCP is unloaded/`[mcp].<svc>=false`/absent from `[TOOLKIT]` — the axiom dev.8 W0 incident (whole-plugin absence) is no longer a contract violation.
- **@engineer `SendMessage` grant (#186).** The self-contained engineer flow alerts root via `SendMessage`, but the frontmatter omitted the grant, so the PLAN-READY alert raced/failed. Declared `SendMessage` in `agents/engineer.md`; generalized `lint_agent_capabilities.sh`'s tool-claim consistency check (was AskUserQuestion-only) to catch any coordination tool claimed-but-ungranted.
- **Compile-down model pins (#180, folded into #181).** `shctx graph compile` emitted spawns as one object passed positionally to `agent(s)` — the wrong Workflow signature AND unpinned, so a compiled `*.workflow.js` silently inherited the main-loop model (#178 one level removed). `cmd_graph.sh` now emits `agent(prompt, opts)` with `opts.agentType` + `[models]`-resolved `opts.model`; the `--verify` faithfulness diff gains a **model_pin** invariant. `workflow-templates.md` §Compile-down invariant (4). Tests: extended `test_graph_compile.sh`.

### Explored (decided)

- **#181 — template/DSL for dispatch call-sites.** With #180 shipped and the #178 `PreToolUse(Workflow)` guard live, both dispatch classes (graph-derived fanout by construction; hand-authored Workflow by interception) are covered. Decision: do NOT build a broad DSL now; escalate to a skeleton emitter only if the guard's deny-rate climbs. `docs/specs/v630-dispatch-pin-dsl-decision.md`.

### Review hardening (adversarial pass)

A 5-lens adversarial review (20 sonnet agents, verify-each-finding) surfaced defects fixed before landing:

- **`current_role` worktree resolution (`hooks/scripts/_lib.sh`).** The dispatch-record lookup was cwd/branch-relative, so a @coder reading it from INSIDE its own linked worktree (a different toplevel AND branch) missed the record and fell back to role=conductor — making `coder_git_guard.sh` a silent no-op in the coder's normal environment (and affecting every role-scoped guard). Now resolved via `--git-common-dir` (the shared `.git` even from a linked worktree) + a `tool_use_id` glob across sprint dirs (branch-independent). Reproduced + pinned by a real cross-worktree test case.
- **`coder_git_guard.sh` bypasses.** A git write hidden in `bash -c "…"`/`eval`/`sh -c` (opaque to the tokenizer) or glued to a decoy read slipped through; `git read-tree`/`reflog expire` and other plumbing verbs were absent from the fallback. The tokenizer now recurses into shell wrappers, a comprehensive raw write-scan ALWAYS runs as a second independent layer, and glued metacharacters are stripped. New regression cases cover each.
- **`bash_guard.sh` Check 0-bis** now also matches the renamed `agentType:` key when detecting a compiled workflow that illegally spawns a teammate-conductor.
- **Compiler emission** switched to `() => agent(prompt, { agentType, model, label })` thunks with a LITERAL opts at each call site, so a compiled segment is statically `workflow_model_guard.sh`-clean.

### Tests

- New `hooks/tests/test_v630_wiring.sh` (doctrine-wiring guard across all six issues) + `test_coder_git_guard.sh` (31 cases, incl. cross-worktree + shell-nesting bypasses) + `test_teammate_idle.sh`, all wired into `hooks/tests/run.sh`. Full hook suite 63/63.

## v6.2.9 — 2026-07-07

**Closes the one dispatch primitive the model map didn't reach: hand-authored Dynamic Workflows (#178).**

### New — `hooks/scripts/workflow_model_guard.sh`, `hooks/scripts/workflow_model_lint.py`

- **`PreToolUse(Workflow)` dispatch-model-pin guard.** Every OTHER dispatch primitive resolves its
  model from the single `[models]` map (`skills/context/references/model-map.md`) — Agent/Task via
  `dispatch_guard.sh`, teammate spawns via `commands/spawn.md §Model pin` — but a raw Workflow-tool
  `agent()` call bypassed it silently: the Workflow tool's own documented default is to omit
  `model:` and inherit the MAIN-LOOP model, exactly the opposite of shepherd's operator law (every
  dispatched subagent = sonnet unless explicitly overridden). Field incident (2026-07-07): a
  Fable-5 planter session dispatched a Workflow whose `agent()` calls omitted model/agentType;
  every deep-audit subagent ran on Fable at xhigh effort until the operator caught it mid-run.
- **Best-effort JS-lite static scan** (`workflow_model_lint.py`), not a JS parser: masks every
  string/template literal and comment to same-length blanks before scanning, so a prompt that
  merely *mentions* `"model:"` in prose — or a JSON schema field happening to be named `model` —
  can never fake a pass. Flags three shapes the same way: a bare `agent(prompt)` with no opts
  argument, an opts object literal missing both keys at its top level, and a non-literal opts
  expression (a variable/spread) that can't be verified statically. Scans `tool_input.script`
  inline or reads `tool_input.scriptPath` from disk; a saved/named workflow with no visible script
  text, or an unreadable path, fails OPEN (logged, never silently treated as clean).
- **Operator override**: a `// shepherd:model-pin-override` line comment anywhere in the submitted
  script acknowledges unpinned dispatch for that one call — the same brief-marker idiom
  `dispatch_guard.sh` already uses (`mode: self-contained`, `dispatcher: engineer-self-contained`).
  Always surfaced via `additionalContext` and logged, never a silent bypass.
- **Config**: `[hooks].workflow_model_guard = block` (default) `| warn | off`, mirroring the
  `[release].devlast_guard` / `[spawn].coordinate_drive_guard` convention. Halt code
  `WORKFLOW-MODEL-PIN-MISSING`.

### Docs

- `docs/configuration.md §[hooks]`: new `workflow_model_guard` row + explanatory paragraph; also
  backfilled the pre-existing but undocumented `flag_handrolled_fanout` key.
- `README.md`: `workflow_model_guard.sh` added to the mechanical-enforcement-hooks list and the
  Models section under "Under the hood".

### Tests

- `hooks/tests/test_workflow_model_guard.sh` (new, 17 cases): bare/non-compliant calls blocked;
  `model:`/`agentType:` pins pass; string-content-blind against both a prose mention and a nested
  schema field named `model`; a non-literal opts expression is flagged, not given the benefit of
  the doubt; multi-call scripts name only the actual violator; the `subagent(` word-boundary is
  respected; the override marker, `scriptPath`, `warn`/`off` modes, and the no-visible-script
  fail-open path are each covered.
- `hooks/tests/run.sh`: 4 new fast-path smoke cases + the dedicated suite wired in. Full suite:
  60/60.

---

## v6.2.8 — 2026-07-07

**The refinement sweep — the plugin-wide compaction v6.2.7 deferred, plus modular skills.** Prompt surface cut 73%: 202,192 → 54,725 words (~263k → ~71k est. tokens) across 122 → 51 load-bearing files, with zero behavior change outside four named removals. The 71-doctrine directory is dissolved; every load-bearing rule now lives in exactly one narrow skill, loaded per-dispatch instead of per-plugin.

### New — modular skills (6, was 3)

- **`skills/adaptation`** — the self-improvement loop every flock agent runs: harvest→store→inject→cite, decay-6, `prior:<mem_id>`, the canonical `## INSIGHTS` taxonomy, the excellence bar.
- **`skills/motivation`** — focus record + FOCUS-HEARTBEAT (two-legs distinction preserved verbatim), native `/goal` templates (operator-armed; lead-session-only), `/loop` discipline + caps, drive contract, SOAK, the AUTONOMOUS-SENTINEL triple-gate (canonical, all 7 SENTINEL-* codes).
- **`skills/harness`** — the Claude Code capability map: Agent Teams limits, Workflow tool, `/loop` modes, `/goal` semantics, ToolSearch scope rule, tool-presence truth, lazy-load economics, capability-enforcement pattern; references for workflow + loop templates (the 9×-repeated loop skeleton now stated once). Links to live docs for deterministic freshness.
- **`skills/thinking`** — operator-authored problem-decomposition protocol (body untouched; description made trigger-specific).
- `skills/shepherd` rebuilt as contract (≤10k-char SKILL.md) + 9 references (pipeline, flock, escalation, spawn-flags, operating-philosophy, invariant-matrix, seed-template, branching-model, grading-rubric). `skills/context` slimmed; gains `references/toolkit.md` + `references/model-map.md`.

### Changed — engineer is a team lead; discovery specializes

- **Self-contained `@engineer` is the INTRO default**: root spawns the engineer as a named teammate and dispatches NO discovery/orientation wave of its own (`ROOT-INTRO-USURPED`). The engineer's fixed loop: discovery wave (MINIMUM 5 — 2 `@discovery` + 3 intro-`@auditor`, scaled upward at his discretion) → draft plan → `@critic` → update → repeat until GREEN → ONE finalized plan → alert root → rest.
- **`@discovery` specializes in external information** (documentation, web research, release notes, MCP state) compiled into research reports; codebase orientation inside a combo wave belongs to intro-`@auditor` lanes.
- Every agent profile now ends in a skill-load list — a dispatch loads its slice, never the whole plugin.
- New principle in the shepherd contract: **DURABLE ARTIFACT** — every top-tier dispatch terminates in exactly one durable artifact.

### Removed (operator-directed)

- **`/shepherd:start` + solo-conductor mode.** The teammate boot (T0 checks) folds into `agents/conductor.md §Boot verification`; the spawn boot prompt references the profile directly — no command indirection. Conductor is TEAMMATE-only; `MODE-MISUSE`/`MODE-DETECTION-AMBIGUOUS` retired; `TEAMMATE-FLAG-MISUSED` renamed `TEAMMATE-BOOT-MISSING`.
- **shctx `escalate`, `watch`, `profile`** (44 → 41 subcommands; `profile` merged into the maintained `[models]` table system; `teammate_idle.sh` + `conductor_write_guard.sh` updated in the same commit). `handoff` STAYS — it is a gated stage of `sprint close`.
- `doctrines/_candidates/` promotion template; unwired `[focus].loop_default`/`loop_max_default` doc keys.

### Refined — staged handoff (`--staged`)

Planter finalizes seed → `shctx seed verify` green → mailbox `seed-ready` to `shepherd-spawn-<slug>` → SEED-READY banner → rest. Shepherd session arms a delayed start: `shctx mailbox recv` polled via ScheduleWakeup ≤270s, explicit `shctx mailbox ack`, timeout `[spawn].staged_timeout_minutes` (default 90) → `STAGED-TIMEOUT`. No new schema.

### Tooling + tests

- `scripts/xref.py` (new): cross-reference map + dangling-ref gate; `scripts/filetree.sh` taught the modular layout (it was silently excluding new skills from the word-count gate).
- 43 scripted doctrine-path retargets across hooks/tests (suffix-aware anchor mapping); wiring tests re-anchored with a stale-citation lint replacing the dead doctrine-resolution loops.
- Suites: hooks 55/55, ctx 48/48, llm 2/2, eval 3/3. Determinism lint (hedge-word ban over load-bearing lines): 0 hits. Dangling refs: 0 (1 intentional negative-test exemption).
- Method: 25-reader behavior inventory → 61-entry guard-string registry (the rewrite contract) → 3-lens design critique → 5 worktree lanes with per-file adversarial fidelity verifiers (REDO cap 3) → merge train → scripted hook/test retarget → seam review.

---

## v6.2.7 — 2026-07-02

**The conductor is read + dispatch only, mechanically — plus the field incident that proved why prose isn't enough.** During this cycle a live spawn session dispatched `@critic` as a native teammate twice, then `@coder` once, despite the profile prose forbidding both. Root cause: the platform's native teammate-spawn is a natural-language instruction, not a tool call — `dispatch_guard.sh`'s `PreToolUse(Agent|Task)` hook structurally cannot see it. This release closes that gap with two deterministic gates instead of more prose, and uses the same lever to retire the conductor's remaining direct write/git-write authority.

### New — `hooks/scripts/conductor_write_guard.sh` (#180)

- **`PreToolUse(Edit|Write|Bash)`.** The conductor no longer carries `Edit`/`Write` in its tool grant, in EITHER mode — no `.md`-only carve-out remains. This hook is the mechanical backstop: it denies any `Edit`/`Write` call and any Bash command with git-write semantics (`commit`/`push`/`merge`/`rebase`/`cherry-pick`/`worktree add|remove|prune`/`branch -d`/`checkout -b`/`tag`/`reset`), filesystem mutation (`rm`/`mv`/`sed -i`/shell redirection into a file), or a mutating `shctx` subcommand (`seed`, `close-lane`, `adapt roll|reflect`, `loop init|record|close|focus upsert`, `mem add|pin|unpin|rm`, `lock acquire|release`, `worktree create-batch|merge|gc`, `config init|claude-md`, `migrate`, `release`, `prune --confirm`, …) — whenever the call is the conductor's own turn (`current_role` resolves `conductor` — i.e. not a tagged `@coder`/`@auditor`/`@worker`/`@discovery`/`@engineer`/`@critic` dispatch) AND a sprint is actually open (sprint-branch shape, or a registered non-retired teammate row). Read-only Bash (`git log/status/diff/show/branch/worktree list`, `gh` reads, `shctx query/search/status/doctor/dash/inject/toolkit/models show/refresh/lint/seed verify/plan verify/graph compile --verify`) passes through unmatched.
- **Every write becomes a `@worker` dispatch.** Plan/report/handoff/ledger/CLAUDE.md materialization, gate commits, worktree lifecycle, and rebase-merges are now composed by the conductor (exact content or exact command sequence — that's where the judgment lives) and handed to `@worker` as a deterministic brief. The conductor's ONE remaining direct external mutation is `mcp__plugin_github_github__issue_write` — opening/closing carry-forward and drift-risk GitHub issues, nothing else.
- New halt codes `CONDUCTOR-WRITE-DENIED` / `CONDUCTOR-GIT-WRITE-DENIED` (both modes), generalizing the pre-6.2.7 `TEAMMATE-GIT-WRITE`/`TEAMMATE-ARTIFACT-WRITE` contract to SOLO mode too.
- `agents/conductor.md`: tools grant trimmed (no `Edit`/`Write`/`execute_sql`; `issue_write` added), Hard prohibition #1 rewritten, SOLO- and TEAMMATE-mode side-effect boundary tables updated to name `@worker` as the vehicle for every write.

### New — `shctx teammate register` refuses non-conductor teammates (#180)

- **The real fix for the critic/coder-as-teammate incident.** `skills/context/scripts/cmd_teammate.sh`'s `register` subcommand now hard-refuses any `--type` other than `conductor`/`shepherd:conductor` (case-insensitive) — exit 1, no row inserted, loud `CONDUCTOR-ONLY-TEAMMATE` error naming the doctrine. This is the one deterministic choke point every teammate passes through regardless of how the native-teammate-spawn instruction is worded, which is why it catches what `dispatch_guard.sh` structurally cannot.

### Hardened — `hooks/tests/lint_agent_capabilities.sh`

- Conductor now has its own dedicated lint block (it isn't in `READONLY_ROLES` — it keeps `Agent`+`Bash` for dispatch and read-only inspection): asserts no `Edit`/`Write`/`NotebookEdit`/`MultiEdit` grant, and that `conductor_write_guard.sh` is registered in `hooks.json`.

### Research — `docs/specs/workspace-symbol-graph-research.md`

- A design/research doc surveying workspace-object-relationship tracking (VS Code's workspace-symbol provider, LSP servers, tree-sitter/ast-grep, SCIP, stack-graphs, Glean, Kythe, CodeQL, Neo4j/Kùzu/DuckDB) for a future "object management system" that extends `shctx`'s existing symbol index with a relationship graph. Recommendation: reject the heavyweight server-coupled systems (Glean/Kythe) as a near-term default; extend the existing SQLite `index_symbols` schema with an `index_edges` table (recursive-CTE graph queries) as Phase 1, tree-sitter-based multi-language extraction as Phase 2, and revisit SCIP/embedded-graph-DB adoption only if 1/2 prove insufficient by measurement. Concrete schema + example queries included. Not implemented this cycle — long-term direction only, per the operator's framing.

### Fixed — the CLOSE-FINALIZE procedure still told the conductor to run the git writes the new guard blocks

- A first cut of this release added `conductor_write_guard.sh` and the tool-grant change but left `agents/conductor.md`'s own CLOSE-FINALIZE steps (rebase-merge, branch delete, next-branch cut, release pipeline, worktree teardown), the WAVE-GATE bullet, the intro paragraph, Hard prohibition #2, the mode-comparison table, and the Stage-Graph walk-algorithm's "conductor-inline" seam description all still narrating the conductor running `git commit`/`checkout`/`push`/`branch -d`/`worktree remove` **directly** — exactly what the new hook now denies. Every one of those is rewritten to dispatch `@worker` with the exact command sequence instead.
- `conductor_write_guard.sh`'s deny-list had the same gap in the mechanism itself: it caught `checkout -b` (branch creation) but not a bare `git checkout <branch>` / `git switch <branch>` — the precise HEAD-drift move `doctrines/conductor-cwd.md` Bans 2–3 already name as forbidden. Both are now denied (`git branch <name>` with no delete flag, and read verbs, remain unaffected).
- Net: `agents/conductor.md` is 785 lines (was 837 pre-cycle, 791 after the first cut) — real prose compaction in the sections directly touched by this change (intro, several Hard Prohibitions, the Lane-per-conductor rationale, CLOSE-FINALIZE), not a plugin-wide pass. A full compaction sweep across all nine `agents/*.md` files and `skills/shepherd/doctrines/*.md` (the actual 5-9%-of-context concern) is still a separate, dedicated piece of work — this fix only guarantees the file this cycle touches doesn't contradict itself.

### Tests

- `hooks/tests/test_conductor_write_guard.sh` (new, 16 cases) + 3 smoke `run_case` entries in `hooks/tests/run.sh`.
- `skills/context/tests/test_cmd_teammate_conductor_only.sh` (new, 6 cases) — pins the `CONDUCTOR-ONLY-TEAMMATE` refusal for `critic`/`engineer`/`coder` and acceptance of `conductor`/`shepherd:conductor`/`Conductor`.
- `hooks/tests/lint_agent_capabilities.sh` extended with the conductor-specific block.
- `test_conductor_write_guard.sh` extended to 19 cases (checkout/switch denial + `git branch --show-current` read-only pass-through).
- Full suites verified against this branch: hooks 53/55 (2 pre-existing environment failures, confirmed present on the pre-patch baseline too — an sqlite view bootstrap issue unrelated to this change), context 31/50 (30/50 pre-existing baseline; +1 from the new teammate-gate test). No regressions introduced.

---

## v6.2.6 — 2026-07-02

**Clarify the self-contained engineer: a flock leader with a read-only sub-flock, spawned as a named teammate.** v6.2.5 introduced the self-contained engineer but left the topology ambiguous — an engineer dispatched as a bare subagent read its own "self-contained" prose and self-activated a discovery fan-out it was never spawned to lead, replacing the discovery *dynamic workflow* with a static fan-out and (worse) initializing a phantom unnamed engineer. This release makes the role unambiguous. It is behavioral/wiring only — no new machinery.

### Changed — the engineer is a flock leader that runs its own read-only waves (`doctrines/engineer-self-contained-plan.md`, #172)

- **The sub-flock is the three read-only / adversarial roles ONLY** — `@discovery`, intro-mode `@auditor`, and its own `@critic`. These are the *exact* waves root used to run on the engineer's behalf (the INTRO-COMBO-WAVE + the post-plan critic). In self-contained mode the engineer runs them **in its own window**, so root runs **neither** its own INTRO-COMBO-WAVE **nor** `@critic` — the same workflow, **compartmentalized**, sparing the majority of the context root used to incur. No `@coder`/`@worker`; **no code is touched**; the only artifacts are the plan + its reports.
- **Real `@critic`, not an embedded pass.** The engineer now dispatches an actual `@critic` agent against its own plan (brief tagged `[INVOCATION-CONTEXT].dispatcher: engineer-self-contained`) and revises ≥1 — the adversarial-agent gate every flock leader runs on its own output — then emits the hash-tied critic-proof unchanged. (Embedded rubric kept only as a platform fallback.)
- **Discovery is the scaled dynamic wave, not a fixed fan-out.** The engineer's `@discovery` + intro-`@auditor` batch is bounded, scope-partitioned, and T-shirt-scaled — the planter's `§Step 2-bis` leader-runs-its-own-wave pattern — never a hard-coded "always 5."
- **Hard mode determination.** Self-contained activates only when `mode: self-contained` **and** `dispatcher: root-shepherd` **and** genuinely running as a teammate. Any ambiguity → classic (consume root's waves, dispatch nothing). Ambiguity never self-activates.

### Fixed — deterministic spawn topology + mechanical guards (`hooks/scripts/dispatch_guard.sh`)

- **`ENGINEER-TOPOLOGY-MISMATCH` (new).** An Agent/Task dispatch of `@engineer` whose brief carries `mode: self-contained` is refused — a self-contained engineer must be a **named teammate-spawn**, never a subagent. This is the mechanical fix for the "unnamed subagent engineer" failure. Classic engineer dispatch (no mode marker) is unaffected.
- **`WRONG-TIER-DISPATCH` (tightened).** A teammate dispatching `@engineer` is now refused **unconditionally** (no nested/phantom engineer). A teammate dispatching `@critic` is refused **unless** the brief carries `dispatcher: engineer-self-contained` — so the engineer teammate gates its own plan, but a conductor lane still cannot re-gate a fixed one.
- **`ENGINEER-SUBFLOCK-VIOLATION` (new).** The engineer tags every sub-flock dispatch `dispatcher: engineer-self-contained`; a marked dispatch to anything outside the read-only trio (`@coder`/`@worker`/nested `@engineer`) is refused. This gives "no code is touched during this phase" the same mechanical teeth as the topology check, not prose alone.
- The marker match is anchored to a real field assignment (line-start, optional `[INVOCATION-CONTEXT].` prefix or block indent), so a classic brief that merely mentions the phrase in prose is not misread, while both the dotted and block marker forms are caught.
- The engineer's `Agent` grant scope pin (`lint_agent_capabilities.sh`, #172) now covers `{shepherd:discovery, shepherd:auditor, shepherd:critic}` — the read-only sub-flock — so a future broadening to a write role cannot land silently.

### Tests

- `test_dispatch_guard.sh` +6 cases (topology mismatch, nested engineer, marker-scoped critic self-gate vs conductor re-gate, intro-audit wave). `test_engineer_self_contained.sh` extended to pin the clarified contract. `lint_agent_capabilities.sh` updated for the trio scope. **51/51 hooks + 49/49 ctx.**

---

## v6.2.5 — 2026-07-01

**Config-driven model map, a self-contained engineer with an irrefutable critic-proof, and an outcome-safe workdir prune.** Three lean additions, all behavioral / config / CLI wiring — no heavy architecture. At ultra-parallel scale for long durations, hand-pinning a model on every spawn is a class of error; a plan handed to root only to be re-critiqued is wasted context; and a long-lived workdir accretes state nobody ever sweeps. This release removes all three.

### New — the `[models]` map (`doctrines/model-map.md`, #170)

- **One table maps every role to its model.** `.claude/shepherd.toml [models]` sets the model each flock/meta role dispatches with. Every dispatching tier (root, conductor, engineer) resolves it with **`shctx models resolve <role>`** and injects the result as the Agent `model:` pin — generalizing the v6.0.9 conductor pin into a single source. `shctx models show` (`--md`/`--json`) renders the resolved 9-role table + source per row and doubles as the spawn preflight.
- **Built-in defaults = the stated defaults.** `root`/`planter`/`engineer` = `opus[1m]`; `conductor`/`critic`/`discovery`/`coder`/`auditor`/`worker` = `sonnet`. A project with no `[models]` block behaves exactly as these defaults; set any role to any slug for total control.
- **root is advisory.** A config key cannot rebind a running main-chat session, so `[models].root` names the model the session *should* run — the preflight warns on mismatch (an under-powered root is the coordination-quality bottleneck for parallel spawns); the 8 spawned roles are the ones hard-driven.
- **Section-aware config read.** `cfg_section_get` (mirrored in both `_lib.sh` copies) resolves bare role keys *within* `[models]`, so they never collide with same-named keys elsewhere. The resolution chain leaves insertion points (profile/mode presets, root-tier-derived defaults) for a future release with zero rework to the map.

### New — self-contained engineer + the critic-proof (`doctrines/engineer-self-contained-plan.md`, #169)

- **Plan construction is re-emphasized as the whole point of the engineer:** seed + context → one multi-phase plan; each phase = N granular tasks/stages conditionally linked via the Stage Graph for near-automatic execution; the finished, critic-gated plan is then sliced vertically into independent lanes, each mapped to a team led by a conductor running coder/worker waves with auditor self-review.
- **Self-contained (teammate) mode.** Root MAY spawn `@engineer` as its own teammate. The engineer then runs an in-session `@discovery` wave (its `Agent` grant is scoped to `shepherd:discovery`, the same read-only bound the planter carries) plus an **embedded adversarial critic pass** — a teammate cannot dispatch `@critic` (`dispatch_guard.sh` Check 4 stays), so the critic *rubric* runs in-context — and **revises at least once**. Classic root-tier mode (discovery wave before + the distinct `@critic` after) remains the default, higher-independence path.
- **The critic-proof — irrefutable, not trust.** The engineer emits a hash-tied `<plan>.critic-proof.json` via **`shctx plan record-critique`** (pre/post plan hashes, `edited`, verdict, iterations). Root accepts the plan with a **thin mechanical gate** — `shctx seed verify` + **`shctx plan verify`** + lane-count sanity — and does NOT re-critique. `shctx plan verify` re-hashes the live plan, so a proof with `edited=false`, a stale hash, or no critique fails with a named code (`CRITIC-PROOF-MISSING` / `PLAN-UNEDITED` / `CRITIC-PROOF-STALE` / `PLAN-UNCRITIQUED`). Latent critique, deterministic proof.

### New — `shctx prune` workdir + registry GC (`doctrines/workdir-prune.md`, #171)

- **Outcome-safe by construction.** `--dry-run` is the default (prints the plan + a `/tmp` CSV, removes nothing); `--confirm` executes on-disk sweeps by **MOVING** targets into `/tmp/shepherd-prune-<epoch>/` — the snapshot IS the removal, `mv` back to restore. Eligibility is fenced on **all three**: sprint/branch ≠ current git branch, a terminal state, and age ≥ floor.
- **On-disk sweeps execute now:** stale `dispatch/<sprint>/` dirs, aged logs, over-retention precompact snapshots. **DB-row sweeps ship preview-only** (eligible counts printed, nothing deleted), enabled incrementally in a later patch — every DB `DELETE` is table-guarded (a workdir DB may lack later migrations). Never touches `index_releases`, current focus, `sprint_metrics`, pinned memory, or active locks/loops. Windows via `[prune]` (`logs_days`/`dispatch_days`/`snapshots_keep`/`findings_sprints`); `--vacuum` reclaims file space.
- **gitignore fix:** `.artifacts/memory/` + `.shepherd/memory/` are now ignored (precompact snapshots were leaking into `git status`).

### Tests

- New deterministic gate tests: `skills/context/tests/test_models_resolve.sh`, `test_plan_verify.sh`, `test_prune.sh`; hooks wiring guard `hooks/tests/test_engineer_self_contained.sh` (pins the doctrine ↔ profile ↔ CLI ↔ matrix citations for all three features + a dangling-citation check). The engineer's `Agent` grant is pinned to the `shepherd:discovery` scope by `lint_agent_capabilities.sh` (#119/#169). Suites: 49/49 context, 51/51 hooks, 2/2 llm, 3/3 eval. The three features are deterministic pure functions, so gate tests are the correct lane (no LLM-judged eval applies).

---

## v6.2.4 — 2026-06-30

**The flock-output review gate + the REDO loop (#167).** A conductor could forward a wave's
coder output to root on the coder's own "self-gate green" claim — pushing the verify-and-force-
redo burden UP to root, which became the de-facto reviewer of every diff and bloated the one
context that must stay clean over a whole sprint. The field case (#167): a coder told to surface
silent task panics instead reinvented a canonical helper, added a workspace-wide unstable build
flag for one call site, and never addressed panics — and it compiled green. This release makes
review a binding gate at both tiers and gives the redo a clean, named loop. Behavioral wiring
only — reuses the `@auditor`, the hot-fix vehicle ladder, Pattern B overlap, and the coder brief;
no new command, CLI verb, or state table.

### New — `doctrines/flock-output-review.md` (the binding contract)

- **FLOCK-OUTPUT REVIEW gate (conductor tier).** Before emitting `WAVE-COMPLETE`, a conductor
  MUST hold a `review_verdict: PASS` from a `@auditor` in the new **`wave-review` mode** — a
  read-only review of the wave's coder diffs against a fixed four-item checklist: (1) satisfies
  the linked issue's INTENT, not merely compiles; (2) no fragile global (global/unstable build
  flag or workspace-wide feature for one local call site); (3) no reinvention of a canonical
  helper/type under a new name (behavioral dedup); (4) no passes-local-breaks-CI pattern (env
  var overriding a config-file setting, feature-resolution divergence, stale-incremental false
  green). Delegating the diff-read keeps the conductor's context on the conclusion, not the diffs.
- **The REDO loop (both tiers).** A `REDO` verdict forces the **named** author to redo the
  **named** scope — never a blanket wave re-run. The REDO brief is the original coder brief plus a
  `[REDO]` block (`[PRIOR-DISPATCH]` + `[REDO-CONSTRAINT]`); the vehicle is the existing hot-fix
  cardinality ladder; the cap is ≤3 iterations, then `REDO-CAP-EXCEEDED` → HARD-STOP. REDO is the
  proactive sibling of HOTFIX (which fires reactively on a gate/audit finding); both share the
  vehicle and the cap.
- **Root tier — delegate the verdict, never repair the source.** At `LANE-INTEGRATE` root now
  delegates the diff-review to an `@auditor` that returns a verdict and keeps the conclusion, not
  the raw diffs; a `REDO` verdict issues a `REDO-DIRECTIVE` via `SendMessage` to the owning
  teammate-conductor (the existing "route the fix through the owning teammate, never a direct root
  fix" path). Root never edits a teammate's source.

### Mechanical teeth

- The `WAVE-COMPLETE` payload carries a required `review_verdict: PASS` + `reviewer`. A teammate
  `WAVE-COMPLETE` missing it is a `DISPATCH-CONTRACT-VIOLATION` — root refuses the wave (extends
  the existing "missing wave-gate evidence" clause). In SOLO mode the close `completeness` auditor
  verifies every wave recorded a PASS.
- New halt code `REDO-CAP-EXCEEDED` at both the conductor and root tiers.
- `doctrines/invariant-enforcement-matrix.md §V-bis` records the coverage (rows 16–18), honest
  about which legs are hard-blocks vs conductor self-checks.

### Wiring

- `agents/conductor.md` — FLOCK-OUTPUT REVIEW gate + REDO loop in the Step 2 BODY walk; the
  `REDO-CAP-EXCEEDED` halt code; a binding reminder and an anti-pattern.
- `agents/shepherd.md` — `LANE-INTEGRATE` flipped to delegate-first; `REDO-DIRECTIVE` + the
  review-evidence refusal in the escalation triage; `REDO-CAP-EXCEEDED`; a delegate-the-verdict
  anti-pattern; the doctrine added to the loaded set.
- `agents/auditor.md` — the `wave-review` mode, its four-item checklist, and the
  `## WAVE-REVIEW VERDICT` output block.
- `skills/shepherd/flock.md` + `skills/shepherd/references/agent-briefs.md` — the per-wave
  mandatory review in the dispatch reference; the `@coder` REDO-brief variant and the
  `@auditor` wave-review brief variant.
- `commands/start.md` + `commands/spawn.md` — the review step in the lane walk and the
  `review_verdict` + `reviewer` fields in the `WAVE-COMPLETE` payload.

### Tests

- `hooks/tests/test_flock_output_review.sh` (registered in `run.sh`) — a wiring guard that fails
  if any load-bearing leg (the doctrine, the four profile citations, the matrix row, the payload
  evidence) is dropped, and verifies every `doctrines/<x>.md` citation in the new doctrine
  resolves. Hooks suite **50/50** (was 49/49).

### Docs

- `README.md` — a new "Unreviewed handoff" failure-mode row, the Body-pipeline review gate, the
  doctrine added to the list. The command box's right border is now aligned (every row is the
  same width).

---

## v6.2.3 — 2026-06-29

**The eval harness, plus per-lane focus records.** Two threads. The headline is the **eval
harness** — the standing follow-up carried since v6.2.0: the plugin's latent agent
instructions finally have a behavioral eval, not just gate-tested storage. The second thread
completes the v6.2.2 FOCUS-HEARTBEAT.

### New — the eval harness (`services/llm` + `services/eval` + `shctx eval`)

The plugin preaches a latent/deterministic split; it now lives it against its **own** latent
outputs. `shctx eval` quality-scores a latent agent output (a conductor reflection, a
discovery report, a seed) against a rubric, judged by the **local Claude Code** — never a
hosted API (the project's standing LLM-access rule).

- **`services/llm`** — a self-contained LLM service that routes every model call through the
  local Claude Code in headless print mode (`claude -p`), with its own portable timeout
  watchdog (macOS ships no `timeout` binary), an `opus`-by-default model (best by default,
  never a silent downgrade for cost), and a mock seam (`SHEPHERD_LLM_MOCK`) that makes
  downstream gate tests deterministic and free. The single owner of the model call — nothing
  else invokes `claude` directly.
- **`services/eval`** — a pure, stateless judge: it builds a judge prompt from a rubric
  (`rubrics/<kind>.rubric.json`), parses the model's per-dimension scores, and computes a
  **deterministic** weighted overall vs the rubric threshold. The scores are latent; the
  prompt build, the math, the verdict, and the exit code are code. Ships rubrics for
  `reflection`, `discovery`, and `seed`; a new subject is one JSON file, no code change.
- **`shctx eval <run|report|list>`** — the registry-side glue. Resolves a subject (e.g. the
  stored reflection note for a sprint), calls the eval service, and records the verdict to
  **`eval_runs`** (migration `0018`), surfaced by a new `shctx dash` EVAL row + `shctx eval
  report`.
- **Optional close-time scoring** — `[eval].eval_on_close` (default `off`) has the conductor
  score the close reflection at CLOSE-FINALIZE and record it. Off by default because it spends
  an LLM call; on, it tracks reflection quality across sprints.

Two lanes per the project's test/eval discipline: a **gate lane** (`services/llm/tests`,
`services/eval/tests`, `test_cmd_eval.sh` — deterministic, free, <2s, judge mocked) covering
the eval→llm boundary, the score math, the threshold verdict, DB recording, and every error
path; and a **live lane** (`services/eval/evals/run_eval.sh`, real judge, gated by
`SHEPHERD_EVAL_LIVE=1`) that proves the judge discriminates golden-good from golden-bad by a
margin. Live smoke against a real local judge: reflection good 100 / bad 20, discovery good 69
/ bad 20 — lane PASSED.

### Fixed — per-lane focus is now storable and readable

- **Migration `0017_focus_lane.sql`** — rebuilds the `focus` table with primary key
  `(sprint, lane)`; `lane = ''` is the sprint-level record (every existing row migrates to it,
  preserving all v6.0.9 behavior). Version-gated, applied once.
- **`shctx loop focus upsert|show --lane=<id>`** — the handler now keys reads and writes on
  `(sprint, lane)`, surfaces `lane` in the text / md / json output, and defaults to the
  sprint-level record when `--lane` is omitted. Help text + usage updated.
- **`precompact_snapshot.sh`** snapshots the sprint-level cursor explicitly (`AND lane=''`),
  guarded by a column-existence check so a DB still at migration 0013 keeps working.
- **`agents/conductor.md`** — the teammate-conductor heartbeat now re-anchors to its **lane**
  focus record (`--lane={lane_id}`) instead of the sprint-level one; the WAVE-GATE focus
  refresh notes the SOLO (sprint-level) vs TEAMMATE (`--lane`) split. `commands/focus.md`
  documents the `--lane` flag.

### Tests

`test_loop_lifecycle.sh` applies 0017 and asserts the round-trip: a lane record is independent
of the sprint-level record, both coexist for one sprint, bare `show` returns the sprint-level
row. Whole-repo gate lanes green: **46/46 context + 49/49 hooks + 2/2 services/llm + 3/3
services/eval**; the live eval lane PASSED against a real local judge.

---

## v6.2.2 — 2026-06-29

**Cleanup + a long-sprint drift guard + a public-launch README.** A subtraction pass:
the grafted "ponytail" review apparatus is excised in full, a new lean mechanism keeps the
root on-task across multi-hour sprints, and the README is rebuilt to publish. No schema
change, no new hook, no new runtime — all behavioral wiring on the existing focus spine.

### Removed — the "ponytail" (full excision)

The `/shepherd:ponytail` command and its `senior-engineering.md` doctrine were a copy-paste
of an external reviewer concept grafted on as a standalone command — the opposite of the
lean-behavioral-layer north-star. Both are gone:

- **Deleted** `commands/ponytail.md` and `skills/shepherd/doctrines/senior-engineering.md`.
- **Stripped** every reference: the `@auditor`/`@coder` profile citations + their `.reference.md`
  mirrors, `operating-philosophy.md`, the doctrines index, `SKILL.md` (triggers, command table,
  file-map), the `[ponytail]` config section in `docs/configuration.md`, and the example toml block.
- **Kept** the floor: each of the eight ex-primitives built on a doctrine the flock already
  carries (`agent-excellence.md`, `auditor-hypothesis-driven.md`, `grading-rubric.md`,
  `wrapper-must-earn.md`, `subtract-dont-add.md`). The auditor/coder revert to those natively —
  no quality cliff. The `AUDITOR-REFINE` loop template survives (it never depended on the command).

### New — the FOCUS-HEARTBEAT (`[focus].heartbeat_actions` / `heartbeat_interval`)

The field symptom: on a multi-hour sprint the root drifts off-task. The FOCUS-LOOP already
re-anchors at every wake and survives compaction, but a long FOCUS-ACT stretch with no teammate
event has no wake — so the north-star recedes and the root wanders. The heartbeat closes that gap:

- A cadenced **re-anchor + self-drift-check** fires *within* a long active stretch, on two unequal
  legs: `[focus].heartbeat_interval` is the **deterministic** leg (the native `/loop` owns the clock,
  so a real wake fires on a real schedule — the one that guarantees a re-anchor); `[focus].heartbeat_actions`
  (default 20, on) is a **soft, best-effort self-prompt**, a latent estimate, not a counted guarantee.
  A natural wake re-anchors anyway.
- It re-reads the focus record (never working memory), emits the compact `[FOCUS-HEARTBEAT]` block
  (objective · active_node · invariants · next_action), then checks whether the last stretch advanced
  the active node within invariants. Wandered → `[DRIFT-WARN] self`: return to the node, **file** the
  digression rather than chase it inline (bounded — `subtract-dont-add.md`).
- **Reuses** the existing focus record + native `/loop` clock + coordinate cycle. No migration, no hook —
  which is precisely why the action-count is a soft nudge (nothing backs a counter) and the wall-clock
  interval is the deterministic path. Cache-safe: the block is emitted, never injected into a brief prefix.
- Wired into the FOCUS-LOOP composite (`references/workflow-templates.md`, `loop-templates.md`),
  the root self-drift leg of the coordinate PROBE (`coordinate-active-drive.md §IV-b.3`), both
  orchestrator profiles, `/shepherd:focus` (new `--heartbeat` flag), the config schema, and both example tomls.

### Changed — README rebuilt for public release

Full rewrite to a launch-ready guide: punchy hero + the failure-mode table, a 60-second mental
model, three install paths, a five-minute quickstart, a per-command reference, eight usage
playbooks (single sprint, patch autopilot, parallel lanes, seed authorship, the drift heartbeat,
context inspection, bounded loops, cleanup), an under-the-hood section, troubleshooting/FAQ, and an
accurate file map. Reflects the post-excision eight-command set (adds the previously-undocumented
`/shepherd:focus`) and documents the heartbeat.

### Verification

49/49 hook smoke tests green. Zero dangling `ponytail` / `senior-engineering` / `SENIOR-STANDARD`
references across the shipped surface. README lists exactly the eight commands that exist.

---

## v6.2.1 — 2026-06-28

**Self-sufficient spawn, deterministic seed teeth, leaner engineer.** A refinement
pass on the proven planter/engineer/spawn spine — not a redesign. The framework's
highest-precision artifact finally gets a mechanical floor, a seedless `/spawn` plants
itself instead of dead-ending, the engineer sheds its transcription tax, and a class of
duplicated normative text is purged. All lean wiring; no new runtime, no schema change.
Every behavior the framework strives for (the flock, lanes-as-teammates, precision seeds,
drift-resistance, parallel execution) is preserved — made enforceable instead of aspirational.

### New — `shctx seed verify` + the seed pre-flight gate (the teeth)

The seed pre-flight had been prose self-policing since v5.x (`seed-naming.md` openly
deferred "future sprints will add teeth"). It is now a script:

- **`shctx seed verify <path>`** (`skills/context/scripts/cmd_seed.sh`) — deterministic,
  no network. HARD-fails (exit 1) on a hallucinated `file_scope` path, an over-cap footprint
  (≤ 400 sprint / ≤ 200 patch-arc), a `TODO:`/`FIXME:` marker, prescriptive `Lane N` numbering
  (#67), or a priority-bearing deliverable with no `**GH:**` anchor; warns on a thin mesh,
  missing frontmatter, or a `Sequencing:`/semver judgment. Tolerates the idiomatic seed forms —
  directory/recursive globs, em-dash/parenthetical path annotations, embellished `(NEW - reason)`
  markers, and flow-style `[a, b]` scope. A path created this sprint is exempted with a trailing `(NEW)`.
- **`hooks/scripts/seed_preflight_check.sh`** — a `PreToolUse(Write)` guard that runs the gate on
  every `*.seed.md` write and blocks a failing seed before it can reach a spawn. Config
  `[seed].seed_gate = block (default) | warn | off`; fails OPEN on any tooling hiccup.
- **Single source of truth.** The checklist and its numbers (mesh-row floor, footprint cap) now
  live ONLY in the script; the three disagreeing prose copies (`seed-template.md`, `planter.md`,
  `seed-anchored-by-issues.md`) were deleted and replaced with a pointer.

### New — self-sufficient `/spawn`: the `SEED-AUTHOR` node

A seedless single-`--scope sprint` `/spawn` (or `/start`) no longer dead-ends. The walk opens on a
`SEED-AUTHOR` node: a present seed is a pass-through; a missing one emits ONE turn-ending confirm
and plants the seed **inline** via the planter inner frame (two-meta-loading), gates it with
`shctx seed verify`, and falls through to `INTRO-COMBO-WAVE`. The three forked seedless behaviors
(refuse / best-effort-degrade / staged-wait) collapse into one. No `AskUserQuestion` is re-admitted
to execution sessions — **v6.1.7 holds**; intent arrives as the operator's chat reply and is captured
in the committed seed. Multi-sprint / `--parallel` still route a missing seed to `/shepherd:plant`.

### Changed — leaner engineer (transcription seams cut)

- **Conditional re-mesh.** The engineer scales Phase-0 effort to the seed's age: a co-timed seed
  (planted this session) leans on the discovery wave with only a targeted gap-check; the full
  drift-delta re-mesh is reserved for a stale patch-arc-ahead seed. Both modes stay first-class.
- **Acceptance authored once.** Acceptance predicates live solely in the GH issue body; the seed
  line and the engineer's step `[ACCEPTANCE]` reference it rather than re-typing — killing the
  silent seed↔step divergence.
- **§7-bis deleted.** The seed's non-binding "Stage decomposition hint" was authored, then thrown
  away and re-derived; removed. The engineer composes the binding `## Stage Graph` from Phase-0,
  preserving the #67 firewall. Six cross-references updated.

### Fixed — duplicated-normative-text drift (behavior-neutral)

- `conductor.md` no longer claims SOLO "carries `AskUserQuestion`" — a tool removed from its
  toolset in v6.1.7 (the stale claim would have failed at the exact no-seed moment it described).
- The dead `$CLAUDE_AGENT_TEAMMATE_NAME` / `$CLAUDE_PROJECT_SESSION_TYPE` env signals (empty on the
  live platform since #93) are demoted from PRIMARY to documented-dead in
  `dispatch-tier-separation.md`, matching the profile.
- New lint (`lint_agent_capabilities.sh`, run by the hook suite) flags any profile that claims a
  tool its frontmatter does not grant — the regression guard for the class above.

### Tests

- `skills/context/tests/test_cmd_seed.sh` (16 cases) + `hooks/tests/test_seed_preflight_check.sh`
  (9 cases), including the path-resolver tolerance + flow-style false-negative cases surfaced by
  a 3-lens pre-merge review. Suites: context 45/45, hooks 49/49.

---

## v6.2.0 — 2026-06-27

**Operating philosophy bound, self-improvement made apparent, native self-paced loops.**
Part cleanup, part evolution: the how-to-work doctrine becomes a first-class framework
binding, the adaptation loop is surfaced where the operator actually looks, and `/loop`
gains the native self-paced pacing mode. All lean wiring over native tools — no new
runtime, and the only new schema is none (the loop pacing sentinel rides an existing
free-text column).

### New — `doctrines/operating-philosophy.md` (CLAUDE.md binding)

The how-to-work philosophy is bound as a thin **index** doctrine: it names the four
flock-scoped principles that had no home — the **latent-vs-deterministic split**
(`agent-excellence.md` Rule 7, read every dispatch), skillify-success, the
context-window diagnostic, and the `DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT`
return vocabulary — and cites the covered majority rather than re-pasting it. Surfaced at
SessionStart (`[context].announce_core_doctrine`) and the flock foundational block. A
portable twin (`examples/minimal/CLAUDE.md`) materializes into consumer repos via the new
`shctx config claude-md` — an append-only, never-clobber managed block (`--force`
re-syncs only the block).

### New — adaptation loop made visible

- **`shctx adapt reflect --sprint --note [--pin]`** — a one-line, first-person close
  reflection (Reflexion) stored as a `kind='prior'` lesson and injected into the next
  sprint's planning brief. Idempotent per sprint; pin-preserving on re-run.
- **SessionStart adaptation surface** — inverted from the old empty-only note: a
  non-empty registry now surfaces prior counts + the newest lesson + any active TREND
  ALERT (`[context].announce_adaptation`; the trend probe is gated to ≥3 closes).
- **`shctx dash` ADAPT row** — sprint/prior counts + latest lesson at a glance.
- **Close-step wiring** — the deterministic `shctx adapt report --trends` now runs at
  CLOSE-FINALIZE (replacing the "eyeball the report" instruction it always forbade), and
  a "Learned" line lands in the close report.

### New — `/loop` native self-paced pacing

- **`--self-paced`** delegates to the native Claude Code `/loop` with no fixed interval:
  the platform picks a dynamic, cache-window-aware delay and ends the loop early on
  convergence. Sound for terminate-on-`false` (convergent) templates only — WATCH +
  FOCUS loops keep fixed `--interval` (self-paced would stop a watch on the first healthy
  tick).
- **`shctx loop native-cmd`** emits the exact native `/loop` invocation deterministically
  from stored pacing, so the model never reconstructs it per wake (Rule 7 in practice).

### Notes

- Gate tests: 44/44 context + 45/45 hooks; every new shctx surface and behavioral path is
  covered, and the changes passed a six-dimension adversarial review.
- `wall_minutes` stays an explicit `--wall-min` input. A git-derived auto-fill was
  prototyped then rejected — it measured branch age, not sprint duration, and would have
  fired the cost-rising trend spuriously on long-lived branches.

## v6.1.8 — 2026-06-17

**Field-shape deduplication — `shctx dups` (#157).** The third leg of the
mechanical shape-gate set (with `dep-hygiene` and `check-impls-defs`). Name-matching
dedup (`index_symbols` / `dedup-check.sql` / `dedup_write_guard.sh` / the conductor
`DEDUP-GATE`) catches a duplicate ONLY when the second definition reuses the first
one's name. It is blind to the dominant large-workspace rot: a **second type for an
existing concept under a different name** — the rename-to-evade-dedup shadow that
compiles green and slips every name-keyed gate (a 2026-06-17 audit of one workspace
found 22 such clusters). `shctx dups` closes that gap by clustering on **field
shape**, and gives subagents a way to *recognize a pre-built struct they can reuse
without remembering its name* — the match is surfaced, by shape, at authoring time.

### New — `shctx dups <scan|check|registry>`

- **`scan`** — workspace census: parses every `pub struct`/`pub enum`, fingerprints
  each by its `(field_name, normalized_type)` set, clusters by similarity, and
  reports each cluster with members (`file:line` + consumer count), pairwise
  similarity, and a **suggested canonical** (lowest dep tier). `--update` persists
  the corpus to `index_struct_shapes`; `--fail-on {medium|high|foundation-blocking}`
  is a non-zero CLOSE/CI gate. The headline `foundation-blocking` severity flags an
  orphan canonical (zero consumers) sitting beside a live shadow.
- **`check <file> | --stdin --as <path>`** — authoring-time gate: matches a
  candidate's NEW defs against the corpus and reports any same-shape existing type
  (*"…is 0.85-similar to `pkg::X` — reuse it?"*). Exits `5` above the block
  threshold. Used by the PreToolUse hook and as a coder Phase-0 self-check.
- **`registry show|allow|unallow|pin|unpin|update`** — curated `concept→canonical`
  pins + a **DO-NOT-MERGE allow-list** for intentional distinct-role twins (a venue
  `Fill` vs a backtest `SimFill`). Tracked at `<ns>/dups-registry.json`.

### Similarity, parsing, storage

- **Metric:** `sim = name_weight·jaccard(field_names) + (1−name_weight)·jaccard(typed_pairs)`.
  The field-NAME blend catches a shadow that restated `Uuid→String` / `DateTime→String`
  / `f64` field-for-field under a new name. Field-less (marker) shapes and shapes
  below `dups_min_fields` are excluded.
- **Parser** (`skills/context/scripts/dups-core.py`, stdlib python3) — a brace /
  generic / attribute-aware scanner over Rust source realizes the proposal's
  "Rust + syn" intent without a build step and is deterministic + unit-testable.
  Tree-sitter multi-language is a later extension; the shape model + similarity +
  clustering are language-agnostic. DB I/O routes through python's `sqlite3`
  module (no dependency on the `sqlite3` binary).
- **Schema:** `migrations/0015_struct_shapes.sql` adds `index_struct_shapes`
  (the field-shape corpus, sibling of `index_symbols`/`index_concepts`).
- **Refresh:** `shctx refresh --scope=shapes` (folded into `--all`, hence
  `sprint open`) keeps the corpus current.

### Enforcement + integration

- **New PreToolUse(Write|Edit) hook** `hooks/scripts/dups_write_guard.sh` — the
  shape-shaped sibling of `dedup_write_guard.sh`. `@coder` `.rs` writes only;
  config `[dups].dups_hook = off | warn (default) | block`. Fails open at every
  step (non-coder, non-rust, no python3, empty corpus → silent pass); it can only
  block on a real shape match.
- **New doctrine** `doctrines/shape-dedup.md`; `zero-duplicate-tolerance.md` gains
  Layer 4 + a cross-link.
- **Config** `[dups]` (`docs/configuration.md` + both example `shepherd.toml`s):
  `dups_threshold`, `dups_block`, `dups_name_weight`, `dups_min_fields`,
  `dups_hook`, `dups_registry` (keys are `dups_`-prefixed because `cfg_get` is
  section-agnostic). `rust-service` wires a `shape-dedup` close gate into
  `[gates].extra`.
- **Tests:** `skills/context/tests/test_cmd_dups.sh` (scan/check/registry/gate/persist)
  and `hooks/tests/test_dups_write_guard.sh` (block/warn/off + fast-paths), plus
  smoke cases.

### Fix — the `shctx absent` false negative

A live v6.1.7 session reported `shctx absent`. Root cause: `shctx` is plugin-local
and **never on `$PATH`** — it is invoked by the absolute path
`${CLAUDE_PLUGIN_ROOT}/skills/context/scripts/shctx`. A `command -v shctx` /
`which shctx` probe returns absent **by design**, and when `$CLAUDE_PLUGIN_ROOT`
does not propagate into the agent's Bash env (some remote/web launches) even the
full-path invocation fails. Neither is evidence of absence.

- **`hooks/scripts/session_open.sh`** now surfaces, at SessionStart, the absolute
  `shctx` path resolved from the **hook's own location** (`hooks/scripts → ../..`),
  correct regardless of `$CLAUDE_PLUGIN_ROOT`, with the explicit note that
  `command -v shctx` returns absent by design. Config-gated
  `[context].announce_shctx_path = on (default) | off`.
- **`skills/context/SKILL.md`** documents the rule authoritatively (never PATH;
  `command -v` is the #1 false-negative; invoke by absolute path).
- **Test:** `hooks/tests/test_shctx_locator.sh` (surfaces the path with
  `$CLAUDE_PLUGIN_ROOT` unset; off-switch suppresses).

### Fix — staged-handoff (v6.1.7) never actually worked

Verifying the v6.1.7 staged-handoff feature (`/shepherd:spawn --staged` +
`seed-ready` mailbox signal) surfaced a shipped defect: the `mailbox.kind` CHECK
constraint (from `0007`) was a closed enum
(`heartbeat_payload|escalation|ack|status|generic`), so
`shctx mailbox send --kind=seed-ready` was **rejected by the schema** — the signal
could never be sent. Every future doctrine adding a routing tag would have hit the
same wall, silently.

- **`migrations/0016_mailbox_kind_relax.sql`** rebuilds `mailbox` with a permissive
  `CHECK(kind <> '')` (root-cause fix, not a one-value patch), preserving columns,
  data, the FK, both partial indexes, and the unread view.
- **`doctrines/staged-handoff.md`** `jq` consume snippet corrected to iterate the
  JSON array (`.[] | select(...)`; `recv` emits an array).
- **Test:** `skills/context/tests/test_staged_handoff.sh` drives the full
  `send → recv --unread-only --mark-read → ack` seed-ready round-trip.

Both full suites green (hooks 44/44, shctx 44/44).

## v6.1.6 — 2026-06-15

Two-lane release. **Lane A** makes teammate-conductors *actually leverage* the
native Claude Code `Workflow` (Dynamic Workflows) tool instead of reflexively
`ToolSearch`-ing for it and mis-degrading. **Lane B** introduces `/shepherd:ponytail`
and the **senior-engineering operating standard** — the primitives that turn the
`@auditor` and `@coder` into senior devs, cemented into their profiles and adaptable
to the project and user.

> The trigger for Lane A was a live failure: an `/effort ultracode` session, told to
> "use the Workflow tool," ran `ToolSearch select:Workflow`, got nothing, and declared
> the tool "confirmed absent" — the *exact* mistake teammate-conductors make. The fix
> is not more prose (there was already plenty) but a **recorded first-action
> self-check** that an agent cannot skip.

### Lane A — teammates actually leverage Dynamic Workflows

- **New doctrine `doctrines/workflow-tool-self-check.md`** — the operational
  front-end for the native `Workflow` tool, consolidating the detect / never-
  ToolSearch / benefit guidance that was scattered across `references/glossary.md §1`,
  `capability-discovery.md §V`, `workflow-compile-down.md`, and
  `primitive-axis-binding.md §IV` (and still got skipped). ONE first action:
  *is the token `Workflow` in your visible tool list?* → record
  `workflow_tool: present|absent` → branch. **Present** → compile gate-free fan-out
  out-of-context (framed as the conductor's OWN benefit: clean context window + ≤16
  background agents, not a tax). **Absent** (web/remote, #146) → degrade to in-context
  `Agent(...)` — correct and expected. **NEVER `ToolSearch`** for it (the
  `WORKFLOW-SELFCHECK-TOOLSEARCH` anti-pattern), not even under `/effort ultracode`.
- **Wired as a first action** into `agents/conductor.md` (prohibition #22 rewritten +
  mode-comparison rows + a step 0 in the teammate compile sequence), `agents/shepherd.md`
  (root Step 0 + `[ROOT-START] workflow_tool=…`), `commands/spawn.md` (teammate boot
  prompt), and `commands/start.md` (lane walk step 0 + `WAVE-COMPLETE.workflow_tool` /
  `.fanout` fields). Corrected the stale "always present" phrasing to the
  environment-dependent visible-tool-list test.
- **Enforcement seam:** new `@auditor` completeness extension
  (`agents/auditor.md §workflow-substrate discipline`) — files `PRIMITIVE-INVERSION`
  when a lane hand-rolled in-context fan-out where the tool was present, and a LOW
  finding when the self-check was skipped or the tool was ToolSearched. In-context
  fan-out where the tool is **absent** is correct and never flagged.

### Lane B — `/shepherd:ponytail` + the senior-engineering standard

- **New doctrine `doctrines/senior-engineering.md`** (the "ponytail" doctrine) — the
  senior-engineering operating standard for `@auditor` + `@coder`, eight primitives
  that build on the existing flock doctrines (cite, never duplicate): (I) comprehend
  intent before you touch (Chesterton's fence); (II) root-cause over symptom;
  (III) blast-radius- & cost-to-reverse-weighted severity; (IV) justify the tradeoff,
  not just the change; (V) conform to THIS project and THIS user via a precedence
  ladder (project doctrines > `[CODE-STYLE]` ledger > `code-style` skill > adaptation
  priors > the neighbors > defaults); (VI) cross-concern systemic-risk detection;
  (VII) bounded restraint (the most senior move is often the smaller diff);
  (VIII) preserved read-only/tier discipline. `SENIOR-STANDARD-MISUSE` anti-pattern.
- **New command `/shepherd:ponytail` (`commands/ponytail.md`, also `/ponytail`)** — an
  on-demand senior **review → refine → verify** pass on a target (diff, path, file, or
  PR) **outside** the sprint pipeline: Pattern 3 (Adversarial Verification) + Pattern 4
  (Generate-And-Filter), bounded as the AUDITOR-REFINE loop. Review-only by default;
  `--apply` runs the coder-refine + re-verify loop; `--cement` persists the conventions
  the pass observed into project memory / the style ledger. Fully adapted via styles,
  project doctrines, config, and adaptation priors.
- **Cemented into the profiles:** `agents/auditor.md` and `agents/coder.md` now cite
  `senior-engineering.md` in §"Doctrines this role honors" with the per-role primitive
  summary, and the FIRST-loaded reference skills (`auditor.reference.md`,
  `coder.reference.md`) carry the senior lens. New config section `[ponytail]`
  (`senior_standard`, `default_mode`, `max_verify_iterations`, `apply_requires_approval`,
  `conformance_sources`) in `docs/configuration.md`.

### Wiring

- `skills/shepherd/SKILL.md` — `/shepherd:ponytail` + `/ponytail` triggers, command-table
  row, and §XI file-map rows for both new doctrines + the command.
- `skills/shepherd/doctrines/README.md` index — rows for `workflow-tool-self-check.md`
  and `senior-engineering.md`.
- `CLAUDE.md` command table + file-contracts; `README.md` command banner.

## v6.1.5 — 2026-06-15

Kickoff-hardening + config-auto-scaffold + observability release (#147), extended
with **two new capabilities** — #148 supervised self-heal and #146 capability
auto-discovery — plus a reliability follow-up that repairs the
**operator-signaling inversion** (the planter under-asked while the shepherds
over-asked), the **"`Workflow` tool is always present" overclaim** that made
web/remote sessions give up instead of degrading, and two **latent namespace/DB
defects** the new kickoff wiring exposed.

### Authorized supervised self-heal — AUTONOMOUS-SENTINEL (#148)
- New loop template (`references/loop-templates.md §AUTONOMOUS-SENTINEL`) +
  binding doctrine (`doctrines/autonomous-sentinel.md`) for **authorized
  supervised autonomy** — the supervised-remediation superset of SOAK-LOOP.
  Stages: PROBE (seeded acceptance predicates, live) → CLASSIFY
  (HOLD/REGRESSED/NEW) → ACT (dispatch a ≤S `@coder` hotfix through the existing
  hotfix-dispatch ladder → gates-before-deploy → re-probe) → TERMINATE (K clean
  ticks / N-HF cap / hard-stop). Hard rails: gates-before-deploy, ≤S / ≤3
  concurrent / ≤N total HF caps, no destructive DB ops, auto-rollback on red,
  paper-only (never flip to live without authorization), operator-override-each-
  tick, full audit trail.
- New config key `[close].autonomous_sentinel` (default `"off"` — detection-only).
  It must be `"on"` AND the seed must declare `close: autonomous-sentinel` AND a
  complete `sentinel_rails` block must be present before a single remediation
  fires (three independent opt-in gates). New halt codes `SENTINEL-RAILS-MISSING`
  / `-SCOPE-EXCEEDED` / `-HF-CAP` / `-ROLLBACK` / `-HARD-STOP` / `-LOOP-CAP`.
- Reconciled the depth-3 "remediating inside a watch loop" anti-pattern in
  `references/loop-templates.md §SOAK-LOOP` and `doctrines/outcome-enforcement.md
  §Seam 4`: detection-only stays the DEFAULT and the anti-pattern for the
  UNAUTHORIZED case; the explicitly-authorized AUTONOMOUS-SENTINEL case is carved
  out.

### Capability auto-discovery (#146)
- Shepherd now auto-detects the Claude Code plugins/skills available in the
  environment and adapts without operator wiring. A cheap, one-time-per-session
  SessionStart probe (`hooks/scripts/capability_discovery.sh`) enumerates
  installed plugins + skills and writes an **EPHEMERAL** capability roster
  (`<ns>/cache/discovered-capabilities.json`, gitignored) kept strictly distinct
  from the operator-curated `toolkit.json` — discovery never overwrites intent.
  The roster is merged at read time into the `[TOOLKIT]` surfaces (SessionStart
  roster + engineer/coder/planter brief injection via the new `shctx toolkit
  discovered`), labeled auto-discovered and bounded at 12.
- New doctrine `doctrines/capability-discovery.md` codifies the guarded-integration
  pattern ("if `/remember` is available → use at handoff/CLOSE-FINALIZE + resume,
  else shepherd-native"; same for `superpowers`, `pr-review-toolkit`), so behavior
  degrades cleanly when a plugin is absent — shepherd never hard-depends on a
  third-party plugin.
- The probe also records whether the native **`Workflow` tool** is present;
  web/remote sessions that omit it degrade to in-context `Agent(...)` fan-out
  instead of giving up (cross-referenced in `references/glossary.md`).
- New config key `[discovery].auto_capabilities` (`on` default | `off`), resolved
  via `cfg_get` (local → project → XDG-global precedence). Zero hot-path cost,
  fail-open.

### Seed-optional kickoff (#8)
- `/shepherd:start` (Step 0) and `/shepherd:spawn` (Hard-stop #2 / Check 6) no
  longer hard-refuse on a missing seed for a single `--scope sprint` run: derive
  the objective from the repo/issue ledger, or ask ONE batched kickoff question,
  then run — per `doctrines/operator-signaling.md §"Seed is recommended, not
  required"`. `--parallel` and multi-sprint `--scope patch|minor|version` walks
  still HARD-refuse (seeds are load-bearing there for collision detection + walk
  enumeration).

### Config auto-scaffold (#15)
- New **`shctx config init`** scaffolds `.claude/shepherd.toml` from the bundled
  minimal template when absent (idempotent): derives `[project].name` (git
  remote → cwd basename) and `[gates]` (Cargo.toml→cargo, go.mod→go,
  pyproject/setup.py→pytest+ruff, package.json→npm), and realigns `[paths]` to
  the active shctx namespace. Adds `shctx config get/show/path`.
- Wired at kickoff: start/spawn root scaffold → `[CONFIG]` notice → PROCEED
  (action-biased); plant scaffold → ONE batched `AskUserQuestion` to refine
  `[branching]`+`[gates]` (replaces the #120 hard STOP).

### Observability dashboard (#13)
- New **`shctx dash`** — a one-glance, read-only sprint snapshot composed from
  primitives the root already maintains (focus, graph state, live teammates,
  unread mailbox, open escalations, active loops, GitHub cache freshness). No
  new table/subsystem; bash-3.2-safe; degrades cleanly on missing DB/tmux.
  Monitoring recipe: `/shepherd:loop <interval> shctx dash`.

### Four config toggles (#10)
- `shctx config get <key> [default]` is the uniform resolver (local→project→XDG)
  the toggles read through. Defaults reproduce pre-v6.1.5 behavior exactly:
  `[autorun].on_grade_floor` (abort), `[autorun].inter_sprint_pause` (brief),
  `[spawn].max_parallel` (4), `[spawn].dashboard_cadence` (3m). The
  previously-undocumented `[autorun]` section is now in `docs/configuration.md`.

### Neutralized the bundled example (#9) + subagent-preference (#11)
- `examples/axiom/` → `examples/rust-service/`; scrubbed all domain-specific
  references (finance/polymarket/geo-block) from the example and ~23 doctrine
  teaching snippets. `geo-block-law.md` rewritten as a generic
  regulated-upstream-API teaching example. Historical `.artifacts/` docs are
  intentionally left intact.
- `doctrines/agent-excellence.md` Rule 6 (token-conservation / subagent
  preference) is now wired into every agent profile.

### Reliability follow-up — operator-signaling inversion
`doctrines/operator-signaling.md` (v6.1.4) was correct, but its posture was
never reproduced into the agent profiles that actually become system prompts at
runtime. `AskUserQuestion` is granted correctly in every profile — the inversion
was a **prose-propagation gap**, not a tools-grant bug:
- `agents/planter.md`: added a standing **"the planter asks freely"** posture at
  the top of plant mode (previously the ONLY trigger was the rare no-config
  bootstrap branch, so the common case invented answers instead of asking).
- `agents/conductor.md`: SOLO = `AskUserQuestion` is a narrow escape valve only;
  TEAMMATE mode MUST NOT call it (the `MODE-MISUSE` halt code now names the
  tool).
- `agents/shepherd.md`: root action-bias note — the defined gates are the only
  operator stop points; no invented mid-run confirmation asks.

### Reliability follow-up — the `Workflow` tool is NOT "always present"
- `references/glossary.md` listed the native `Workflow` tool alongside
  `Agent`/`Bash`/`Edit` as always-present and blamed any absence solely on "a
  build below the Dynamic Workflows floor." Claude-Code-on-the-web /
  remote-execution sessions omit it **even on a supporting build**, so a
  spawn/loop that reached for it gave up instead of degrading. Corrected to
  **environment-dependent** presence, with the visible-tool-list test as the
  only authority and degrade-to-`Agent(...)` as the documented path (ties into
  #146).

### Reliability follow-up — two latent defects the kickoff wiring exposed
Both were invisible to the green suites (the harnesses set neither
`CLAUDE_PLUGIN_ROOT` nor a `shepherd.db` registry); #15's config-scaffold pulled
them onto the kickoff hot path:
- **`shctx_skill_root()` returned bare `$CLAUDE_PLUGIN_ROOT`**, but `schema/` +
  `references/` live at `$CLAUDE_PLUGIN_ROOT/skills/context/`. `scaffold.sh`'s
  `cp references/naming-conventions.md` aborted under `set -e`, so `shctx
  init`/`config init` never created the DB and every downstream `shctx` command
  failed. Now prefers the dispatcher-exported `SHCTX_SKILL_ROOT`, else
  `$CLAUDE_PLUGIN_ROOT/skills/context`. Verified end-to-end (init exits 0,
  creates `shepherd.db`, copies `CONVENTIONS.md`).
- **9 hooks hardcoded `$ns/root.db`** while v6.1.2+ `shctx init` creates
  `shepherd.db`, so `[[ -f "$DB" ]]` was always false → silent no-op, disabling
  the spawn-coordination guards (`coordinate_drive_guard`,
  `worktree_teardown_guard`, `teammate_idle`, …) on every modern project. New
  `hook_db_path()` in `hooks/scripts/_lib.sh` mirrors the skills-side
  `shctx_db_path()` (prefer `shepherd.db`, fall back to an existing `root.db`,
  default `shepherd.db`); all 9 assignments route through it.

Tests: hooks 38/38 (+1 for the #146 capability-discovery probe), context 42/42.

## v6.1.4 — 2026-06-12

A reliability + native-alignment release. Fixes the **`dev.{last}` → `dev.{last+1}` release-trigger miss** that cut a stray dev branch instead of releasing, corrects a wrong **native `/loop` expiry constant** that had propagated as a load-bearing invariant, makes Claude Code's **`Workflow` tool** unmistakable (it was being mistaken for a `ToolSearch` target and given up on), restores **tmux pane observability** plus the dead-pane cleanup that had been documented but never built, and gives planning + main-chat sprint sessions a **native operator-signaling** path — without letting execution sessions become approval-seekers.

### Release trigger — never cut `dev.{sprints_per_patch}` again
- **The bug.** At the close of `dev.{last}` (e.g. `v0.3.5-dev.9`, `sprints_per_patch = 10`) the conductor cut `dev.10` instead of firing the release cascade. Root cause: `agents/conductor.md` Step 5 and `agents/shepherd.md` RF-4 stated the mod-N condition in *prose* but showed an *unconditional* `git checkout -b {next}` beneath it — and an exhausted-context conductor runs the visible command and drops the prose.
- **Mechanized the decision.** Both briefs now run `shctx release --dry-run` (the authoritative oracle) *before* the rebase, and gate the next-branch cut on an explicit `[ "$N" -lt "$((K-1))" ]` conditional with the release path stated first.
- **Deterministic backstop.** New `hooks/scripts/release_trigger_guard.sh` (`PreToolUse(Bash)`) blocks creating/publishing a `…-dev.N` branch where `N ≥ sprints_per_patch`, while allowing mid-patch cuts, `dev.0` rollovers, and remediation deletes. Config: `[release].devlast_guard = block (default) | warn | off`. A raw pre-filter skips JSON parsing on every Bash call that doesn't mention `dev.N` (≈zero added cost). 13-case behavioral test matrix.
- **Wired `sprints_per_patch` into `cmd_release.sh`** (was hardcoded `=10`, silently wrong for projects on 5/7).

### Native `/loop` expiry — "3 days" was wrong; it's 7
- Corrected ~19 references across `references/loop-templates.md` and `references/workflow-templates.md` asserting a "3-day" outer bound. Per `code.claude.com/docs/en/scheduled-tasks`, fixed-interval and self-paced loops expire after **7 days**. The canonical note now distinguishes interval mode (runs until stopped or 7 days), self-paced mode (1 min–1 hr dynamic delay, ends early when done), and `Esc`-to-stop.

### Loops — discoverable from a cold session
- `SKILL.md §0-ter` surfaces loops in the always-on layer: the Q4 trigger, the role→template map, an "author your own" recipe, and the bounded + measurable invariants.
- `[LOOP-CONTEXT]` added to `agents/worker.md` and `agents/discovery.md` so a looped agent reads its `new_findings` contract in its own brief; the conductor gains a mid-sprint loop-recognition note.

### The `Workflow` tool vs "workflow patterns" vs GitHub Actions
- New `references/glossary.md` disambiguates the three senses of "workflow" and states the rule that broke a sprint: the native **`Workflow` tool is always present and is NEVER a `ToolSearch` target** — if it isn't visible you're below the version floor, so fall back to in-context `Agent(...)`. First-mention corrections added at `workflow-compile-down.md`, `hotfix-dispatch.md`, and `conductor.md`.

### tmux observability + dead-pane cleanup (#66.6)
- New `shctx panes` (`status` / `capture` / `tail` / `prune`) — the first consumer of the long-orphaned `teammates.tmux_pane_id` column. `capture` snapshots each live teammate pane to `<ns>/logs/panes/`; `status` is a per-lane liveness dashboard (run under `/loop` for a live view).
- New `hooks/scripts/tmux_pane_cleanup.sh` on `SessionEnd` reaps panes of closed teammates (the documented-but-unbuilt #66.6 gap). Config: `[tmux].pane_cleanup = on (default) | off`.
- `shctx teammate heartbeat` now self-heals `tmux_pane_id` from `$TMUX_PANE` (zero brief changes), so the column populates without operator wiring.

### Native operator signaling — the planner asks, execution runs
- `AskUserQuestion` enabled for the planter, root shepherd, and SOLO conductor (teammate-conductors still escalate to root via `SendMessage`).
- New `doctrines/operator-signaling.md`: the **planter asks freely** (planning is interactive), while **execution sessions are action-biased** — `AskUserQuestion` is a narrow escape valve (no-seed kickoff, irreversible outward actions, hard blocking forks) with an explicit ban on confirmation/approval-seeking and on inventing new stop points. Codifies that the **seed is recommended, not required**.

## v6.1.3 — 2026-06-12

The toolkit-hardening, bash-3.2-portability, and **outcome-enforcement** release. Fixes the v6.1.2 toolkit "Permission denied" that fired at session start, repairs three macOS bash-3.2 breakages (including a silently-broken hotfix guard and unbounded precompact-snapshot pileup), removes the retired `autorun`/`parallel` machinery for good, and adds a behavioral layer that makes the *seeded outcome* — not just green gates — the thing that closes a sprint.

### Toolkit — the v6.1.2 feature, hardened

- **The reported bug.** `hooks/scripts/toolkit_surface.sh` and `skills/context/scripts/cmd_toolkit.sh` shipped in v6.1.2 with git mode `100644` (non-executable). The SessionStart hook is invoked by path, so it failed with `Permission denied` on every new session. Both are now `100755`. A new regression guard — `hooks/tests/test_exec_bits.sh` — asserts every path-invoked hook/CLI script carries the executable bit (the smoke harness runs scripts via `bash <file>`, which is mode-agnostic, so this class slipped past every other test).
- **CLI ↔ docs reconciliation.** The documented `add` syntax was unusable (`add <name> --desc=… --global` while the CLI required `--name=`, `--description=`, `--scope=global`). The CLI now accepts the ergonomic aliases `--global` / `--local` (for `--scope=…`) and `--desc` (for `--description`); `commands/toolkit.md` and `doctrines/toolkit.md` are corrected to match.
- **Doctrine accuracy.** Dropped `api` from the canonical type enum (it is non-canonical → WARN); marked `scope` + `capabilities` *required* (the `validate` command enforces them); reworded the over-promising "pinned never drop" and "add is idempotent" claims to match the code (add refuses duplicates; pinned-first within the cap).
- **Bounded injection + defensiveness.** `shctx toolkit md` (the brief-injection surface) now caps at 12 entries, pinned-first, matching the SessionStart hook; interactive `list` stays uncapped. Empty-`capabilities` rendering is guarded. New `hooks/tests/test_toolkit_surface.sh` covers merge / local-wins / pinned-first / 12-cap / graceful-empty; `test_toolkit.sh` gains alias coverage.

### bash 3.2 portability (macOS default `/bin/bash`)

Three hooks/CLI scripts used bash-4-only constructs that silently broke on the operator's platform:

- **`hotfix_vehicle_guard.sh` (#135).** Used `${SUBAGENT_TYPE,,}` (bash-4 lowercase) → "bad substitution" on 3.2, so an `H=1` hotfix spawned as a `shepherd:conductor` teammate slipped past the guard. Replaced with portable `tr`. The guard's primary case now actually enforces — `test_hotfix_vehicle_guard.sh` goes 9/10 → 10/10.
- **`precompact_snapshot.sh`.** The retention trim used `mapfile` (bash 4+); on 3.2 it died under `set -u`, so snapshots were *written but never trimmed* — the "so many precompact files" pileup. Replaced with a portable read loop; retention (default 5) now holds.
- **`cmd_issues.sh`.** `declare -A` (associative arrays) is a fatal "invalid option" on 3.2, breaking `shctx issues` outright. Reworked to safe `printf -v` / `${!var}` indirection (no `eval`).

These two fixes turn the hooks smoke suite from 33/35 → **37/37** (the two newly-green tests plus the two new toolkit tests).

### Precompact snapshots — relocated + meaningful

- **Relocated** from `<workdir>/snapshots/` to **`<workdir>/memory/snapshots/`**, co-located with other ephemeral rehydration state. Writer (`precompact_snapshot.sh`) and reader (`focus_rehydrate.sh`) move together; a fail-open one-time migration sweeps any snapshots from the legacy location, and the reader falls back to it so an in-flight snapshot taken before the upgrade still rehydrates.
- **Kept (they are meaningful):** snapshots carry the focus digest, graph cursor, trace tail, mailbox, and lock state — the load-bearing compaction-resilience payload. The "noise" perception was the broken retention (above), now fixed.

### Outcome enforcement — make the seeded outcome close the sprint

Shepherd ships code and green gates reliably but drifts off the *outcome* a seed promised. New `doctrines/outcome-enforcement.md` binds outcome verification to four existing seams, **behavioral wiring only — no new schema or state table**:

- **Seam 1 — SEED:** each `seed §6` deliverable's acceptance is a *runnable* predicate (grep+count / structural assertion / LOC floor / log·metric·DB query / health probe), not prose (`references/seed-template.md §6-bis`).
- **Seam 2 — PLAN-GATE:** the `@critic` confirms every deliverable carries a runnable predicate; a plan that drops one or leaves prose-only fails with `PLAN-MISSING-OUTCOME-VERIFICATION` (`agents/critic.md`).
- **Seam 3 — CLOSE (the enforcement point):** the close auditor *re-runs* every seeded predicate against live HEAD/state **before** grading; a promised-true predicate that now returns false is an `OUTCOME-REGRESSION` (HIGH) that caps the completeness grade (`agents/auditor.md`, `agents/conductor.md §3`, `references/grading-rubric.md`). Reuses the same read-only re-run INTRO already runs on the *prior* sprint.
- **Seam 4 — SOAK (optional, post-close):** a new **SOAK-LOOP** template (`references/loop-templates.md`, a WATCH-LOOP specialization) re-verifies the predicates on a wall-clock interval (T+1d, T+7d) via native `/loop` + `Monitor`, surfacing `OUTCOME-REGRESSION` on post-delivery drift. Detection-only; never auto-remediates. Invoke: `/shepherd:loop "soak outcomes for <sprint>" --agent worker --interval 1d --max 6`.

### Retired-command cleanup

Deleted the thin retired-redirect stubs (`/shepherd:autorun` + `/shepherd:parallel`, retired since v5.1.4): `commands/{autorun,parallel}.md` and `skills/shepherd/{autorun,parallel,planter}.md`. References in `CLAUDE.md` and `SKILL.md` are scrubbed; the live `--auto` / `--parallel <N>` flags, the `[autorun].min_grade` config key, and the `shepherd-parallel-<slug>` teammate-naming prefix are unaffected.

### Doctrine + brief fixes (batched issues)

- **#61** — `agents/engineer.md` gains a work-shape→vehicle tier-matching table so a conductor/teammate is not allocated for single-file or markdown work.
- **#100** — `agents/conductor.md` boot adds a hard W0-GATE precondition: no body batch fires until INTRO ground-truth certification has passed (block-and-recheck, never proceed-and-hope).
- **#120** — the planter (`agents/planter.md`, `commands/plant.md`) now has a fresh-project bootstrap: when `.claude/shepherd.toml` is absent it surfaces `examples/minimal/shepherd.toml` and stops for operator confirmation.
- **#123** — reconciled the `-dev.N` seed-filename conflict: intermediate per-sprint seeds may carry `-devN`; the version-scale-roadmap restriction applies only to final shipped artifacts (`doctrines/version-scale-roadmap.md`, `references/seed-template.md`).

### Closed as verified-shipped

Verified present + wired and closed: **#107** (toolkit registry, v6.1.2), **#121** (namespace resolution parity, v6.0.8), **#134** (Focus Loop, v6.0.9), **#87** (compile telemetry, v6.0.9), **#103** (engineer model pin + `ENGINEER-MODEL-FAIL`, v6.0.3+), **#99** (teammate git guard, v6.0.9), **#119** (planter discovery wave, v6.0.7+), and **#135** (hotfix vehicle guard — fixed and now enforcing, this release).

### Test suite — repaired the `shctx` harness (23/40 → 40/40)

The `skills/context/tests` suite had 17 pre-existing failures (present on `main`) — not a sqlite issue (the migrations apply cleanly), but **v6.1.2 renames that never reached the test harness**:

- `root.db` → `shepherd.db`: `shctx init` now creates `shepherd.db`, but the harness (`_setup.sh`) and 22 tests still hardcoded `root.db` in their direct `sqlite3` queries → "no such table" against a fresh empty file. Renamed throughout (leaving `test_workdir.sh`'s intentional legacy-detection assertions).
- `plans/`+`reports/` → `docs/plans/`+`docs/reports/`: `test_init` / `test_lint` referenced the pre-v6.1.2 top-level dirs the scaffold no longer creates.
- `cmd_doctor.sh` hard-coded the label `root.db` regardless of the actual file — now reports the real `shctx_db_path` basename (a real cosmetic bug).
- `test_compile_telemetry` asserted spaced JSON (`"…": 1`) against compact output (`"…":1`).

Both suites now pass clean: **hooks 37/37, context 40/40**.

---

## v6.1.2 — 2026-06-11

The self-improvement-substrate release: a persistent **tool toolkit** so a session never forgets a capability, a standardized + back-compatible workdir layout, **per-flock-role loop templates**, discovery waves on Dynamic Workflows, and a flock-profile polish pass.

### Toolkit — persistent tool memory (operator request)

The flagship of this version. A mutable registry (`toolkit.json`) of commonly-used tools — MCP servers, skills, plugins, CLIs, ssh targets — so a Claude Code session never forgets a capability exists and the operator never has to re-explain it (e.g. `ssh pzzld@laptop` for a self-hosted dev surface, the `context7` MCP). It is the **tool-memory sibling** of the adaptation loop's lesson-memory (`doctrines/self-improvement.md`).

- **Two tiers, merged at read time.** Project-local `<namespace>/toolkit.json` (tracked) ⊕ user-global `$XDG_CONFIG_HOME/shepherd/toolkit.json`; the `scope` field routes each entry, and local overrides global on name collision — so cross-project tools live once, globally.
- **Entry schema.** Required `{ name, scope (local|global), type (mcp|skill|plugin|cli), capabilities[], description }` plus optional `invocation`, `when`, `tags`, `pinned`. JSON Schema at `skills/context/references/toolkit.schema.json`; the validator warns (never fails) on a non-canonical `type` so ssh/service targets are permitted.
- **CLI.** New `skills/context/scripts/cmd_toolkit.sh` (registered in `shctx`): `toolkit list|add|rm|pin|unpin|show|md|init|validate`. Lazily creates the file on first `add`; `md` emits compact markdown (graceful-empty — nothing on an empty registry, exactly like `shctx adapt priors`).
- **Three surfaces keep it in front of the model.** (1) A SessionStart hook `hooks/scripts/toolkit_surface.sh` injects a compact, ≤12-entry, pinned-first roster every session (fail-open; suppressed by `[hooks].quiet_warnings`); (2) the `shctx toolkit` CLI; (3) a `[TOOLKIT]` block injected into engineer/coder/planter briefs via `cmd_inject.sh` (variable-tail, cache-discipline-preserving).
- **Doctrine + command + examples.** `skills/shepherd/doctrines/toolkit.md` (bounded / graceful-empty / never-store-secrets), `commands/toolkit.md` (`/shepherd:toolkit`), `examples/{axiom,minimal}/toolkit.json`, and the five tool-using agents (engineer, coder, worker, discovery, planter) gained a one-line toolkit-awareness nudge. Test: `skills/context/tests/test_toolkit.sh`.

### Standardized workdir layout — one consistent tree, totally back-compatible (operator request)

The per-project workdir now follows a standardized internal tree — `docs/{plans,reports,diagrams,handoffs,specs,journal}/`, `logs/`, `archive/`, `cache/`, `scripts/`, `templates/`, `tmp/`, `types/`, plus `toolkit.json` (tracked) and `shepherd.db` (gitignored). Adopted **additively** per the `#121` "never mass-rename" invariant.

- **`root.db` → `shepherd.db`, with auto-detection.** `shctx_db_path()` prefers `shepherd.db`, falls back to legacy `root.db`, defaults to `shepherd.db` for new projects — mirroring the existing `.shepherd/`↔`.artifacts/` resolution. Zero change for legacy trees.
- **`plans/` + `reports/` now nest under `docs/`.** `[paths]` defaults updated; `scaffold.sh` scaffolds the full tree with `.gitkeep` for tracked-but-empty dirs.
- **Opt-in migration.** `shctx migrate --layout v2` `git mv`s `plans/`→`docs/plans/`, `reports/`→`docs/reports/`, renames `root.db`→`shepherd.db`, and creates the new dirs — idempotent, no-clobber.
- **`*.{group}.{ext}` naming, formalized.** `references/naming-conventions.md` documents the uniform `<slug>.<group>.<ext>` rule and adds log patterns `{date}.log.md` (human) + `{ts}.log.jsonl` (machine); `cmd_lint.sh` accepts both the legacy and new locations + log groups. `.gitignore` covers `shepherd.db*` under both namespaces and keeps `toolkit.json` tracked.

### Per-role loop templates — bounded, role-shaped Loop-Until-Done (operator request)

`/shepherd:loop` (Pattern 6) gains a per-flock-role catalog so the loop primitive is reusable per agent. New `skills/shepherd/references/loop-templates.md` defines seven templates — **CODER-CONVERGENCE** (fix-until-green), **DISCOVERY-EXHAUST** (research-until-comprehensive), **WORKER-WATCH** / **WORKER-CONVERGENCE**, **AUDITOR-REFINE**, **ENGINEER-PLAN-REFINE**, and the orchestrator's **FOCUS-LOOP** — each specializing an existing composite, each with a hard `--max` cap and a measurable terminate-on predicate. New binding doctrine `skills/shepherd/doctrines/loop-templates.md`; `commands/loop.md` points operators at the catalog. No new halt codes (reuses the v6.0.9 circuit-breaker set).

### Discovery waves compile to Dynamic Workflows (operator request)

All discovery fan-out now compiles like coder/audit fan-out instead of dispatching as inline Agent batches. `doctrines/workflow-compile-down.md` §V documents `INTRO-COMBO-WAVE` and `DISCOVERY-COMBO-WAVE` as compile targets (gate-free, parallel-safe → one `Promise.all` of discovery + auditor [+ worker] spawns); `intro-combo-wave.md` and `discovery-combo-wave.md` adopt the compile framing; `pipeline.md` gains the missing `DISCOVERY-COMBO-WAVE` taxonomy row. The compiler `cmd_graph.sh` was already role-agnostic (`spawns_for_node` expands any role mix) and verified end-to-end — the change is a clarifying comment plus a fixed latent bug where a node typed `dynamic_workflow` would not have matched the compiler's literal node-type key.

### Spawn flow — per-sprint context certification, teammate Dynamic Workflows, default FOCUS-LOOP (operator request)

Four coordinated `/shepherd:spawn` fixes so the team substrate behaves as designed:

- **Per-sprint context-certification wave.** The spawn-flow walkthrough now makes the root's INTRO-COMBO-WAVE explicit (it was mandated in `agents/shepherd.md` but omitted from `commands/spawn.md`'s flow): `@discovery` × N gather ground-truth, intro-mode `@auditor` × 2 **certify** it (regression / carry-forward / freshness) — the sprint's own certifiable current context. Always-on under spawn (every T-shirt) and **fresh per sprint** — each `--scope patch`/`--auto` sprint and each `--parallel` sibling certifies its own; a prior sprint's context is never inherited. `intro-combo-wave.md` gains the spawn framing.
- **Teammate-conductors compile their lane fan-out.** The contract required it (`dispatch-cascade.md §IV-bis`, `conductor.md`) but no operational instruction existed, so teammates dispatched in-context. Added the explicit `shctx graph compile --segment=<entry> --verify` → run → `shctx graph mark` sequence (in-context fallback only on confirmed runtime failure) to the `commands/spawn.md` teammate boot prompt and `agents/conductor.md` Step 2 + hard-prohibition #22; hand-rolled in-context step fan-out is a `PRIMITIVE-INVERSION` off-substrate violation. Reconciled the self-contradictory `SKILL.md §X`: under spawn, **both** root and each teammate compile their respective fan-out (mode-agnostic).
- **Root adopts the FOCUS-LOOP by default on team init.** Coordinate mode is reframed as *operating* the Pattern-6 FOCUS-LOOP (wake → act → probe, opened at SEED-VERIFY), entered the instant teammates spawn — the active engine, not a passive focus-record write backstopped only by `coordinate_drive_guard.sh`. The root stays engaged and drives until CLOSE-FINALIZE.
- **Long-running conductors adopt their own FOCUS-LOOP.** A teammate-conductor opens a lane-keyed focus loop at Step 0 (lane start, before any node — so a teammate that skips INTRO still gets one) and runs wake → act → probe over its lane micro-Stage-Graph, refreshing at each wave so a long lane doesn't drift.

All four default-on, config-gatable via the new `[focus].loop_default` key; doctrine framing in `coordinate-active-drive.md`.

### Flock profile polish

Description-field shrink for the two genuinely bloated meta profiles — `conductor` (198→157 chars) and `shepherd` (195→152) — moving mode/tier detail into the body; `planter`/`auditor` tightened further. Frontmatter already consistent across all nine (`name → color → model → thinking → description → tools`); no value changes.

### Foundation

- Version moved to 6.1.2 across the six sources of truth (`plugin.json`, `marketplace.json` ×2 keys, both `SKILL.md` frontmatters, `README.md`, this file).
- Removed a stray tracked `err.txt` and the dogfood repo's `.artifacts/` tree reorganized onto the standard layout (`plans/`+`reports/` → `docs/`).
- All new bash honors house style — `set -uo pipefail`, source `_lib.sh || exit 0`, exit-0-always hooks, `resolve_namespace`/`resolve_workdir` (never hardcoding `.artifacts`/`.shepherd`), and graceful-empty reads. New test auto-discovered by `skills/context/tests/run.sh`.

---

## v6.1.0 — 2026-06-09

### Spawn pane-massacre containment — blanket worktree teardown can no longer run mid-sprint (#141)

A `/shepherd:spawn` session tore down every live teammate's worktree mid-sprint. A root re-engaged by the coordinate-drive `Stop` hook ran the blanket `git worktree list | grep agent- | … remove --force` loop (followed by `git worktree prune`) **while teammates were still live in their tmux panes** — every pane's worktree vanished, every teammate session died, and the lead quit with them. Compounding it, teammates had booted at the lead session's Opus-4.8 model instead of the conductor's pinned `sonnet`, multiplying cost by the lane count. Five guards close the gap:

- **`teammate_git_guard.sh`** now denies `git worktree add|remove|prune` from teammate sessions (previously only `merge|rebase|push|cherry-pick`), while still allowing read-only `git worktree list`. The missing coverage was exactly the command that caused the incident.
- **New `worktree_teardown_guard.sh`** (`PreToolUse(Bash)`, registered in `hooks/hooks.json`) hard-denies blanket `git worktree prune` and `list | … | remove` sweeps whenever `v_teammates_live > 0`, emitting the `WORKTREE-TEARDOWN-LIVE` halt code. Scoped single-lane `git worktree remove .worktrees/<slug>-<lane>` is still allowed. Config-gated via `[spawn].worktree_teardown_guard = block | warn | off`; fail-open on any uncertainty.
- **`agents/conductor.md` Step 8 + `agents/shepherd.md` RF-5** gate the blanket teardown loop on `v_teammates_live == 0` — it is a CLOSE-only sweep, never a mid-sprint action.
- **`doctrines/coordinate-active-drive.md` + `coordinate_drive_guard.sh`** redefine idle-prune as scoped, per-lane worktree removal by explicit path, never the blanket loop — killing the trigger path where the `Stop` hook nudged the root to "prune idle teammates."
- **`commands/spawn.md`** makes an explicit `model: sonnet` pin mandatory in the `TeamCreate` instruction and adds a pre-spawn Opus cost advisory — teammates were inheriting the lead session's model rather than the `shepherd:conductor` definition's frontmatter.

Verification: 35/35 hook smoke tests pass (`bash hooks/tests/run.sh`), including the extended `test_teammate_git_guard.sh` (worktree cases) and the new `test_worktree_teardown_guard.sh` (#141 blanket-teardown gate).

---

## v6.0.9 — 2026-06-09

<!-- GROUPING CONVENTION (#130): buckets in fixed order — Focus loop / Compaction, Template loops, Hotfix dispatch, Teammate integration, Telemetry, Foundation. Each `###` heading names its concern + issue refs. -->

### Focus Loop + compaction resilience — survive compaction by snapshot + rehydrate, not by self-trigger (#134)

Honest framing first: current Claude Code exposes **no** way for an agent to trigger or steer its own compaction, and **no** machine-readable context-budget surface. The only official threshold lever is the global env var `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`. So "stay on-track through compactions" is implemented as making compaction **safe** (snapshot the drive-state + rehydrate) and **predictable** (documented threshold), keyed off a durable focus record — not as the (impossible) self-timed compaction.

- **Loop foundation (closes the v6.0.7 overclaim).** `/shepherd:loop` advertised `shctx loop init|record|close|status|list` but had no backing — no `cmd_loop.sh`, no `loop` table, no dispatcher entry. New `skills/context/scripts/cmd_loop.sh` + migration `0012_loop_state.sql` (`loops` + `loop_iterations` + `v_loops_active`) + a `loop` entry in the `shctx` allowlist implement the full verb surface, plus a `focus <upsert|show>` verb.
- **Focus record.** Migration `0013_focus.sql` (`focus` table + `v_focus_current`) — the sprint north-star: objective, active node, ready-set, obligations, invariants. It lives in `root.db`, so it survives compaction natively; written at SEED-VERIFY, refreshed at each WAVE-GATE, finalized at CLOSE-FINALIZE (wired into `agents/conductor.md` + `agents/shepherd.md`).
- **PreCompact snapshot.** New `hooks/scripts/precompact_snapshot.sh` on the new `PreCompact` event captures the in-context drive cursor (`state.json` ready/in_flight, `trace.jsonl` tail, undrained `mailbox`, `shepherd.lock`, focus digest) to `<ns>/snapshots/`, sets a rehydrate-pending flag, trims to `[compaction] snapshot_retention` (default 5), and **never blocks compaction** (exit 0).
- **Rehydration.** New `hooks/scripts/focus_rehydrate.sh` on `SessionStart` + `UserPromptSubmit` drains the pending flag once and re-injects the snapshot digest as `additionalContext`, so the orchestrator resumes its drive deterministically after a compaction.
- **Threshold doctrine.** `docs/configuration.md` documents the sole official knob (`CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`) — global, no per-model form, opt-in, **no shipped default** — with a ~70 suggestion for long Sonnet-root sprints. New `[compaction]` / `[focus]` config sections (both examples updated).
- **`/shepherd:focus`** (`commands/focus.md`) wraps `loop --kind=focus`; interval mode delegates to the native Claude Code `/loop`.

### Template loops — first Pattern-6 named composites (operator request)

Three named loop composites added to `skills/shepherd/references/workflow-templates.md` and the `skills/shepherd/doctrines/workflow-patterns.md` composite table — the **first** composites with `Pattern basis = Pattern 6` (alongside the existing Pattern-2 `INTRO-COMBO-WAVE` / `DISCOVERY-COMBO-WAVE` / `HOTFIX-BATCH`): **FOCUS-LOOP** (orchestrator self-orientation; the runtime shape of coordinate-mode drive), **CONVERGENCE-LOOP** (gate-rerun-until-green), **WATCH-LOOP** (interval monitoring via the native `/loop`). All declare a mandatory `max_iterations`, are Loop-OUTER (never nested inside a fanout iteration body, per the existing illegal-composition rule), and reuse the existing `PLAN-MISSING-LOOP-CAP` / `LOOP-REPORT-INVALID` / `LOOP-CAP` halt codes (no new codes).

### Hotfix dispatch — mechanical guard for the H=1 rule (#135)

The v6.0.8 cardinality ladder was doctrine-complete but **unenforced**. New `hooks/scripts/hotfix_vehicle_guard.sh` (`PreToolUse` Agent|Task) denies a teammate / `TeamCreate` spawn whose context is a single-cluster (`H = 1`) hotfix, emitting the now-registered **`WRONG-VEHICLE`** halt code (added to the halt-code tables in both `agents/conductor.md` and `agents/shepherd.md`). The doctrine itself is unchanged — this closes the enforcement gap, not a wording gap.

### Teammate integration authority — root-only merge, reviewed (#99 + operator)

Team-based conductors must **never** integrate their own worktree into the dev branch. New `hooks/scripts/teammate_git_guard.sh` (`PreToolUse` Bash) denies dev-branch integration commands (`git merge` / `rebase` / `push` / `cherry-pick`) from teammate sessions — keyed on the `teammates` table by `session_id` — while still allowing legitimate in-worktree `git add` / `git commit`, emitting the registered **`TEAMMATE-GIT-WRITE`** halt code. A new **`LANE-INTEGRATE`** seam (`skills/shepherd/pipeline.md` + `agents/shepherd.md`) makes integration a root-exclusive, **size-gated reviewed** decision: small diffs root-reviews inline; lanes ≥ 200 changed lines get an `@auditor` diff-review concern before merge. New binding doctrine `skills/shepherd/doctrines/teammate-integration-authority.md`.

### Compile-down telemetry — measurable pilot feedback (#87)

New migration `0014_compile_runs.sql` (`compile_runs` + `v_compile_runs_sprint`) captures, per compiled segment per run: segment size, peak concurrency vs the ceiling, the §IV faithfulness-diff result (the structured object `shctx graph compile --verify` already emits), seam-handoff outcome, and every degradation-to-direct-dispatch event with its cause. `shctx adapt` gains a `## Compile-down telemetry` close-report subsection (mirroring the existing cache-telemetry precedent over `v_cache_usage`). The dead `shctx graph trends` reference in `dispatch-cascade.md §VII` (never implemented) is repointed to the live `shctx adapt report --trends`. A **deliberate degradation test** (`skills/context/tests/test_compile_telemetry.sh`) exercises the direct-dispatch fallback — the path #87 flagged as the real risk.

### Foundation — design spec, tests, namespace discipline

- Authoritative design-of-record: `.artifacts/docs/specs/2026-06-09-v609-focus-loop-and-compaction-resilience.spec.md` (four-pass: goals/deliverables, assumptions/constraints, diagrams, derivations).
- New tests, all registered in their harnesses: `skills/context/tests/test_loop_lifecycle.sh`, `test_compile_telemetry.sh`; `hooks/tests/test_precompact_snapshot.sh`, `test_focus_rehydrate.sh`, `test_hotfix_vehicle_guard.sh`, `test_teammate_git_guard.sh`.
- All new hook scripts honor house style — `set -uo pipefail`, source `_lib.sh || exit 0`, **exit 0 always** (decision via stdout JSON), config-gated, runaway-bounded, and namespace-resolved via `resolve_namespace` / `resolve_workdir` (never hardcoding `.artifacts` / `.shepherd`, per #121).
- Version already at 6.0.9 across the six sources of truth (bumped at branch cut); this section is the hand-authored record.

---

## v6.0.8 — 2026-06-09

<!-- GROUPING CONVENTION (#130): within a patch section, organize `###` headings into concern buckets in this fixed order — Planter / Models, Hotfix dispatch, Adaptation, Namespace / Hooks, Foundation. Each `###` heading names its concern and cites its issue refs inline as `(#NNN)`. One heading per coherent change; a change spanning files stays one heading. This keeps multi-lane patches coherent without a separate index. -->

### Planter model policy + discovery wave — hard ABORT becomes soft ADVISORY, root engineer pin hardened (#119, #103)

The planter's wrong-model gate no longer aborts. Opus (`claude-opus-4-8` / `claude-opus-4-8[1m]`) remains the RECOMMENDED default; Fable 5 (`claude-fable-5`) is documented as the SUPERIOR (pricier) upgrade; Sonnet (`claude-sonnet-4-6`) and Haiku (`claude-haiku-4-5-20251001`) are ALLOWED with a degraded-seed-quality WARNING.

- **`commands/plant.md` + `agents/planter.md`:** the `## Step 0 — Model gate` hard-ABORT block (`PLANTER ABORT — wrong model`) is replaced by `## Step 0 — Model advisory` — a tier table (Fable 5 superior · Opus recommended · Sonnet/Haiku allowed-degraded) that emits a one-shot `PLANTER MODEL ADVISORY` and then proceeds. Planting never refuses on tier. The frontmatter descriptions, the "You are model opus because…" prose, the halt-code table row, and the "every minute of planter Opus time…" closing line are all reframed from necessity to recommendation. The planter `model:` frontmatter default stays `opus[1m]` (the recommended default is unchanged — only the gate softens).
- **Bounded discovery wave (#119):** the planter's Hard-prohibition #1 carves a strictly bounded exception — in plant mode, for a broad/unfamiliar scope, the planter MAY fan out a read-only `@discovery` wave (1–3 parallel lanes, `subagent_type=shepherd:discovery`, never the flock pipeline) that feeds the 12-row planter mesh. A new `§Step 2-bis` documents the bounds (read-only, scope-partitioned, Pattern A/F) and reconciles it against `intro-combo-wave.md` / `discovery-combo-wave.md`. The `Agent` tool is granted at the front of the planter `tools:` list to enable this dispatch; `hooks/tests/lint_agent_capabilities.sh` pins the grant to its documented read-only `shepherd:discovery` scope (a planter that grants `Agent` must document the discovery-only bound), so the grant cannot silently broaden to `@coder`/`@auditor` without the prose contract.
- **Root engineer model pin HARDENED (#103) — kept HARD, contrasted with the soft planter advisory.** The single root `@engineer` dispatch (`agents/shepherd.md`) now pins the explicit model id `claude-opus-4-8[1m]` at the dispatch site (with the 200k `claude-opus-4-8` documented as a fallback if `[1m]` is unavailable) rather than relying on the frontmatter alias resolving silently. A model-resolution / unavailable / API error surfaces `ENGINEER-MODEL-FAIL` and PAUSES — never treated as an empty plan, never silently retried, never advanced to the `@critic` gate. This is a **HARD halt**, explicitly distinguished from the planter's **SOFT** `PLANTER MODEL ADVISORY`: the engineer's Opus tier is the single point of failure for the sprint INTRO phase, so it must stop, not warn. The planter softening deliberately does NOT leak into the engineer pin.

### Hotfix dispatch ladder — reach for a dynamic workflow before a teammate (#135)

New binding doctrine `skills/shepherd/doctrines/hotfix-dispatch.md` defines the hotfix cardinality ladder over `H` = the count of file-disjoint independent hot-fixes:

- **`H = 1`** → ONE single subagent via a dynamic-workflow `agent()` step — **NEVER a teammate** (and only after confirming the fix is not merely awaiting another agent's result; re-count first). Fixes the v6.0.x defect where the shepherd spun up a hot-fix teammate for a single-coder dispatch.
- **`H ∈ (1, 5]`** (domain notation; excludes 1, includes 5) → ONE batched dynamic workflow dispatched **directly by the root shepherd** (conductor inline in solo) — not delegated to a teammate.
- **`H ≥ 6`** → a dedicated HOT-FIX lane: one teammate-conductor instance with its own Stage-Graph loop to drive the batch to convergence (spawn-mode only; solo surfaces a `HARD-STOP` recommendation). The `H = 6` boundary is hard.

The ladder selects the **vehicle**; the existing **≤3 concurrent coders** and **3 HOTFIX iterations** caps are orthogonal and still bind inside whichever vehicle is chosen. Wired into `agents/conductor.md` (new HOTFIX-vehicle walk-tick bullet), `agents/shepherd.md` (the HOTFIX-CLOSE default — formerly "re-spawn a small teammate" — now follows the ladder), `skills/shepherd/pipeline.md` (§II HOTFIX-DYNAMIC cardinality cross-ref + §XVI See also), and `skills/shepherd/doctrines/workflow-patterns.md` (named-composite `HOTFIX-BATCH` row for the `(1,5]` Pattern-2 fanout + See also).

### Adaptation surface — trends report, prior decay, recommend verb (#103)

Three slim, SQLite-canonical, graceful-on-empty additions to the `shctx adapt` surface (no schema migration — `updated_at` already exists):

- **`shctx adapt report --trends`** mechanizes `doctrines/adaptation-loop.md §VI` deterministically: a pure-SQL `TREND ALERT` over the last 3 sprints detecting (a) a HIGH/CRITICAL concern recurring in ≥2 of 3 sprints, (b) sprint grade trending strictly worse (A→B→C), and (c) avg wall/api cost rising sharply (newest ≥ 1.5× oldest). Emits nothing on insufficient history; `--md`/`--json`.
- **Prior decay in `shctx adapt roll`:** every recurrence touches the prior's `updated_at` (last-seen); unpinned `kind='prior'` rows not re-seen within `SHCTX_ADAPT_DECAY_SPRINTS` sprint closes (default 6) are pruned via a measured inter-sprint-gap cutoff, so the store self-cleans over long arcs. Bounded (deletes only), idempotent, pin-protected, and graceful (a young store with <2 sprints never prunes).
- **`shctx adapt recommend [--md|--json]`** turns measured `sprint_metrics` averages + recurring priors into a concrete dispatch RECOMMENDATION (suggested lane count, t-shirt size band, watch-concerns); empty store ⇒ "no history yet, use defaults". Wired into the engineer `[DB-CONTEXT]` (omit-when-empty), routed through the dispatcher usage stanza, and covered by new `test_cmd_adapt.sh` cases (trends fire / graceful-empty, decay prune-vs-pin, recommend md/json fields).

### Namespace resolution — hooks/skills parity, single `${SHEPHERD_WORKDIR}` point (#121, #122)

- **(#121) Hooks/skills namespace split-brain fixed.** `hooks/scripts/_lib.sh::resolve_namespace` auto-detected `.artifacts` before `.shepherd` and defaulted to `.artifacts`, contradicting the documented contract and the skills-side `resolve_workdir`. A default-`.shepherd/` consumer's 12 hook scripts would write event logs / dispatch tags / locks into a different directory than the shctx runtime reads. Fixed: precedence realigned to `SHEPHERD_WORKDIR` → `SHCTX_ROOT_OVERRIDE` → existing `.shepherd/` (tie-break winner) → existing `.artifacts/` → default `.shepherd/`, exactly matching the skills lib and `docs/configuration.md §SHEPHERD_WORKDIR`. The header comment was corrected, `adaptation-loop.md §23` brought in line with the resolved-path phrasing, and a new `hooks/tests/test_resolve_namespace.sh` (6 cases, registered in `hooks/tests/run.sh`) pins the contract so the divergence cannot silently return. Behavior-neutral for this repo and the axiom project (both run a single pre-existing `.artifacts/` tree).
- **(#122) Close-finalize false-positive — regression test pinned.** The destructive-instruction false positive (a PRIOR sprint's close report committed and reachable from the current LIVE branch's HEAD triggering a delete of the live branch) was already fixed by the v6.0.7 `#127` slug-scoped `close_finalize_check.sh` rewrite. Verified by live repro and now pinned by a new step-4b regression case in `hooks/tests/test_close_finalize_check.sh` (prior-sprint close report in HEAD + current live sprint branch on origin → no block).

### Foundation — version bump, changelog grouping, release mechanics (#130)

- Version bumped 6.0.7 → 6.0.8 across the six sources of truth.
- Introduced the **#130 CHANGELOG concern-bucket grouping convention** (this section's structure; recorded as an HTML comment at the top of each patch section): a fixed bucket order — Planter/Models, Hotfix, Adaptation, Namespace/Hooks, Foundation — over the repo's existing flat `### <concern> (#refs)` heading idiom, so multi-lane patches stay coherent without a separate index.
- **`shctx release` JSON bumper fix:** `bump_file()`'s `json)` case now patches BOTH the top-level `.version` AND any nested `plugins[].version` (guarded by `has("plugins")`), so `marketplace.json`'s nested plugin-block version stops silently drifting at release time. `plugin.json` has no `plugins` key, so the guard makes it a no-op there.
- `CLAUDE.md` `## Shepherd file contracts` inventory updated for the new `hotfix-dispatch.md` doctrine (plus the already-shipped v6.0.7 `workflow-patterns.md`), the planter advisory-model + discovery-wave change, the marketplace dual-key version-sync note, and the `${SHEPHERD_WORKDIR}` hook namespace-resolution contract.

---

## v6.0.7 — 2026-06-04

### Stop hook: close-finalize check converted to deterministic script (#127 fires #1–17)

The `type: "agent"` close-finalize Stop hook prompt has been replaced with a deterministic shell script (`hooks/scripts/close_finalize_check.sh`). This closes the long-running false-positive chain (#127) that survived the v6.0.6 prompt hardening.

**Fire #17 (trigger for this fix):** `/shepherd:plant` for `v0.3.5-dev.0` committed a planter mesh report (`2026-06-04-planter-mesh.md`) to `.artifacts/reports/`. The agent saw "a report committed to reports/ on a dev branch that exists on origin" and emitted CLOSE-FINALIZE INCOMPLETE, ignoring that the filename doesn't match the `*v035-dev0-close.md` slug pattern. Plant-mode artifacts in the reports directory are a new context trigger for the agent's free-form failure mode.

**Root cause (shared by all 17 fires):** an agent-type hook free-forms `ok: false` from session context rather than mechanically applying detection logic. Fire #10 showed the hook can "correctly diagnose everything... and still return ok:false." A script cannot override its own logic with narrative context.

**Script invariants vs prior agent prompt:**

| Check | Old (agent prompt) | New (script) |
|-------|--------------------|-------------|
| Sprint-branch guard | agent regex | `[[ $BRANCH =~ -dev\.[0-9]+$ ]]` |
| Subworktree guard | agent compare | `pwd -P == git show-toplevel` |
| Slug derivation | agent inference | `sed` — strict `^[0-9]+-dev[0-9]+$` sanity |
| Signal A scope | `--all` (all refs!) | `HEAD` only — excludes other branches/worktrees |
| Signal A pattern | `*${slug}*close*.md` (loose) | `{NS}/reports/*-v${slug}-close.md` (exact convention) |
| Plant-mode artifacts | not excluded (fire #17) | don't match strict pattern; implicitly excluded |
| Signal A empty → | agent may override | `exit 0` — hard coded, no override possible |
| Destructive remediation | `git push origin --delete` in reason | removed entirely |
| Failure mode | free-form ok:false | exit 0 (fail-open on every error) |

### Six canonical workflow pattern templates (`references/workflow-templates.md`)

Added a new reference defining the **six canonical workflow patterns** that form the structural vocabulary for every Stage Graph authored under `/shepherd:plant`:

| # | Pattern | Flock binding | Key use |
|---|---------|---------------|---------|
| 1 | **Classify-And-Act** | `@discovery` → branch → target agent | Unknown task routing |
| 2 | **Fanout-And-Synthesize** | parallel `@coders`/`@workers` → synthesizer | Parallel decomposable work |
| 3 | **Adversarial Verification** | producer → `@auditor` swarm (no shared context) | High-stakes artifact validation |
| 4 | **Generate-And-Filter** | parallel generators → `@critic` gate (rubric + dedupe) | Multiple viable approaches, rubric selects |
| 5 | **Tournament** | N attempts → bracket `@critic` pairs → final judge | Comparative ranking over rubric scoring |
| 6 | **Loop-Until-Done** | `@worker`/`@discovery` → check node → conditional back-edge | Convergent iteration; `max_iterations` required |

Each pattern entry covers: ASCII diagram, when-to-use trigger conditions, Stage Graph shape with YAML node/edge notation, flock agent binding table, composition notes, and anti-patterns. A composition index maps the six legal cross-pattern compositions (prefix routing, sequential pipeline, layered verification, nested iteration, competitive implementation, routed competition).

### Workflow pattern selection doctrine (`doctrines/workflow-patterns.md`)

Added a new **binding doctrine** that makes pattern selection an explicit, enforced Phase 0 decision rather than an implicit conductor judgment:

- **Decision tree (Q1–Q4):** deterministic selection from "task type unknown?" through "parallel decomposable?" through "adversarial challenge needed?" through "convergent iteration?" to direct dispatch for XS leaf nodes.
- **Composition grammar:** legal vs illegal pattern nestings, with three axes (prefix routing, sequential pipeline, nested iteration). Illegal compositions include Generate-And-Filter inside Tournament, Loop inside Fanout body, and Adversarial Verification as classifier.
- **Circuit-breaker invariants per pattern:** non-overlapping scope guarantee (Pattern 2), rubric-before-dispatch invariant (Pattern 4), bracket-declaration and match-isolation requirements (Pattern 5), mandatory `max_iterations` and structured `new_findings` field (Pattern 6).
- **Rigor additions:** checkpoint nodes for L/XL compositions (materializes state to `shctx sprint record` at composition boundaries), escalation laddering (L1–L4 escalation levels replace bare HALTs), and a composition depth limit of ≤3 levels (critic gates justification for deeper nesting, `COMPOSITION-TOO-DEEP` halt code).
- **Enforcement surface:** nine new halt codes wired to existing enforcement points (dispatch guard, PLAN-GATE, preflight doctor, conductor inline).
- **Pattern-to-flock alignment table:** canonical role bindings per pattern — wrong agent type for a role is `DISPATCH-WRONG-ROLE`.

### `/shepherd:loop` command (`commands/loop.md`) — NEW v6.0.7

Added a first-class slash command that runs **Pattern 6 (Loop-Until-Done)** directly from the operator interface:

- **Flags:** `--max <N>` (iteration ceiling, default 5; > 10 requires operator acknowledgement), `--agent <worker|discovery>`, `--interval <duration>`, `--until <field>`, `--resume <loop-id>`
- **In-session mode:** shepherd drives the `wake → act → probe → yield` coordinate cycle directly, dispatching one iteration per turn until convergence or cap
- **Interval mode:** when `--interval` is set, shepherd registers the loop state in SQLite then delegates recurring scheduling to the native Claude Code `/loop` skill (`/loop <duration> /shepherd:loop --resume <loop-id>`); each wake-up runs exactly one iteration and exits
- **Circuit breakers:** `--max` is mandatory (validated in preflight); values > 10 require live operator confirmation; cap-exceeded emits `LOOP-CAP` halt rather than silently exiting; missing `new_findings` field emits `LOOP-REPORT-INVALID`
- **SQLite state:** `shctx loop init / record / close / status / list` verbs manage loop lifecycle in `.artifacts/root.db`
- **Halt codes:** `LOOP-INVALID-AGENT`, `LOOP-INVALID-INTERVAL`, `LOOP-REPORT-INVALID`, `LOOP-CAP`, `LOOP-STATE-MISSING`
- SKILL.md `metadata.triggers` updated to include `/shepherd:loop`; command added to §X invocation table

### SKILL.md §XI updated

Added `references/workflow-templates.md` and `doctrines/workflow-patterns.md` to the §XI file map with load-trigger annotations ("Phase 0 seed analysis; plan authoring; PLAN-GATE").
Added `commands/loop.md` to the §X invocation table.

---

## v6.0.6 — 2026-06-04

### Close-finalize hook false-positive fix — CRITICAL (#122, #127)

The Stop hook's close-finalize agent prompt triggered a false-positive mid-sprint that proposed `git push origin --delete <live-sprint-branch>`, which would orphan active lane worktrees and in-flight deploy refs. Root cause: three defects compounded:

1. `find . -path '*reports*' -name '*close*' -newer .git/HEAD` was unanchored (recursed into `.worktrees/`), not sprint-slug-scoped, and compared mtime (refreshed by worktree creation) instead of authorship.
2. The second condition (`git ls-remote --heads origin` non-empty) is always true mid-sprint under the proactive-push doctrine.
3. The destructive remediation (`git push origin --delete`) required only ONE positive signal.

**Fix:** The prompt now requires **two independent signals** before flagging: (a) a close report committed in git (`git log --diff-filter=A --all`) AND (b) the sprint branch still on origin. Replaced `find`-mtime detection with git-log-based authorship check scoped to the sprint slug. Added a subworktree fast-path (step 2) since `git rev-parse --show-toplevel` ≠ `pwd` when inside a worktree. Removed the destructive `--delete` command from the prompt entirely — the hook now directs the operator to conductor §CLOSE-FINALIZE steps rather than prescribing destructive remediation directly.

### Namespace drift fix — resolve_namespace defaults to .artifacts (#121)

Hook scripts created `.shepherd/logs/` unconditionally as the default namespace while docs and seed-template consistently use `.artifacts/`. When both directories co-existed, `.shepherd` won (checked first), causing a permanent split and a perpetual shctx warning.

**Fix:** `_lib.sh` `resolve_namespace()` now checks `.artifacts` before `.shepherd` and defaults to `.artifacts`. Projects with only `.shepherd` (older installs) continue to work via the fallback. Projects using `SHEPHERD_WORKDIR` are unaffected.

### Hardcoded MCP tool names removed from planter and seed-template (#124)

`agents/planter.md` hardcoded `mcp__plugin_github_github__*`, `mcp__plugin_sentry_*`, and `mcp__plugin_supabase_*` tool IDs in its YAML `tools` frontmatter and mesh table. In harness setups where GitHub MCP runs under a different server name (e.g. `mcp__github__*`, Docker MCP gateway, or CLI-only), those names are dead and agents silently fail to fetch the issue ledger.

**Fix:** Removed all `mcp__plugin_*` names from planter's YAML `tools` frontmatter; added `ToolSearch`. Added a callout box in the mesh section instructing the planter to discover available GitHub/Sentry/Supabase tools via `ToolSearch` at session start, with `gh` CLI as the fallback for GitHub. Updated `seed-template.md` Phase 0 mesh rows 1, 5, and 6 to the same ToolSearch-first pattern. Conductor's MCP tool list is unchanged (read-only tools, standard harness assumption).

### Plant bootstrap path for missing shepherd.toml (#120)

`/shepherd:plant` Step 1 assumed `.claude/shepherd.toml` existed and had no fallback for a first-ever plant. On a fresh project the planter hand-derived config from `examples/axiom/shepherd.toml`, producing inconsistent results.

**Fix:** `commands/plant.md` Step 1 now includes a bootstrap clause: if `.claude/shepherd.toml` is missing, the planter surfaces a clear instruction to copy from `${CLAUDE_PLUGIN_ROOT}/examples/minimal/shepherd.toml` and halts rather than guessing config values inline.

### Background process prohibition — conductor hard prohibition #21 (#108)

Conductor and worker agents repeatedly used `run_in_background: true` on long-running commands (`cargo check`, `cargo test`, build daemons). Background processes lose context on compaction, cannot be monitored turn-to-turn, and orphan when the session ends.

**Fix:** Added hard prohibition #21 to `agents/conductor.md`: `run_in_background: true` is forbidden in any tool call for both SOLO and TEAMMATE modes. Long-running work goes to `@worker` with explicit monitor-and-report briefs. `@worker` is also forbidden from backgrounding. Violation code: `BACKGROUND-PROCESS-SPAWN`.

---

### Sprint numbering: planter starts new patch arcs at dev.0, not dev.1 (field issue: FL03/pzzld v0.0.8)

When `/shepherd:plant` was invoked for a brand-new patch arc (no prior dev.N branches on origin), the planter derived the first sprint number from the prior patch's last sprint (e.g., v0.0.7-dev.5 → dev.6 for v0.0.8) rather than resetting to dev.0. This violates the hard invariant in `references/branching-model.md`: *"The sprint AFTER dev.{last} is dev.0 of the NEXT PATCH — never dev.{sprints_per_patch}."*

**Root cause:** `agents/planter.md` Step 3 documented scope dispatch but gave no algorithm for deriving N, leaving the model to infer from ambient context — which is wrong at patch-arc boundaries.

**Fix:** Added an explicit N-derivation block to Step 3:
1. Run `git ls-remote --heads origin 'v{X}.{Y}.{Z}-dev.*'` for the current patch version
2. If no dev.N branches exist → N = 0 (hard rule; brand-new patch arc)
3. If dev.N branches exist → N_next = highest existing N + 1
4. Explicit callout: do NOT use the prior patch's sprint counter as a base

Also updated `commands/plant.md` argument-hint and Step 2 note to surface this rule at invocation time.

---


## v6.0.5 — 2026-06-02

### Schema migrations: fix `ALTER TABLE … RENAME` view-dangling on SQLite ≥ 3.25 (debug-session find)

A debug session on the v6.0.5 cut surfaced a **pre-existing, release-blocking** defect
unrelated to the spawn work: migrations `0009_locks_mode_sprint.sql` and
`0011_mem_entries_prior_kind.sql` (recreate-table migrations) ran `DROP TABLE` + `ALTER
TABLE … RENAME TO` **while the dependent view still existed** (`v_active_locks` /
`v_mem_recent_7d`), dropping the view only afterward. On SQLite ≥ 3.25.0 `RENAME`
validates every view/trigger in the schema, so the rename aborted with `error in view
…: no such table: …`. Because `0009` halts mid-chain, `0010`/`0011` never applied —
**every fresh `shctx init` and `shctx sprint open` was broken on modern SQLite**
(observed on 3.45.1), and the context test suite ran **24/37**.

- Fix: drop the dependent view **before** the table swap in both migrations; recreate it
  after the rename. Net schema is identical — only the statement order changes to satisfy
  SQLite's modern `RENAME` validation. Idempotent migrations already applied on older
  SQLite are unaffected (the `schema_versions` guard prevents re-run).
- After the fix: full migration chain applies (11 versions), all three dependent views
  query, and the context suite is **37/37** (was 24/37).
- **Root-cause note:** this shipped because **no CI runs the test suites** (only
  `release.yml` exists). Recommend adding a workflow that runs `hooks/tests/run.sh` +
  `skills/context/tests/run.sh` on a modern SQLite — tracked as a follow-up.

### Coordinate-mode active-drive — `/shepherd:spawn` no longer pauses at the dispatch boundary (#113 / #98 / #112)

Closes the single most expensive `/shepherd:spawn` failure: **the root pausing the
moment it dispatches teammate-conductors.** After `TeamCreate` the root's turn ended
and it waited passively — there was no contract for the window between "team spawned"
and "first teammate event," and the default LLM behavior in that gap is to stop. The
operator (who chose spawn precisely to step away) returned to a session paused at the
dispatch boundary with nothing shipped (a full day lost in the field report that
motivated this). Passive `TeammateIdle` waiting "only fires when a conductor goes idle
— typically at the END of its work" (#113), idle teammates surfaced no signal (#98),
and post-`WAVE-COMPLETE` prune was deferred (#112).

- **New doctrine `doctrines/coordinate-active-drive.md`** — the binding contract:
  - **Two kinds of stop, rigorously separated:** the enumerated, closed set of
    legitimate *operator-pauses* (pre-spawn approval, `HARD-STOP`, operator-question,
    dispute adjudication, scope-confirmation, ROOT CLOSE REPORT, explicit interrupt)
    vs *passive-wait* (ending the turn with undrained coordinate state and no operator
    question pending — the bug). One-line rule: **yield to events, never to the
    operator — unless the operator is the only one who can answer the open question.**
  - **Kickoff guarantee (§III):** teammates BEGIN their lane on creation (first action
    `/shepherd:start --teammate`, no go-signal); root **confirms liveness** before
    treating dispatch as complete. Closes the mutual-wait deadlock (teammate waits for
    a kickoff while root waits for a teammate event).
  - **The coordinate cycle (§IV):** `wake → act (drain mail/idle) → probe (liveness +
    per-lane `git diff --stat` drift, `[DRIFT-WARN]`) → yield-to-events`. The same
    turn-end mechanic as passive-wait, opposite correctness: yield is cheap and
    auto-resumes; passive-wait leaves work undrained and implicitly asks the operator.
  - **Idle-without-signal (§VI, #98)** proactive probe; **active inspection cadence
    (§V, #113)** realizable subset (event-anchored sweeps; honest about no wall-clock timer).
- **Mechanical backstop `hooks/scripts/coordinate_drive_guard.sh`** (`Stop` hook,
  per the #86/#66 "mechanize prose-only invariants" lesson): blocks a premature root
  halt while a live spawn session has an `idle` teammate or lead-bound unread mail.
  - **Fast-path:** no DB / zero live teammates → exit 0. Solo `/shepherd:start`,
    `/shepherd:plant`, and ALL non-spawn work are never touched — the guard only ever
    engages inside an active spawn session.
  - **Runaway-bounded (#114 class):** a per-session 2-nudge cap then **fails OPEN**, so
    a deliberate "stop with idle teammates" is never trapped; fails open on any error;
    `[spawn].coordinate_drive_guard = block (default) | warn | off`.
  - 9-case dedicated test (`hooks/tests/test_coordinate_drive_guard.sh`, wired into
    `hooks/tests/run.sh`) — fast-path, block, lead-vs-teammate-bound mail, runaway cap,
    config off/warn. Full suite **28/28**.
- **Wired into:** `agents/shepherd.md` (Hard prohibition #14 — no dispatch-boundary
  operator-pause; coordinate-mode active-drive; Step 2 confirm-liveness-then-drive),
  `agents/conductor.md` (teammate begins-on-boot), `commands/spawn.md` (`TeamCreate`
  kickoff wording; post-spawn confirmation is not a turn-end; active-drive responsibility
  row), `commands/start.md` (teammate begin-immediately), `doctrines/root-shepherd-
  orchestration.md §II`, `doctrines/claude-code-platform-alignment.md §V` (Stop-hook
  registration), `doctrines/spawn-escalation.md §XII`, `doctrines/README.md` index,
  `docs/configuration.md` (new `[spawn]` section).

### Caching + native-leverage hardening (live-docs rigor audit)

A documentation-rigor audit against the **live** Claude Code docs (Agent Teams / hooks /
sub-agents / Dynamic Workflows / prompt-caching, verified 2026-06-02) confirmed the
coordinate-active-drive claims (`Stop {"decision":"block"}`, `SendMessage` lead
auto-resume v2.1.77, the event-driven wake model, no `team_name` on subagents) and
surfaced these fixes:

- **`TeammateIdle` routing hardened.** The live payload carries `session_id` (+ optional
  `agent_id`/`agent_type`) but **not** `teammate_name`; `teammate_idle.sh` now routes by
  `teammate_name` when present, **falls back to `session_id`**, and **fails loud** if
  neither matches — so the coordinate-drive backstop can't silently no-op on schema drift.
- **Dead heartbeat machinery retired.** The v5.1.7 per-tool teammate-heartbeat emission in
  `subagent_telemetry.sh` keyed on `$CLAUDE_TEAMMATE_NAME` (empty on the live platform) and
  never fired — removed in favor of native `TeammateIdle`-driven liveness + the
  `shctx teammate liveness` staleness poll. `spawn-escalation.md §V` +
  `claude-code-platform-alignment.md §V` reconciled.
- **Caching corrected + optimized.** `brief-cache-discipline.md` reframed — the prior
  "implicit breakpoints *inside* the brief" model was inaccurate; the genuinely-cached
  prefix is the agent system prompt (`agents/<role>.md`) + tools, and the brief's
  stable-first ordering earns *coherence* + a reusable conversation prefix. Biggest dollar
  lever is TTL: **`ENABLE_PROMPT_CACHING_1H=1`** for `--scope >= patch` (surfaced in
  `docs/configuration.md §[spawn]` + spawn preflight). Brief tails made deterministic
  (`open-issues.sql` `ORDER BY number`, dropped volatile `updated_at`) and the coder
  `[ROLE]` line made cross-sprint-stable (dropped `{sprint_branch}`).
- **Doc accuracy:** hook event count 29 → 31; `sqlite-canonical-state.md` path made
  namespace-neutral (`.shepherd` default); `workflow-compile-down.md` reconciled
  (binding *model* vs opt-in spike *backend*).

The 3 sanctioned mechanizations (adaptation/self-improvement, code-styles, context-DB
comms) were audited as cleanly mechanized + queryable-without-reindex — on-philosophy,
no change. hooks 28/28; context 37/37.

## v6.0.4 — 2026-05-31

### Adaptation + self-improvement loop, made SQLite-canonical (#94 / #95)

Closes the adaptation / self-improvement loop as a **thin behavioral layer over existing
substrate — no new engine**. The advisory markdown registry (`{paths.ctx}/sprint-patterns.md`)
is **retired**; its signal now lives in the project DB and flows back into planning
automatically.

- **New `shctx adapt` verb** (`skills/context/scripts/cmd_adapt.sh`, registered in `shctx`):
  - `adapt roll --sprint=<b> --grade=<G> [...]` — at CLOSE-FINALIZE, writes one
    `sprint_metrics` row **and** harvests this sprint's HIGH/CRITICAL `audit_findings` into
    `mem_entries(kind='prior')` lessons (deduped by concern → bounded growth). Idempotent.
  - `adapt priors --metrics|--lessons|--all [--json|--md]` — measured dispatch averages +
    recent lesson priors; graceful-empty (emits nothing on a cold store).
  - `adapt report [--md|--json]` — the materialized sprint-patterns view.
- **Schema** (migrations gap-filled by `cmd_migrate`): `0010_sprint_metrics.sql`
  (`sprint_metrics` + `v_sprint_metrics_avg`); `0011_mem_entries_prior_kind.sql` —
  recreate-table migration adding `'prior'` to the `mem_entries.kind` CHECK (preserving rows,
  both indexes, `v_mem_recent_7d`).
- **#94 adaptability:** spawn **Check 8** (`commands/spawn.md`) and engineer lane sizing read
  `shctx adapt priors --metrics` — measured `avg_sprint_minutes` / `avg_api_per_sprint` /
  `avg_lane_count` replace the static `90`/`200` defaults once history exists. The loop now
  shapes dispatch *sizing* mechanically, not just plan content.
- **#95 self-improvement:** harvested priors are injected as **cache-tail** variable content
  into the engineer + planter `[DB-CONTEXT]` blocks (`cmd_inject.sh`) and into `/shepherd:plant`
  + engineer Phase-0; a plan/seed that acts on a prior cites its `prior:<mem_id>` (the
  measurement signal).
- **Doctrine:** `adaptation-loop.md` rewritten advisory→SQLite-canonical; new
  `self-improvement.md` (harvest→inject contract); indexed in `doctrines/README.md`; referenced
  from `agent-excellence.md`. Stale `sprint-patterns.md` references across engineer/critic/
  auditor/discovery/worker references, `SKILL.md`, `flock.md`, `preflight-doctor.md`,
  `scope-scale-workload.md`, `flock-cohesion.md`, and the `session_open.sh` hook reconciled to
  the registry. Harvest source (`shctx audit insert` → `audit_findings`) reachable post the
  v6.0.3 0007-migration relocation fix.

### Lane-model reconciliation — few fat lanes over many thin sessions

Corrects a standing contradiction: `primitive-axis-binding.md` binds **Agent Teams = lanes,
Dynamic Workflows = step fan-out, subagents = steps**, yet the lane-count *minimums*
(M≥6 / L≥8 / XL 10–15, "more lanes is better") pushed lane granularity down to *step*
granularity — minting a Claude session where a subagent belongs.

- A lane is a **vertical slice run by a teammate-conductor that fans its wave-steps to a
  cluster of subagents / a Dynamic Workflow** — not one-session-per-step, not a per-wave stage.
- The inflated minimums become **few-fat-lanes guidance** (typically S 1–2, M 2–4, L 3–5,
  XL 4–6), sized to genuinely-isolable slices + measured `avg_lane_count` (#94), with **in-lane
  re-spawn per wave** for fresh context instead of more lanes.
- Minting a session per step is flagged `PRIMITIVE-INVERSION`; `@critic` now rejects
  **mis-sized** projections in either direction (too few disjoint slices, or too many thin
  sessions), replacing the one-directional "under-parallelized" reject.
- Reconciled across `agents/engineer.md` (canonical §Lane-count guidance), `critic.md`,
  `conductor.md`, `shepherd.md`, `seed-template.md`, `primitive-axis-binding.md`,
  `engineer.reference.md`, `flock.md`, `sprint-as-patch.md`, `SKILL.md`.

### Verification

- `bash skills/context/tests/run.sh` — 37/37 (incl. new `test_cmd_adapt.sh`).
- `bash hooks/tests/run.sh` — 27/27 (incl. modified `session_open.sh`).
- Fresh-DB migrate `0001 → 0011` clean; empty store ⇒ unchanged cold-start behavior.

---

## v6.0.3 — 2026-05-30

### Substrate-defect patch — Agent-Teams orchestration hardening (#97–#103)

Operational defects surfaced during live `/shepherd:spawn` runs on the v6.0.x native
substrate (Agent Teams + Dynamic Workflows). A diagnostic pass first isolated the failure
class: a 4-cell Dynamic-Workflow dispatch probe + a 16-way concurrent fan-out probe
confirmed that **`opus[1m]` resolves correctly in subagent dispatch and DW handles large
Sonnet fan-out cleanly** — the failures were neither the model nor the dispatch substrate,
but Agent-Teams *coordination* gaps. Fixes:

- **#97 — worktree pre-creation.** Root now `git worktree add`s every lane worktree and
  emits `[WORKTREE-READY]` *before* `TeamCreate`; the teammate boot prompt's INHERITED
  CONTEXT carries `worktree_status: pre-created`. Eliminates the boot-time
  `ANOMALY: worktree missing` round-trip that blocked every lane. (`commands/spawn.md`,
  `agents/shepherd.md`)
- **#98 — stall heartbeat.** Conductors must heartbeat at every phase boundary even when
  blocked on a background task, and on idle-without-`WAVE-COMPLETE` must send a status
  (`{phase, last_node, in_flight_task}`) within 1 turn. New canonical rule in
  `spawn-escalation.md §V`. (`agents/conductor.md`, `commands/spawn.md`)
- **#99 — `TEAMMATE-GIT-WRITE`.** Teammate git authority is bounded to its own
  worktree-branch commits; `git rebase`/`merge`/`push`/`worktree` halt with
  `TEAMMATE-GIT-WRITE`. Reinforced at every decision point (Hard prohibition #19,
  halt-codes table, Side-effect boundary) + new `dispatch-tier-separation.md §IV-bis.8`.
- **#100 — mechanical wave-gate.** Wave advancement is enforced by the task list, not
  prose: root TaskCreates a `wave-{N}-gate-{sprint_slug}` marker, each lane's next-wave
  IMPL task carries `addBlockedBy` (set via `TaskUpdate`, *not* a `TaskCreate` arg),
  released via `TaskUpdate(status: completed)` after the gate passes. A task with an
  unresolved `blockedBy` cannot be claimed, so no lane jumps the gate. New
  `WAVE-GATE-NOT-RELEASED` (root-side).
- **#102 — lane-task ownership.** New doctrine `lane-task-ownership.md`: every teammate
  task title is prefixed `"{lane_id}: "` and `TaskUpdate(owner:)`-set; root routes
  `TaskCompleted` by prefix; terminal tasks carry none. New `TASK-LANE-MISMATCH`
  (Hard prohibition #20).
- **#103 — engineer dispatch hardening.** New `ENGINEER-MODEL-FAIL`: root surfaces the
  raw error and PAUSEs instead of treating a null/error `@engineer` return as an empty
  plan. The `@engineer` `opus[1m]` pin is **retained** (probe-cleared; single
  once-per-sprint dispatch, not a large-set surface; 1M headroom for XL plan authorship).

No closed-flock contract change; no new commands. Patch-level: dispatch-logic + brief
templates + one new doctrine (`lane-task-ownership.md`) + two updated doctrines. The
tracked-for-v6.0.3 feature depth (#94/#95 adaptability + self-improvement) remains
operator-deferred to v6.0.4 (this cycle's foundation work is the prerequisite).

### Coherence remediation (full-repo passover)

A 7-concern read-only audit of the v6.0.x plugin surfaced ~35 coherence findings from the
rapid v6.0.0→v6.0.2 evolution. All fixed:

- **CRITICAL — migration foundation.** `schema/0007_canonical_state.sql` sat in `schema/`
  root, which `cmd_migrate.sh` never globs — so the v5.1.7 operational tables (`teammates`,
  `mailbox`, `escalations`, `deliverables`, `discovery_findings`, `audit_findings`,
  `heartbeats`) were **never created in any consumer DB**. Relocated to
  `migrations/0007_canonical_state.sql` (idempotent), removed its self-inserted
  `schema_versions` row, and switched the runner to **gap-fill** (apply any version absent
  from `schema_versions`, repairing DBs stranded past the orphan). Verified end-to-end.
- **HIGH — `shctx sprint open` unbroken.** `--mode=sprint` violated the `locks_history`
  CHECK (rc=19 every call); `0009_locks_mode_sprint.sql` recreates it with `sprint`/`spawn`.
- **CRITICAL — task-list contradictions.** `claude-code-platform-alignment.md` claimed the
  task list is "not consumed" (contradicting the #100/#102 wave-gate mechanics), and the
  "TaskCreated/TaskCompleted hook" routing in `spawn-escalation.md`/`lane-task-ownership.md`
  was a phantom (no such hook registered). Both reconciled: the task list is consumed for
  lane-routing + wave-gating; root routes by the `"{lane_id}: "` title prefix observed via
  `TeammateIdle`/`SendMessage`, not a hook.
- **Halt-code registry.** Added ~12 referenced-but-undefined codes to the canonical
  `conductor.md` table + `shepherd.md` root-side triage; canonicalized `SEED-DRIFT` into
  `-MECHANICAL`/`-SUBSTANTIVE`/`-DETECTED`; standardized `SCOPE OVERFLOW`.
- **Retired-mechanic purge.** `PAUSE-FOR-DEPENDENCY` (retired v6.0.1 #70) was still injected
  into every `@coder` brief + live in four doctrines — replaced with the native
  await-edge / `SendMessage` / finding-at-close pattern.
- **Doc sync.** Doctrine index completed (30→50 rows); `--auto` reaffirmed as a stable
  `--scope patch` alias (rescinded the never-honored removal); `workflow-compile-down.md`
  marked binding (the primary path); meta-orchestrator count corrected to three across
  `CLAUDE.md`/`README.md`/`SKILL.md`; v5.1.7 tables documented; stale §-anchors fixed.

Verification: both test harnesses green (context 36/36, hooks 27/27); fresh-DB migrate
applies 0001→0009 with every operational table present.

---

## v6.0.2 — 2026-05-29

### Groove-recovery patch — Wave 0: define the truth (ontology + primitive↔axis binding)

v6.0.1's slimming + the introduction of "lanes" blurred shepherd's core ontology and
broke its mapping of Claude-native primitives to their roles. In a live axiom session the
root spawned the conductor wave via **Dynamic Workflows** instead of **Agent Teams**, and
the teammates then failed to compile their step fan-out into workflows — each native
primitive used for the OTHER one's job (#89). Root cause: shepherd never pinned
primitive↔axis, and Dynamic Workflows is a ~1-day-old research-preview feature for which
the model has **no training prior**, so shepherd's (ambiguous) doctrines were its only
teacher. v6.0.2 is a four-wave, gated groove-recovery patch. **This entry covers Wave 0
(doctrine only) — the foundation that gates the mechanism (Wave 1), substrate (Wave 2),
and slim/validate (Wave 3) waves that follow.**

**A — canonical primitive↔axis binding (#89, #88).** New doctrine
`doctrines/primitive-axis-binding.md` pins every axis to one primitive and one unit:
planning → none → `waves × steps`; teammate-state/parallelization → **Agent Teams** →
one teammate-conductor per **lane**; execution → **Dynamic Workflows** → the compiled
script over **subagents**; worker → **subagents** → the **steps**. Spawning teammates =
Agent Teams (never a workflow); a teammate's gate-free fan-out = a compiled Dynamic
Workflow (never hand-rolled dispatch). **Never invert.** Cross-linked from
`claude-code-platform-alignment.md §VII`, `native-coordination.md`, and
`dispatch-tier-separation.md §I-bis` (the ontological tier ↔ unit mapping).

**B — ontology rewrite: `waves × steps`; lanes as a post-plan projection (#88).** The
engineer now authors the plan as **N sequential waves; each wave is X steps; each step ≈
one subagent**, with **NO lane concept**. A **lane** is a cohesive **vertical slice across
waves**, formed **only in spawn mode, after the plan**, owned by one teammate-conductor —
and it **never nests inside a wave**. Removed every `wave: <N>` field on a lane, every
"wave is a set of lanes", and every "min lanes per wave" tabulation across `engineer.md`
(+ `engineer.reference.md`), `references/seed-template.md`, `planter.md`, `pipeline.md`,
`flock.md`, `dispatch-tier-separation.md`, `SKILL.md`, `conductor.md`, `shepherd.md`,
`critic.md`, `root-shepherd-orchestration.md`, `sprint-as-patch.md`, `commands/spawn.md`,
`README.md`. The decomposition discipline split cleanly: planning = many narrow steps per
wave (substantive LOC floor); spawn = a **total** lane count (never per-wave).

**B-bis — lane refresh (durable lane, recyclable teammate).** One teammate-conductor
occupies a lane at a time, but at a wave boundary root MAY shut down an idle lane's
teammate and spawn a fresh one to take over the **same** lane for the next wave (fresh
context, lower compaction cost). Refreshing a lane's teammate is **not** a new lane — you
count lanes (constant across waves), never teammate-instances. This is the origin of the
retired "per lane per wave" phrasing (`primitive-axis-binding.md §II.1`).

**C — Phase-0 split (#88).** The pre-plan **discovery wave** runs at root BEFORE the
engineer (INTRO-COMBO-WAVE); the engineer now **consumes** its `[DISCOVERY-CONTEXT]` /
`[INTRO-AUDIT-CONTEXT]` as primary ground truth and verifies targeted gaps, rather than
re-running the full mesh itself (fixes the `engineer.md` Step 2 contradiction). The mesh
enumeration is the *coverage spec*; the engineer self-runs only when the wave is disabled
(XS / `intro_wave.enabled = false`). Carry-over / open-issue handling becomes a candidate
dedicated lane, not steps folded into the plan body.

**D — #67 / #20 reconciled.** `seed-template.md §6` (Deliverables, not "MUST-LAND lanes")
landed in v6.0.0; v6.0.2 fixes the residual §7 "coder lanes per wave" minimums and frames
the planter's seed-quality table around **deliverables** (lane decomposition is the
engineer's authority). The mandatory-`subagent_type` dispatch contract (#20) is verified
consistent across `SKILL.md §I`, `flock.md §I`, `conductor.md`, `shepherd.md`, and
`dispatch-tier-separation.md §IV-bis`.

**E — #75 reconciled.** Verified `doctrines/workflow-compile-down.md` is on-disk,
coherent, and cross-linked (`platform-alignment.md §VII`, `stage-graph.md`); all internal
doctrine references resolve.

**Gate 0 (green):** grep proves no live file nests "lane" in "wave" or tabulates "lanes
per wave" (every residual mention is a negation or the anti-pattern definition); the
binding table is canonical + referenced by 17 files; `SKILL.md` and the agent profiles
agree on the dispatch contract; #75 reconciled.

### Wave 1 — make it stick (mechanism) + hardening pass

Turns the Wave-0 truth into mechanical refusals, and folds in an operator-directed
hardening pass (doc validation against live Claude Code docs, a bug-hunt, description
hygiene, and the start/spawn boundary).

- **`hooks/scripts/dispatch_guard.sh` (new, PreToolUse Agent|Task).** Hard-blocks the
  dispatch-class violations: `DISPATCH-MISSING-SUBAGENT-TYPE` (omit / general-purpose /
  Explore / Chat), `DISPATCH-TEAMMATE-TYPE-MISMATCH` (a flock role carrying `team_name` —
  a step spawned as a lane, #66.1 / #61), `TEAMMATE-NESTING-ATTEMPT`, `WRONG-TIER-DISPATCH`
  (teammate → engineer/critic), `DISPATCH-OFF-FLOCK`. Enforces step→subagent /
  lane→teammate-conductor (#89, #66).
- **`bash_guard.sh`** gains the #89 **inversion-1** block (a `*.workflow.js` carrying
  teammate-spawn markers is refused — `PRIMITIVE-INVERSION`) and the #91 cargo
  sequential-gate block (`run_in_background:true` on a cargo gate is refused).
- **`doctrines/invariant-enforcement-matrix.md` (new, #86)** — the coverage map pairing
  every invariant with its mechanism + type (hard-block / flag / lint / auditor / doctrine)
  + status, surfacing the prose-only gaps that caused #66 / #59 / #74. Honest row-by-row
  status for the eight #66 violations (1/4 hard-blocked + tested; 2/3/6 flag-candidates;
  5/7 auditor; 8 doctrine + partial block) and the two #89 inversions (1 hard-blocked; 2
  flagged-by-design, hard block scoped to #85/Wave 2 since hand-rolled fan-out is a
  legitimate runtime-failure fallback).
- **`lint_agent_capabilities.sh`** extended for #84: least-privilege sweep across all nine
  agents pins that no agent carries a destructive MCP verb under `acceptEdits` (dual-use
  reads + release verbs are documented retentions); #74 read-only trio lint retained.
- **`hooks/tests/test_dispatch_guard.sh` (new)** + wired into `run.sh` — Gate 1 evidence:
  reproduces the two #89 inversions + dispatch-class #66 violations and proves each is
  blocked, with well-formed dispatches passing. **`hooks/tests/run.sh` 26/26 green.**
- **Doc validation (live `code.claude.com/docs`).** Confirmed Dynamic Workflows (CC ≥
  v2.1.154; ≤16 concurrent / ≤1000 total; no mid-run input; no FS/shell; `acceptEdits`;
  within-session resume; **orchestrates subagents only, cannot spawn teammates** — a
  platform-level reinforcement of the #89 binding, now cited in `primitive-axis-binding.md
  §III.1`), Agent Teams (v2.1.32 experimental), and subagents (no `description` char cap;
  "subagents cannot spawn subagents"). Surfaced discrepancy: the docs spawn teammates via
  natural-language lead instruction (not `Agent({team_name})`) and don't document
  `CLAUDE_TEAMMATE_NAME` — shepherd's convention; flagged for operator review, not yet
  rewritten.
- **Description hygiene.** All nine agent + both SKILL.md + six reference descriptions
  rewritten to single-line, **XML-free** (dropped `<example>`/`<commentary>` blocks),
  ≤200 chars; the shepherd SKILL.md description was 2414 chars — **over the documented
  1,536 skill cap** — now 187.
- **start/spawn boundary.** `/shepherd:spawn` is stated as the **primary** command
  (root + teammate-conductor lanes via Agent Teams + Dynamic Workflow execution);
  `/shepherd:start` is the **solo, lightweight** path (one sprint, no teams/lanes). Fixed a
  residual lane-per-wave construct in `commands/spawn.md`. Planter + seed-template made
  **spawn-aware** (deliverables decompose into file-disjoint vertical slices the engineer
  projects into lanes; the planter never defines lanes itself).
- **Bug-hunt fixes** (subagent review, no HIGH): case-fold consistency in dispatch_guard
  Check 3 (MEDIUM-1); anchored the workflow `team_name` marker to avoid false-blocking a
  comment mention (MEDIUM-2); added the `CLAUDE_PROJECT_SESSION_TYPE` teammate signal;
  single-quote in the workflow marker class; fixed a dangling `§V.2` cross-ref. Both
  MEDIUM fixes locked in with regression tests.

**Gate 1 (green):** `test_dispatch_guard.sh` reproduces the two #89 inversions + the
dispatch-class #66 violations and proves each mechanically blocked; allowlist lint green.

**Wave 1 follow-ups (gaps tracked in the matrix, not yet hard-mechanized):** #66.2/#66.3
cargo `CARGO_TARGET_DIR` / `--frozen` warns; #59 close-finalize since-last-commit gate;
#90 spawn boot-prompt SCOPE RULE.

### Wave 2 + finalization — native substrate, platform reconciliation, productionize

Operator-directed finalization: deliver the governance + context-management core by elegantly
composing Claude Code's native tools, update the README, and make the repo product-grade.
Much of the substrate already existed (`shctx graph compile` with a faithfulness diff); this
wave **reconciles it to the verified platform mechanism, completes the topology tooling, and
hardens the operational substrate.**

- **#93 RESOLVED — platform mechanism verified against live docs (2026-05-29).** Teammates
  spawn via the **`TeamCreate`** tool family + a natural-language lead instruction referencing
  the `shepherd:conductor` subagent definition — there is **no `team_name` parameter on
  `Agent`/`Task`** (those spawn subagents), and a teammate session exposes **no identity env
  var** (`anthropics/claude-code#35447`, closed not-planned); identity is delivered only in
  hook-input JSON. **Dynamic Workflows orchestrate subagents only — never teammates** (confirms
  the #89 binding; only the call-shape was wrong). Reconciled across `commands/spawn.md`,
  `agents/conductor.md`, `agents/shepherd.md`, `dispatch_guard.sh`,
  `claude-code-platform-alignment.md §I` (Open investigation → **Resolved**),
  `invariant-enforcement-matrix.md`, and `primitive-axis-binding.md §III.1/§IV`.
- **Honest, env-independent dispatch guard.** `dispatch_guard.sh` now detects a teammate
  session from the hook-input **`cwd`** (a `.worktrees/` path) — env-independent, since the
  platform exposes no teammate env var — with the `subagent_type` discipline as the mechanical
  floor and the `team_name`/teammate-tier checks documented as defence-in-depth (layered over
  the platform's structural no-nesting guarantee). New `cwd` regression in
  `test_dispatch_guard.sh`; **hooks 26/26 green.**
- **`shctx graph diagram` (new, #77 topology utility).** Emits a **Mermaid execution diagram**
  of the Stage Graph — seam vs fan-out classification (matching the compiler's φ-map), labeled
  edges, and an optional per-segment compiled-fan-out overlay — to
  `{workdir}/graph/diagrams/{sprint}.mmd` or stdout. Complements the existing
  `shctx graph compile` (Dynamic Workflow emission + soundness/completeness/determinism
  faithfulness diff + manifest seam-export) per `workflow-compile-down.md`.
- **Operational substrate: `$SHEPHERD_WORKDIR`.** New first-class resolver `resolve_workdir()`
  (`skills/context/scripts/_lib.sh`, mirrored in `hooks/scripts/_lib.sh`) honors
  `$SHEPHERD_WORKDIR` → existing `.shepherd` → existing `.artifacts` → default `.shepherd`.
  **Fixed a canonical-state split-brain bug:** five `cmd_*.sh` (escalate/deliverable/mailbox/
  report/teammate) and five hooks (teammate_idle/deliverable_check/subagent_telemetry/
  lock_guard/dedup_write_guard) hardcoded `.artifacts/root.db`, so a `.shepherd`-default project
  silently used the wrong DB — all now resolve through the namespace. The workdir ships its own
  `.gitignore` (secrets + runtime trimmed: `*.env`/`*.key`/`*.pem`/`secrets/`/…; design records
  under `docs/` preserved); the root `.gitignore` mirrors the `.shepherd/` runtime entries. New
  `skills/context/tests/test_workdir.sh` pins the precedence; documented in
  `docs/configuration.md`.
- **Root proactivity + compartmentalization (operator-emphasized).** `agents/shepherd.md`
  (Coordinate mode) and `root-shepherd-orchestration.md` now make **proactive idle-teammate
  pruning** a standing root behavior — once a teammate's wave payload is materialized, prune it
  (reclaim compute, avoid forced compaction) and **refresh** the lane with a fresh teammate at
  the next wave boundary. Compartmentalizing each wave into fresh context is the default.
- **#71 `release.yml` fixed** — `actions/checkout@v6`'s credential-persistence breaking change
  (PR #2286) broke the authenticated `git push` steps once the v6.0.1 `detect` regex fix let
  the pipeline proceed; pinned checkout to `@v5` + explicit `token:` + `persist-credentials`.
- **#72 critic false-positive fixed** — the critic's Necessity audit now resolves the full
  Cargo **feature graph** before flagging reachability (default sets, `foo = ["bar"]` chains,
  umbrella `full` rollups, optional-dep `dep:`/`x?/feat`, workspace/`--features`), so a
  transitively-enabled feature (e.g. `native-runtime` via `full`) no longer raises a spurious
  CRITICAL; genuinely dead features downgrade to a verify-first observation.
- **README** rewritten to the finalized v6.0.2 story; all six version sources confirmed synced.

**Gate (green):** `hooks/tests/run.sh` 26/26; `test_workdir.sh` passes; `shctx graph diagram`
verified end-to-end. (Context DB tests require `sqlite3`, absent in this environment —
environmental, not a regression.)

**Tracked for v6.0.3 (non-core depth — operator-deferred):** adaptability + self-improvement
mechanisms (filed as issues); the still-tracked matrix gaps (#59 close-gate hard hook, #90
boot-prompt SCOPE RULE, #66.2/#66.3 cargo warns, #66.6 dead-pane prune); the deeper cross-run
concurrency budget (#83); the full hand-rolled-mechanic deletion (#70/#53/#58); and
compile-down telemetry (#87). The governance core + native-substrate execution path are in
place; these add depth.

---

## v6.0.1 — 2026-05-29

### Reposition onto Claude Code's native substrate (Dynamic Workflows + Agent Teams + subagents)

Patch 1 of the v6 line repositions shepherd: **retain the governance core, slim
the hand-rolled orchestration mechanics, and adopt Claude Code's native
primitives as the primary execution substrate.** Dynamic Workflows (research
preview, 2026-05-28) finally make out-of-context agent fan-out a platform
capability; shepherd now contributes *discipline* (closed flock, hard-refusal
dispatch contract, audited Stage Graph, canonical SQLite+git state) while the
platform contributes *execution*. Epic #76.

**Invariants held** (unchanged by the slim): the closed flock + behavioral
contracts; mandatory `subagent_type` with refusal rules; the critic / wave /
close gate topology; SQLite + git as canonical state; the engineer-authored,
critic-gated Stage Graph as the dispatch contract.

**A — capability-enforced read-only reviewers (#74).** Dropped
`execute_sql` from `@auditor` / `@discovery` allowlists; `Write` is retained but
path-scoped by the existing `lock_guard.sh` PreToolUse hook (Option B). Added
`hooks/tests/lint_agent_capabilities.sh` — fails if a read-only reviewer regains
a mutating verb (or keeps un-scoped `Write`). The read-only contract is now
allowlist-enforced, holding even under a Dynamic Workflow runtime's `acceptEdits`
where no orchestrator is in the loop.

**B — `workflow-compile-down.md` doctrine landed (#75).** The compile-down
evaluation doctrine (the §IV faithfulness contract, §V φ node→construct map, §VI
canonical-state seam) with cross-links from `platform-alignment §VII`,
`stage-graph.md`, and the doctrine web.

**C — dispatch-contract consistency (#20, #67).** Verified the mandatory-
`subagent_type` flip and the seed-template lanes→deliverables rename already
landed in v6.0.0; reconciled the residual stale text (`specialist-dispatch.md`,
`agent-briefs.md`, planter density prose).

**D — `shctx graph compile` (#77).** Emits gate-free agent-fanout segments of the
Stage Graph as Dynamic Workflow scripts — the **primary** path for those
segments (not a toggle). Built on the existing `shctx plan extract` surface (one
source, two projections); bounded `Promise.all` (≤16 concurrent / ≤1000 total);
read-only steps carry no edit tools; CLOSE-SWARM is the default first target. The
§IV faithfulness diff (`--verify`: soundness / completeness / determinism) gates
every compiled segment. Wired as primary in `dispatch-cascade.md §IV-bis` and the
conductor walk; mode-agnostic (solo + teammate); runtime failure degrades to
in-context dispatch.

**E — native coordination (#78).** `native-coordination.md` maps the retired
mechanics onto native primitives (in-script ordering / Agent Teams `SendMessage`
/ subagents) and **demonstrates** parity before deletion.

**F — slim (#70, #53, #58).** Deleted pause-for-dependency entirely
(`agent_pause_detector.sh`, `cmd_pauses.sh`, `pause-for-dependency.md`, the
`shctx pauses` verb, the `PAUSE-FOR-DEPENDENCY` / `RESUME-LANE` node types, and
the satellite subgraph). Coders/workers now file a `BRIEF-AMENDMENT REQUEST` or a
finding at close; cross-lane deps are engineer-composed graph edges the compiled
segment `await`-orders. Heartbeat *auto-relay* (#53, never built) and
idle-*pruning* (#58) are documented as moot; teammate **liveness** + Agent Teams
state are intentionally kept. `hooks/tests/test_pause_retired.sh` proves no
residual dependency.

**G — version cycle + release workflow (#71).** Fixed the silently-skipping
release pipeline: the `detect` regex accepted only a space/EOL after the version
triple, so descriptive PR titles (`vX.Y.Z: <summary>`, the convention since
v6.0.0) never matched — the pipeline no-opped (the 9-second runs). The regex now
accepts the `:` delimiter. Corrected the README "Current version" line that had
drifted to 5.1.9 because the v6.0.0 bump step never ran.

Suites green: `hooks/tests` 25/25, `skills/context/tests` 35/35 (incl. the new
compile, capability-lint, and pause-retired tests).

---

## v6.0.0 — 2026-05-28

### Dispatch enforcement + planter authority excision

Major bump. v5.1.9 modernized the dispatch model (registry-loaded
`subagent_type` replaced inline body injection — issue #20) but removed the
old enforcement language without an equivalent replacement, leaving a
permissive fallback path that produced three consecutive failed sprints on
`fl03/axiom v0.3.4-dev.0/1/2` (2026-05-25..27). v6.0.0 closes the gap:

**Hard refusal contract (binding) — `doctrines/dispatch-tier-separation.md §IV-bis`:**

| Combination | Halt code |
|---|---|
| `subagent_type` missing OR `general-purpose` / `Explore` / `Chat` | `DISPATCH-MISSING-SUBAGENT-TYPE` |
| `team_name` set + `subagent_type ≠ shepherd:conductor` | `DISPATCH-TEAMMATE-TYPE-MISMATCH` |
| `subagent_type` outside closed-flock-six (no specialist clearance) | `DISPATCH-OFF-FLOCK` |
| Teammate-conductor constructs `team_name` (any value) | `TEAMMATE-NESTING-ATTEMPT` |
| Teammate-conductor dispatches `@engineer`/`@critic` | `WRONG-TIER-DISPATCH` |
| SOLO mode spawning OR TEAMMATE mode running SOLO ops | `MODE-MISUSE` |

These codes are terminal for the offending dispatch. Root does NOT
auto-resume on `WRONG-TIER-DISPATCH` or `TEAMMATE-NESTING-ATTEMPT` — the
teammate brief is malformed and needs operator review.

**Wave-tier model promoted to canonical doctrine** —
`doctrines/root-shepherd-orchestration.md §I-bis`:

- INTRODUCTION (§1) = root-direct subagents (`@discovery` × N + intro
  `@auditor` × 2 + `@engineer` + `@critic` + plan materialization +
  operator approval gate). No teammates spawned.
- BODY (§2) = teammate-conductors, one per lane per wave. Each conductor
  walks its lane's micro-Stage-Graph using its OWN subagent waves.
- CLOSE (§3) = root-direct subagents (`@auditor` × 3-5 close-swarm split
  by concern, on aggregated sprint output). CLOSE-FINALIZE git ops run at
  root.

**Planter authority excised** — `agents/planter.md §Authority boundary` +
`references/seed-template.md §6` (renamed from "MUST-LAND lanes" to
"Deliverables (issue-anchored)") closes FL03/shepherd #67:

- Lane numbering (`Lane N`) and sequencing (`sequential after Lane K`) are
  the engineer's exclusive authority in the plan. Removed from seed
  template.
- Wave composition table (§7) demoted to NON-BINDING recommendation. The
  engineer's `## Stage Graph` is the binding decomposition.
- Per-deliverable T-shirt sizes removed from seed template — engineer
  analyzes at plan-time.

**Scope is workload-scale, never a quality bar** —
`doctrines/version-scale-roadmap.md` + `scope-scale-workload.md` opening
notes are now binding:

- A planter may NOT defer or downscope work because "it's just a patch."
- A conductor may NOT come up short on lanes citing patch size.
- "Reshape as a `@worker` dispatch" framing for sprints that don't deliver
  their seed-promised work is forbidden — that is seed/implementation
  drift, gradeable as a `@critic` RECONSIDER or `@auditor completeness`
  C+ cap, NOT a sprint reclassification.

**New halt codes** — root-side (`agents/shepherd.md §Halt codes`) and
conductor-side (`agents/conductor.md §Halt codes`):

- `DISPATCH-MISSING-SUBAGENT-TYPE`
- `DISPATCH-TEAMMATE-TYPE-MISMATCH`
- `DISPATCH-OFF-FLOCK`
- `TEAMMATE-NESTING-ATTEMPT`
- `MODE-MISUSE`
- `MODE-DETECTION-AMBIGUOUS` (formalized; was implicit prior)

**Boot-prompt hardening** — `commands/start.md §Step T0 (--teammate path)`
now runs a four-check refusal block (INVOCATION-CONTEXT present,
`dispatcher == teammate-conductor`, lane brief slice present,
`ROOT-SESSION-NAME` populated) before any dispatch. SOLO `/shepherd:start`
unchanged.

**Spawn HARD PROHIBITIONS rephrased** — `commands/spawn.md §Build the
teammate prompt` rewrites the prohibition block from descriptive ("NO X")
to machine-checkable ("MUST REFUSE X and SendMessage halt_code: <code>,
blocking: true"). Same content, enforceable shape.

#### Closes / references

- Closes FL03/shepherd #65 (shepherd:coder dispatched as teammate)
- Closes FL03/shepherd #66 (root shepherd ignored feedback / dispatch
  protocol)
- Closes FL03/shepherd #67 (seed-template lane prescription)
- Downstream blast radius: axiom v0.3.4-dev.0/1/2 failed sprints, axiom
  issues #1487-#1494 (P0/P1 production fires opened 2026-05-26/27)

#### Migration

Projects on v5.1.x must update any direct Agent calls in custom doctrines
or hooks to set `subagent_type: "shepherd:<role>"` explicitly. The
permissive fallback to `general-purpose` is GONE — calls without it will
refuse at dispatch time. Hooks that compose dispatch briefs (e.g., custom
`agent_pause_detector.sh` extensions) should also be audited.

#### Files moved together

- `.claude-plugin/plugin.json` → 6.0.0
- `.claude-plugin/marketplace.json` → 6.0.0
- `skills/shepherd/SKILL.md` frontmatter → 6.0.0
- `skills/context/SKILL.md` frontmatter → 6.0.0
- `README.md` header
- `CHANGELOG.md` (this entry)

---

## v5.1.8 — 2026-05-21

### Platform-alignment patch

Adopts Claude Code v2.1+ hook primitives where they cover ground shepherd
previously had to handle by inference, ships the v5.1.7 carry-forward bug
fix, and documents how shepherd's teammate-coordination model maps to the
official **Agent Teams** primitive (Claude Code v2.1.32+). The flock model
and SQLite-canonical store are unchanged; this release is additive across
hooks, doctrines, and one helper-shim fix.

Closes #19, #21, #22, #23, #24, #26, #55. Documents the platform mapping
for #53 indirectly via the new alignment doctrine.

#### Hook surface (new events — Lane B)

- `CwdChanged` — `hooks/scripts/cwd_changed.sh` (59 lines). Informs the
  conductor when cwd drifts into a sub-worktree, paired with
  `doctrines/conductor-cwd.md §Ban 1`. Informational only; never blocks.
  Subagents (coder, auditor, etc.) are exempt — only conductor-role cwd
  drift fires the warning.
- `UserPromptSubmit` — `hooks/scripts/user_prompt_submit.sh` (88 lines).
  Auto-injects `shctx status --md` as `additionalContext` for
  `/shepherd:start` and `/shepherd:spawn` invocations; surfaces a friendly
  "no shepherd.toml" warning when the host project is unconfigured.
  `/shepherd:ctx` is intentionally not auto-primed (operator is about to
  query manually).
- `WorktreeCreate` / `WorktreeRemove` — `hooks/scripts/worktree_lifecycle.sh`
  (133 lines, single script registered for both events). Records worktree
  lifecycle in the new `worktrees` SQLite table; on remove, prunes the
  zombie `worktree-agent-*` ref if no HEAD pointer remains. Closes #22.
  Idempotent; never blocks. Defensive against schema drift — Claude Code
  docs don't yet specify the payload field structure, so the hook reads
  `.worktree.path` / `.worktree.branch` then falls back to pwd + current
  branch. Extraction is recorded in `<namespace>/logs/hooks/YYYY-MM-DD.jsonl`
  for drift audit.

#### Hook surface (new event types — first adoption of `type: agent`)

- **Agent-based hook** on `PostToolUse(Edit|Write)` with
  `if: "Edit(*.plan.md)"` / `if: "Write(*.plan.md)"`: **Phase 0 mesh
  verification**. Verifies every "landed in tree" / "confirmed at" /
  "in tree:" claim in a sprint plan against the sprint branch's
  `git log` (not file-content grep — that's what produced the false-landed
  L5/L6 claims on `fl03/axiom v0.3.2-dev.1`; see issue #23). Surfaces
  unverified claims as a warning so the engineer doesn't propagate false
  "done" markers to the next session's handoff. Closes #23. Default-on;
  `if` filter gates spawn so the hook only runs on plan-md writes (low
  frequency). Timeout 90 s, max 10 tool calls.
- **Agent-based hook** on `Stop`: **WAVE-GATE cherry-pick check**.
  Fast-paths via `git branch | grep -c '^  agent-'` (0 ⇒ ok, no further
  tools); on active sprint branches checks each `agent-*` branch for
  stray commits not reachable from sprint HEAD and surfaces a warning.
  Closes #21. Default-on; the fast-path keeps the per-turn cost bounded
  (~$0.001/turn Haiku when no agent branches exist; ~$0.005/turn during
  active multi-lane sprints). Timeout 30 s, max 5 tool calls.

#### Schema (Lane A)

- Migration `0008_worktrees.sql` — adds `worktrees` table
  (`id PK, path, branch, tool_use_id, agent_role, sprint, created_at,
  removed_at, status`) + 2 indexes (`status`, `sprint`). Additive only;
  no ALTER on existing tables, WAL mode preserved.

#### Doctrines (Lane D)

- **NEW** `skills/shepherd/doctrines/claude-code-platform-alignment.md`
  (617 lines) — maps shepherd's teammate / mailbox / heartbeat /
  escalation / deliverable primitives to the Claude Code v2.1.32+
  official **Agent Teams** primitive (opt-in via
  `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`). 22-row primitive map; 5
  bridging rules with owner / bridge / failure-mode triples; 8
  anti-patterns; 3-version migration roadmap (v5.1.8 document mapping →
  v5.2.0 evaluate `TaskCreated`/`TaskCompleted` consumption → v6.0.0
  evaluate `[teams].platform_backend` opt-in). Documents the mailbox
  bridging rule (shepherd persists across sessions; platform `SendMessage`
  is in-session only).

#### Bug fixes (Lane C)

- **#55** — `cmd_discovery.sh` legacy subverbs (`list`, `show`, `search`,
  `clear`) were broken because they called `resolve_namespace` /
  `current_sprint` helpers that live in `hooks/scripts/_lib.sh`, not in
  `skills/context/scripts/_lib.sh` (the lib sourced when these cmd
  scripts are invoked via bare `bash`). Fix: add cross-lib shims to the
  context lib so direct invocation works without cross-coupling to the
  hooks lib. New smoke test `skills/context/tests/test_helpers_in_ctx_lib.sh`
  regression-guards both helpers (sources lib, asserts `declare -F`,
  asserts non-empty output, asserts absolute path).

#### Session-open hardening (Lane E — v5.1.8 extension)

- **#24** — `session_open.sh` Anchor 5: agent-branch stray-commit survey.
  At SessionStart, walks `git branch | grep '^  agent-'` and runs
  `git rev-list --right-only --count "<sprint>...<branch>"` for each;
  surfaces any branch with stray commits not reachable from the sprint
  HEAD as a warning. Catches lost work from context-truncated prior
  sessions BEFORE the conductor reads the handoff and inherits a "complete"
  claim that is false on the sprint branch. Complements the WAVE-GATE Stop
  hook (which catches strays during the active session) — together they
  form a session-boundary safety net per the issue's recommendation.
- **#26** — `session_open.sh` Anchor 6: multi-plan.md reconciliation
  surface. When a sprint branch has more than one plan file (e.g.,
  `v0.3.2-dev.1.plan.md` + `v0.3.2-dev.1b.plan.md`), the file list is
  surfaced as a warning so the conductor reconciles all plans, not just
  the primary. Matches `^<sprint>([.-][a-z0-9]+)?\.plan\.md$` to catch
  the common addendum-suffix conventions (`.b`, `-b`, `-addendum`).
- **#19** — informational hook warning UI rendering. Added `[hooks].quiet_warnings`
  opt-out in `shepherd.toml` (default `false`, preserving v5.1.7 and prior
  behavior). When `true`, `emit_context` skips JSON emission while still
  calling `log_event` — operators can grep
  `<namespace>/logs/hooks/YYYY-MM-DD.jsonl` to recover the warning text
  out-of-band. `session_open.sh` refactored to route its final emission
  through `emit_context` so the opt-out gate applies uniformly.
  Documented in `docs/configuration.md §[hooks]`.

#### Plugin-manifest evaluation (decided non-features)

- **`settings.json` at plugin root with `agent: "shepherd"`** — evaluated
  and deliberately deferred. The platform key activates the named agent
  as the main-thread agent for every Claude Code session where the
  plugin is enabled, applying its system prompt, tool restrictions, and
  model globally. That would change main-chat behavior for every
  shepherd-installed session, breaking `/shepherd:start` solo mode's
  expectation that main chat behaves as a regular Claude. Better path:
  conditional activation on `/shepherd:spawn` only, which requires
  upstream Claude Code support we don't have today. Cited in alignment
  doctrine §VI.
- **`monitors/monitors.json`** — evaluated. shepherd already streams
  events into `<namespace>/logs/events-YYYY-MM-DD.jsonl`; a monitor
  `tail -F` over that file would create a noisy notification stream
  during every dispatch. Deferred; revisit if operators want it.
- **`.lsp.json`** — not applicable to shepherd's domain.
- **`bin/`** — evaluated. Exposing `shctx` directly on `$PATH` would
  shorten invocations. Deferred to v5.2.0 (multi-install conflict risk).

#### Known gaps (carry to v5.1.9 / v5.2.0)

- **TeammateIdle `tool_name` fidelity gap** — carry from v5.1.7; still
  open (`CLAUDE_TOOL_NAME` env var not set in `SubagentStop` context).
- **WorktreeCreate / WorktreeRemove payload schema** — Claude Code docs
  don't yet specify field structure. `worktree_lifecycle.sh` is
  defensive but actual fields may shift; log-stream the extracted
  payload to catch drift.
- **#47 / #53** — deferred to v5.2.0+ unchanged.

#### Deferred to v5.2.0+

- `TaskCreated` / `TaskCompleted` hook consumption (Claude Code Agent
  Teams primitives) — evaluation pending platform's experimental-flag
  removal.
- `SubagentStart` hook consumption — replaces inference of spawn time
  from `subagent_telemetry.sh` `SubagentStop` event; would unblock
  per-spawn telemetry rows.
- `PreCompact` / `PostCompact` hooks — auto-snapshot dispatch state for
  context-truncated session resume (mitigates lost-work landmines like
  #21 / #24 from a different angle).
- `bin/` directory with `shctx` on PATH.

---

## v5.1.7 — 2026-05-20

### SQLite-canonical operational state

Architectural shift: `.artifacts/root.db` becomes canonical for ephemeral
operational state (teammate liveness, heartbeats, mailbox, escalations,
deliverables, structured discovery/audit findings). Markdown reports are
materialized views over rows. File-canonical store is reserved for
human-authored durable artifacts (specs, plans, seeds, agent profiles,
doctrines, CHANGELOG, README).

Resolves the v5.1.5/v5.1.6 spawn-rollout defect cluster (#43, #44, #49,
#50, #51, #52) via the same shift — each bug was a file-bound symptom of
a missing canonical store; the cluster collapses once the store exists.
Also generalizes axiom's per-package feature CI feedback (#54) into a
workspace-tool-general doctrine.

#### Schema (Lane A1)
- New migration `0007_canonical_state.sql` adds 7 tables + 3 views:
  `teammates`, `heartbeats`, `mailbox`, `escalations`, `deliverables`,
  `discovery_findings`, `audit_findings`. Additive only — no ALTER on
  existing tables. WAL mode preserved.

#### Doctrine (Lane A2)
- New `doctrines/sqlite-canonical-state.md` — binding rule + allow-list
  + anti-patterns + migration guidance + back-compat statement.

#### shctx surface (Lanes A3, A4)
- New subcommands: `shctx teammate {register,heartbeat,status,liveness,
  prune,retire}`, `shctx mailbox {send,recv,ack,stale}`, `shctx escalate
  {<create>,list,resolve}`, `shctx deliverable {promise,complete,stalled}`,
  `shctx report <kind>`.
- Extended: `shctx discovery insert`, `shctx audit insert`.
- Tests under `skills/context/tests/test_cmd_*.sh` + `test_schema_0007.sh`.
- Shctx dispatcher whitelist updated to include the 5 new subcommands.

#### Agent profile amendments (Lanes B1, B2)
- `agents/discovery.md` — row-write Hard Prohibition (closes #43);
  `MISSING-RUN-ID` halt code.
- `agents/critic.md` — Step 0.5 deliverable promise/complete contract (closes #52).
- `agents/auditor.md` — Step 0 deliverable contract; new `Canonical gates
  (intro-mode regression)` section that runs `[gates].extra` from
  `shepherd.toml` (closes #52, #44).
- `agents/conductor.md` — Cargo discipline (binding under spawn) section
  mandating `CARGO_TARGET_DIR=target/.lanes/<lane-slug>` + `--frozen` on
  every cargo invocation in the flock (closes #50).
- `agents/shepherd.md` — `TEAMMATE-CRASHED` halt code + Crashed-teammate
  detection section (closes #49).
- `commands/spawn.md` — Cargo discipline (binding) block injected into the
  conductor brief template.

#### New command (Lane B3)
- `/shepherd:cleanup` — prunes stale/crashed teammates from canonical state
  via `shctx teammate prune` (closes #51). Operator-confirmed; never
  auto-prunes live entries.

#### Hook integration (Lane B4)
- `hooks/scripts/subagent_telemetry.sh` extended to emit teammate
  heartbeats when `CLAUDE_TEAMMATE_NAME` is set.
- `hooks/scripts/teammate_idle.sh` — new `TeammateIdle` hook marks
  status=idle, surfaces open escalations + stalled deliverables to lead.
- `hooks/scripts/deliverable_check.sh` — new `Stop` hook auto-marks
  promises stalled after 10 min.
- `hooks/hooks.json` — registers `TeammateIdle` and `Stop` entries.

#### Hotfix (Lane B5 — close-audit blockers)
- Fixed broken SQL escape idiom `${var//\'/\'\'}` (4-char artifact, not
  SQL-doubled apostrophe) across all 5 new v5.1.7 scripts AND 3
  pre-existing scripts that carried the same bug (`cmd_mem.sh`,
  `cmd_profile.sh`, `cmd_query.sh`). Replacement is now `''` (literal
  two-apostrophe SQL escape).
- Added numeric-id validation `[[ $id =~ ^[0-9]+$ ]]` to `mailbox ack`,
  `deliverable complete`, `escalate resolve` — closes a live SQL
  injection vector confirmed in audit.
- `cmd_report.sh` materializer switched from `|` separator to ASCII
  `\x1f` Unit Separator across all 4 query sites — fixes corruption when
  finding bodies contain markdown table chars or newlines.

#### Backlog hygiene (Lanes W1, W2)
- 22 open issues in #18–#39 triaged: 3 superseded, 13 still-valid,
  1 close-as-stale. Report at `.artifacts/docs/handoffs/2026-05-20-old-issue-triage.md`.
  Operator close review pending for #18, #25, #32, #39.
- v5.1.6 fixes verified in tree: #45 (dispatch-tier separation) and #46
  (in-process Agent tool restriction, upstream Claude Code #31977) both
  have grep-evidenced verification comments; recommended for close.

### Known gaps (carry to v5.1.8)
- `cmd_discovery.sh` and other legacy subverbs call `resolve_namespace` /
  `current_sprint` helpers that live in `hooks/scripts/_lib.sh` but not
  `skills/context/scripts/_lib.sh` — direct bash invocation of legacy
  subverbs breaks. Pre-existing bug surfaced by Lane A4. New v5.1.7
  insert paths bypass the broken precondition.
- Heartbeat hook fires on `SubagentStop` not per-tool-call; `tool_name`
  column always logs `unknown` because `CLAUDE_TOOL_NAME` env var is not
  set in that hook context. Liveness detection works; tool-name fidelity
  doesn't. Fix or accept in v5.1.8.

### New doctrine (also lands in v5.1.7 — reframe of #54)
- `doctrines/workspace-member-isolation-gate.md` — generalizes axiom's
  per-package feature CI feedback (#54) into a workspace-tool-general
  doctrine. The defect class ("workspace-unified passes, per-member
  isolated fails") affects cargo, pnpm, npm workspaces, turborepo, go
  work, bazel, gradle multi-project, maven reactor — any workspace-aware
  build tool. Doctrine specifies the acceptance contract; per-ecosystem
  realization is project-owned (typically via `shepherd.toml [gates].extra`
  consumed by the v5.1.7 intro-mode regression auditor extras gate).
  Closes #54.

### Deferred to v5.2.0+
- #47 — cross-patch `--scope=minor` / `--scope=version` enumeration
- #53 — `SendMessage heartbeat_payload` first-class runtime primitive
  (shctx infrastructure ready; upstream-dependent)

---

## v5.1.6 — 2026-05-19

### Root-shepherd tier + lane-per-conductor fanout + `--scope` flag

v5.1.6 introduces a **three-tier dispatch hierarchy** under `/shepherd:spawn`,
downgrades the conductor to Sonnet with dual-mode behavior (solo retains full
surface; teammate is restricted), restricts `@engineer` and `@critic` to
root-tier-exclusive dispatch under spawn, adds a `--scope` flag for workload
scaling, and lifts engineer plan minimums toward ultra-parallel composition
(M=6, L=8, XL=10–15 lanes per wave).

The primary new spawn pattern is **lane-per-conductor fanout**: the engineer
designs the plan as W waves × L_w lanes per wave; for each wave, root spawns
L_w teammate-conductors (one per lane). Each teammate gets a tiny stable
prefix (one lane's brief + the conductor profile body), pushing cache hit
rates higher and reducing context pollution. More small focused teammates
becomes both cheaper and higher-quality than fewer broad ones.

`/shepherd:start` and `/shepherd:spawn` remain two independent execution
paths. `/shepherd:start` (solo, main chat) is backward-compatible — full
pipeline, conductor profile, all six lanes dispatchable. `/shepherd:start
--teammate` (NEW) is the teammate-session entry point spawned by `/shepherd:spawn`:
skip Phase 0 / INTRO / engineer / critic (root already did those); read assigned
lane brief; execute lane; surface WAVE-COMPLETE.

#### New

- **`agents/shepherd.md`** — root-tier profile (model: inherit, color: gold).
  Adopted by main chat under `/shepherd:spawn` (operator-explicit only).
  Owns `@engineer` + `@critic` dispatch, artifact materialization from
  teammate payloads, cross-teammate dispute resolution, close-swarm
  coordination. Two-meta-loading with planter for delegated seed work.
- **`doctrines/root-shepherd-orchestration.md`** — root-tier behavioral
  contract: three modes (idle/dispatch/coordinate), responsibilities,
  prohibitions, escalation triage matrix, close-mode flow.
- **`doctrines/dispatch-tier-separation.md`** — binding three-tier matrix.
  Teammate-conductors CANNOT dispatch `@engineer`/`@critic` — surface
  `PLAN-AUTHORSHIP-REQUEST` / `PLAN-GATE-REQUEST` escalations instead.
  Solo-mode `/shepherd:start` retains full dispatch (exemption documented).
- **`doctrines/scope-scale-workload.md`** — `--scope` flag semantics, 4-tier
  mapping (sprint/patch/minor/version), composition with `--parallel`,
  preflight gating for minor/version (operator double-confirm), sprint
  enumeration algorithm.
- **`/shepherd:start --teammate`** flag — teammate-session entry point.
  Skips Phase 0/INTRO/engineer/critic (root did those); loads conductor
  in TEAMMATE mode; reads assigned lane brief from boot prompt; walks
  lane micro-Stage-Graph (DEDUP-GATE → IMPL → LANE-CLOSE); surfaces
  WAVE-COMPLETE via SendMessage.
- **`/shepherd:spawn --scope <value>`** flag — workload scale declaration:
  `sprint` (1 sprint, default), `patch` (≡ retired `--auto`), `minor`
  (experimental, requires `confirm minor`), `version` (experimental,
  requires `confirm version` + resource warning).
- **`/shepherd:spawn Check 0`** — operator-explicit invocation enforcement.
  Refuses nested spawn from teammate sessions (detects via
  `$CLAUDE_AGENT_TEAMMATE_NAME`, INVOCATION-CONTEXT, parent-session env).

#### Changed

- **`agents/conductor.md`** — `model: inherit` → `model: sonnet`. New
  "Conductor modes" section documents dual-mode behavior (solo vs teammate)
  + mode-detection signals. Three new hard prohibitions (#13–#15) for
  teammate mode: no engineer dispatch, no critic dispatch, no artifact
  writes. Lane-per-conductor model documented inline. Peer-to-peer
  messaging permissions defined. Side-effect boundary table split into
  SOLO and TEAMMATE mode sub-tables.
- **`agents/engineer.md`** + **`agents/critic.md`** — new
  `WRONG-TIER-DISPATCH` halt code; tier check is first prohibition in
  Step 0 of critic protocol. `[INVOCATION-CONTEXT]` brief field added.
  Engineer body gains "Ultra-parallel plan template (spawn mode)" section
  with lane structural requirements (`lane_id`, `wave`, `file_scope`,
  `parallel_with`, `steps`, `acceptance` in YAML form). Critic gains a
  seventh core duty: ultra-parallel discipline audit.
- **Engineer plan template** — minimum lane counts raised under spawn mode:
  M=6 (was 4), L=8 (was 6), XL=10–15/wave (was 6+/wave). Body LOC floor
  scaled accordingly (M=400, L=700, XL=1500+). Solo mode retains v5.1.5
  minimums.
- **`commands/spawn.md`** — new Check 0 (operator-only), new `--scope`
  flag section, main chat now adopts `agents/shepherd.md` (not
  `planter.md`) under spawn, boot prompt includes `INVOCATION-CONTEXT` +
  lane-fanout fields + `ROOT-SESSION-NAME`. Teammate first action is now
  `/shepherd:start --teammate` (not bare `/shepherd:start`). Hard-pause
  prompts for `--scope=minor` and `--scope=version`.
- **`commands/start.md`** — `--teammate` flag documented. Teammate path
  is a 5-step lane-execute walk distinct from the solo full pipeline.
- **`skills/shepherd/SKILL.md`** §I — three-tier meta table replaces the
  two-row planter/conductor table. §X invocation row updated for `--scope`.
  §XI see-also adds three new doctrine rows.
- **`skills/shepherd/flock.md`** §VI — three-tier meta table replaces
  two-row table; tier-separation cited.
- **`README.md`** — v5.1.6 section header, three-tier meta table, lane
  table updated with root-tier-exclusive notes on engineer/critic.
- **`CLAUDE.md`** — Shepherd plugin commands table updated with
  `/shepherd:start --teammate` and `--scope` flags. File-contracts section
  enumerates `agents/shepherd.md`.

#### Migration notes

- Operators running `/shepherd:start` in main chat see no behavior
  change — conductor profile remains the runner in SOLO mode. Tier
  separation does NOT apply solo. Backward-compatible with all v5.1.5
  and prior versions.
- Operators using `/shepherd:spawn` now have main chat adopt the
  `shepherd` root profile instead of `planter`. The planter profile is
  loaded only by `/shepherd:plant` or when seed authorship is delegated
  mid-spawn. Both profiles coexist (planter-loaded BEFORE spawn) — the
  shepherd is the outer frame, planter the inner.
- `--auto` is preserved as an alias for `--scope patch` to avoid breaking
  operator muscle memory. Deprecation in v5.2.0, removal in v6.0.0.
- The conductor model downgrade (`inherit` → `sonnet`) lowers cost for
  ALL conductor invocations, including `/shepherd:start` solo. Per
  operator request for cost discipline + Agent Teams behavioral consistency.

#### Known gaps (filed as GH issues)

- In-process teammates cannot dispatch the `Agent` tool (mirror of
  Claude Code #31977) — recommend `tmux` `teammateMode` for `/shepherd:spawn`
  until upstream lands.
- `--scope minor` and `--scope version` ship with sequential-only enforcement;
  cross-patch / cross-minor parallel walks deferred to v5.2.0.
- Peer-to-peer `SendMessage` between sibling teammates is permitted in tmux
  teammateMode; in-process support pending upstream.

---

## v5.1.5 — 2026-05-19

### Spawn flow optimization + flock normalization + token discipline

v5.1.5 is a surface-area optimization release. No new commands, no new agent
roles, no new doctrines. Four parallel lanes tightened the plugin's internal
consistency and token efficiency.

#### Lane A — spawn flow tightened

`commands/spawn.md` streamlined (1027 → 600 effective lines): cleaner dispatch
logic, new **Teammate tool feed** section documenting exactly what flows from
main chat to the teammate-conductor at spawn time. `spawn-escalation.md`
similarly trimmed (494 → 471). `commands/start.md` unchanged.

#### Lane B — conductor dispatch decision tree + specialist examples

`specialist-dispatch.md` expanded (152 → 530 lines) with a **DISPATCH DECISION
TREE** and four worked specialist examples. `conductor.md` reinforced with
three new anti-patterns (#28–30) strengthening flock-first defaults.
`Agent`, `ToolSearch`, and `SendMessage` added to the conductor tools list.

#### Lane C — flock agent normalization

All six flock agents (`engineer`, `critic`, `coder`, `auditor`, `worker`,
`discovery`) normalized to a cache-stable section order with a strive-higher
preamble, `## Adaptability`, and `## What I am NOT` sections. Model
assignments corrected: conductor remains `inherit`-only; flock restored to
original models (5× Sonnet 4.6, engineer Opus 1m).

#### Lane D — cache discipline + token conservation docs

`brief-cache-discipline.md` gained a **BRIEF ASSEMBLY CHECKLIST**.
`cache-telemetry.md` updated with per-role v5.1.5 hit-rate calibration.
`agent-excellence.md` added a sixth rule (token conservation).
`skills/shepherd/SKILL.md` gained a foundational **Token + cache discipline**
section.

### Changed

- `commands/spawn.md` — streamlined; new Teammate tool feed section
- `skills/shepherd/doctrines/spawn-escalation.md` — trimmed to essential content
- `skills/shepherd/doctrines/specialist-dispatch.md` — DISPATCH DECISION TREE + 4 worked examples
- `agents/conductor.md` — 3 new anti-patterns; Agent/ToolSearch/SendMessage in tool list
- `agents/{engineer,critic,coder,auditor,worker,discovery}.md` — normalized section order + model assignments
- `skills/shepherd/doctrines/brief-cache-discipline.md` — BRIEF ASSEMBLY CHECKLIST added
- `skills/shepherd/doctrines/cache-telemetry.md` — per-role v5.1.5 calibration
- `skills/shepherd/doctrines/agent-excellence.md` — sixth rule: token conservation
- `skills/shepherd/SKILL.md` — Token + cache discipline foundational section

---

## v5.1.4 — 2026-05-19

### Teammate-conductor + planter/conductor profile split

v5.1.4 introduces `/shepherd:spawn` for teammate-driven sprint execution and
extracts the orchestrator behavior into two canonical profile files at
`agents/conductor.md` (sprint-runner) and `agents/planter.md` (seed-author +
ambient babysitter). Main chat stays lean as the planter while a spawned
teammate runs the sprint as conductor. `/shepherd:autorun` and
`/shepherd:parallel` retire into `/shepherd:spawn --auto` and
`/shepherd:spawn --parallel <N>` respectively — consolidated command surface
is `{plant, start, spawn, ctx}`.

#### New

- **`agents/conductor.md`** (445 lines, cyan, inherit model) — canonical
  sprint-runner profile adopted by `/shepherd:start` whether main chat or a
  spawned teammate is the runner. Lifts ~620 lines of orchestrator behavior
  from `SKILL.md`, `pipeline.md`, `flock.md`, `autorun.md`, `parallel.md`.
  Strict side-effect boundary (Hard Prohibition #12: no git writes, no
  filesystem cleanup outside dispatch). Tools list trimmed to GitHub
  read-only.
- **`agents/planter.md`** (582 lines, violet, `opus[1m]`) — dual-mode
  profile (plant + spawn babysitter). Lifts ~280 lines from
  `skills/shepherd/planter.md` + `commands/plant.md`. Adds 6/6 net-new
  babysitter subsections: escalation triage, git custody, cleanup
  stewardship, concurrent-write discipline, hand-back timing, observation
  contract. Tools list includes GitHub write tools per side-effect
  ownership.
- **`commands/spawn.md`** (995 lines) — `/shepherd:spawn` command with
  `--parallel <N>` (fan out N sibling teammate-conductors with planter-side
  dev-order merge gate, cap N ≤ 4) and `--auto` (sequential autopilot,
  fresh teammate context window per sprint, planter handles inter-sprint
  cleanup + git + handoff). Platform compatibility note for GitHub issue
  #31977.
- **`skills/shepherd/doctrines/spawn-escalation.md`** (750 lines) —
  canonical teammate↔planter escalation contract: SendMessage primary
  channel, filesystem durable fallback at `~/.claude/tasks/{team}/`,
  `PostToolUse`-driven heartbeat row in shctx, wave-boundary commit
  discipline (≤ 1 wave loss horizon for in-process teammates with no
  `/resume`).

#### Retired

- `/shepherd:autorun` → use `/shepherd:spawn --auto`
- `/shepherd:parallel` → use `/shepherd:spawn --parallel <N>`
- `commands/{autorun,parallel}.md` collapsed to thin delta notes
- `skills/shepherd/{autorun,parallel,planter}.md` collapsed to thin
  redirects pointing at the canonical successors

#### Refactored (thin-loader pattern)

- `commands/start.md`: 99 → 52 lines. Loads `agents/conductor.md` as a
  system-prompt addendum; Step 0 bootstrap preserved (shepherd.toml,
  branch detect, doctrines, handoff, CLAUDE.md).
- `commands/plant.md`: 138 → 52 lines. Loads `agents/planter.md`; Opus
  model gate preserved.
- `skills/shepherd/SKILL.md`: dispatch-procedure block collapsed to a
  pointer at `agents/conductor.md` (mitigates the R3 triple-drift risk
  surfaced by the D-LIFT survey).
- `skills/shepherd/flock.md`: new §VI Meta tier section listing planter
  and conductor profiles.
- `skills/shepherd/pipeline.md`: §IX/§X autorun-walk + parallel-walk now
  correctly attribute loop/fanout control to the **planter** (the
  conductor doesn't loop itself under `--auto`).
- `CLAUDE.md`: flock count corrected to six domain agents + two meta
  orchestrators; commands table updated with spawn row + retirement
  notice; file contracts expanded with `agents/conductor.md` and
  `agents/planter.md` invariants.

#### Phase 0 discovery reports

- `2026-05-19-teammate-api-discovery.md` (D-API) — Agent Teams platform
  surface: `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=true`, in-process
  teammateMode, SendMessage mailbox, `TeammateIdle`/`TaskCreated`/
  `TaskCompleted` hooks. Hard limits documented.
- `2026-05-19-profile-lift-survey.md` (D-LIFT) — ~620 + ~280 lines of
  lift identified by file:line range; 6 babysitter gaps cataloged as
  net-new; 5 overlap questions adopted with operator resolutions.
- `2026-05-19-teammate-subagent-roadmap.md` (R-ROADMAP) — GitHub issue
  #31977 (open, labeled `bug`) is the load-bearing constraint;
  tmux-mode teammates already have Agent tool. Verdict YES-EVENTUAL /
  MEDIUM. Design is forward-compatible — no spawn-side redesign when
  the bug fixes.
- `2026-05-19-flock-teammate-efficacy.md` (R-FLOCK) — per-agent matrix.
  Top-3 leaf-teammate candidates: `@discovery` > `@worker` > `@engineer`.
  Pattern B (peer-to-peer flock teammates) NOT recommended for v5.1.4 (no
  role attestation; deps already file-mediated).

#### Known limitations

- **In-process `teammateMode` + GitHub #31977**: teammate sessions in
  in-process mode do not expose the `Agent` tool, so a spawned teammate
  cannot dispatch the flock the way main chat can. **Workaround**: use
  tmux `teammateMode` for full functionality, or stay on `/shepherd:start`
  in main chat until the bug lands. See `commands/spawn.md
  §Platform compatibility` for the full table.

---

## v5.1.3 — 2026-05-19

### Cleanup, cache discipline, dispatch telemetry

v5.1.3 fixes the base. No new conductor capabilities, no new agent roles, no
semantic changes to the dispatch pipeline. The sprint is a focused sweep:
smaller, more stable agent prefixes; brief ordering that puts variable
content last so prompt caching can do its job; SubagentStop telemetry that
proves the wins are real; and a sweep of accumulated cruft.

#### Agent restructure (Lanes A1 + A2)

- **Five-agent prefix/reference split** — `agents/{engineer,coder,critic,worker,discovery}.md`
  trimmed to the cacheable prefix (frontmatter, identity, prohibitions,
  halt codes, mandatory protocol, report shape, "What you are NOT"); verbose
  reference catalogs extracted to `skills/shepherd/agents/<role>.reference.md`
  loaded on demand via Skill at agent startup.
- **`agents/auditor.md` trim** — same restructure; reference content extracted
  to `skills/shepherd/agents/auditor.reference.md`.
- **Inline `Greatness is the bar` preamble removed** — replaced with a single
  `> See doctrines/agent-excellence.md.` line per agent (doctrine already
  existed; the inline duplication just bloated every dispatch).
- **`tools:` frontmatter audit** — each agent's MCP tool list now contains
  only tools actually invoked by its documented protocol.

#### Brief assembly discipline (Lane B)

- **New doctrine `doctrines/brief-cache-discipline.md`** — stable framing first
  (`[ROLE]` → `[SKILLS]` → `[DOCTRINES]` → `[PROTOCOL-REMINDERS]`), variable
  content last (`[FILE-SCOPE]` → `[CONTEXT-INVENTORY]` → `[DO-NOT-DUPLICATE]` →
  `[ACCEPTANCE]` → `[NON-GOALS]` → `[WORKTREE]` → `[BASE-COMMIT-EXPECTED]`).
  Enforcement is post-hoc via the completeness auditor.
- **`pipeline.md` §V** gains a "Cache-first brief ordering" subsection citing
  the new doctrine.

#### Dispatch telemetry (Lane C)

- **New hook `hooks/scripts/subagent_telemetry.sh`** — captures cache stats
  per subagent dispatch (`cache_read_input_tokens`,
  `cache_creation_input_tokens`, `ephemeral_5m_input_tokens`,
  `ephemeral_1h_input_tokens`, `hit_rate`). Non-blocking on any failure;
  emits `parse_error` rows rather than silently no-op.
- **Registry schema migration 0006** — new `index_cache_usage` table and
  `v_cache_usage` view aggregating per sprint + role.
- **New `shctx query cache-usage`** — surfaces hit-rate per sprint + role.
- **`shctx refresh --scope=telemetry`** — ingests JSONL events into the
  registry idempotently.
- **New doctrine `doctrines/cache-telemetry.md`** — what's captured, where it
  lands, how it surfaces in close reports, threshold guidance (exploratory
  baseline for the first 2–3 sprints; < 40% aggregate hit-rate is a MEDIUM
  finding flag once baselines settle).

#### Cleanup (Lane D)

- Dead command-script sweep (no scripts removed; all `cmd_*.sh` reachable
  through the `shctx` dispatcher's dynamic dispatch or via internal stage
  composition in `cmd_sprint.sh`).
- Stale-reference audit across `skills/shepherd/doctrines/` and
  `skills/shepherd/{pipeline,planter,SKILL}.md` — all `v4.x` / `v5.0.x`
  references are legitimate historical-origin annotations; no operative
  references to removed mechanisms were found.
- `_candidates/` directory contains only its README (the promotion-pipeline
  doc); no orphan candidates to promote or delete.
- Gitignored-but-tracked sweep: zero hits.
- Version-source-of-truth files verified at 5.1.3 across `plugin.json`,
  `marketplace.json`, both SKILL frontmatters, README, and this changelog.

#### Version-scale roadmap doctrine (Lane E)

- **New doctrine `doctrines/version-scale-roadmap.md`** — codifies the
  four-tier scale factor: major `vX` (~1000 sprints, vision), minor `vX.Y`
  (~100 sprints, roadmap), patch `vX.Y.Z` (≤ 10 sprints, the planning unit),
  dev `vX.Y.Z-dev.N` (1 sprint, the execution branch — cut from the patch
  branch as a cushion). Extends `sprint-as-patch.md` upward by naming the
  three levels above the dev sprint.
- **`planter.md` §0** updated to anchor seed authorship at PATCH scope
  (seeds do not carry dev.N suffix).
- **`agents/engineer.md`** updated to cite the doctrine and clarify the
  engineer operates at DEV scope (decomposing the patch seed).

---

## v5.1.2 — 2026-05-17

### Hook teeth, anti-laziness preambles, dir-watch, specialist dispatch, slug naming, discovery registry

The v5.1.1 release landed the new doctrines + agent contracts; v5.1.2 lands
the matching hook teeth, registries, and consistency sweeps. Doctrines from
v5.1.1 now have machine-enforced guardrails instead of being agent-prompt
discipline alone.

#### Hook hardening

- **New `hooks/scripts/_lib.sh`** — shared library every hook sources.
  Exports `is_shepherd_project`, `resolve_namespace`, `json_field`,
  `json_response`, `emit_context`, `emit_deny`, `pass_silent`, `log_event`,
  `current_role`, `current_sprint`, `sprint_root`, `in_subworktree`.
  jq-preferred with python3 fallback. Every emit goes through `log_event`,
  which appends a JSONL entry to `<ns>/logs/hooks/YYYY-MM-DD.jsonl`.
- **New `hooks/scripts/agent_invocation_tagger.sh`** — `PreToolUse(Agent|Task)`
  parses the agent body's `# @<role>` header and writes
  `<ns>/dispatch/<sprint>/<tool_use_id>.json` so downstream hooks can make
  role-conditional decisions without re-parsing prompts.
- **New `hooks/scripts/discovery_capture.sh`** — `PostToolUse(Agent|Task)`
  indexes `## DISCOVERY REPORT` blocks to `<ns>/discoveries/<sprint>/<id>.json`
  for cross-sprint reuse.
- **New `hooks/scripts/dedup_write_guard.sh`** — `PreToolUse(Write|Edit)`
  scans @coder-emitted content for new public symbol declarations
  (rust / python / ts/js / go) and BLOCKS if the symbol already exists
  elsewhere in the workspace. The hook layer's expression of
  zero-duplicate-tolerance — the conductor's pre-dispatch DEDUP-GATE
  remains the primary check; this catches what slips through.
- **`bash_guard.sh` extensions** — adds three role-conditional BLOCK checks
  on top of the v5.1.0 commit-on-lane block: auditor invoking gates from a
  sub-worktree (false-CRITICAL prevention), @discovery invoking
  state-modifying Bash (read-only enforcement), parallel cargo invocations
  WARN, cd-into-worktree WARN.
- **`lock_guard.sh` extensions** — role-based write-path enforcement:
  @discovery may only Write to `{paths.reports}/<date>-discovery-*.md`;
  @auditor may only Write to `{paths.reports}/<date>-(intro-)audit-*.md`;
  @coder Write must land inside the recorded `[WORKTREE].Path` from
  `agent_invocation_tagger`'s dispatch record. Sprint-lock conflict still
  WARN-only (does not block).
- **`agent_pause_detector.sh` extension** — beyond writing the structured
  pause record to `<ns>/pauses/<id>.json`, the hook now ALSO auto-drafts a
  near-complete dispatch brief stub at `<ns>/pauses/<id>.brief.md` per
  the satellite role (coder / discovery / worker / auditor). The conductor
  reads a ready-to-fire brief instead of composing one from scratch.
- **`session_open.sh` extension** — fourth check: when HEAD matches the
  sprint branch pattern, verify the corresponding `plan.md` exists (slug
  OR legacy dotted form). Surfaces missing-plan as a warning so engineer
  dispatch isn't silently skipped.
- **`bash_post.sh` extension** — cwd-drift detection post-Bash; surfaces
  when the conductor's cwd has migrated into a sub-worktree.

#### Anti-laziness — `agent-excellence` doctrine + strive-higher preambles

- **New doctrine** `skills/shepherd/doctrines/agent-excellence.md` — every
  agent must aim higher than "ship code that compiles". Refuse lazy
  duplication, honor language idioms, halt rather than ship sub-standard
  work. Pairs with `dedup_write_guard.sh` (the hook teeth) and the
  zero-duplicate-tolerance doctrine.
- **Strive-higher preamble** prepended to all six `agents/*.md` so every
  flock-agent loads the excellence contract before the role-specific
  instructions.

#### Slug naming convention

- **New doctrine** `skills/shepherd/doctrines/seed-naming.md` — branches
  keep dots (`v5.1.2-dev.3`); filenames collapse them (`v512-dev3.seed.md`).
  Origin: operator caught the planter producing `v0.3.2-dev.5.seed.md`
  (dotted form bleeding from `{sprint_branch}`) when the convention had
  been the slug.
- **`shepherd.toml` schema extension** — `[branching].patch_slug_pattern`
  and `sprint_slug_pattern` added. If absent, framework falls back to
  branch pattern with a deprecation warning.
- **Templates + briefs migrated** to use `{sprint_slug}` / `{patch_slug}`
  for filename construction in `skills/shepherd/references/seed-template.md`,
  `skills/shepherd/references/agent-briefs.md`, `skills/shepherd/SKILL.md`,
  `skills/shepherd/pipeline.md`, `skills/shepherd/doctrines/preflight-doctor.md`,
  `skills/shepherd/doctrines/mid-flight-operator-amendment.md`,
  `skills/shepherd/doctrines/gates-restoration.md`, `commands/plant.md`,
  `commands/parallel.md`, `agents/engineer.md`.
  Branch placeholders preserved where the value is the literal branch
  (git commands, dispatch dir key, milestone target, etc.).
- **Examples in `examples/{axiom,minimal}/shepherd.toml`** include the new
  slug pattern keys.
- **`docs/configuration.md` §[branching]`** documents both pattern pairs.

#### Dir-watch — content-hash gating

- **New migration** `skills/context/schema/migrations/0005_watch_paths.sql` —
  registers watched directories and their last-seen content hash.
- **New `skills/context/scripts/cmd_watch.sh`** — `shctx watch
  add/mark/status/list/remove` over the watch_paths table.
- **New doctrine** `skills/shepherd/doctrines/dir-watch.md` — semantics,
  hashing strategy, integration points (engineer mesh, conductor pre-MESH
  fast-path).

#### Specialist dispatch

- **New doctrine** `skills/shepherd/doctrines/specialist-dispatch.md` —
  framework is "closed at six + specialist exceptions". The flock proper
  remains six; a specialist agent (security-reviewer, perf-analyzer, etc.)
  may be dispatched in addition when the seed names one explicitly.
- **`skills/shepherd/SKILL.md`** + **`skills/shepherd/flock.md`** language
  updated from "closed flock" to "closed at six + specialist exceptions".

#### Discovery registry CLI

- **New `skills/context/scripts/cmd_discovery.sh`** — `shctx discovery
  list/show/search/clear` over the `<ns>/discoveries/<sprint>/<id>.json`
  files captured by `discovery_capture.sh`. Engineer pulls cross-sprint
  discoveries at MESH without re-parsing report markdown.
- **`shctx` dispatcher** routes `discovery` and `watch` subcommands to
  their new handlers.

#### Plugin description trim

The verbose multi-version description in `.claude-plugin/plugin.json` and
`.claude-plugin/marketplace.json` collapsed to a single capability
statement. Per-version detail lives here in CHANGELOG.md.

#### Deferred to v5.1.3

- **Lane B — CLI subcommand reorg** (`shctx workspace/brief/lane/discovery/
  watch/pauses` groups). Scope comparable to all six landed lanes
  combined; better as an isolated refactor.
- **`cmd_doctor.sh` extension** for v5.1.1+ surfaces (`<ns>/discoveries/`,
  `<ns>/dispatch/`, `<ns>/logs/hooks/` writability, intro-wave plan-node
  presence detection). The doctor exists at v5.0.4 baseline; v5.1.1
  surfaces uncovered.
- **`agent_insight_capture.sh` refactor to `_lib.sh`** — v5.0.9 logic still
  functions; refactor risk not worth the cleanup this patch.

---

## v5.1.1 — 2026-05-15

### Discovery agent + INTRO-COMBO-WAVE + hypothesis-driven auditor + sprint-as-patch

Per operator request: introduce `@discovery` (read-only orientation, no
terminal-mutating Bash, sole task is to comprehend) so the conductor and
engineer don't burn context on exploratory reads. Pair with an intro-mode
parallel wave at sprint open. Tighten auditor methodology via
`superpowers:systematic-debugging`. Reframe sprint scope as patch-equivalent
("every dev.N sprint IS a patch in scope").

- **New agent** `agents/discovery.md` — sixth lane in the flock. Sonnet, `thinking: high`, color blue. Tools: Read/Grep/Glob/NotebookRead/LSP, read-only Bash, MCP read-only, Web*, Skill, ToolSearch, TaskCreate/Get/List/Update, and Write restricted to `{paths.reports}/<date>-discovery-<id>.md`. NEVER: Edit, MCP write, Agent dispatch. Five canonical use-case patterns: PRE-MESH-DISCOVERY, PRE-HOTFIX-DISCOVERY, ARCHITECTURE-DISCOVERY, DOCTRINE-RECONCILIATION-DISCOVERY, MCP-STATE-DISCOVERY.
- **New doctrine** `skills/shepherd/doctrines/discovery-readonly.md` — `@discovery` contract, role boundaries vs `@worker` / `@auditor` / `@critic`, max-concurrent rules, report shape, cross-sprint reuse via `<ns>/discoveries/<sprint>/<id>.json`.
- **New doctrine** `skills/shepherd/doctrines/intro-combo-wave.md` — INTRO-COMBO-WAVE between SEED-VERIFY and MESH. Default composition: 3 discoveries (prior-close-audit-summary, canonical-types-freshness, gh-state-inventory) + 2 intro-mode auditors (regression, carry-forward-disposition). All read-only, all in one Agent batch. Engineer reads outputs as `[DISCOVERY-CONTEXT]` + `[INTRO-AUDIT-CONTEXT]` in its MESH brief.
- **New doctrine** `skills/shepherd/doctrines/auditor-hypothesis-driven.md` — every finding now carries Hypothesis + Falsification attempt + Confidence. LOW-confidence findings land under `## Open questions`, not as GH issues. Bayesian finding-class weighting from sprint-patterns registry. Auditor loads `superpowers:systematic-debugging` as Step 1.
- **`agents/auditor.md` rewrite** — Step 1 loads `superpowers:systematic-debugging`. Three modes: `close` (grades), `regression` (intro mode, no grade), `carry-forward-disposition` (intro mode, no grade). Per-finding contract requires the hypothesis triple. Per-concern emphasis sections now lead with a hypothesis-first prompt. New `## Verifications` section for disproved hypotheses.
- **New doctrine** `skills/shepherd/doctrines/sprint-as-patch.md` — every `dev.N` sprint is operator-equivalent to a full patch. Planter sizes seeds at patch-grade; engineer authors plans at patch-grade body depth; critic rejects under-scoped seeds; auditor grades against patch-grade output expectation. T-shirt lane minimums revised: M → 4, L → 6, XL → 6/wave.
- **`skills/shepherd/planter.md` §0** — sprint-as-patch sizing made binding for planter seed authorship.
- **New doctrine** `skills/shepherd/doctrines/hook-event-log.md` — `<ns>/logs/hooks/YYYY-MM-DD.jsonl` schema, jq queries, retention guidance, anti-patterns (no live tailing, no secret logging).
- **New doctrine** `skills/shepherd/doctrines/preflight-doctor.md` — `shctx doctor` preflight semantics, exit-code matrix, integration with `/shepherd:start`.
- **`skills/shepherd/SKILL.md`** — six-agent flock table, INTRO-COMBO-WAVE in §1 INTRO checklist, sprint-as-patch impactfulness contract made binding, six new doctrines indexed in §XI file map, six new anti-patterns (#23–#28).
- **`skills/shepherd/flock.md`** — new `## @discovery` section between `@critic` and `@worker`. Six-agent flock language throughout.
- **`skills/shepherd/pipeline.md`** — `DISCOVERY` and `INTRO-COMBO-WAVE` node types added to §II stage taxonomy. New edge predicates: `on-research-complete`, `on-intro-wave-complete`, `on-intro-audit-complete`.
- **`skills/shepherd/references/agent-briefs.md`** — six discovery brief templates (D-A through D-F) + intro-mode auditor templates + INTRO-COMBO-WAVE single-message dispatch pattern.

#### Hook hardening + preflight (initial scope; full hook overhaul deferred to v5.1.1)

The v5.1.0 release lands the new doctrines + agent contracts; the matching
hook teeth + `shctx doctor` ship in v5.1.1. Doctrines/agent contracts are
the load-bearing change; hooks are the guardrail. Operator can adopt v5.1.0
with hooks left at v5.1.0-baseline; v5.1.1 will add:

- `hooks/scripts/_lib.sh` shared library (jq/python fallback, log_event)
- `hooks/scripts/agent_invocation_tagger.sh` (PreToolUse on Agent|Task)
- `hooks/scripts/discovery_capture.sh` (PostToolUse on Agent|Task)
- `bash_guard.sh` extension (auditor cwd guard + discovery state-modify block)
- `lock_guard.sh` extension (role-based write-path enforcement)
- `agent_pause_detector.sh` extension (auto-draft satellite brief stub)
- `skills/context/scripts/cmd_doctor.sh` (`shctx doctor` preflight)
- `<ns>/logs/hooks/YYYY-MM-DD.jsonl` event log activation

Doctrines/agent contracts are the load-bearing change; hooks are the
guardrail. Operator can adopt v5.1.1 with hooks left at the v5.1.0 baseline.

---

## v5.1.0 — released

### Flock cohesion — shared substrate across agents

Per operator observation: "every agent feels isolated rather than acting as part of a larger group so the agents feel like they need to re-invent everything every time from scratch." This release names the structural gap and lands the substrate.

- **New doctrine** `skills/shepherd/doctrines/flock-cohesion.md` — verbalizes the shared-substrate model. Four channels: canonical-types (static "what exists where"), graph state + trace (mechanical "who is doing what now"), pauses (synchronous "I need this"), and insights (asynchronous "I noticed this"). All four are read at MESH; written at DISPATCH and REPORT.
- **`[SIBLING-LANES]` brief block** (`skills/shepherd/references/agent-briefs.md`) — every wave dispatch brief now lists the other lanes in the wave with their `[FILE-SCOPE]` summaries and the symbols/artifacts they produce. The single most-requested affordance: agents finally see what their siblings are doing. Validity checklist updated.
- **`## INSIGHTS` report section** (`agents/coder.md`, `agents/worker.md`) — optional cross-lane observations any agent can append to their final report. Canonical kinds: `relocation`, `extension`, `duplication`, `consolidation`, `gap`, `nit`. Replaces the absent "I saw something interesting" channel.
- **New hook** `hooks/scripts/agent_insight_capture.sh` — `PostToolUse(Agent|Task)` parses `## INSIGHTS` blocks, writes one JSON record per entry to `<ns>/insights/<sprint>/<id>.json`. Silent when no INSIGHTS block is present.
- **New: `shctx insights <list|show|export|clear>`** (`skills/context/scripts/cmd_insights.sh`) — registry CLI. `export --md` renders as markdown for engineer mesh row 13 consumption.
- **`agents/engineer.md` Phase 0 mesh row 13** — engineer reads the prior sprint's insights at next-sprint mesh; decides per-kind how to action (relocation → consider scoping a lane; nit → aggregate before acting; etc.). Insights NOT actioned are surfaced under "Cross-lane insights not scoped this sprint" — operator visibility is the rule.

### Dispatch cascade — Stage Graph as rule engine

Per operator request: "create some type of rule engine layer that would allow the conductor to dispatch all agents using conditional links so agents cascade through the plan." The plan is now extractable into a machine-readable topology that `shctx graph` walks deterministically — the conductor's only LLM-driven step per tick is brief authoring + edge-label selection; routing is mechanical.

- **New doctrine** `skills/shepherd/doctrines/dispatch-cascade.md` — the plan IS the program; the conductor IS the interpreter; the Stage Graph IS the topology.
- **New: `shctx plan <extract|topology|validate>`** (`skills/context/scripts/cmd_plan.sh`) — parse plan.md's `## Stage Graph` YAML block, materialize `<ns>/graph/state.json`, pretty-print topology, run structural validation (acyclic, predicates resolve, parallel_with mutual).
- **New: `shctx graph <status|next|mark|trace|reset>`** (`skills/context/scripts/cmd_graph.sh`) — the walker. `next` returns the next-eligible batch honoring `parallel_with` cliques. `mark <id> --state=done --exit=<edge>` advances state and auto-promotes downstream nodes when their in_predicates are satisfied. `trace` is append-only at `<ns>/graph/trace.jsonl`.
- **New: `shctx pauses <list|show|resolve|clear>`** (`skills/context/scripts/cmd_pauses.sh`) — the PAUSE-FOR-DEPENDENCY registry. Hook captures pauses; conductor reads structured records via `show`; `resolve --satellite-sha=<sha>` marks completion.
- **New hook** `hooks/scripts/agent_pause_detector.sh` — `PostToolUse(Agent|Task)` parses agent output for `Halt code: PAUSE-FOR-DEPENDENCY`, extracts the structured satellite request, writes `<ns>/pauses/<id>.json`, and surfaces an `additionalContext` alert. Eliminates the LLM re-parsing step.
- **`adaptation-loop.md §V-bis`** — node-level telemetry from `trace.jsonl` (duration, exit-edge frequency, halt rate per node-type) feeds the sprint-pattern registry with finer-grained signal than sprint-level summaries.
- **`pipeline.md §V`** — walk algorithm now references the `shctx graph` runtime mechanization.

### Field feedback from v5.0.8 / axiom v0.3.2-dev.0

**§1 — `PAUSE-FOR-DEPENDENCY` primitive (most requested).** First-class Stage Graph escape hatch for mid-lane out-of-scope dependencies. Coder emits a structured halt → conductor dispatches an XS/S satellite `@coder` → `SendMessage` resumes the paused lane. Cap: 2 satellites/lane. Cherry-pick order invariant: satellite commit lands before resumed-lane commit.
- New: `skills/shepherd/doctrines/pause-for-dependency.md`
- `agents/coder.md` — `PAUSE-FOR-DEPENDENCY` halt code, trigger protocol, report shape
- `skills/shepherd/pipeline.md` — `PAUSE-FOR-DEPENDENCY` + `RESUME-LANE` stage taxonomy; `on-pause-dep` edge predicate; `§XV-quint` subgraph walkthrough

**§2 — Coder lane file-scope cap.** `agents/engineer.md` — soft cap of ≤3 files per lane MAY-MODIFY; single-file exception at >300 LOC.

**§3 — Parallel cherry-pick conflict documentation.** `skills/shepherd/references/branching-model.md §VII-bis` — file overlap between parallel lane branches is expected; how to resolve; STAGE-GRAPH-VIOLATION vs legitimate conflict.

**§4 — Conductor anchor drift hygiene.**
- New: `hooks/scripts/bash_post.sh` — `PostToolUse(Bash)` detects cwd drift into sub-worktrees
- `hooks/hooks.json` — wires the new PostToolUse hook
- `hooks/scripts/session_open.sh` — adds sprint-patterns.md absence warning
- `hooks/scripts/bash_guard.sh` — adds `cd`-into-worktree warning + corrected cargo-parallel regex (no longer false-positives on `cargo check && cargo test`)

**§5 — Cargo sequential gates doctrine.**
- New: `skills/shepherd/doctrines/cargo-sequential-gates.md`
- `skills/shepherd/pipeline.md §XV-sext` — referenced at WAVE-GATE
- `skills/shepherd/SKILL.md §2 BODY` — cross-referenced from gate sequence
- `hooks/scripts/bash_guard.sh` — Check 2: warn on backgrounded cargo invocations (`&` not `&&`)

**§6/§7 — /reload-plugins escape hatch + MCP preference.**
- New: `skills/shepherd/doctrines/plugin-reload-escape.md`
- `skills/shepherd/pipeline.md §XV-sept` — Phase 0 MCP availability + reload note

**§8 — Programmatic GH issue triage (`shctx issues classify`).** Replaces the per-sprint LLM enumeration pass with deterministic label/milestone/severity bucketing from the cached `index_issues` table.
- New: `skills/context/scripts/cmd_issues.sh` — subcommands `classify` and `list`; buckets `blocking-this-sprint`, `labeled-non-issue`, `tracking-future`, `drift-risk`, `unclassified`; `--unclassified-only` for focused LLM review
- `skills/context/scripts/shctx` — registers `issues` subcommand under the `<noun> <verb>` convention
- `agents/engineer.md` Phase 0 mesh row 1 — preferred path is `shctx issues classify`; MCP/gh enumeration is the fallback when cache is stale

**§9 — Sprint-patterns registry verification.**
- `hooks/scripts/session_open.sh` — surfaces `sprint-patterns.md` absence at session start
- `skills/shepherd/SKILL.md §1` — existence check added to INTRODUCTION checklist
- `skills/shepherd/doctrines/adaptation-loop.md` — on-first-close creation protocol

**§10 — Feedback classification.** `skills/shepherd/doctrines/adaptation-loop.md §VI-bis` — framework-generic vs project-specific feedback rule; framework-generic candidates are flagged in close reports for doctrine promotion.

### Fix: prevent dual-namespace split-brain between `.shepherd/` and `.artifacts/`

The root cause: `shctx init` (no flags) defaulted to `.shepherd/` on a fresh project while example `shepherd.toml` files had `[paths]` entries referencing `.artifacts/`. The conductor's Write calls then created `.artifacts/` as a directory side effect, leaving both namespaces present. `shctx_artifacts_root()` always preferred `.shepherd/` while the conductor kept reading `.artifacts/*` — split-brain until the operator migrated by hand.

- `scaffold.sh` — guard refuses to scaffold namespace X when namespace Y already carries the shctx `.gitignore` marker and X does not yet exist. Emits a clear error with remediation steps.
- `_lib.sh` — `shctx_artifacts_root()` now emits a stderr warning when both directories coexist; suppressed via `SHCTX_QUIET=1` in callers that handle this themselves.
- `cmd_doctor.sh` — reports the dual-namespace state as a `WARN` check with a fix instruction.
- `examples/minimal/shepherd.toml` — `[paths]` updated from `.artifacts/` to `.shepherd/` (the v5.0.0+ default); comment added explaining the namespace coupling.
- `examples/axiom/shepherd.toml` — comment added explaining `.artifacts/` is the legacy namespace for that project.
- `skills/context/SKILL.md`, `skills/shepherd/SKILL.md` — hardcoded `.artifacts/` references replaced with namespace-neutral `<namespace>/`.

---

## v5.0.7 — 2026-05-12

**Hotfix: hooks schema.** `hooks/hooks.json` was missing the top-level `"hooks"` wrapper key, causing plugin load failure (`expected record, received undefined`). All event handlers now correctly nested under `{"hooks": {...}}`. Version refs bumped across all five sources of truth.

---

## v5.0.6 — 2026-05-12

**Single-plugin-repo migration + conductor anchor discipline.** Two
independent threads:

1. **Repo isolation.** The plugin tree moved out of `plugins/shepherd/`
   to the repo root in earlier commits; this release finishes the
   migration so manifests, docs, the `shctx release` pipeline, and the
   test suite all agree the repo IS the plugin.
2. **Conductor anchor discipline.** Field feedback flagged a failure
   mode beyond the v5.0.3 cwd ban: the conductor's `git switch <agent-branch>`
   (for "inspection") and `git worktree add` from inside an existing
   worktree silently produced **worktrees-within-worktrees** state.
   v5.0.6 codifies the broader anchor invariant.

### Changed — doctrines

- **`doctrines/conductor-cwd.md` extended to anchor discipline.** Title
  + scope broadened from "conductor cwd" to "conductor anchor (cwd +
  HEAD + worktree context)". Three explicit bans with the correct
  alternative for each:
  - Ban 1 — `cd`/`pushd` into a worktree (the v5.0.3 cwd rule, preserved).
  - Ban 2 — `git switch` / `git checkout` to an `agent-*` lane branch.
    The conductor's HEAD MUST remain `{sprint_branch}` (or `{patch_branch}`/
    `{main_branch}` during release plumbing). Inspect agent branches via
    `git -C <worktree-path>` only.
  - Ban 3 — `git worktree add` from inside a worktree. Always run from
    the sprint root, or use `shctx worktree create-batch` which assumes it.
  Mandatory three-check verification (`pwd` / `git rev-parse --abbrev-ref
  HEAD` / `git rev-parse --git-dir == --git-common-dir`) added to the
  doctrine and wired into the §1 INTRO conductor checklist.

### Added — anti-pattern

- **SKILL.md anti-pattern #22** — `Conductor git switch/git checkout to an
  agent-* lane branch → HEAD drift → wrong-base worktrees → nesting`.
  Cross-references `doctrines/conductor-cwd.md` Ban 2 + Ban 3.

### Changed — anti-pattern

- **SKILL.md anti-pattern #15** sharpened to specify the drift mode (cwd)
  and link to `doctrines/conductor-cwd.md` Ban 1 — distinguishing it from
  the new HEAD-drift case in #22.

### Changed — repo isolation (single-plugin-repo migration finish)

- `.claude-plugin/marketplace.json` — drop the `fl03-skills` entry;
  shepherd `source` is now `.`; homepage URLs point at the repo root.
- `.claude-plugin/plugin.json` — homepage URL fixed; the `.shepherd/root.db`
  description typo corrected to `.artifacts/root.db`.
- `CLAUDE.md` rewritten for the root-level layout (the repo *is* the
  plugin; no more `plugins/shepherd/` prefix).
- `README.md` install section now leads with `/plugin marketplace add
  fl03/shepherd` and symlinks the repo root, not the old subpath.
- `CHANGELOG.md` no longer claims to cover `fl03-skills` (which now lives
  in its own repo).
- `examples/axiom/CLAUDE-snippet.md` — plugin URL + version pin fixed.
- `skills/shepherd/flock.md` — rephrased the `code-style` reference now
  that `fl03-skills/skills/code-style/` lives outside this repo.
- `skills/context/SKILL.md`, `skills/context/schema/0001_init.sql` —
  doctrine + schema header comments updated to the new layout.
- `skills/context/scripts/cmd_release.sh` — `VERSION_FILES` and
  `CHANGELOG_PATH` rebuilt against the root-level manifest set.
- `skills/context/scripts/cmd_doctor.sh` — config-doc pointer updated.
- `skills/context/tests/test_release.sh` — fixtures match the new bump
  targets.

### Added — adaptation loop (self-improvement)

- **`doctrines/adaptation-loop.md`** (new) — sprint pattern registry (`{paths.ctx}/sprint-patterns.md`): append-only, per-sprint. Write protocol: completeness auditor at CLOSE-SWARM. Read protocol: `@engineer` mesh row 10, `@planter` seed context. Conductor fires `[TREND]` alert at PAUSE when 3+ same-concern CRITICAL/HIGH across 3 consecutive sprints.
- **`agents/engineer.md`** — mesh row 10 (sprint-pattern registry), four action triggers (systemic risks / chronic carry-forwards / recurring halts / clean-streak concerns), plan-quality bar item, ENGINEER REPORT field.
- **`agents/engineer.md`** — mesh row 11 (prior close-audit reports self-learning hook): reads `{paths.reports}/*-audit-*.md`, surfaces `HF-this-sprint=no, carry=yes` findings into the carry-forward checklist; recurring deferred findings flagged `[CHRONIC-CANDIDATE]`.
- **`agents/critic.md`** — §6 sprint-pattern awareness, Pattern Echoes output section, clarified PROCEED WITH CHANGES vs RECONSIDER boundary.
- **`agents/auditor.md`** — completeness concern writes sprint-pattern journal entry (5-step); `## Pattern delta` report section.
- **`agents/worker.md`** — Pattern 5: sprint pattern registry backfill brief template.
- **`skills/shepherd/planter.md`** — mesh row 12 names `sprint-patterns.md`; §VI.A sprint-pattern seed-action table.

### Added — operator communication + session continuity

- **`skills/shepherd/SKILL.md` §VIII** — Operator communication norms: mandatory surface moments, status line format `[NODE] {node-id} → {outcome} | {one-sentence key finding}`, no-silent-proceeding rule, no walls-of-text rule.
- **`skills/shepherd/SKILL.md` §IX** — Session continuity: 5-step mid-sprint recovery protocol (locate plan → read walk trace → survey git log → check orphan worktrees → reconstruct walk position).

### Changed — language-agnostic gates

- `skills/shepherd/SKILL.md` §III and `skills/shepherd/flock.md` — gate sequence now uses `{gates.format}`, `{gates.check}`, `{gates.lint}` from `shepherd.toml [gates]` instead of hardcoded `cargo` commands. Language-skill auto-fix note added.
- `skills/shepherd/flock.md` — anti-pattern #17: missing sprint-pattern registry read at mesh time.

### Added — doctrines (axiom dev.8a field feedback)

- **`doctrines/work-bound-to-tracking.md`** (new) — every intentional gap in production code cites a GH issue number via a language-native stub primitive (`todo!("see #N")` / `throw new Error("TODO see #N")` / `raise NotImplementedError("see #N")` / `panic("TODO see #N")`). Enforcement: `@engineer` counts stubs at mesh, `@coder` must pair stub with GH issue, `@auditor` greps for naked TODO/FIXME/XXX/HACK.
- **`doctrines/mid-flight-operator-amendment.md`** (new) — four amendment types (clarification, feature addition, production regression, architectural decision) with defined conductor responses; dispatcher-patch ledger at `{paths.ctx}/dispatcher-patches/{sprint_branch}-pc-{N}.md`; HARD-STOP triggers (secret rotation, north-star change, security rollback).
- **`doctrines/_candidates/README.md`** (new) — promotion pipeline from project-specific memory to framework-intrinsic doctrine; candidate template with frontmatter; promotion checklist.
- **`doctrines/worktree-base-drift.md`** — `§Canonical no-isolation workaround (v5.0.6)`: when `isolation:"worktree"` defaults to `main`, drop isolation entirely; rely on file-disjoint `[FILE-SCOPE]`; coders commit directly to sprint branch. Documents what you lose (cherry-pick barrier, worktree-confinement enforcement) and mitigations (disjoint plan + post-wave `git diff --stat`).
- **`doctrines/conductor-cwd.md`** — `§HEAD advancement in no-isolation mode`: HEAD advancing as coders commit to the sprint branch is NOT a doctrine violation; the invariant is "HEAD stays on `{sprint_branch}`", not "HEAD stays pinned to dispatch-time SHA".

### Added — pipeline stages + dispatch patterns

- **`skills/shepherd/pipeline.md`** — `HOTFIX-DYNAMIC` stage type: variable-cardinality `@coder` batch derived from gate-error cluster analysis at walk-time (vs. pre-declared HOTFIX). Stage Graph YAML example included.
- **`skills/shepherd/pipeline.md` §XIII-bis** — Structured gate output + parallel HF dispatch: `--message-format=json --keep-going` collects full error surface; errors parsed and clustered by file-disjoint scope; one `@coder` per cluster dispatched in a single batch. Gate JSON artifacts stored in `.shepherd/runs/`.

### Added — standard worker dispatch templates

- **`skills/shepherd/references/agent-briefs.md`** — W-A/B/D/E standard worker brief templates:
  - **W-A** — test-surface audit (classify all tests into 4 buckets; 10 min, 30 calls)
  - **W-B** — Phase 0 mesh validation (GH issues + Sentry + deploy status; 15 min, 20 calls)
  - **W-D** — bulk GH issue triage + close script generation (20 min, 60 calls)
  - **W-E** — production diagnostic for regression amendments (15 min, 40 calls)

### Added — plugin hooks

- **`hooks/hooks.json`** (new) — plugin-shipped hooks activating automatically on install; three guards:
  - `SessionStart` → `session_open.sh`: verifies conductor HEAD is not on `agent-*`/`lane-*` branch and cwd is the primary worktree; warns on orphan sub-worktrees.
  - `PreToolUse(Bash)` → `bash_guard.sh`: blocks `git commit` when HEAD is on an agent/lane branch (`permissionDecision: deny`).
  - `PreToolUse(Write|Edit)` → `lock_guard.sh`: warns when `.artifacts/shepherd.lock` or `.shepherd/shepherd.lock` is held by a different session ID.

### Notes for upgraders

- The doctrine extension is **behavioral**, not schema-level — no
  migrations, no config changes, no breaking interface for consumer
  `shepherd.toml` files. Conductors that already honored `conductor-cwd.md`
  inherit Ban 2 + Ban 3 as the same intent, now explicit.
- Subagents (coders, auditors, workers) **may continue to freely inhabit
  worktrees**. The doctrine binds the conductor's session only; this is
  called out explicitly in the "When the rule does not apply" section.
- The session-open verification adds three `git rev-parse` calls. Negligible
  cost; catches drift before it produces silent breakage.
- **Hooks require jq or python3** in the shell environment at hook execution time. Both are standard on macOS and common Linux distributions.

---

## v5.0.4 — 2026-05-05

**v5.0.3 field-feedback batch + ctx production-grade pass + token-budget
pipelines.** Compiled live from the v5.0.3 conductor's working notes during
the axiom v0.3.0-dev.5 sprint
(`~/src/fl03/axiom/.artifacts/docs/shepherd-v503.feedback.md`). Every
addition cites the originating §. Plus operator-driven asks: ctx command
production-grade, multi-step automation pipelines, flag consistency, and
project-agnostic cleanup.

### Added — doctrines

- **`doctrines/worktree-base-drift.md`** *(§1)* — explicit ban on
  `Agent({ isolation: "worktree" })` for sprint coder dispatch. Conductor
  pre-creates worktrees from sprint HEAD via `shctx worktree create-batch`,
  then pastes `[WORKTREE-PATH]` and `[BASE-COMMIT-EXPECTED]` into briefs.
  Eliminates the v5.0.3 axiom dev.5 BASE-DRIFT pattern.
- **`doctrines/worktree-confinement.md`** *(§3)* — ALL coder writes
  (including `.shepherd/ctx/*.md`) MUST land under `[WORKTREE].Path`.
  Writes to sprint root are silently dropped from the cherry-pick;
  documented with the field origin and a worked example.
- **`doctrines/coder-brief-format-shared-artifacts.md`** *(§4)* — when
  multiple coder lanes write to the same shared file, the brief specifies
  Pattern A (line-range partition), Pattern B (footer-append), or
  Pattern C (single-author-per-file). Prevents cherry-pick conflicts.

### Added — references

- **`references/grading-rubric.md`** *(§9)* — explicit weight + numeric
  formula for synthesizing per-concern audit grades into a sprint-level
  grade. Default weights: completeness 0.35, code-quality 0.20,
  dependency-topology 0.20, data-flow 0.15, datastore-state 0.10.
  Overridable via `[gates.audit_weights]` in shepherd.toml.

### Added — context registry

- **`shctx worktree create-batch <lane-id…> [--from=<branch>]`** *(§1)* —
  pre-creates one worktree per lane-id at `.claude/worktrees/agent-<id>`
  rooted at the HEAD of `--from` (default: current branch). Emits
  `[BASE-COMMIT-EXPECTED] <SHA>` for the brief. Idempotent.
- **`shctx doctor [--md|--json]`** — first-class diagnostic / pre-flight:
  required binaries, namespace dir + project.json, schema version +
  pending migrations, lock state (held/stale/free), refresh staleness per
  zone, shepherd.toml locatability. Exit 0 / 1 / 2 (ok / fail / warn).
- **Multi-step pipelines (operator ask):**
  - **`shctx sync [--scope=…|--all]`** — refresh → lint → status.
  - **`shctx ready`** — init → migrate → refresh `--all` → lint → doctor.
  - **`shctx sprint open <branch>`** — lock acquire → refresh `--all` →
    lint → status.
  - **`shctx sprint wave <id> [--all]`** — refresh github+artifacts → lint
    (replaces `auto_refresh = ["on-wave-gate"]`).
  - **`shctx sprint close <branch>`** — close-lane (each known) → handoff
    create → worktree gc → lock release.
  - **`shctx audit`** — read-only validation: lint → doctor → status.
- **`shctx_gh_retry()` helper in `_lib.sh`** *(§8)* — 3× retry with
  exponential backoff for transient `gh` failures (504/502/503/timeout).
  Wired into `refresh-github.sh` + `cmd_close-lane.sh`.
- **`shctx export --all`** — bundles every export kind (canonical-types,
  open-issues, open-prs, recent-releases, drift-risk, mem) to a directory.
- **`shctx mem show <id>` + `shctx mem rm <id>`** — completes the mem CRUD
  surface (was add/list/search/pin/unpin).
- **`shctx lock release --force`** — explicit alias for force-clearing a
  stuck lock (parallel to `lock reap`).
- **Role-tailored `shctx inject`** *(token budget)* — engineer gets the
  full context surface (limit 80); coder gets a `[FILE-SCOPE]`-filtered
  subset (limit 30); auditor gets cross-cutting state only (limit 25).
  `--limit=N` overrides; `--full` removes the cap. Meaningful per-brief
  token reduction without quality compromise.

### Added — flag consistency

- **`--all` is the canonical universal flag** across `refresh`, `search`,
  `style init`, `worktree gc`, `lock release`, `export`. Aliases
  `--scope=all` where applicable; preserves backward compat. The
  inconsistency caller-side (`--all` here, `--scope=all` there) is
  resolved.

### Added — Stage Graph node taxonomy

- (No new node types; `WORKTREE-CREATE-BATCH` is now the conductor-inline
  predecessor of every `WAVE-IMPL` per `worktree-base-drift.md`.)

### Hardened — auditor discipline *(§2)*

- **`agents/auditor.md`** — new hard constraint: auditors verify
  `git rev-parse HEAD` matches the sprint root before invoking any gate
  command. `WORKTREE-DRIFT` halt code added. Every gate finding cites the
  gate's `Finished` or `error:` line verbatim as evidence.
- **`doctrines/auditor-readonly.md`** — adds the WORKTREE-DRIFT halt
  with field-origin attribution.

### Hardened — coder discipline *(§3)*

- **`agents/coder.md`** — new hard prohibition: NEVER write outside the
  worktree, including `.shepherd/ctx/*.md` artifacts. Cite
  `doctrines/worktree-confinement.md`.

### Hardened — SUBTRACT doctrine *(§5)*

- **`doctrines/subtract-dont-add.md`** — LOC-delta measurement scoped to
  `[gates.subtract_paths]` from `shepherd.toml`. Documentation, audit
  artifacts, plans, reports, journals are OUTSIDE scope by construction.
  Default glob is Rust-leaning (`crates/**/*.rs bin/**/*.rs **/*.toml
  **/*.sql`); override per-project for other languages.

### Hardened — pipeline.md

- New § XV-bis: worktree `target/` policy (worktrees DO share parent
  cache; coder no-cargo prohibition stays in force).
- New § XV-ter: `SendMessage` (existing agent) vs `Agent({...})` (new
  spawn) distinction for operator-directed amendments *(§7)*.
- New § XV-quater: shared-context append discipline (cross-ref).

### Compressed — token optimization (operator ask)

- **`SKILL.md` § VII anti-patterns** — collapsed from 18 verbose
  paragraphs to 21 single-line cues with doctrine cross-references.
  Authoritative content lives in the doctrines; the cue list is just
  the conductor's mental index.
- **Role-tailored inject** (above) — delivers the token savings where
  briefs are largest.

### Project-agnostic cleanup

- **`cmd_init.sh`**, **`styles/rust.md`**, **`doctrines/use-mcp-not-cli.md`**
  — replaced residual axiom-specific examples with project-agnostic
  placeholders. Bundled defaults are now neutral; project-specific
  details belong in the consumer's `.shepherd/styles/<lang>.md` and
  `.claude/doctrines/`.
- **`doctrines/conductor-cwd.md` + `gates-restoration.md`** — added
  "Project-agnostic principle:" preamble to each, separating the
  framework-intrinsic rule from its field-origin attribution.
- **Auto-detection** of `.shepherd/` vs `.artifacts/` audited across
  every script: only `_lib.sh` and `cmd_init.sh` reference either path
  literally; all other scripts route through `shctx_artifacts_root()`.
- **`[gates.subtract_paths]`** added to `docs/configuration.md` — gives
  projects an explicit knob for the SUBTRACT scope without baking
  language-specific globs into the framework.

### Tests

- 5 new tests: `test_doctor.sh`, `test_sync.sh`, `test_sprint_pipelines.sh`,
  `test_worktree_create_batch.sh`, `test_flag_aliases.sh`. Suite is now
  27/27 passing on macOS bash 3.2.

### Migration notes

- No new schema migrations — all v5.0.4 features run on the v5.0.3 schema
  (0001–0004). `shctx migrate` is a no-op for v5.0.3 → v5.0.4 upgrades.
- Coder briefs SHOULD now include `[WORKTREE-PATH]` (in addition to
  `[BASE-COMMIT-EXPECTED]` from v5.0.3). Pre-v5.0.4 conductors recording
  the SHA but no path keep working.
- `shctx inject coder --scope=<glob>` is new; old call form
  `shctx inject coder` still works (returns the unfiltered top-30 set).

### Pushed to v5.1+ (intentionally NOT in this patch)

- syn-based Rust symbol parser (drops shell regex)
- Vector embeddings on top of FTS5 for semantic search
- `index_imports` + `index_callers` cross-reference tables
- Hook-based engineer source-code-write filter (currently a doctrine)
- `shctx ctx-merge <file> <wt-1> <wt-2>` automated section-partitioned
  merger for shared `.shepherd/ctx/*.md` files
- Per-worktree `target/` isolation via `CARGO_TARGET_DIR` (currently
  documented in pipeline.md § XV-bis as opt-in via `[env]` block)

---

## v5.0.3 — 2026-05-05

**Field-feedback-driven discipline + tooling.** Compiled live from the v5.0.1
conductor's working notes during the axiom v0.3.0-dev.4 XL rescue sprint
(`~/src/fl03/axiom/.artifacts/docs/shepherd_feedback_v501.md`). Every
addition cites the originating §.

### Added — doctrines

- **`doctrines/conductor-cwd.md`** *(§2.1)* — the conductor never `cd`'s mid-Bash. Use `git -C <path>` and absolute paths instead. Bash's persistent cwd was causing conductor commits to land on worktree branches.
- **`doctrines/gates-restoration.md`** *(§2.4)* — when gates are red, run a conductor-inline `GATES-DISCOVERY` first to capture the FULL latent error inventory, then brief Lane 0 on all errors — not just the engineer-found subset. Cuts the 5–7-iteration hot-fix cascade pattern.

### Added — brief contract

- **`[BASE-COMMIT-EXPECTED]` block** in coder briefs *(§2.3)* — the conductor records `git rev-parse HEAD` of `{sprint_branch}` immediately before dispatch and pastes the SHA into the brief. The coder's new **Step 0.5** verifies and halts with `BASE-DRIFT` on mismatch (catches worktrees branched from `main` instead of the active sprint branch — the v5.0.1 cherry-pick storm).
- New halt code: **`BASE-DRIFT`** (alongside `BRIEF INVALID`, `CONTEXT-INVENTORY STALE`, `DUPLICATION RISK`, `BRIEF-AMENDMENT REQUEST`, `SCOPE OVERFLOW`).

### Added — context registry

- **`shctx search <text>`** *(§3)* — FTS5 fast-path over symbol index + artifact content. `--scope=symbols|artifacts|all`, `--md|--json`, `--limit=N`. Solves the "which crate has the BookSnapshot type?" / "did any close report mention X?" queries that grep returns thousands of false positives for.
- **`shctx close-lane <lane-id> --sprint=<branch> [--issues=#a,#b] [--status=...]`** *(§2.7)* — record a mid-sprint lane closure; auto-resolves carry-forward ledger entries by querying `gh issue view --json state`; emits a markdown patch the conductor commits to the ledger.
- **`shctx worktree list|gc|merge`** *(§4 P3)* — worktree hygiene helpers. `gc --older-than=<hours>` prunes stale `.claude/worktrees/agent-*`. `merge <agent-id> --strategy=theirs|prompt --no-cleanup` cherry-picks a coder's worktree HEAD onto the sprint branch with optional cleanup. Uses `git -C <path>` per `doctrines/conductor-cwd.md` — conductor never leaves sprint root.
- **`v_canonical_types` view tightened** *(§2.2)* — now filters to `kind ∈ {struct, enum, trait, class, interface, type-alias}` AND `visibility = pub`. The previous broad-query semantic moved to the new `v_canonical_symbols` view.
- **`auto_refresh = ["on-wave-gate"]` trigger** *(§2.8)* — fire `shctx refresh --scope=github,artifacts` after every `WAVE-GATE`. Combats stale carry-forward / dedup-ledger drift mid-sprint. Recommended for L/XL sprints.

### Added — schema migrations

- **`0003_canonical_types_filter.sql`** — recreates `v_canonical_types` with kind+visibility filters, adds `v_canonical_symbols` for broad queries, adds `lane_closures` table for the `close-lane` audit trail.
- **`0004_fts_search.sql`** — adds `index_fts_symbols` + `index_fts_artifacts` FTS5 virtual tables with sync triggers, plus a `content` column on `artifacts` so artifact body is searchable. Backfills both FTS tables for projects upgrading from older schemas.

### Added — Stage Graph node taxonomy

- **`GATES-DISCOVERY`** — conductor-inline; predecessor of any `WAVE-IMPL` whose mission is "restore the gates" (typically Wave 0 / Lane 0). Per `doctrines/gates-restoration.md`.
- **`LANE-CLOSE`** — conductor-inline (`shctx close-lane <lane-id>`); fires after each `WAVE-GATE` per lane. Carry-forward auto-resolution.

### Hardened — engineer prohibition

- **`agents/engineer.md` "DO NOT write source code" doctrine substantially stiffened** *(§2.5)*. Field origin: v5.0.1 commit `ffd9dbd7` where the engineer wrote `.rs` to "fix two clippy items". The new wording lists the specific path extensions banned, names the auditor `completeness` grep that catches the violation, and gives the alternative pattern (`BRIEF-AMENDMENT REQUEST` for a hot-fix coder lane). Plus a new "When you spot a bug while meshing" section that walks the discipline.

### Hardened — symbol extractor

- **`refresh-symbols.sh`** *(§2.2)* — now indexes `pub use` re-exports (single, group, and `as Alias` rename forms). `re-export` is a new `kind` value. Multi-line `pub trait Foo: Bar where ...` declarations are picked up via the line carrying the trait name.
- Conductor anti-patterns (15–18) added to `SKILL.md` §VII covering all the discipline shifts above (cwd, broad-sweep, base-drift, stale-ledger).

### Tests

- 4 new tests: `test_search.sh`, `test_close_lane.sh`, `test_canonical_types_filter.sh`, `test_pub_use_re_exports.sh`. Suite is now 22/22 passing on macOS bash 3.2.

### Migration notes

- Run `shctx migrate` once per project on upgrade. 0003 + 0004 apply idempotently. Existing projects' `artifacts.content` starts NULL and populates on next `shctx refresh --scope=artifacts`.
- `[context].auto_refresh` is additive. Add `"on-wave-gate"` to opt in; existing projects without the entry behave unchanged.
- `[BASE-COMMIT-EXPECTED]` becomes mandatory in v5.0.3 briefs. Conductors running pre-v5.0.3 plans should add it manually (the SHA from `git rev-parse HEAD` at dispatch time).

### Pushed to v5.1+ (intentionally NOT in this patch)

- syn-based Rust symbol parser (drops shell regex)
- Vector embeddings on top of FTS5 for semantic search
- `index_imports` + `index_callers` cross-reference tables
- Hook-based engineer source-code-write filter (currently a doctrine; would need user-project hook installation)

---

## v5.0.0 — 2026-05-XX

**MAJOR — adds context registry contract.**

- **DEFAULT CHANGE:** per-project namespace is now `.shepherd/` (auto-detects existing `.artifacts/`; `init --artifacts` opts back in).
- **NEW:** `/shepherd:ctx` command + bundled `shctx` CLI.
- **NEW:** Per-project SQLite registry at `.shepherd/root.db` (or `.artifacts/root.db` for legacy opt-in; schema 0001).
- **NEW:** Doctrine `context-registry.md` (cache vs canonical zones, fall-back contract).
- **NEW:** DEDUP-GATE Layer 2 SQL fast-path (`shctx query dedup-check`); grep remains contract.
- **NEW:** `[DB-CONTEXT]` block in coder briefs (optional in c; mandatory in d).
- **NEW:** `mem` subcommand replaces external `remember` plugin.
- **NEW:** Lock-coordinated autorun + parallel sessions (`.artifacts/shepherd.lock`).
- **NEW:** `shepherd.toml` `[context]`, `[context.refresh]`, `[context.lock]`, `[context.naming]` sections.
- **NEW:** Naming-convention enforcement (`shctx lint`).
- **NEW:** `shctx style <init|show|edit|list>` — per-language project style files at `.artifacts/styles/<lang>.md` (rust/python/typescript/go/shell/sql).
- **NEW:** Schema migration `0002_styles.sql` — `styles` table.
- **NEW:** Conductor mechanically injects `[CODE-STYLE]` block from `.artifacts/styles/<lang>.md` into every coder brief whose `[FILE-SCOPE]` matches a language.
- **NEW:** Doctrine `worker-patterns.md` — main-chat dispatch heuristics for non-code work (issue triage, deploy monitoring, branch cleanup, research, file org).
- **HARDENED:** Engineer brief now enforces seed → `superpowers:brainstorming` → `superpowers:writing-plans` load order; auditor `completeness` verifies trace.
- **HARDENED:** Auditor `completeness` checks `[CODE-STYLE]` presence on every code-touching coder lane.
- Self-host: this repo now scaffolds `.artifacts/` and registers its own design specs.

Migration from v4.2.0: run `shctx init` once; existing markdown artifacts continue to work. DB is optional in milestone (c); becomes contract-mandatory in milestone (d) of the v5.0.0 line.

---

## [4.2.0] — 2026-05-04

The Stage Graph release. Orchestration moves from the conductor's working memory into a declarative DAG the engineer's plan emits. Plus a hard zero-tolerance dedup contract enforced as a conductor-side pre-dispatch gate.

### Added

- **`skills/shepherd/pipeline.md`** — the Stage Graph contract. Defines node taxonomy, edge labels, walk algorithm, and the canonical sprint DAG. Pattern B is now a graph constraint (`parallel_with`); WORKER-IO is auto-batched with WAVE-1-IMPL by graph construction.
- **`skills/shepherd/doctrines/stage-graph.md`** — the principle: every plan emits a Stage Graph; every dispatch is a graph edge; off-graph dispatch is a process violation auditors catch.
- **`skills/shepherd/doctrines/zero-duplicate-tolerance.md`** — three-layer anti-duplication contract. Layer 1: engineer pre-populates `[CONTEXT-INVENTORY]` and `[DO-NOT-DUPLICATE]`. Layer 2 (the primary defense): conductor runs every dedup grep BEFORE the Agent batch fires; hits ≠ expected → dispatch BLOCKED, brief amended to "wire to existing", re-fire. Layer 3: coder-side fallback halt. Includes mechanical `[SKILLS]` auto-attachment per file scope, the `{paths.ctx}/canonical-types.md` workspace catalog contract, and cross-coder coherence rules.
- **`DEDUP-GATE` graph node** — runtime body of the Brief-Validity Checklist; predecessor of every WAVE-IMPL.
- **`CANONICAL-TYPES-REFRESH` worker node** — fires at every dev.0; refreshes `{paths.ctx}/canonical-types.md` so subsequent sprints' Phase 0 starts from a current workspace catalog.
- Stage decomposition hint section (§7-bis) in `references/seed-template.md` — the planter sketches a non-binding partial DAG; the engineer specializes it into the binding `## Stage Graph` plan section.
- Required `## Stage Graph` plan section per `agents/engineer.md` §"plan-quality bar".

### Changed

- **`skills/shepherd/SKILL.md` §III** — references the Stage Graph as the dispatch source-of-truth. Conductor checklists per §1/§2/§3 reformulated as graph-walk operations. Anti-patterns table extended (off-graph dispatch, stale canonical-types catalog, dedup-skip elevated to ZERO-TOLERANCE).
- **`skills/shepherd/flock.md` @coder Required-Skills Matrix** — conductor now MECHANICALLY computes `[SKILLS]` per file scope from `[skills.mandatory]` + `[skills.detection]` + `[skills.by_domain]`. Engineer's suggestions are a SUBSET, never authoritative. Skill-attachment audit at sprint close emits `SKILL-DRIFT` findings.
- **`skills/shepherd/flock.md` Brief-Validity Checklist** — IS the runtime body of the DEDUP-GATE node. Failure on any line BLOCKS dispatch.
- **`skills/shepherd/references/agent-briefs.md` Brief-Validity Checklist** — restructured into brief-shape / skills auto-attachment / anti-duplication pre-flight sections, each enforced before the Agent batch fires.
- **`agents/coder.md` Startup Protocol** — Step 2 now requires reading `{paths.ctx}/canonical-types.md` first; Step 3 (dedup grep) framed as a fallback tripwire (the conductor's pre-flight is the contract, not the coder's halt).
- **`agents/engineer.md`** — plan-quality bar requires `## Stage Graph` section; hard prohibitions extended to forbid omitting the graph.
- **`skills/shepherd/autorun.md`** — loop is "walk graph, then re-walk new graph for next sprint" instead of "remember the per-stage discipline". Cognitive load drops.
- Plugin manifest description updated to surface Stage Graph + DEDUP-GATE.

### Compatibility

Pre-4.2.0 plans without `## Stage Graph` continue to work — the conductor falls back to the §III §1/§2/§3 sequencing in `SKILL.md`. New plans (post-install) MUST emit the graph.

### Why this version

The pre-4.2.0 conductor re-derived dispatch sequencing at every decision point by reading SKILL.md §III + flock.md + the plan in working memory. Cognitive cost was high; failure modes (silent drift, skipped Pattern B, ad-hoc dispatch, **duplicate code re-introduced across sprints**) compounded. v4.2.0 moves orchestration from working memory to declarative artifact: the engineer emits the graph; the conductor walks it; deviation is structurally visible. Plus the DEDUP-GATE makes duplicate-code-shipping mechanically impossible — the conductor blocks the Agent batch before the coder ever sees it.

---

## [4.1.0]

GitHub-leverage release. Planter publishes patch arcs into GH milestone descriptions; sprint seeds remain local. Lane discipline anchored by GH issues. Full-ledger Phase 0 sweep (combats tunnel vision). Carry-forward chronic flagging at ≥ 2 patch crossings.

## [4.0.0]

Initial extracted-and-generalized cut from the v3.2.0 axiom-pinned skill. Closed-flock contract (5 agents: engineer, critic, coder, auditor, worker). Three-section sprint pipeline. Project-agnostic via `.claude/shepherd.toml`. Four commands (`plant`, `start`, `autorun`, `parallel`).

---

## Tagging

After this release lands on `main`:

```bash
git tag -a v4.2.0-shepherd -m "shepherd v4.2.0 — Stage Graph + DEDUP-GATE"
git push origin v4.2.0-shepherd
gh release create v4.2.0-shepherd --notes-from-tag --title "shepherd v4.2.0"
```
