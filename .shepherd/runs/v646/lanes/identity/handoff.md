# Lane `identity` handoff, run v646

Status: COMPLETE. No commit, no push. All changes remain unstaged in the shared worktree
for the root session to commit.

Objective: a freshly initialized project can dispatch, and errors name the actual failure.
Met, verified by the conductor directly against a live `$TMPDIR` fixture, not by trusting
coder claims. Evidence below.

## 1. What broke and what changed, per deliverable

### Deliverable 3, init identity (`wave_c_bootstrap.rs`, Step I + Step D)

Before: `shepherd init --confirm` wrote no `.shepherd/project.json` and inserted no `projects`
row (`w0-gate.md` sections 4-5), yet exited 0 and `shepherd doctor` reported `status: ok`
(`w0-gate.md` section 6). Every registry-backed verb then failed with a circular remediation:
`shepherd mem list` -> `ERROR: no project registered - run 'shepherd init' first`, whose fix
is the same `init` that produced the broken state.

After: `init --confirm` writes `.shepherd/project.json` (`{"id":"<uuid-v7>","scaffolded_at":<unix-seconds>}`,
via `uuid::Uuid::now_v7()`) through the existing descriptor-safe `write_no_clobber` (temp file
+ `linkat` + `unlinkat`, `O_EXCL`, never clobbers), and inserts exactly one matching `projects`
row with `ON CONFLICT(id) DO NOTHING`. Re-running `init --confirm` over the pzzld state (db and
toml present, identity absent) is a HEAL and exits 0, not an error and not a second row.

Conductor's own live check, `$TMPDIR` fixture, after the fix:
- artifact set now includes `.shepherd/project.json`
- `{"id":"01a012d3-0520-7ea1-beaa-a00c078481c5","scaffolded_at":1787022214}`
- `SELECT id FROM projects` returns that same id
- `shepherd mem list` exits 0 (previously `ERROR: no project registered - run 'shepherd init' first`)
- with identity removed, `shepherd doctor` prints `status: failed`, exit 3, and
  `issue: project identity is absent: run \`shepherd init --confirm\` (.shepherd/project.json)`

### Deliverable 4, error classification (`dispatch.rs`, `wave_f_knowledge.rs`, Step E + Step G)

Before: `w0-gate.md` section 8: a plain absent identity file produced
`ERROR: cannot open project identity <path> without following symlinks: No such file or
directory (os error 2)`, a security-refusal string for a condition with zero symlinks in the
fixture (`find . -type l` = 0). Section 9: the same misdirection hit ordinary knowledge files
too, e.g. `shepherd dups check src/lib.rs` on an absent file.

After: one classifier, `ReadSubject` + `classify_nofollow_open_error`, `pub(crate)` in
`dispatch.rs`, consumed by both `dispatch.rs::read_regular_nofollow` and
`wave_f_knowledge.rs::read_regular_nofollow` at all four of its call sites
(`project_id()`, `dups_registry()`, `dups_check()`, `load_insights()`). Errno mapping:
`ENOENT` -> subject's not-found text, `ELOOP` -> unchanged security wording, `EISDIR`
(reachable in practice only via the post-`fstat` `is_file()` check, see section 4 below) ->
"not a regular file", anything else -> a generic open failure carrying the raw errno, never
the symlink wording.

Conductor's own live check after the fix:
- `dispatch start` with identity absent:
  ``ERROR: project not scaffolded — run `shepherd init`: <path>`` (previously the symlink
  refusal)
- `dups check nope.rs`: `ERROR: no such file: nope.rs`, subject-aware, does NOT say
  "run `shepherd init`"
- a real symlinked identity is still refused: `resolved project path is not canonical`
  (this refusal actually fires in `context.rs::validate_resolved_project_paths`, called
  before `dispatch.rs::read_project_id` ever runs; see section 4)
- NOFOLLOW unchanged everywhere

### Scope addition, doctor install integrity (`wave_c_bootstrap.rs`, Step D, assigned mid-lane by team-lead)

`doctor` now reports the resolved PATH of `shepherd`, whether it is native or a
launcher/wrapper, and skew against the running checkout build. Three new free functions:
`resolve_shepherd_on_path()`, `classify_binary_format()` (magic-byte sniff: `#!` -> `Script`,
ELF/Mach-O(x6 byte orders)/PE -> `Native`, else `Unknown`), `compare_binary_freshness()`
(`resolved_mtime - current_exe() mtime`, short-circuits to `Some(0)` via `same_binary()`
when the resolved file is the running binary). These land in a new `warnings: Vec<String>`
field, deliberately kept out of the `ok`/exit-3 computation (justification in gates-D.md
section 3: PATH state is environment-dependent and would make wave 1's pinned
`home_and_doctor_are_read_only_until_explicitly_confirmed` flaky, and would regress
`init --confirm` for a developer who has never installed the CLI system-wide, since
`health_report(&context).ok` gates `init`'s own abort check at `wave_c_bootstrap.rs:176-180`).

Live output: `resolved shepherd: /Users/jo3/.cargo/bin/shepherd (native, 3352 s stale)` plus a
warning naming the reinstall command. Reviewed adversarially with two byte-different binaries
reporting an identical `--version` (this is the exact incident the check exists to catch: a
version-only comparison is a gate that cannot fail, since a stale copy and its fix both print
`shepherd-cli 6.4.6`).

## 2. Gate ledger, every gate shown red on purpose, per `gates-*.md`

| Gate | Step | Break introduced | Literal red | Green after revert |
|---|---|---|---|---|
| GI1 complete artifact set | I | `remove_file(&identity)` right after `init` | `project identity must exist: Os { code: 2, kind: NotFound, ... }` | 1 passed |
| GI2 doctor is honest | I | stubbed `health_report`'s identity read to `None` | `left: Some(0)` vs `right: Some(3)` (doctor exits 0, prints `status: ok`) | 1 passed |
| GI3 atomicity | I | `Scaffold::rollback` stubbed to `return;` | `docs must be rolled back after a failed init` | 1 passed |
| GI4 idempotent heal | I | dropped `ON CONFLICT DO NOTHING` in `register_project` | `ERROR: cannot register project: UNIQUE constraint failed: projects.id`, `left: Some(1)` vs `right: Some(0)` | 1 passed |
| GI5 config path expressions | I | n/a, pinned unchanged | `config_reads_typed_defaults_and_requires_confirmation_to_create_its_document` untouched | pass |
| GI6 dispatch still refuses | I | n/a, covered by GE1/GE4 | no auto-heal introduced | pass |
| GE1 ENOENT, identity | E | reverted `Errno::NOENT` arm to old string | `cannot open project identity <path> without following symlinks: No such file or directory (os error 2)` (both CLI- and unit-level) | 2 tests, pass |
| GE2 ELOOP, identity | E | unit: pointed fixture at regular file; CLI: `fs::copy` instead of `symlink` | unit: `symlinked identity must be refused: ProjectId(...)`; CLI: `assertion failed: !start.status.success()` | pass |
| GE3 EISDIR, identity | E | fixture wrote a regular file instead of `fs::create_dir` | `ERROR: invalid project identity document <path>: expected ident at line 1 column 2` (a different failure mode, proving the test is real) | 1 passed |
| GE4 subject awareness | E | collapsed `not_found_message` to identity wording for both subjects | `ERROR: project not scaffolded — run \`shepherd init\`: definitely-missing.rs` | 1 passed |
| GE5 pinned, zero edits | E | n/a, never shown red by design | `dups_check_rejects_symlinks_and_oversized_files`, 24 insertions / 0 deletions to the file, this test untouched | pass |
| GD1 stale binary detected | D | `compare_binary_freshness` replaced with `Some(0)` always | back-dated binary (2001-09-09) reports `"resolved_shepherd_skew_seconds": 0, "warnings": []`, wrongly healthy | 12 passed (x3 flake check) |
| GF1 wave_g regression | F | reverted fixture to hand-inserted `'project-g'` row | `wave_g_coordination.rs:261`, `left: Null` vs `right: "ok"` | 7 passed |
| GF1 wave_h regression | F | reverted fixture to hand-inserted `'project-h'` rows | `wave_h_execution_cli.rs:181`, `left: Null` vs `right: "blocking-this-sprint"`; `:209` escalation text mismatch | 3 passed |
| GG1 not-a-regular-file wording | G | collapsed `not_a_regular_file_message` to `File`-subject string for both subjects | `dispatch_cli.rs:380`, `ERROR: not a regular file: <path>` (identity subject silently lost its `"project identity "` prefix) | 2 new tests + full suite pass |
| GX1 workspace baseline | conductor | n/a, baseline recorded before wave 1 | `bash scripts/gate.sh` green before | green after |

Final: `bash scripts/gate.sh` REAL_EXIT=0. `cargo test -p shepherd-cli --no-fail-fast` green
across every target (per plan.md section 12; at the time gates-E.md and gates-I.md were
captured, `content_compiler`, `wave_g_coordination`, `wave_h_execution_cli` were still red for
reasons outside this lane's Step E/I file scope, root-caused there rather than assumed; Step F
in wave 2 is this lane's own fix for the latter two, see section 3.1 below).

Per-step scoped test counts, from the gate files directly: Step E final scoped run, 19 lib +
6 `dispatch_cli` + 6 `wave_f_knowledge` (before Step G's two additions); Step I, 10
`wave_c_bootstrap_cli` + 1 lib; Step D, 12 `wave_c_bootstrap_cli` (10 wave-1 + 2 new) + 3 lib;
Step F, 7 `wave_g_coordination` + 3 `wave_h_execution_cli`; Step G final scoped run, 7
`dispatch_cli` + 7 `wave_f_knowledge` + 19 lib.

## 3. The three things the next sprint most needs to know

### 3.1 A regression this lane caused and repaired, and how it was nearly shipped

Wave 1's `projects` INSERT broke `wave_g_coordination` and `wave_h_execution_cli`. Both wave 1
coders AND its auditor dismissed the failures as unrelated, reasoning the test files were
byte-identical to base. That is a category error: an unchanged test can be broken by changed
production behaviour. Both fixtures ran `init --confirm` then hand-inserted their own
`projects` row (`'project-g'`, `'project-h'`); production resolves identity with
`SELECT id FROM projects ORDER BY id LIMIT 1` (`wave_g_coordination.rs:541`,
`wave_h_execution.rs:561`, and `wave_d_planning.rs:781`'s `report_project_id`), and a uuid v7
(`01...`) sorts before `project-g`/`project-h`, so every dependent row keyed to the literal id
became unreachable. Proof, from Step F's root-cause capture:

```
$ shepherd init --confirm
$ sqlite3 ... "INSERT INTO projects ... VALUES ('project-g',...)"
$ sqlite3 ... "SELECT id FROM projects ORDER BY id LIMIT 1;"
01a012b7-c7c4-7b61-b2fc-4ba198ac68a2      # init's uuid, not project-g
```

Step F repaired `wave_g_coordination.rs` and `wave_h_execution_cli.rs` to read the id `init`
actually minted from `.shepherd/project.json` via a new `project_id(root: &Path) -> String`
helper in each test file, rather than hand-inserting a competing row. Reverting the repair
reproduces the exact regression: `wave_g_coordination.rs:261` `left: Null, right: "ok"`;
`wave_h_execution_cli.rs:181` `left: Null, right: "blocking-this-sprint"` and `:209` an
escalation-text mismatch. **Lesson for review briefs: never accept "this file did not change"
as proof a failure is unrelated to a change in production behaviour.**

### 3.2 Two seed citation errors, so the next sprint does not inherit them

(a) The seed cites `crates/cli/tests/dispatch_cli.rs:232` as pinning the symlink refusal.
That line is inside `linked_worktree_uses_only_the_primary_project_and_active_run_store` and
asserts primary-root precedence across a linked git worktree, not a symlink refusal.
`dispatch.rs`'s symlink path had NO test at all before this lane; Step E added it
(`read_project_id_refuses_a_symlinked_identity_with_the_security_wording`, unit level, and
`dispatch_refuses_a_symlinked_project_identity`, CLI level). The only pre-existing test in the
workspace asserting `without following symlinks` was `wave_f_knowledge.rs:111` (now at line
101 after 24 lines were appended; the test body itself was never touched,
`dups_check_rejects_symlinks_and_oversized_files`).

(b) The existing init gate `init_refuses_unconfirmed_mutation_then_materializes_only_layout_v5_roots`
(`wave_c_bootstrap_cli.rs:45`) asserted five ABSENT retired roots while never asserting
`project.json` or the `projects` table, so it was green on a namespace that could not dispatch.
That is the inert-gate shape (`w0-gate.md`, "Why the existing gate did not catch it"). It is
now extended (Step I's GI1) and was shown failing before the extension landed.

A second discovery during Step E, not a seed error but adjacent: even after the fix, a real
symlinked identity is refused before `dispatch.rs`'s own NOFOLLOW branch ever runs.
`context.rs::validate_resolved_project_paths`, called unconditionally inside
`ExecutionContext::discover` before `read_project_id`, trips first with
`ContextError::NonCanonicalProjectPath` (`project_id: resolved project path is not canonical:
<path>`). So `dispatch.rs`'s identity-subject `ELOOP` branch is unreachable via the CLI; it is
reachable and tested directly through `read_project_id`/`read_regular_nofollow`, which take a
bare `&Path`. Two tests cover this honestly (unit-level with a real on-disk symlink, CLI-level
asserting the CLI's actual security-shaped message and that it never carries the "not
scaffolded" remediation a plain absence gets).

### 3.3 Known limitation, deliberately not fixed (plan.md section 13)

`compare_binary_freshness` (`wave_c_bootstrap.rs:872`) short-circuits to `Some(0)` when the
resolved PATH binary IS the running binary (`same_binary()`, `(dev, ino)` match), emitting no
warning in that case. So the skew check cannot fire in the operator's most common invocation,
plain `shepherd doctor` from PATH. Defensible, since a stale binary cannot diagnose its own
staleness, but a silent zero is weaker than saying the check could not be performed.
Recommended follow-up: emit an explicit "skew not assessable, doctor is running as the
resolved binary" note, and where a checkout build exists, compare against it instead. Not
fixed here: it is a refinement of a requirement that was itself a late scope addition, and the
delivered check does catch the failure that motivated it (GD1, a binary back-dated to
2001-09-09, correctly flagged as stale when it is NOT the running binary).

## 4. Also carry forward

- **Out of scope, worth a follow-up.** `wave_b1_status_handoff.rs:662` holds a THIRD copy of
  the nofollow read, and `:473` swallows its error with `.ok()?`. It should adopt the shared
  `ReadSubject` classifier defined in `dispatch.rs`.
- **Latent, currently inert.** `crates/cli/tests/wave_e_coordination.rs` has the identical
  hand-inserted competing `projects` row pattern (`'project-lock'`) that Step F fixed
  elsewhere. `wave_e_coordination.rs:119` has its own `project_id(registry)` helper
  (`ORDER BY id LIMIT 1`), used only to satisfy the `project_id` foreign key on
  `locks_history` writes. It passes today (6/6) only because no test in that file asserts on
  the resolved project id's value, only that `project_id()` resolves to SOME row. Left
  untouched deliberately, per the Step F brief; flagged as structurally the same fragility.
- **Process note.** plan.md section 11 (the wave 2 scope addition) was written at 21:05, then
  destroyed when an external actor reset plan.md to its committed 246-line state. Step D was
  dispatched citing that section, found it missing, did NOT halt, and instead cross-verified
  the requirement independently from `lanes/distribution/plan.md`,
  `lanes/distribution/blocker-stale-binary.md`, `carry-forward.md`, and `seed.md`, all four
  agreeing, before delivering. Section 11 was restored at 22:05. Good failure behaviour worth
  keeping as the pattern for a broken citation: verify from independent sources, do not halt
  and do not guess.
- **Platform errno verification, not assumed.** Step E wrote a standalone C program (outside
  the repo, never touching a repo file) to observe real Darwin kernel behaviour for
  `open(..., O_RDONLY | O_NOFOLLOW)`: symlink -> `errno=62` (`ELOOP`), absent -> `errno=2`
  (`ENOENT`), directory -> `open()` SUCCEEDS (`fd=3, errno=0`). So on Darwin the
  "not a regular file" outcome for a directory comes from the pre-existing post-`fstat`
  `is_file()` check, never from an `open()`-level `EISDIR`. GE3 and GG1 both prove the
  directory case through that actually-reachable code path, with a real on-disk directory, not
  a hand-built error value.
- **Every gate in section 2 was shown red on purpose before being trusted.** The literal
  failing output for each lives in the five `gates-*.md` files in this directory; none was
  left in a broken state, each break was reverted and the file diffed byte-identical to its
  pre-break form before moving on.

## 5. Files changed, 10 files, 1509 insertions / 113 deletions

| File | Lines |
|---|---|
| `crates/cli/src/cmd/dispatch.rs` | 171 |
| `crates/cli/src/cmd/wave_c_bootstrap.rs` | 818 |
| `crates/cli/src/cmd/wave_f_knowledge.rs` | 61 |
| `crates/cli/tests/dispatch_cli.rs` | 126 |
| `crates/cli/tests/wave_c_bootstrap_cli.rs` | 338 |
| `crates/cli/tests/wave_f_knowledge.rs` | 48 |
| `crates/cli/tests/wave_g_coordination.rs` | 21 |
| `crates/cli/tests/wave_h_execution_cli.rs` | 36 |
| `crates/cli/Cargo.toml` | 2 |
| `Cargo.lock` | 1 |

**Flag for the integrator: `Cargo.lock` and `crates/cli/Cargo.toml`.** The
`config = { workspace = true }` dependency (plan.md section 4, I4) was added on team-lead's
explicit ruling after an open question (plan.md section 7, item 1: lane D needed the same
line for `wave_a_models.rs:285`; default if unresolved was "this lane writes it"). The config
lane was told to CONSUME the dependency, not add it, so there is a single writer. Verify no
second `config = { workspace = true }` line or conflicting `Cargo.lock` entry lands from lane
D's own diff at merge time.

## 6. No commit, no push

This conductor made zero `git commit` and zero `git push` calls, per the lane's out-of-scope
statement (plan.md section 6). All ten files above are modified in the shared worktree,
uncommitted. The root session owns staging, commit message, and push.

## 7. Addendum: the five-site identity resolution decision (post-close)

The team-lead found that `SELECT id FROM projects ORDER BY id LIMIT 1` appears in FIVE production
files, not just the two test fixtures Step F repaired:

| Site | Shape |
|---|---|
| `crates/cli/src/cmd/wave_e_coordination.rs:119` | byte-identical to wave_g |
| `crates/cli/src/cmd/wave_g_coordination.rs:539` | byte-identical to wave_e |
| `crates/cli/src/cmd/wave_h_execution.rs:561` | different message, exit code 5 |
| `crates/cli/src/cmd/wave_d_planning.rs:783` | `report_project_id`, third message, exit code 5 |
| `crates/cli/src/cmd/wave_f_knowledge.rs:407` | takes `context`, falls back to `project.json` |

Those five resolve "the current project" by alphabetical accident rather than by identity.

**Decision: carry the production defect to v6.4.7, do not refactor now.** Two measured reasons.

1. **It is unreachable in production today.** `grep -rn "INSERT INTO projects" --include='*.rs'
   crates/*/src/` returns exactly ONE hit, `wave_c_bootstrap.rs:462`, added by this lane. No SQL
   migration seeds a row either. So a real namespace holds 0 or 1 row and the `ORDER BY` never has
   two candidates. The sprint only saw it because two fixtures hand-inserted a competitor.
2. **It is not the clean helper extraction it appears to be.** The five bodies carry three
   different error messages and two different exit codes. Unifying them changes user-visible
   behaviour of five registry-backed verbs, in four files this lane does not own, after the lane's
   blockers were already fixed and green.

**What was added instead, so the carry-forward is not merely a note.** The invariant "there is
exactly one production inserter" was load-bearing and enforced by nothing.
`wave_c_bootstrap_remains_the_sole_production_inserter_of_projects`
(`crates/cli/tests/wave_c_bootstrap_cli.rs`) scans every `*.rs` under `crates/*/src/`, asserts the
only `INSERT INTO projects` is `wave_c_bootstrap.rs`, and fails with a message naming all five
call sites and stating the correct fix: a shared resolver keyed to `.shepherd/project.json`, never
a second writer. Test sources are excluded, since fixtures legitimately insert.

Gate GH1, evidence in `gates-H.md`: shown red by planting a temporary second inserter, restored
to green with a clean `git diff`. Suite is 13 passed.

So whoever adds the second inserter in v6.4.7 is told exactly what they broke and where, rather
than discovering it as five commands silently picking a project alphabetically.

## 8. Final state at lane close

- Lane source committed by the root session at `29570a2` ("a fresh project can dispatch, and
  errors name the actual failure"). `ReadSubject` present in `dispatch.rs` and
  `wave_f_knowledge.rs`; the single `INSERT INTO projects` present in `wave_c_bootstrap.rs`.
- Uncommitted at close: `crates/cli/tests/wave_c_bootstrap_cli.rs` only, carrying the GH1
  invariant gate.
- `cargo build -p shepherd-cli` clean. Full `cargo test -p shepherd-cli --no-fail-fast` green,
  zero failures across every target. `rustfmt --edition 2024 --check` exits 0 on all lane files.
- `scripts/gate.sh` last run RED on `release workflow contract`, which is NOT this lane's. That
  check sits over `.github/workflows/**` and `scripts/**`, both forbidden to this lane and both
  actively modified by the release and distribution lanes. This lane's diff is confined to
  `crates/cli/`.
- Worth passing to whoever owns that check: it prints three `ok:` sub-assertions and then reports
  `FAILED`, so its failure signal comes from something it does not print. A check that reports
  every sub-assertion green and then fails is hard to action, and is a close cousin of the
  inert-gate shape this sprint has been hunting.

## 9. Post-close verification of the stash split

The team-lead's `git stash -u` split a coder mid-edit across `wave_f_knowledge.rs`, producing two
complementary partial states, and asked for a re-verification that every call site carries the
right subject. Audited, all four correct:

| Line | Path read | Subject |
|---|---|---|
| 418 | `context.project_id_path` | `ReadSubject::ProjectIdentity` |
| 548 | `context.dups_registry_path` | `ReadSubject::File` |
| 587 | knowledge file | `ReadSubject::File` |
| 679 | knowledge file | `ReadSubject::File` |

The concern that "a call site left on the old form still compiles" does NOT apply to this
signature. `read_regular_nofollow(subject: ReadSubject, path: &Path, limit: u64)` takes the
subject as a mandatory first positional parameter, and Rust has no default arguments, so an
unconverted call site cannot compile. Compiling is sufficient evidence of COVERAGE here; only
which subject each site passes required review, and that is what the table above records. The
failure mode being guarded against is real in languages with defaults or varargs and structurally
impossible in this one.
