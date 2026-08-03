# v6.5.0-dev.0 Implementation Plan

**Goal:** Retire the bash CLI layer behind a complete Python CLI with a Jinja2
template engine, standardize run artifacts under `.shepherd/runs/{run}/`, and
refine the planning contract (planter/engineer/conductor) with internalized
superpowers discipline.

**Architecture:** Everything lands in `services/cli` (deterministic space)
plus doctrine markdown (latent space contracts). The CLI owns paths, schemas,
rendering, and validation; doctrine references CLI commands instead of
restating mechanics. Contracts change once, in one place, and every consumer
reads the same file.

**Global constraints** (every wave inherits these):

- Python 3.11 floor, Typer + Tortoise + pydantic + jinja2 only (no new deps).
- Bash parity before bash deletion: each ported command keeps flags, output
  shape, and exit codes; the load-bearing bash-test assertions migrate to
  pytest in the same wave as the port.
- `services/cli/tests` green after every wave (`poetry run pytest -q`);
  `hooks/tests/run.sh` green except the pre-existing changelog gate until the
  version-bump wave fixes it; no `--no-verify`.
- Rendered artifacts carry no timestamps in their bodies; lineage lives in a
  sidecar manifest. StrictUndefined everywhere.
- Doctrine edits keep the existing file map (no new skills, no new agents).
- Net-negative LOC on production source (bash deletion ≈ −4,400 dominates).

## Wave 1 — CLI foundations (exclusive: services/cli/)

1. `resolution.py`: `--git-common-dir` root resolution, `in_subworktree`,
   `resolve_user_home` (~/.shepherd, SHEPHERD_HOME override). DONE + tests.
2. `render.py` + `templates/`: jinja2 Environment factory (StrictUndefined,
   trim_blocks, lstrip_blocks, sorted-dict tojson filter), template resolution
   project `.shepherd/templates/` → user `~/.shepherd/templates/` → package
   data; `render` command (`--var`, `--vars-json`, `--out`, `--manifest`);
   lineage manifest = {template, template_sha256, vars_sha256, output_sha256}.
   Consumes: resolution.py. Produces: `render_template(name, ctx) -> str`,
   `shepherd render <name>`.
3. `run.py` command group: pydantic `RunState` schema (schema_version, run,
   kind, branch, base, seed, plan, status, lanes[{id, plan, worktree, branch,
   accepted_commit, merged, state, updated_at}], updated_at); atomic write
   (tempfile + fsync + os.replace); `run init|show|list|set|lane` plus the
   #242 boundary-merge ledger: `run wave accept <lane> --commit <sha>` /
   `run wave merged <lane>` / `run wave pending` (non-empty pending set at a
   gate is the mechanical stop). Produces: `run_dir(run)`, `lane_dir(run,
   lane)` used by templates and hooks.
4. `style.py` profile resolution: `.shepherd/profiles/{p}/style.md` →
   `~/.shepherd/profiles/{p}/style.md` → bundled styles; `style init` scaffolds
   the profile dir shape; migrate legacy `styles/*.md` in layout-v3.
5. `migrate.py` layout-v3 (follows the v2 pattern at migrate.py:131-140):
   `docs/plans/{slug}.seed.md` → `runs/{slug}/seed.md`, `.plan.md` →
   `runs/{slug}/plan.md`, close/phase0/handoff reports into their run dirs,
   `styles/*.md` → `profiles/{lang}/style.md`; idempotent, never clobbers.
6. Templates (first set): `handoff.md.j2` (replaces awk + str.replace
   engines), `boot-prompt.md.j2` (stable blocks FIRST, volatile lane vars
   LAST), `lane-plan.md.j2`, `seed.md.j2`, `plan.md.j2`, `inject.md.j2`,
   `judge-prompt.md.j2` (eval). handoff.py re-pointed to render.py.

## Wave 2 — the seven ports (exclusive: services/cli/, skills/context/scripts read-only)

Port order respects coupling: `adapt` → `inject`; `plan`+`graph` as one unit;
`loop`, `panes`, `release` independent. Each port: typer module + pytest suite
migrating that command's bash-test assertions + parameterized SQL (#234 class
eliminated). Specific fixes folded in: graph-next cursor regression test on a
21-node fixture (#225); teammate `register-lead` port + UNIQUE retrofit
migration 0022 (dedupe rows, unique index if absent) (#241/#223); `release`
keeps gh/git subprocess with retry. `graph`/`plan` state moves to
`runs/{run}/graph/` with a compat fallback read of `<ns>/graph/`.

Then re-point the nine bash-shelling modules (sync, ready, audit, sprint,
dash, refresh, init, dups, + graph consumer in dash) at in-process Python;
port `refresh-{symbols,github,artifacts}.sh`; relocate `dups-core.py` into
`shepherd_cli/`; bundle schema/ + queries/ as package data (importlib.resources
with filesystem fallback).

## Wave 3 — bash retirement + hooks (exclusive: skills/context/scripts/, hooks/)

1. `shctx` becomes a 3-line exec shim to `bin/shepherd`; delete `cmd_*.sh`,
   `_lib.sh`, `refresh-*.sh`, `scaffold.sh`; drop `find_bash_shctx`/`PORTED`
   shim from `__main__.py`; rewrite `test_shim_passthrough` to assert the
   unknown-command error; migrate remaining load-bearing bash tests.
2. Hook path flips: 5 hooks call `bin/shepherd`; `seed_preflight_check.sh`
   matches `runs/*/seed.md` AND legacy `*.seed.md`; `hooks.json` plan
   matchers gain `runs/*/plan.md` + `runs/*/lanes/*/plan.md`;
   `session_open.sh` plan-validity reads `[paths]`-aware run dirs (fixes the
   pre-existing hardcoded `plans/` bug).
3. Identity gates: `agent_invocation_tagger.sh` stamps a session-tier marker
   file; `coordinate_drive_guard.sh` gates on the positive marker (root-only)
   instead of registry inference (#232/#228); liveness scoping to the live
   team roster + lead-session-start stale-sweep (#229); `conductor_write_guard`
   allows writes under the conductor's own `runs/{run}/lanes/{lane}/` (lane
   plan custody); `close_finalize_check.sh` asserts `[gates.extra]` ran (#59
   — reads the gate ledger the doctor now writes); doctor gains
   `gates-invocation` + `binary-version-mismatch` checks (#59/#235).

## Wave 4 — doctrine sweep (exclusive: skills/shepherd/, skills/context/references/, agents/, commands/, docs/)

1. `skills/context/references/naming-conventions.md` → canonical artifact
   schema: run layout table (exact paths), ownership table (who writes what),
   sanitization rules, gitignore split, run.json fields. Everything else
   references it.
2. Path sweep per the res_12 §5 inventory: seed-template.md §File path,
   planter.md, engineer.md, shepherd.md, conductor.md, spawn.md, start.md,
   pipeline.md, flock.md, escalation.md, cleanup.md — `{paths.plans}/{slug}`
   forms become `{run_dir}` forms; `.artifacts/` literals become `.shepherd/`.
3. Planning refinement (internalized superpowers discipline, no new skills):
   - engineer.md: superpowers skills "if installed"; plan contract gains
     per-step `Interfaces: consumes/produces`, the banned-placeholder list,
     the pre-critic self-review walk (spec coverage / placeholder scan /
     symbol consistency); reviewer-gated step sizing language.
   - conductor.md: lane plan custody (checkbox tracking, `## Deviations`
     append-only log); review-plan-critically-first; files-as-context-bus
     (reports to files, ≤15-line returns); `merge-base --is-ancestor` pre-ff
     assertion (#242); stop-and-escalate-not-guess.
   - spawn.md: boot prompt rendered via `shepherd render boot-prompt`
     (stable-first ordering), carries lane-plan PATH not pasted brief;
     structured `git_custody: root|lane` boot field the profile must echo
     (#230); substrate preflight (env var + probe) replacing the advisory
     Check 1 + permission-mode inheritance guidance (#220).
   - seed-template.md: optional `## Operational state` extension slot (#237).
4. Harness currency: agent frontmatter `effort:` where reasoning depth was
   prose (`thinking:` keys retired); SKILL.md `when_to_use`; note TeamCreate
   removal already correct; teammate model non-inheritance wording aligned
   with current docs.

## Wave 5 — close (repo root)

Repo self-migration (`.artifacts/` → `.shepherd/` via `shepherd migrate
--layout v3` + config repoint + carry-forward file move); `.gitignore` run
split; CHANGELOG entries for v6.4.1 (repairing the missed gate) and v6.5.0;
plugin.json + pyproject 6.5.0; full suites (pytest, hooks, remaining ctx);
eval rubric refresh (seed rubric gains placeholder/interface checks); push;
draft PR; close #239 #244 #234 #225 #241 #235 #230 #242 #220 #59 #232 #228
#229 #221 #231 #181 with evidence, close #243 #130 #30 #29 #28 #27 as
superseded-by-plan.

## Acceptance (run at close)

- `poetry run pytest -q` green; `bash hooks/tests/run.sh` 74/74.
- `grep -r "cmd_" services/cli/shepherd_cli --include='*.py' | grep -v test`
  → 0 bash shell-outs to the retired layer.
- `ls skills/context/scripts/` → shctx shim only (or gone).
- `git check-ignore .shepherd/runs/x/graph/f` passes;
  `git check-ignore .shepherd/runs/x/seed.md` fails (tracked).
- `shepherd render handoff --vars-json <f>` byte-identical across two runs.
- `shepherd run init v650-dev0 && shepherd run show v650-dev0` round-trips.
- LOC delta net-negative on production source (`git diff --shortstat`).

## Deviations

(append-only; entries added as they occur)
