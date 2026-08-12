# The plugin layout is an interface contract

**Status:** locked
**Date:** 2026-08-12
**Applies to:** v6.4.5 arc, deliverable #279 (`content/` compiler)

## What happened

`hooks/`, `skills/` and `docs/` were moved under `src/` to tidy the repository root. The move was 44 pure renames and it broke the plugin completely. Nothing reported it.

That last part is the important part, so it is worth being precise about why:

- **`claude plugin validate` returned `✔ Validation passed`** on the broken tree. It validates manifest *shape*. It parses `hooks/hooks.json` as JSON and never opens the `command` strings inside, so 43 hooks pointing at deleted scripts validate clean. Confirmed empirically, alongside a control (`"hooks": "./nope/hooks.json"` **is** rejected, so the manifest path check is real — it just does not reach inside the file).
- **The live session kept working**, because the running plugin is the cached install of the *previous* release (`~/.claude/plugins/cache/pzzld/shepherd/6.4.4/`), not the working tree. The breakage was latent until publish, at which point it lands on users with no CI signal in between.

Measured damage on the moved tree: **17 of 21** root-resolving gate tests red (0 of the same 6-test sample passing, versus all 6 green on `f0f05e1` extracted to `/tmp` — causation proved, not inferred), all 43 hook registrations inert, all 7 skills undiscoverable, the `.shepherd/shepherd.toml` gate command failing on every run, and `release.yml` silently skipping its `SKILL.md` version bump forever because the step is guarded by `[ -f ]`.

## The rule

**Component directories are discovered by convention at the plugin root.** From the plugin reference:

> **Common mistake**: Don't put `commands/`, `agents/`, `skills/`, or `hooks/` inside the `.claude-plugin/` directory. Only `plugin.json` goes inside `.claude-plugin/`. All other directories must be at the plugin root level.

| Directory | Purpose |
|---|---|
| `.claude-plugin/` | `plugin.json` and `marketplace.json` only |
| `agents/` | agent definitions |
| `commands/` | flat Markdown skills |
| `skills/` | `<name>/SKILL.md` directories |
| `hooks/` | `hooks.json` |
| `bin/` | executables added to the Bash tool's `PATH` |

`marketplace.json` declares `source: {source: "github", repo: "FL03/shepherd"}`, so **the plugin root is the repository root**. There is no subdirectory indirection to hide behind.

## Why a manifest override does not rescue a move

`plugin.json` does support explicit component paths (`"skills": "./src/skills/"`, `"hooks": "./config/hooks.json"`, and so on; `skills` *adds to* the default scan, the others *replace* it). So the two entry points can be relocated and will validate.

It still does not work, and the reason is one sentence in the reference:

> `${CLAUDE_PLUGIN_ROOT}` — Absolute path to the plugin's **installation directory**.

That is the plugin root, **not** the directory `hooks.json` happens to live in. Relocating `hooks.json` does not re-base the 43 `${CLAUDE_PLUGIN_ROOT}/hooks/scripts/*.sh` commands inside it. So the override fixes discovery of two entry points and leaves everything they point at broken.

Counting it honestly: the override path is ~1,000 edits (43 hook commands, 24 tests resolving `../..`, `filetree.sh`'s path→class dispatch table, `xref.py`'s `SCAN_DIRS`, `release.yml`, three `shepherd.toml` gate commands, and ~945 prose citations across `agents/` and `commands/`) to reach the same functional state one `git mv` reaches. It also leaves the repo shape diverging from what the Codex and Pi adapters emit, since those consume the same layout.

## Decision

1. **The root layout stands.** `agents/`, `commands/`, `skills/`, `hooks/` stay at the repository root. Reverted in this commit.
2. **The contract is checked, not remembered.** `scripts/check-plugin.sh` holds six rules, each with a self-test proving it can fail. It runs in the `fast` gate tier — pure filesystem work, no compilation — so it fires on every commit that touches a plugin-shaped path, and in CI.
3. **`content/` is still the answer to the underlying want.** The instinct behind the move — author once, stop maintaining parallel copies — is right, and deliverable #279 already specifies it: role and skill bodies authored under `content/`, **compiled out** to `agents/`, `commands/`, `skills/` and `hooks/` at the root. Emitted artifacts stay committed so `source: github` installs need no build step. That gives single-source authoring *and* keeps every harness reading the shape it expects. `content/` is a new source tree that emits into the root layout; the root layout has to survive for the compiler to have a target.

## What the gate checks

| Rule | Catches |
|---|---|
| component dirs are at the root | the exact move that caused this |
| hooks json is discoverable | `hooks/hooks.json` absent with no manifest override |
| hook commands resolve | a `${CLAUDE_PLUGIN_ROOT}` command pointing at a deleted or non-executable script |
| plugin root refs resolve | the same, across `agents/`, `commands/`, `skills/`, `scripts/`, `bin/`, `docs/` |
| skills are shaped correctly | a skill directory with no `SKILL.md` |
| configured gates resolve | a `.shepherd/shepherd.toml` gate command naming a path that no longer exists |

Verified by reproducing the move: five of the six rules fire, against a tree the official validator passes.

## Known-red, pre-existing, not caused by the move

Both fail identically on `f0f05e1` (pre-move) and should not be attributed to the revert:

- `test_changelog_current.sh` — `plugin.json` is v6.4.5 and `CHANGELOG.md` has no `## v6.4.5` section yet. Expected mid-arc; release-gate criterion 7 closes it.
- `test_engineer_self_contained.sh` — `.claude/shepherd.toml` is missing `[models]` and `[prune]` blocks. A dogfood-config gap, unrelated.

`skills/*/SKILL.md` sitting at `version: 6.4.4` against `plugin.json`'s `6.4.5` is **not** drift: `release.yml:219` bumps them as part of the release commit. It is worth knowing only because that step is `[ -f ]`-guarded and was silently skipping while the files were moved.
