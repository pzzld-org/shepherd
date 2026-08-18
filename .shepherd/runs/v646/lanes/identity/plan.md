# Lane `identity` — plan (run v646)

Objective: a freshly initialized project can dispatch, and errors name the actual failure.

Owning conductor: lane `identity`. Escalation target: team-lead.
Base commit at boot: 58aadf4, branch v6.4.6.
W0-GATE evidence: `./w0-gate.md` (reproduced 2026-08-17, before any fix).

## 1. What W0 proved

| Claim | Measured |
|---|---|
| `init` writes no identity | `.shepherd/project.json` ABSENT after `init --confirm`, exit 0 |
| `init` registers no project | `SELECT COUNT(*) FROM projects` = 0, table present |
| doctor lies | `status: ok`, exit 0, on that namespace |
| remediation is circular | `shepherd mem list` -> `no project registered — run 'shepherd init' first` |
| ENOENT reads as a symlink attack | 0 symlinks in fixture, yet `cannot open project identity ... without following symlinks: No such file or directory (os error 2)` |
| the bug is wider than the seed recorded | `dups check src/lib.rs` on a missing file also says `without following symlinks` |

Fixture matched the operator's pzzld vault exactly: 507904-byte database, 89-byte comment-only
`shepherd.toml`. The vault is not corrupted. It is what `init` produces.

## 2. Corrections to the seed's citations

Verified against the tree, both matter for the gate ledger:

1. Only ONE test asserts `without following symlinks`: `crates/cli/tests/wave_f_knowledge.rs:111`
   (`dups_check_rejects_symlinks_and_oversized_files`). The seed also cites
   `crates/cli/tests/dispatch_cli.rs:232`, but that line sits inside
   `linked_worktree_uses_only_the_primary_project_and_active_run_store` and asserts primary-root
   precedence, not a symlink refusal. **dispatch.rs's symlink path has no test.** This lane adds it.
2. `crates/cli/tests/wave_c_bootstrap_cli.rs:45` is the inert init gate. It asserts
   docs/ctx/runs/shepherd.toml/shepherd.db plus five absent retired roots, and never looks at
   `project.json` or the `projects` table. It is green on a namespace that cannot dispatch.

## 3. Locked directions carried into every step

1. `init` is the single, `--confirm`-gated, descriptor-safe place to create identity.
2. Dispatch KEEPS HARD-FAILING on missing identity. No auto-heal, no lazy create, anywhere.
3. Scaffolding is atomic or it fails, with the rollback set defined in step I3 below.
4. `doctor` FAILS LOUDLY on a namespace missing identity.
5. NOFOLLOW stays. Only the error classification changes.
6. `dep:config` owns configuration. The direction is one-way, never back toward `dep:toml`.

## 4. Waves

Two steps, one wave, file-disjoint. The errno classifier is shared by `dispatch.rs` and
`wave_f_knowledge.rs`, so a two-wave split would serialize them behind the definition. Instead
**Step E owns both files**, which also forces the classifier to be co-designed with both of its
consumers rather than fitted to one and bent for the other. Step I is independent.

### Step E — errno classification (deliverable 4)

Owns, exclusively:
- `crates/cli/src/cmd/dispatch.rs`
- `crates/cli/src/cmd/wave_f_knowledge.rs`
- `crates/cli/tests/dispatch_cli.rs`
- `crates/cli/tests/wave_f_knowledge.rs`

Changes:
1. Define ONE classifier in `dispatch.rs` as `pub(crate)`. `cmd.rs` already declares
   `pub mod dispatch;`, so `wave_f_knowledge.rs` can `use` it with no module-table edit.
   **Do not add a new module file**: `crates/cli/src/cmd.rs` is outside this lane's scope.
2. The classifier is SUBJECT-AWARE. W0 section 9 proves why: the same helper reads project
   identity (`wave_f_knowledge.rs:406`) and ordinary knowledge files (`:543`, `:578`, `:670`).
   Two subjects:
   - project identity -> ENOENT: ``project not scaffolded — run `shepherd init` ``
   - ordinary file -> ENOENT: a plain not-found message. It must NOT tell the user to run `init`.
3. Errno mapping, both subjects:
   - `ENOENT` -> the subject's not-found text
   - `ELOOP` (and `EMLINK`/`EFTYPE` where the platform reports NOFOLLOW that way) -> the existing
     security refusal wording, unchanged
   - `EISDIR` -> not a regular file
   - anything else -> a generic open failure carrying the raw errno, never the symlink wording
4. Apply it in `dispatch.rs:178` `read_regular_nofollow` and `wave_f_knowledge.rs:953`, replacing
   both hardcoded strings. Delete the duplication; do not leave two copies in sync by hand.
5. `NOFOLLOW` flags are untouched. The only change is which message an error maps to.

Acceptance: `cargo test -p shepherd-cli`, plus gates GE1 to GE5.

### Step I — init creates identity, doctor tells the truth (deliverable 3)

Owns, exclusively:
- `crates/cli/src/cmd/wave_c_bootstrap.rs` (this file is also the doctor module:
  `health_report` and `DoctorReport`)
- `crates/cli/tests/wave_c_bootstrap_cli.rs`
- `crates/cli/Cargo.toml` (see I4; pending team-lead's ruling)

Changes:

**I1. `init` writes `.shepherd/project.json`.** In `initialize_project`
(`wave_c_bootstrap.rs:281`), after the directory tree and before returning. Document shape is
already pinned by the healthy repo and by every test fixture:
`{"id":"<uuid-v7>","scaffolded_at":<unix-seconds>}`. Generate with `uuid::Uuid::now_v7()`;
`uuid` is already a direct dependency of `crates/cli` and the workspace enables feature `v7`.
Write it through the existing descriptor-safe `write_no_clobber`, which is temp-file +
`linkat` + `unlinkat` and never clobbers.

**I2. `init` inserts the `projects` row.** `Registry::execute` is public
(`crates/registry/src/registry.rs:107`), so this needs NO change under `crates/registry/src/**`.
Insert id + timestamps with conflict-do-nothing semantics so a re-run stays exit 0 and cannot
produce a second row. The id MUST equal the id in `project.json`; a namespace whose file and row
disagree is a new failure mode and must be rejected, not silently preferred one way.

**I3. Atomic or nothing, with the rollback set stated exactly.** Rollback removes ONLY artifacts
THIS invocation created. It must never delete a pre-existing user artifact.
- `write_no_clobber` currently returns `Ok(())` whether it published or found the name taken.
  Make it (or a sibling) report which happened, so the caller knows what it owns.
- Rollback set = the subset of {`project.json`, `shepherd.toml`, `shepherd.db`, and each
  directory in `PROJECT_DIRECTORIES`} that did not exist when this invocation began AND that this
  invocation created. Nothing else, ever.
- On any failure after the first mutation, unwind that set in reverse creation order and return
  the underlying error, naming which artifact could not be written.
- Re-running `init` over a partially-scaffolded namespace (the pzzld state: db and toml present,
  identity absent) is a HEAL, not a rollback case. It adds the missing identity and row and exits
  0. This is the one and only healing path, and it is `--confirm`-gated.

**I4. Move `typed_config_value` off `toml::Value`.** `wave_c_bootstrap.rs:322` hand-walks a dotted
key over `toml::Value`. Locked decision D3 puts configuration on `config`.
- Measured constraint: `config` is NOT reachable from `crates/cli` today. `crates/cli` depends on
  the `shepherd` umbrella, `crates/sdk/lib.rs:62` re-exports only `shepherd_core::*`, and `config`
  is a private optional dep of `crates/core` used solely in `crates/core/src/loader.rs:20`.
- `crates/core/**` is FORBIDDEN to this lane, so a core-side helper is not an option here.
- Therefore this step adds `config = { workspace = true }` to `crates/cli/Cargo.toml` and uses
  `config`'s own path expressions, replacing the hand-walk.
- **ESCALATED, not yet resolved.** Seed deliverable 6 assigns lane D `wave_a_models.rs:285`, which
  needs the same dependency line, so two lanes may both edit `crates/cli/Cargo.toml`. Awaiting
  team-lead. If the ruling is that lane D owns it, I4 drops out of this lane and the call site
  hands off, and this step's other work is unaffected.
- Existing behavior is pinned by `wave_c_bootstrap_cli.rs:94`
  (`config_reads_typed_defaults_and_requires_confirmation_to_create_its_document`) and must not
  change: same keys resolve, unknown keys still exit 2.

**I5. `doctor` fails loudly on a namespace missing identity.** `health_report` currently checks
four directories and the registry schema. Add findings, each of which sets `ok = false` and so
drives the existing exit code 3 at `wave_c_bootstrap.rs:255`:
- `project.json` absent
- `project.json` present but not a regular file, unreadable, or not valid JSON
- `id` missing, not a string, or not a valid `ProjectId`
- no `projects` row, or a row whose id disagrees with the file
Doctor stays READ-ONLY. It reports; it never repairs. `home_and_doctor_are_read_only_until_explicitly_confirmed`
(`wave_c_bootstrap_cli.rs:139`) pins that and must pass unchanged.

Acceptance: `cargo test -p shepherd-cli`, plus gates GI1 to GI6.

## 5. Gate ledger

Every gate is shown to FAIL ON PURPOSE and the failing output is recorded in `./gates.md`.
A gate that has never been red is not evidence (prior C2: nine inert gates in one sprint).

| Gate | Command | Proves | Shown to fail by |
|---|---|---|---|
| GI1 complete artifact set | `cargo test -p shepherd-cli --test wave_c_bootstrap_cli` | init produces project.json, valid uuid id, and exactly one projects row | delete `project.json` after init inside the test, re-assert, capture the red |
| GI2 doctor is honest | same target, new test | doctor exits 3 and names the missing identity | run the new test against the pre-fix `health_report`, capture `status: ok` passing where it must fail |
| GI3 atomicity | same target, new test | a forced mid-scaffold failure leaves nothing this run created | pre-create `project.json` as a DIRECTORY, assert clean unwind; then stub the rollback out and capture the leftover |
| GI4 idempotent heal | same target, new test | second `init --confirm` exits 0, still exactly one row; identity-less namespace heals | drop the conflict-do-nothing clause, capture the duplicate-row failure |
| GI5 config path expressions | same target, existing test at :94 | `config get` behavior unchanged after leaving `toml::Value` | feed a known-bad key, assert exit 2 |
| GI6 dispatch still refuses | `cargo test -p shepherd-cli --test dispatch_cli` | no auto-heal was introduced anywhere | assert dispatch on an identity-less namespace still exits non-zero |
| GE1 ENOENT | `cargo test -p shepherd-cli --test dispatch_cli` | real missing file yields "project not scaffolded", from a REAL errno | assert the old symlink wording, capture the red |
| GE2 ELOOP | same | real symlink still yields the security refusal. NEW coverage, see section 2 | point the test at a regular file, capture the red |
| GE3 EISDIR | same | real directory yields "not a regular file" | as above |
| GE4 subject awareness | `cargo test -p shepherd-cli --test wave_f_knowledge` | a missing KNOWLEDGE file does NOT say "run shepherd init" | make both subjects share one string, capture the red |
| GE5 pinned unchanged | `cargo test -p shepherd-cli --test wave_f_knowledge` | `dups_check_rejects_symlinks_and_oversized_files` (:111) passes with ZERO edits | n/a, this gate must never go red |
| GX1 workspace | `bash scripts/gate.sh` | green before, green after | n/a, baseline recorded before the wave starts |

Errno realism is mandatory. Each of GE1 to GE3 constructs the real condition on disk (absent
path, actual symlink, actual directory) and lets the kernel produce the errno. No hand-built
error values.

## 6. Out of scope

Forbidden paths: `crates/core/**`, `crates/cli/src/cmd/wave_a_models.rs`,
`crates/cli/src/cmd/native_hook.rs`, `crates/cli/src/cmd/wave_b2_run.rs`, `crates/component/**`,
`hooks/**`, `scripts/**`, `.github/**`, `content/**`, `agents/**`, `conformance/**`.

Already fixed this session, NOT to be rescheduled or reverted: `native_hook.rs` PreToolUse
fail-closed classification, `wave_b2_run.rs` RUN_SUBDIRS, `crates/core/src/guard/engine.rs`
Workflow dispatch and carrier-form target roles.

No installers, no publish, no `git commit`, no `git push`. Changes stay in the worktree; the root
session commits.

Observed but deliberately NOT fixed here, flagged for handoff: `wave_b1_status_handoff.rs:662`
holds a THIRD copy of the nofollow read, and `:473` swallows its error with `.ok()?`. Out of this
lane's file scope. It should get the shared classifier in a follow-up.

## 7. Open questions for the owning lead

1. **`crates/cli/Cargo.toml` ownership.** I4 needs `config = { workspace = true }`. Lane D needs
   the same line for `wave_a_models.rs:285`. Who writes it? Default if no answer: this lane writes
   it and the handoff flags it for the integrator.
2. **Subagent dispatch is blocked.** Every Task/Workflow subagent is denied every tool with
   `dispatch record ... is unknown in run v646: record is absent`, because nothing binds a
   subagent that the host did not send a `shepherd_dispatch` block for. Until that clears, this
   lane cannot run implementer waves as designed. Escalated separately with the source-level
   diagnosis.

## 8. Verified technical facts (checked against the tree, not assumed)

Each of these was confirmed before the wave was briefed, so no coder has to rediscover it.

| Fact | Evidence |
|---|---|
| `config::Config::try_from<T: Serialize>(&T)` exists | `config-0.15.19/src/config.rs:150` |
| `.get::<T>(key)` and `.get_string(key)` take dotted path expressions | same file, `:107` and `:114` |
| `config` is NOT reachable from `crates/cli` today | `crates/sdk/lib.rs:62` re-exports only `shepherd_core::*`; `config` is a private optional dep of `crates/core`, used only at `crates/core/src/loader.rs:20` |
| `Registry::execute` is public, so the `projects` INSERT needs no registry change | `crates/registry/src/registry.rs:107`; `transaction` at `:136` |
| `projects` columns | `crates/registry/src/migrate/sql/0001_init.sql:14`: id, name, scope, metadata, tags, created_at, updated_at |
| `uuid` is a direct `crates/cli` dep and the workspace enables `v7` | `crates/cli/Cargo.toml:99`; root `Cargo.toml:81` |
| `write_no_clobber` is already atomic and descriptor-safe | `wave_c_bootstrap.rs:527`: temp file, `linkat`, `unlinkat`, `NOFOLLOW`, `O_EXCL` |
| `cmd.rs` declares `pub mod dispatch;`, so a `pub(crate)` classifier there is reachable from `wave_f_knowledge.rs` with no module-table edit | `crates/cli/src/cmd.rs:11` |
| the three "no project registered" call sites are OUT of scope | `wave_b1_mem.rs:369`, `wave_e_coordination.rs:127`, `wave_g_coordination.rs:547` |
| doctor's failure exit code already exists | `wave_c_bootstrap.rs:255` `CliError::reported_with_code(3)` when `!report.ok` |
| `toml` carries an explicit workspace warning against this migration's reverse | root `Cargo.toml:60` |

## 9. Execution status

- W0-GATE: DONE, `./w0-gate.md`, both deliverables reproduced before any fix.
- Plan: DONE, this file.
- `scripts/gate.sh` baseline: recorded before any change.
- Implementation wave: **HELD**. Subagent dispatch is denied at PreToolUse for every Task and
  Workflow child, because the `shepherd` binary on PATH (`~/.cargo/bin/shepherd`, built 20:31:38)
  predates the in-flight `native_hook.rs` fix (20:43:45). The hook manifest invokes bare
  `shepherd`, so the stale binary is the one enforcing the guard. Escalated to team-lead with the
  reinstall requirement. No source file will be written by this conductor while held.

## 10. I3 implementation note, verified in source

`descriptor::write_no_clobber` already computes the exact fact the rollback set needs, then
discards it. At `wave_c_bootstrap.rs:~552-566`:

- `linkat(...)` -> `Ok(())` sets `published = true`; `Errno::EXIST` sets `published = false`
- the temporary file is unlinked either way
- then `if !published { return Ok(()); }`

So a caller cannot currently distinguish "I created this file" from "it was already there". Both
return `Ok(())`. Change the signature to surface `published` (a `bool`, or a two-variant enum for
readability) and thread it to the caller. That single fact is what makes the rollback set precise:
only artifacts whose write reported `published == true` in THIS invocation are eligible for
unwind. It also gives `init` the information it needs to distinguish a fresh scaffold from a heal
without a second stat, and stat-then-write would be a TOCTOU race that the descriptor-safe
design exists to avoid.

Both existing symlink-refusal tests for this path must keep passing unchanged:
`init_refuses_a_symlink_namespace_without_touching_its_target` (`wave_c_bootstrap_cli.rs:235`) and
`init_refuses_an_existing_config_symlink_instead_of_reporting_success` (`:253`).
