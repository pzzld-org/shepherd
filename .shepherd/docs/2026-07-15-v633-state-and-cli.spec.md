---
sprint: v6.3.3
date: 2026-07-15
status: implemented — units A/B/C/D/E/F landed; gate suites green (hooks 65/65, context 48/48, cli 30/30); adversarial review pass before commit
drivers: [#200, #193, #195, #198, toolkit-removal, task-list-resilience]
---

# v6.3.3 — state subsystem hardening + the actual CLI

Closing artifacts that seeded this sprint: the v6.3.2 changelog (what shipped),
field reports #200 + #201 + #193/#194/#195/#197 (filed by root during the axiom
v0.3.8-dev.2 spawn), and #198 (deferred CLI plan). Operator directive: "critical
issues dealing with our most recent stateful addition, plus begin the actual CLI"
+ two follow-ups (Task-list flakiness, drop the toolkit feature). All of it = v6.3.3.

The through-line: the *most recent stateful addition* is the teammate liveness /
`declared_state` feature (migration 0019, v6.3.2). It shipped with two latent
defects the field surfaced immediately — the schema can drift out from under the
code (#200), and the write-side of liveness was never automated (#193). Both get
a permanent, self-healing solve here, and the same scoping discipline seeds the
new CLI's first command group (#198/#195).

## Unit A — #200 schema-drift self-heal (CRITICAL)

Root cause: `cmd_init.sh` applies only `0001_init.sql`; migrations are applied by
a SEPARATE `shctx migrate`. A DB created under an older plugin (or half-migrated by
the 0017 abort) lags the code. `cmd_teammate.sh liveness` / `cmd_panes.sh` then
`SELECT declared_state` on a schema that lacks it → `no such column: declared_state`.
Tests passed because the test harness applies `0001 + all migrations` directly.

Fix (permanent, class-eliminating — not a band-aid):
- [ ] `_lib.sh`: extract `shctx_apply_pending_migrations` (gap-fill loop, DRY with
      `cmd_migrate.sh`); add `shctx_ensure_migrated` — a FAST behind-check
      (applied-count vs shipped-count AND max-version) that auto-applies when
      behind, concurrency-tolerant (treat "duplicate column"/"already exists" as
      already-applied), fail-soft (never aborts a caller under `set -e`).
- [ ] `cmd_init.sh`: after seeding `0001`, migrate to HEAD (init must never leave
      a behind DB — the true source of the drift).
- [ ] `cmd_migrate.sh`: call the shared helper (behavior unchanged).
- [ ] `cmd_teammate.sh` + `cmd_panes.sh`: `shctx_ensure_migrated` before the
      declared_state queries; degrade gracefully (column-exists probe, mirror
      `coordinate_drive_guard.sh`) if healing is impossible (read-only/locked DB).
- [ ] `cmd_doctor.sh`: schema-freshness check (DB version vs shipped HEAD; auto-heal
      note + remediation).
- [ ] Tests: regression (init-only-0001 DB → `teammate liveness` heals, no crash);
      `test_migrate.sh` extension (behind DB → HEAD via ensure_migrated); a
      schema-drift GATE test (every declared_state consumer works post-init).

## Unit B — #193 automatic teammate heartbeat (write-side of liveness)

#193: non-conductor teammates (engineer/self-contained) never call
`shctx teammate heartbeat`, so `last_seen_at` freezes at `spawned_at` and liveness
lies (`ok → presumed-crashed` while actively running). The 0019 `declared_state`
read-verdict was a half-fix — it still needs a MANUAL declaration. #193's preferred
fix (b): derive liveness from a signal every role updates for free.

Fix:
- [ ] New `hooks/scripts/teammate_heartbeat.sh` — PreToolUse hook. If the current
      session is a registered teammate (session_id match, mirror
      `teammate_git_guard.sh` detection), stamp `last_seen_at = now` (booting→active)
      and insert a lightweight heartbeat row. Fail-open, silent, cheap. Can't be
      forgotten by a new role — no agent self-report required.
- [ ] Wire into `hooks/hooks.json` PreToolUse (Bash + the mutating matchers).
- [ ] `agents/engineer.md` + `agents/conductor.md`: note that liveness is now
      auto-maintained; manual `heartbeat` is optional (declare `state` at phase
      boundaries only for intent, not liveness).
- [ ] Config toggle `[hooks].teammate_heartbeat = on|off` (default on).
- [ ] Tests: `hooks/tests/test_teammate_heartbeat.sh` (registered teammate →
      last_seen_at advances; non-teammate/root → no-op; missing DB → fail-open).

## Unit C — #198 begin the actual CLI (Python + Poetry) [DELEGATED, in progress]

`services/cli/` — Poetry package `shepherd_cli`, console entrypoint `shepherd`,
typed session/pid-scoped DB access layer, first command group = teammate
liveness/status/state (scoped-by-construction → also resolves #195's liveness
scoping), self-heal mirroring Unit A, and a `shctx` shim (un-ported subcommands
delegate to the bash `shctx`, so `shepherd` is a working superset day one).
Deterministic feature → gate tests are the proof (no LLM eval). Coordinator wires
the services/README row + changelog + any PATH note.

## Unit D — drop the toolkit feature

Forgotten, net-negative surface. Remove wholesale:
- [ ] Delete: `commands/toolkit.md`, `skills/context/scripts/cmd_toolkit.sh`,
      `skills/context/references/toolkit.md`, `skills/context/references/toolkit.schema.json`,
      `hooks/scripts/toolkit_surface.sh`, `skills/context/tests/test_toolkit.sh`,
      `hooks/tests/test_toolkit_surface.sh`.
- [ ] Unwire: `shctx` dispatcher (drop `toolkit` case + usage), `hooks/hooks.json`
      (SessionStart toolkit_surface), `hooks/tests/run.sh`, `test_exec_bits.sh`,
      `cmd_inject.sh` ([TOOLKIT] block), `hooks/scripts/capability_discovery.sh`
      (toolkit surfacing), `conductor_write_guard.sh`, `scaffold.sh` (toolkit dir),
      `.gitignore`, agent docs (coder/discovery/engineer/planter/worker), skills
      (harness/SKILL, shepherd/SKILL, operating-philosophy, context/SKILL,
      naming-conventions), `docs/configuration.md`, `README.md`,
      `examples/minimal/shepherd.toml`.
- [ ] Verify no dangling `toolkit` reference remains in live surface (specs/handoffs
      are historical, left as-is).

## Unit E — Task-list resilience (registry-authoritative wave-gate)

Operator: the harness Task List "commonly gets failures for shepherds so they can't
always update or utilize the solution quickly." Shepherd wave-gating is currently
enforced by `TaskUpdate`/`addBlockedBy` on a `wave-{N}-gate-{slug}` marker — a hard
dependency on a flaky tool. Consistent with shepherd's SQLite-canonical philosophy,
make the REGISTRY authoritative and the Task list a best-effort mirror.

Fix:
- [ ] Registry-backed wave-gate: `shctx graph`/a small gate record is the source of
      truth for wave release. Doctrine: NEVER block a wave on a Task-tool failure —
      if `TaskUpdate`/`TaskList` errors or is unavailable, proceed on the registry
      gate and log the downgrade.
- [ ] Update `skills/shepherd/references/pipeline.md`, `commands/spawn.md`,
      `agents/conductor.md`, `agents/shepherd.md`, `skills/harness/SKILL.md`:
      registry is authoritative; Task list is an optional convenience mirror.
- [ ] Tests where a mechanical surface is added.

## Docs / release
- [ ] CHANGELOG v6.3.3 entry (all units, cited to issues).
- [ ] README + docs/configuration deltas (heartbeat hook, toolkit removal, CLI).
- [ ] Close #200, #193, #195, #198 (partial/first-increment), toolkit-removal note,
      task-resilience — each with cited evidence.
- Version already at 6.3.3 in plugin.json + marketplace.json.

## Verification gate (before commit)
- [ ] `bash skills/context/tests/run.sh` green.
- [ ] `bash hooks/tests/run.sh` green.
- [ ] `services/cli` pytest green.
- [ ] `jq empty` on plugin.json/marketplace.json/hooks.json.
- [ ] Adversarial review workflow over the full diff; fix findings.
