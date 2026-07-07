# Profiles — behavior-overlay schema

Profiles let a consumer project adjust flock behavior without forking the
plugin. Per-role dispatch configuration (which model a role runs with) is
declared in the `[models]` table and resolved via `shctx models resolve
<role>` / `shctx models show`; see `references/model-map.md` for that
contract — profiles no longer carry per-role model overrides. This file
documents what remains: the `profiles_defs` schema (`references/schema.md §
profiles_defs`) and the TOML authoring format for non-model overlays
(modifier / extension / override). The `shctx profile` CLI (list/show/
enable/disable/sync) was pruned in v6.2.8 — the per-role dispatch case it
covered lives in `[models]` now, and the reconciliation semantics below
document the `profiles_defs` schema for direct row authorship (migration or
manual insert) rather than a maintained TOML-sync path.

## Kinds

| Kind | Semantics | Example |
|---|---|---|
| `modifier` | Adjusts existing behavior; tweaks a parameter, never adds a pipeline node. | "Skip critic for XS sprints." |
| `extension` | Adds new behavior via a pipeline lifecycle hook. | "After every coder wave, run `cargo audit`; fail on high." |
| `override` | Replaces a built-in default/recommendation with a project-specific one. | "Use these custom DEDUP-GATE recommendations." |

`kind` is a hard CHECK constraint on `profiles_defs.kind` — only these three
values are accepted; an unrecognized value MUST fail validation, never
silently pass through.

## TOML format

```toml
name = "<unique-per-project-slug>"
kind = "modifier" | "extension" | "override"

[config]
# kind-specific keys
```

The file's basename (sans `.toml`) conventionally equals `name`, but the
`name` field inside the file is authoritative.

**Modifier `[config]`:** `skip_critic_for = ["XS"]` (t-shirts to skip
`@critic` on; default never); `auditor_swarm_size = N` (overrides
`[auditor].swarm_size`, default 3); `dedup_grep_first = true` (inverts the
SQL-fast-path/grep order for DEDUP-GATE; default SQL-first); `reason = "..."`
(required rationale).

**Extension `[config]`:** `hook = "post-wave" | "post-sprint" |
"pre-dispatch" | "post-merge"` (required); `command = "<shell command>"`
(required, runs at repo root); `fail_on = "high" | "any" | "never"`;
`timeout_seconds = 300`.

**Override `[config]`:** `target = "<registry-id>"` (required, e.g.
`dedup-gate.recommendation-block`); `replacement = "<markdown body>"`
(required). Override IDs are stable per shepherd minor version; an unknown
target MUST fail.

## Reconciliation — TOML is authoritative

| Situation | Outcome |
|---|---|
| TOML present, DB row absent | Insert row; `source_path` set, `active=1`. |
| TOML present, DB row present, match | No-op. |
| TOML present, DB row present, differ | **TOML wins** — update the row, bump `updated_at`. |
| TOML absent, DB row present, `source_path` set | Disable (`active=0`); re-enable on TOML restore. |
| TOML absent, DB row present, `source_path` NULL | Leave alone (DB-only profile). |
| TOML invalid (parse error or bad `kind`) | Abort; surface error; nothing written. |

TOML wins because humans edit TOML and the DB is a runtime cache — reverse
precedence would silently overwrite operator intent.

## Firing order

Read once at sprint open; live TOML edits do NOT take effect mid-sprint.

1. **Overrides** apply first — replace bundled defaults before any other logic.
2. **Modifiers** apply at the dispatch decision point they target (e.g.
   before composing the `@critic` dispatch).
3. **Extensions** fire on their declared hook during the walk.

## See also

- `references/schema.md § profiles_defs` — column-level reference.
- `references/model-map.md` — per-role model dispatch (the `[models]` table).
- `examples/profile-modifier.toml`, `examples/profile-extension.toml` —
  ready-to-copy starters.
