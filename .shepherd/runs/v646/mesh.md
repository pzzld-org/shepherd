# v6.4.6 planter mesh — consolidated signal sweep

- **Date:** 2026-08-17 · **Branch:** `v6.4.6` (checked out, 7 commits ahead of `origin/main`)
- **PR:** #304 `v6.4.6` — **open** (not draft), base `main`
- **Author:** planter @ plant-v646-2026-08-17
- **Method:** every row below was reproduced first-hand on this machine or read out of the
  cited file/CI log. No row is inferred. Rows marked **STALE-CORRECTED** are prior-sprint
  claims that were re-measured at seed time and found no longer true.

---

## ROW 0 — the operator's four asks, measured against the tree

| Ask | State at seed time | Consequence for the sprint |
|---|---|---|
| Fix install (`cargo` works, `cargo binstall` does not) | Reproduced. Three independent causes, all confirmed (ROW 1–3). | Real work. Highest priority. |
| Stop storing build artifacts in the repo | Reproduced, and it is the **root cause of the install break** — a tracked launcher is symlinked onto PATH ahead of the real binary (ROW 1). | Real work. |
| "Make a git workflow like we used to have" (tag + release on patch merge, then bump, cut next patch, draft PR; mod-10) | **Already fully implemented** in `.github/workflows/gitflow.yml`. Mod-10 enforced twice (`gitflow.yml:130-145`, `scripts/version-bump.py:86 successor()` + a `VersionAuthorityError` guard at `:80`). | **Do not rebuild.** It has never fired because the release it chains from never succeeds (ROW 3, ROW 5). |
| Map flock roles to model tiers "via our map" | **Already implemented.** `shepherd models resolve <role> --harness <claude\|codex\|pi>` returns the 9-role × 3-harness table; `ModelsConfig` at `crates/core/src/settings.rs:545` is the typed schema; `[models]` in `.shepherd/shepherd.toml` is the project override. | Mostly built. Delta is 2 tier values + one missing tier (ROW 9). |

**Mesh conclusion:** two of the four asks are requests to build something that already exists.
Building them again is the exact "hallucinating more work for ourselves" the operator
forbade. The sprint's job is to make the existing machinery *run*, not to author a second copy.

---

## ROW 1 — the install break, reproduced end to end (issue #307)

```
$ command -v shepherd
/Users/jo3/.local/bin/shepherd
$ shepherd --version
shepherd: native binary unavailable.
shepherd: expected executable at /Users/jo3/.local/target/debug/shepherd.

$ ls -la ~/.local/bin/shepherd
lrwxr-xr-x → /Users/jo3/src/fl03/shepherd/bin/shepherd     # the TRACKED repo wrapper
$ diff ~/.local/bin/shepherd bin/shepherd                   # IDENTICAL
$ type -a shepherd
shepherd is /Users/jo3/.local/bin/shepherd
shepherd is /Users/jo3/.cargo/bin/shepherd                  # the real one, never reached
$ file ~/.cargo/bin/shepherd
Mach-O 64-bit executable arm64
$ ~/.cargo/bin/shepherd --version
shepherd-cli 6.4.5                                          # works perfectly
```

**Mechanism.** `bin/shepherd:24` computes `root="$(dirname "${BASH_SOURCE[0]}")/.."` from the
**unresolved** invocation path, so through the `~/.local/bin` symlink `root` becomes
`/Users/jo3/.local` and it hunts `/Users/jo3/.local/target/{release,debug}/shepherd`. It then
tries PATH (`bin/shepherd:31-36`), gets *itself* back from `command -v`, correctly rejects the
self-match — and **stops**, instead of continuing down PATH to `~/.cargo/bin/shepherd`. Exit 127.

Note `resolve_executable` is applied to `$launcher` and to `$installed`, but **never to
`${BASH_SOURCE[0]}` before `root` is derived**. That single omission is the whole defect.

Every registered hook is `"command": "shepherd"` (ROW 7), so this one script turns every hook
in every harness into exit 127.

---

## ROW 2 — `cargo binstall` 404s because no release has ever carried assets

```
$ for t in v6.4.5 v6.4.4 v6.4.3 v6.4.2; do gh release view $t --json assets --jq '.assets|length'; done
0
0
0
0
$ curl -sIL -o /dev/null -w '%{http_code}\n' \
    https://github.com/FL03/shepherd/releases/download/v6.4.5/shepherd-6.4.5-aarch64-apple-darwin.tar.gz
404
$ curl -s https://crates.io/api/v1/crates/shepherd-cli | jq '[.versions[].num]'
["6.4.5"]
```

`crates/cli/Cargo.toml:63` sets `disabled-strategies = ["quick-install", "compile"]`, which
removes every fallback binstall could use. So binstall resolves 6.4.5 from crates.io, builds
the `pkg-url`, gets 404, and has nowhere left to go — a hard failure. `cargo install
shepherd-cli` still works because it compiles the crates.io source tarball and never touches
GitHub releases. That is exactly the asymmetry the operator reported.

`README.md:42-46` documents `cargo binstall shepherd-cli` as the **primary** install path.
The documented happy path is the broken one.

---

## ROW 3 — why assets were never built: macOS arm64 packaging, verbatim from CI

Run `31895705712` (`v6.4.5: repair cross-platform release packaging`):

| Job | Result |
|---|---|
| Resolve release metadata | success |
| Native x86_64-unknown-linux-gnu | success |
| Native x86_64-apple-darwin | success |
| Native aarch64-unknown-linux-gnu | success |
| Component and harness adapters | success |
| **Native aarch64-apple-darwin** | **failure** |
| **Native x86_64-pc-windows-msvc** | **failure** |
| Publish verified release | **skipped** |

```
Native aarch64-apple-darwin  Package Unix archive and SHA-256 sidecars
  tar: Option --owner=0 is not supported
  ##[error]Process completed with exit code 1.
```

`scripts/create-release-tar.sh:47` runs `tar --format=ustar --owner 0 --group 0
--numeric-owner`, under a comment (`:44-46`) asserting that option set is *"shared by GNU tar
on Linux and bsdtar on macOS."* **That assertion is false on the runner image.** GNU tar has
`--owner/--group` and no `--uid/--gid`; older libarchive has `--uid/--gid` and no
`--owner/--group`. There is no single flag set covering both.

Why it escaped review — measured on this machine:

```
$ tar --version
bsdtar 3.5.3 - libarchive 3.7.4
$ tar --format=ustar --owner 0 --group 0 --numeric-owner -C tartest -cf /dev/null -- shepherd
rc=0                                    # passes locally, fails on the runner's older libarchive
```

The failure is **runner-image-version-dependent**, which is why local verification agreed with
the comment and CI did not.

Windows failed independently, `scripts/tests/test-release-installer-windows.ps1:370`:

```
New-Item : Cannot find path '...\dangling-link-destination\missing.exe' because it does not exist.
    + New-Item -ItemType SymbolicLink -Path $danglingDestination -Targe ...
```

The test wants a *deliberately dangling* symlink; Windows PowerShell 5.1 refuses to create one
without `-Force`.

---

## ROW 4 — the release that exists was cut out of band

`gh release view v6.4.5` → `author: FL03`, `created 2026-08-15T19:21:41Z`, `published
2026-08-15T22:13:27Z`. The last release-workflow run was 19:21. The release was therefore
published ~3h after CI last ran, by hand, with zero assets — papering over ROW 3 and producing
exactly the state binstall chokes on.

---

## ROW 5 — the release gate reports green when it does nothing

`release.yml:21-24` triggers on `push: branches: [main, master]`. `release.yml:52` requires the
merge-commit subject to match `^(release:[[:space:]]+)?v([0-9]+\.[0-9]+\.[0-9]+)([[:space:]:]|$)`.
Any other subject sets `proceed=false`, every downstream job is `if:`-skipped, and **the run
concludes `success`**.

Measured:

| Run | Subject | Metadata | Build | Publish | Conclusion |
|---|---|---|---|---|---|
| 19:21 | `fix(publisher): verify crates.io archive custody` | success | skipped | skipped | **success** |
| 18:51 | `feat(release): ship v6.4.5 Cargo-native…` | success | skipped | skipped | **success** |
| 16:30 | `v6.4.5: repair cross-platform release packaging` | success | 2× failure | skipped | failure |

Two green runs that released nothing. `gitflow.yml:26` then chains on `workflow_run …
conclusion == 'success'`, so the entire post-release automation (ROW 0, ask 3) hangs off a
signal that is green for a no-op. It reaches "Verify published release custody", calls
`skip_automatic_or_fail`, prints a `::notice::`, and exits 0.

This is the `gates-that-cannot-fail` failure class from the project memory, sitting on the
release path.

---

## ROW 6 — project identity: a missing file reported as a symlink attack (issue #306)

Operator's recurring blocker:

```
cannot open project identity /Users/jo3/Documents/vaults/pzzld/.shepherd/project.json
without following symlinks: No such file or directory (os error 2)
```

**The symlink is not the cause.** Measured:

```
$ ls -ld /Users/jo3/vaults
lrwxr-xr-x → /Users/jo3/Documents/vaults
$ readlink -f /Users/jo3/vaults/pzzld ; readlink -f /Users/jo3/Documents/vaults/pzzld
/Users/jo3/Documents/vaults/pzzld
/Users/jo3/Documents/vaults/pzzld          # identical; the symlink is benign
$ ls /Users/jo3/Documents/vaults/pzzld/.shepherd/
ctx/  docs/  runs/  shepherd.db  shepherd.db-shm  shepherd.db-wal  shepherd.toml
                                            # no project.json — the file simply is not there
$ cat /Users/jo3/Documents/vaults/pzzld/.shepherd/shepherd.toml
# Shepherd layout-v5 project configuration.
# Defaults are supplied by the typed schema.
                                            # comment-only stub; no [project] block
```

Contrast this repo, which is healthy: `.shepherd/project.json` →
`{"id":"019ff81f-1559-7dfc-ac90-ddb5c11a3ad8","scaffolded_at":1786574214}`.

Two distinct defects:

1. **Scaffolding is non-atomic.** Something created `shepherd.db` (507 KB, populated), a
   `shepherd.toml` stub, and three empty directories, then never wrote `project.json`. The
   project is left permanently half-initialized with no self-heal and no signal.
2. **The error message misdirects every diagnosis.** `crates/cli/src/cmd/dispatch.rs:186-193`
   maps *every* `rustix::fs::open` failure to the single string `"cannot open project identity
   {} without following symlinks: {error}"`. A plain `ENOENT` therefore renders as a symlink
   refusal. The operator's own diagnostic plan for this session opened by asking whether the
   vault was symlink-mapped and whether the hook resolved symlinks — both dead ends, caused by
   this message. `NOFOLLOW` is correct security policy; reporting ENOENT as if it fired is not.

Locked-in behaviour to preserve: `crates/cli/tests/dispatch_cli.rs:232` and
`crates/cli/tests/wave_f_knowledge.rs:111` assert on the genuine symlink refusal path.

---

## ROW 7 — harness hook fidelity (Claude / Codex / Pi)

Four manifests define the same four events, and they disagree.

| Event | `plugins/shepherd/hooks/hooks.json` (Claude, shipped) | `packages/harness-claude/hooks/hooks.json` (superseded) | `plugins/shepherd/codex/hooks/hooks.json` (Codex, shipped) | `packages/harness-codex/hooks/hooks.json` (superseded) | Pi |
|---|---|---|---|---|---|
| SessionStart | `shepherd claude-hook` | node `dispatch-lifecycle.mjs` | `shepherd codex-hook` | node `shepherd_guard.mjs` | **absent** |
| PreToolUse | `shepherd claude-hook` (`Write\|Edit\|Bash\|Agent\|Workflow`) | node `guard-eval.mjs` | `shepherd codex-hook` (`^(apply_patch\|Bash)$`) | node `shepherd_guard.mjs` | **absent** |
| SubagentStart | `shepherd claude-hook` | node `dispatch-lifecycle.mjs` | **MISSING** | node `shepherd_guard.mjs` | **absent** |
| SubagentStop | `shepherd claude-hook` | node `dispatch-lifecycle.mjs` | **MISSING** | node `shepherd_guard.mjs` | **absent** |

- **Codex lost two events in the Rust-native migration.** The superseded node manifest defines
  SubagentStart and SubagentStop; the shipped native one does not. Codex therefore never binds
  or closes subagent dispatch identity — a regression, not a design choice.
- **Pi has no hook manifest at all.** `packages/harness-pi/shepherd.pi.json` declares only
  `transitions.resume` / `transitions.stop`; there is no SessionStart identity bind and no
  PreToolUse guard. Pi is unguarded.
- `hooks/hooks.json` is byte-identical to `plugins/shepherd/hooks/hooks.json` (`diff` clean) —
  and the shipped one is a symlink to it (ROW 8).
- **Eight scripts under `hooks/scripts/` are registered nowhere**: `precompact_snapshot.sh`,
  `bash_post.sh`, `agent_insight_capture.sh`, `cwd_changed.sh`, `discovery_capture.sh`,
  `seed_preflight_check.sh`, `subagent_telemetry.sh`, `_lib.sh`. No manifest references any of
  them — all four route through the `shepherd` binary. `hooks/tests/` holds 26 test files
  exercising them, all passing, none of which prove a registered hook works. Another
  gates-that-cannot-fail cluster.
- No harness registers `PostToolUse`, `Stop`, `PreCompact`, `UserPromptSubmit`, or
  `SessionEnd`, despite `precompact_snapshot.sh` and `bash_post.sh` existing for exactly those.

---

## ROW 8 — the shipped plugin is three symlinks pointing outside itself

`.claude-plugin/marketplace.json` declares `"source": "./plugins/shepherd"`. That subtree is 13
tracked files, three of which are symlinks that escape the plugin root:

```
$ git ls-files -s | awk '$1=="120000"{print $4}'
CLAUDE.md
plugins/shepherd/agents         -> ../../agents
plugins/shepherd/hooks/hooks.json -> ../../../hooks/hooks.json
plugins/shepherd/skills         -> ../../skills
```

All nine agents, all seven skills, and the entire Claude hook manifest live outside the
declared plugin source and are reachable only by traversing two or three levels above it.
Whether that survives installation depends on how the marketplace materializes the source; a
subtree copy or archive of `plugins/shepherd` alone yields a plugin whose agents, skills, and
hooks are all dangling. This needs measuring against a real install, not reasoning.

---

## ROW 9 — the model map exists; three values are wrong

`shepherd models resolve <role> --harness claude`, measured against the operator's stated intent:

| Role | Portable tier (`ModelsConfig` default) | Resolves to (claude) | Operator's intent | Delta |
|---|---|---|---|---|
| root | `inherit-caller` | `inherit` | **opus** | **change** |
| planter | `reasoning-high` | `opus[1m]` | opus | ok |
| engineer | `reasoning-high` | `opus[1m]` | opus | ok |
| conductor | `standard` | `sonnet` | opus **or** sonnet | ok (make lane-overridable) |
| critic | `standard` | `sonnet` | sonnet | ok |
| coder | `standard` | `sonnet` | sonnet | ok |
| auditor | `standard` | `sonnet` | sonnet | ok |
| worker | `standard` | `sonnet` | sonnet | ok |
| discovery | `standard` | `sonnet` | sonnet **or haiku** | **needs an economy tier** |

The portable vocabulary is exactly three tiers — `inherit-caller`, `reasoning-high`,
`standard` (`crates/core/src/settings.rs:557-570`). There is **no economy tier**, so "discovery
on haiku" is currently unexpressible. That is the only genuinely new surface this ask requires.

`agents/*.md` frontmatter carries a second copy of the same mapping (`shepherd: inherit`,
`engineer: opus[1m]`, six at `sonnet`). Two sources of truth for one map; they currently agree
except for root.

---

## ROW 10 — version bump state: already complete

Every version authority is at `6.4.6` — verified, not assumed:

`Cargo.toml` workspace + all 6 path deps · `Cargo.lock` (7 shepherd crates) ·
`.claude-plugin/plugin.json` · `.claude-plugin/marketplace.json` (both root and nested
plugin entry) · `plugins/shepherd/.claude-plugin/plugin.json` ·
`plugins/shepherd/.codex-plugin/plugin.json` · root `package.json` · all 4
`packages/*/package.json` · `packages/harness-pi/shepherd.pi.json` (`fl03:shepherd@6.4.6`).

**The one gap:** `CHANGELOG.md` has no `## v6.4.6` section, and `release.yml:437-462` **hard
fails** (`exit 1`) when notes extraction finds no matching section. It also still reads
`## v6.4.5 — unreleased` although v6.4.5 tagged and published on 2026-08-15. So the release for
this very sprint is already guaranteed to fail before it builds anything.

---

## ROW 11 — open issue signal

Both operator-reported blockers are already filed, and their bodies match what was reproduced:

- **#307** — `shepherd` requires a native binary at `~/.local/target/debug/shepherd`; env
  fallback disregarded. == ROW 1.
- **#306** — pre-tool hook blocks execution when project identity points at a missing file.
  == ROW 6.
- **#301** — consolidate deterministic build and release orchestration under `cargo xtask`.
  Directly relevant to ROW 3; the operator's "maximize dependencies, stop rewriting" rule
  argues for adopting it rather than hand-patching shell.
- **#290** — `harness-codex` depends on `harness-claude` at runtime, violating its own
  dependency rule. == ROW 7 harness-fidelity cluster.
- **#181** — template/compiler layer for dispatch call-sites so `[models]` + `agentType` are
  resolved centrally. == ROW 9.
- **#293** — `install-shctx-launcher.sh` crashes with a raw unbound-variable trace. Same
  launcher family as ROW 1.

`v6.4.5`-milestone issues #277–#283, #266, #239, #235 remain open; several describe work that
has since landed and were never closed.

---

## ROW 12 — STALE-CORRECTED: the v6.4.5 carry-forward's CRITICAL is resolved

`.shepherd/runs/v645/carry-forward.md:§0` declares, as the single most important open item,
that the guard engine is in Python and must be Rust. **Re-measured at seed time: it landed.**

```
$ ls crates/core/src/guard/
engine.rs  json.rs  model.rs  parser.rs  tokenizer.rs
$ ls crates/cli/src/cmd/guard.rs        # exists
$ ls services/                          # services/cli is GONE; only llm/ and eval/ remain
$ git ls-files '*.py' | wc -l
24                                      # tooling + conformance only; no engine
```

Carrying that item forward into v6.4.6 would have burned the sprint's largest lane on finished
work. Recorded here so no downstream role re-opens it.

---

## ROW 13 — no prior close report

No `close.md` exists anywhere under `.shepherd/runs/`. `v645/handoff.md` exists and was read;
it is a mid-sprint halt handoff (usage exhaustion, 2026-08-14), superseded on its headline item
by ROW 12.

---

## ROW 14 — the causal chain, in one place

Everything the operator reported is one failure propagating:

```
create-release-tar.sh uses GNU-tar-only flags
   └─> aarch64-apple-darwin packaging fails (+ Windows symlink test fails)
        └─> "Publish verified release" is skipped
             └─> every GitHub release carries zero assets
                  └─> binstall pkg-url 404s
                       └─> disabled-strategies removed the compile fallback
                            └─> `cargo binstall` hard-fails; only `cargo install` works
                                 └─> bin/shepherd gets symlinked into ~/.local/bin as a stand-in
                                      └─> it shadows the real ~/.cargo/bin/shepherd and exits 127
                                           └─> every hook in every harness fails
                                                └─> and where a binary DOES run, a half-scaffolded
                                                    project reports ENOENT as a symlink attack
```

Meanwhile the release gate reports **green** for doing nothing, so none of it ever surfaced as a
red build.

---

## ROW 15 — the zero-asset history has two distinct causes, not one

Worth recording so nobody "fixes" v6.4.5's cause and assumes the older releases were the same
bug. `v6.3.9`–`v6.4.4` shipped zero assets because the release workflow at those commits had a
single job that called `gh release create` with **no file arguments at all** — it never built a
binary. v6.4.5 is the first version whose workflow builds assets, and it is the first whose
failure is a genuine packaging failure (ROW 3). Both eras produce an identical symptom.

## ROW 16 — two further blockers between a green build and a downloadable asset

Found after ROW 3 and confirmed by reading both files:

1. **The asset verifier looks for packages that were renamed.**
   `scripts/verify-release-distribution.sh:86-87` extracts
   `fl03-{component-runtime,harness-claude,harness-codex,harness-pi}-${version}.tgz`. Measured
   package names:

   ```
   packages/component-runtime/package.json  @pzzld/component-runtime
   packages/harness-claude/package.json      @pzzld/pi-claude
   packages/harness-codex/package.json       @pzzld/pi-codex
   packages/harness-pi/package.json          @pzzld/pi-shepherd
   ```

   `npm pack` (`release.yml:348`) therefore emits `pzzld-pi-claude-6.4.6.tgz`, not
   `fl03-harness-claude-6.4.6.tgz`. Both the scope prefix and three of the four names are
   wrong. This runs at `release.yml:483` inside the publish job, so it fails a build that has
   already succeeded.

2. **crates.io publishing cannot be triggered by the release pipeline.**
   `.github/workflows/cargo-publish.yml:3-4` fires on `push: tags: ["v*.*.*"]`. `release.yml`
   pushes the tag authenticated as `secrets.GITHUB_TOKEN`, and GitHub does not trigger
   workflows from `GITHUB_TOKEN`-authored events. The lane is reachable only by
   `workflow_dispatch`. That is why crates.io carries `shepherd-cli 6.4.5` with no GitHub
   release assets behind it — it was published out of band, like the release itself (ROW 4).

## ROW 17 — the tar fix on this branch is unverified, not verified

`4c7c050` changed `--owner=0` to `--owner 0` in `scripts/create-release-tar.sh`.
`git diff origin/main...HEAD -- scripts/create-release-tar.sh` is empty, so both `main` and
`v6.4.6` carry that form. **No release run has executed the macOS packaging path since the
change** — the runs at 18:51 and 19:21 skipped every job (ROW 5). Local `bsdtar 3.5.3` accepts
both spellings, so a local check proves nothing about the runner image that rejected it.
Whether the branch is fixed is currently unknown, and the only instrument that can answer it is
a macOS runner.

## ROW 18 — GitHub Actions are pinned by tag, not by SHA

Surfaced by the background commit security review against `.github/workflows/rust.yml`, and it
generalizes: every workflow pins mutable tags (`actions/checkout@v7`,
`actions-rust-lang/setup-rust-toolchain@v1`, `Swatinem/rust-cache@v2`,
`taiki-e/install-action@v2`, `github/codeql-action/upload-sarif@v4`), several with a trailing
comment naming an exact version the tag does not guarantee. The repo already knows the correct
pattern — `release.yml:467` pins
`actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c # v8.0.1`. One file does it
right and eight do not. Supply-chain relevant because these workflows hold `contents: write`
and publish release assets. Not on the delivery chain; recorded for the plan to scope.

## ROW 19 — tool access verified at seed time

`gh` CLI (used throughout this mesh), and MCP: Context7, Linear (pzzld workspace), Axiom
(`axiom-node v0.3.9`, online), Obsidian (vault root reachable) all responded. There is no
GitHub MCP server under `MCP_DOCKER`; GitHub access is the `gh` CLI, which is sufficient and is
what every GitHub row above was measured with.
