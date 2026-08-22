# v6.5.6 planter mesh — plugin reliability evidence

**Run:** `v656`
**Tracking:** [#374](https://github.com/pzzld-org/shepherd/issues/374)
**Measured:** 2026-08-22
**Head:** `2c8fea7e440befed6faf245393927c1a6631943d`

## Preface and preflight

This is a **shepherd plugin reliability pass** for `FL03/shepherd@v6.5.6`; hook reliability is in scope.

The checkout is the clean `v6.5.6` branch. `shepherd` resolves to `/Users/jo3/.cargo/bin/shepherd`.
`shepherd doctor` exits 0 and reports this checkout as primary, `.shepherd/` as the namespace,
the native Cargo binary as the resolved CLI, and `status: ok`.

The in-place version check failed on ignored Pi task state:

```text
version-bump: ERROR: .pi/tasks/tasks-01a025f6-932c-7396-a4cc-9965525bfc3f.json:
unclassified 6.5.6 version surface
```

`git status --short` remained empty and `git check-ignore` identified `.gitignore:202:.pi/`.
The same check against `git archive HEAD` passed:

```text
version-bump: OK version=6.5.6 authorities=53 mode=check
```

This is scanner scope debt, not version drift. The execution plan must keep generated runtime
state out of authority scans without weakening the tracked-source check.

During this planting session Pi then rejected the artifact write itself:

```text
Pi component rejected identity or guard request (identity):
{"code":"invalid-identifier","message":"unsafe session id `call_IGcYvykwDDwEpcB5873Eb2Sk|fc_0c4060b9c5de4864016a88e81ff8ec87d08b5ecd3295c62698`"}
```

This live reproduction makes #368 the first execution blocker. The seed was written through the
native filesystem fallback; no implementation work may begin until the Pi identifier path is fixed
and the normal Pi write path succeeds.

## Evidence table

| # | Signal | Measured state | Sprint consequence |
|---|---|---|---|
| 0 | Branch/version preflight | Clean `v6.5.6`; 53 tracked authorities equal `6.5.6`; dependency baseline captured. | Hard gate before dispatch. |
| 1 | Native CLI health | `shepherd doctor` exits 0 through `/Users/jo3/.cargo/bin/shepherd`. | No install probe runs if this regresses. |
| 2 | Project identity failure class | Both vault paths' `.shepherd/project.json` files exist and resolve to the same regular file. | Preserve no-follow security; quoted ENOENT/symlink output is a hard stop. |
| 3 | Historical v6.4.6 scope | `.shepherd/runs/v646/close.md` marks Binstall, PATH shadowing, fresh init, error classification, hook parity, config authority, and release-gate falsifiability closed. | Do not rebuild closed work. Reproduce as regression gates. |
| 4 | Artifact custody | No artifact-like path is tracked. Root `target/` exists but is ignored; release archives are workflow-staged. | No repo launcher, tracked output, or new artifact subsystem. |
| 5 | Cargo install contract | Binstall metadata, cold local fixture, archive-layout tests, and disabled fallbacks already exist. | Prove the release candidate cold; change only on reproduced failure. |
| 6 | Config policy | General settings use `config`; production `toml::` is confined to typed guard predicate objects. | Keep this narrow exception; forbid config behavior through `toml`. |
| 7 | #374 verdict | Build/package matrices pass, but clean semantic role → dispatch → guard → report proof is absent. | Semantic cross-harness dogfood blocks release. |
| 8 | #368 | OPEN and reproduced live: Pi rejects standard `call_*|fc_*` tool-call identifiers. | Normalize tool-call IDs only; preserve strict lane/session IDs. |
| 9 | #370 | OPEN: Pi does not expose all Shepherd roles through its subagent provider. | Register the closed nine-role flock with literal identity preserved. |
| 10 | #320 | OPEN: structured out-of-repo writes deny while equivalent Bash writes allow; missing Bash command permits. | Fail closed without token-scanning theater. |
| 11 | #334 | OPEN: dispatch records carry `lane: null` and `write_scope: ["**"]`, including read-only roles. | Record truthful lane and bounded/non-writable scope. |
| 12 | #367 | OPEN: 6.5.1 rejects legacy 6.4.4 `paths.reports` before actionable migration. | Add bounded compatibility or migration, not parallel config authority. |
| 13 | #369 | OPEN: first-run spawn silently fails when no run was planted. | Make the transition explicit and actionable. |
| 14 | #351 | OPEN: source, installed CLI, package cache, and adapters can report different versions. | Establish one measurable compatibility marker. |
| 15 | #326 | OPEN: organization-transfer URLs and both installation paths need final verification. | Use canonical `pzzld-org` locations and cold probes. |
| 16 | #374 A1 | `bash_post.sh` treats command substrings as gate execution evidence. | Separate observed text, invoked process, and successful result. |
| 17 | #374 A2 | npm high/critical findings lack release ownership and reachability classification. | Fix, remove, or time-bound every reachable finding. |
| 18 | #374 A5 | Tracked `.claude/settings.json` requests unsafe shared permissions and prompt suppression. | Remove unsafe shared defaults and gate recurrence. |
| 19 | Hook carriers | Claude, Codex, Pi, and native adapters exist; declarations were tested, not the full lifecycle. | Produce behavioral event × harness evidence, including honest host limits. |
| 20 | PR/milestone | PR #372 is open, draft, cleanly mergeable, `v6.5.6` → `main`; no v6.5.6 milestone exists. | Keep draft; create and attach the milestone. |
| 21 | Prior lesson | v651 proved correct gates can remain unwired; v646 proved stale premises can survive into a seed. | Acceptance must prove intended cases executed and can fail. |

## Signals swept

- #374 and linked #320, #326, #334, #351, #367, #368, #369, and #370.
- Draft release PR #372, current release metadata, and milestone roster.
- `.shepherd/runs/v646/{mesh,seed,close,carry-forward}.md`.
- `.shepherd/runs/v651/{mesh,seed,close}.md`.
- Cargo manifests/lockfile, install docs, release workflows, package tests, hook carriers,
  generated plugin carriers, guard predicates, and shared harness settings.

## Plan-author constraint

Treat this mesh as evidence, not a backlog invitation. Re-measure every defect, correct
contradictions in `plan.md`, partition file-disjoint work, and prefer deletion or installed
dependencies over new machinery. The one canonical handoff is `.shepherd/runs/v656/seed.md`.
