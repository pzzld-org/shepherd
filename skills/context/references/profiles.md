# Profiles — pluggable behavior overlays

Profiles let consumer projects adjust shepherd flock behavior without forking the plugin. They live in two places — TOML files in `.artifacts/profiles/*.toml` (human-edited) and rows in the `profiles_defs` table (queried by the conductor at dispatch time). `shctx profile sync` reconciles the two.

---

## Kinds

| Kind | Semantics | Example |
|---|---|---|
| `modifier` | Adjusts existing flock behavior. Tweaks a parameter; never adds a new pipeline node. | "Skip critic for XS sprints." |
| `extension` | Adds new behavior. Hooks into a pipeline lifecycle event with a bounded action. | "After every coder wave, run `cargo audit`; fail on high." |
| `override` | Replaces a default. Substitutes a built-in recommendation or rule with a project-specific one. | "Use these custom DEDUP-GATE recommendations instead of the bundled defaults." |

Kind is a hard CHECK constraint on `profiles_defs.kind` — only the three values above are accepted.

---

## TOML format

Every profile file has three top-level pieces: `name`, `kind`, and a `[config]` table. The `[config]` schema is **kind-specific** — modifiers tune existing knobs, extensions declare a hook target and command, overrides replace a registered default by ID.

```toml
name = "<unique-per-project-slug>"
kind = "modifier" | "extension" | "override"

[config]
# kind-specific keys
```

The TOML file's basename (sans `.toml`) is conventionally equal to `name`, but the `name` field in the file is authoritative.

### Modifier `[config]` keys (informational)

Modifiers tune the conductor's runtime knobs. Common keys:

- `skip_critic_for = ["XS"]` — t-shirts to skip @critic on (default: never skip).
- `auditor_swarm_size = 5` — override `[auditor].swarm_size` for this project (default: 3).
- `dedup_grep_first = true` — invert the SQL-fast-path/grep order for DEDUP-GATE (default: SQL first).
- `reason = "..."` — required free-form rationale; surfaces in `shctx profile show`.

### Extension `[config]` keys

Extensions register a side-effect on a lifecycle hook:

- `hook = "post-wave" | "post-sprint" | "pre-dispatch" | "post-merge"` — required.
- `command = "<shell command>"` — required. Runs in the repo root.
- `fail_on = "high" | "any" | "never"` — exit-code threshold.
- `timeout_seconds = 300` — wall-clock cap.

The conductor invokes extensions inline at the matching hook; failure on `fail_on` aborts the next dispatch and surfaces a finding.

### Override `[config]` keys

Overrides target a registered default by ID:

- `target = "dedup-gate.recommendation-block"` — required. The override registry ID.
- `replacement = "<markdown body>"` — required. The replacement content.

Override IDs are stable and documented per shepherd minor version; unknown targets fail at `sync`.

---

## Example: complete modifier file

```toml
# .artifacts/profiles/skip-critic-xs.toml
name = "skip-critic-xs"
kind = "modifier"
[config]
skip_critic_for = ["XS"]
reason = "XS sprints are fully scoped by the seed; critic adds no value"
```

See `examples/profile-modifier.toml` and `examples/profile-extension.toml` for ready-to-copy starters.

---

## Sync semantics

`shctx profile sync` reconciles `.artifacts/profiles/*.toml` ↔ `profiles_defs`. Direction-of-truth rules:

| Situation | Outcome |
|---|---|
| TOML present, DB row absent | Insert new `profiles_defs` row; populate `source_path`, `active=1`. |
| TOML present, DB row present, contents match | No-op. |
| TOML present, DB row present, **contents differ** | **TOML wins.** Update the DB row; bump `updated_at`. |
| TOML absent, DB row present, `source_path` set | Disable (`active=0`); preserve row for audit. Re-enable on TOML restore. |
| TOML absent, DB row present, `source_path` NULL | Leave (DB-only profile; created via `shctx profile create`). |
| TOML invalid (parse error or kind not in CHECK set) | Sync aborts; surfaces error; nothing written. |

Why TOML wins: humans edit TOML; the DB is a runtime cache. Reverse precedence would silently overwrite operator intent.

`shctx profile enable <name>` / `shctx profile disable <name>` flip the `active` flag without touching TOML; useful for A/B-testing extensions without losing the file.

---

## When profiles fire

The conductor reads `profiles_defs WHERE active = 1` at sprint open and applies them in priority order:

1. **Overrides** apply first — they replace bundled defaults before any subsequent logic runs.
2. **Modifiers** apply at the dispatch decision point they target (e.g., before composing the @critic dispatch).
3. **Extensions** fire on their declared hook during the walk.

Profile state is read once per sprint open; live edits to `.artifacts/profiles/*.toml` do not take effect mid-sprint. Run `shctx profile sync` and start a new sprint.

---

## Use cases

- **Skip critic for XS sprints** (modifier) — XS scope is fully encoded by the seed; the critic step adds latency without value. See `examples/profile-modifier.toml`.
- **Post-wave security scan** (extension) — Run `cargo audit` after every coder wave; fail the wave if `high` advisories surface. See `examples/profile-extension.toml`.
- **Custom DEDUP-GATE recommendations** (override) — Replace the bundled "wire to existing instead" guidance with a project-specific block (e.g., "wire to `crate::canonical::*` and update the registry").
- **Larger auditor swarms for L+ sprints** (modifier) — `auditor_swarm_size = 5` for projects whose audit surface justifies it.
- **Custom hook on patch-close** (extension) — Run release-note linter after `post-merge`.

---

## See also

- `references/schema.md` § profiles_defs — column-level reference.
- `examples/profile-modifier.toml`, `examples/profile-extension.toml` — copy-paste starters.
- `${CLAUDE_PLUGIN_ROOT}/skills/shepherd/flock.md` — agent dispatch points where modifiers attach.
- `.artifacts/styles/<lang>.md` — per-language style overrides (separate from profiles; addendum §A2).
