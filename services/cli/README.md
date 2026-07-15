# services/cli — the shepherd Python CLI

The `shepherd` command: a Tortoise ORM + Pydantic + Typer CLI that reads and
writes the SAME sqlite database (`.shepherd/shepherd.db`) the bash `shctx`
tooling already owns. Issue #198 ports the first vertical slice —
`shepherd teammate liveness|status|state` — end to end. Everything else
still runs through bash, transparently, via a passthrough shim (below).
This is not a rewrite; it's a coexistence.

## The stack

| Piece | Role |
|-------|------|
| [Tortoise ORM](https://tortoise.github.io/) | Async models that **mirror** the existing SQL tables (`shepherd_cli/models.py`). `Meta.table` is set on every model; `Tortoise.generate_schemas()` is never called, anywhere, by anything in this service. |
| [Pydantic v2](https://docs.pydantic.dev/) | Typed I/O at the process boundary (`shepherd_cli/schemas.py`) — what `--json` actually serializes, kept separate from the ORM rows that produce it. |
| [Typer](https://typer.tiangolo.com/) | The command surface (`shepherd_cli/app.py`, `shepherd_cli/commands/teammate.py`). Thin sync wrappers around one `asyncio.run` per command — Click calls sync, Tortoise is async, so each command owns exactly one event-loop boundary. |

## Coexistence, not migration

The canonical schema is still the SQL migrations at
[`skills/context/schema/`](../../skills/context/schema/)
(`0001_init.sql` + `migrations/*.sql`) — the same files `shctx` and the
hooks read and write today. This CLI's models describe those tables, they
don't define them. A later increment may flip migration ownership to
Aerich once bash is fully retired; until then, SQL migrations are the
single source of truth and `services/cli` follows.

Concretely, that means:

- Every model in `shepherd_cli/models.py` sets `Meta.table` to an existing
  table name (`teammates`, `projects`, `schema_versions`) and declares only
  the columns this CLI actually reads or writes. Columns it doesn't touch
  (`projects.scope`, `projects.tags`, …) are left alone for bash to own.
- `shepherd_cli/db.lifespan()` never calls `Tortoise.generate_schemas()`.
  If a table doesn't exist yet, that's a bash-side `shctx init` problem,
  not something this CLI will paper over by creating its own copy of the
  schema.
- Path resolution (`shepherd_cli/resolution.py`) mirrors
  [`skills/context/scripts/_lib.sh`](../../skills/context/scripts/_lib.sh)
  precedence exactly — `SHEPHERD_WORKDIR` / `SHCTX_ROOT_OVERRIDE` /
  `.shepherd` vs `.artifacts` / `SHCTX_DB` — so the two tools never
  disagree about which file on disk is "the" database.

## The contract: `shepherd teammate ...`

```bash
shepherd teammate liveness [--stale-mins=5] [--all] [--team=<name>] [--json]
shepherd teammate status <name> [--json]
shepherd teammate state <name> [--set=<init|in-progress|error|complete|idle>]
```

`liveness` prints an aligned table —
`teammate_name  agent_type  status  declared  sec_since_seen  verdict` — or,
with `--json`, an array of `TeammateLiveness` objects
(`shepherd_cli/schemas.py`). `status` prints the latest row for one
teammate (exit 1 + stderr if none exists). `state` reads, or declares and
reads, a teammate's `declared_state`; an unrecognized `--set` value exits 2
with a `TEAMMATE-STATE-INVALID: ...` message on stderr rather than writing
anything.

## Scoping guarantee (#195)

`shepherd teammate liveness` is scoped by default, and the scoping is the
whole point of this being a Python rewrite of the read path rather than a
copy of it. Three mutually exclusive branches, in order:

1. `--all` — no team/project filter at all (bash-parity legacy: every live
   teammate, everywhere).
2. `--team=<name>` — filter to that `team_name` only, deliberately
   bypassing session scoping (how you reach a prior session's team on
   purpose).
3. **Default** — filter to the active project, then to the caller's own
   team: the `team_name` of the teammate row whose `session_id` matches
   the resolved session (`SHEPHERD_SESSION_ID` / `CLAUDE_SESSION_ID`), or,
   failing that, the most-recently-spawned team (`MAX(spawned_at)`).

That default branch is the #195 fix: a freshly spawned session no longer
sees a prior session's ghost teammates just because their rows happen to
still be `active` in the same database. `teammates_live()`
(`shepherd_cli/queries.py`) is the one place this logic lives — the Typer
command layer only renders what it returns.

## The self-heal (#200)

`db.lifespan()` runs `db.ensure_migrated(db_path)` synchronously, with
stdlib `sqlite3`, **before** `Tortoise.init()` ever opens a connection.
If the database's `schema_versions` table is behind the migrations shipped
in `skills/context/schema/migrations/` — by `MAX(version)` or by `COUNT(*)`,
either one catching a gap the other misses — it gap-fills: every migration
file whose 4-digit version is absent from `schema_versions` gets applied,
in filename order, `duplicate column` / `already exists` errors are
treated as "already applied out-of-band" and still recorded
(`INSERT OR IGNORE`). This is the CLI-side twin of `_lib.sh`'s
`shctx_ensure_migrated` / `cmd_migrate.sh`'s gap-fill loop — same
algorithm, same tolerance, different language.

It's fail-**soft** by contract: a missing migrations directory or any
write error returns the count applied so far and gets out of the way,
never raises. As a belt-and-suspenders backstop, `queries.teammates_live()`
catches a residual `no such column` `OperationalError` (self-heal itself
failed) and degrades to a pre-0019 column set with `declared_state=None`
— the same value a genuinely undeclared row carries — rather than
surfacing a raw traceback to the user. A `shepherd teammate` command
should never crash on schema drift; it should heal, or degrade, silently.

## The shctx shim

```
shepherd teammate ...   -> Typer app (this service)
shepherd <anything else> -> os.execv("bash", ["bash", <shctx>, *argv])
```

`shepherd_cli/__main__.py` checks the first argv token against a `PORTED`
set (today: just `{"teammate"}`). Anything not in that set — `shepherd
status`, `shepherd sprint`, `shepherd dash`, all of it — execs straight
into the existing bash `shctx` script, found via
`resolution.find_bash_shctx()`. `os.execv` replaces the process, so stdio
and the exit code pass through untouched; from the outside, `shepherd` is
a drop-in superset of `shctx`, not a second CLI to learn.

The phasing plan: teammates first (#198), because liveness/status/state
was the surface with the live scoping bug (#195) and the live self-heal
bug (#200) — the two bugs this port was written to fix structurally
instead of patching in bash again. Each future increment ports one more
`cmd_*.sh` verb into `PORTED` and retires that much bash, on the same
database, without a flag day.

## Running tests

```bash
bash services/cli/tests/run.sh
# equivalent:
services/cli/.venv/bin/python -m pytest
```

Deterministic, local, no network, no LLM, under 5 seconds. `conftest.py`
builds a temp database by applying `0001_init.sql` then every
`migrations/*.sql` in sorted order via stdlib `sqlite3` — the exact same
files `ensure_migrated` reads at runtime — then seeds a `projects` row and
teammates across two `team_name`/`session_id` pairs (an old "ghost" team
and a current one) so scoping has something real to prove. Tests drive the
CLI via `subprocess` against `python -m shepherd_cli teammate ...` with
`SHCTX_DB` and `CLAUDE_PLUGIN_ROOT` pointed at that database, and parse
`--json` output rather than scraping the table renderer.

`test_liveness_verdict_parity.py` is the load-bearing one: it runs the
*same* database through both `shepherd teammate liveness --json` and
`bash skills/context/scripts/cmd_teammate.sh liveness`, and asserts the
computed verdict matches per teammate. That's not a unit test of the
Python verdict logic in isolation — it's a parity gate against the bash
implementation this CLI is meant to coexist with, not replace out from
under.

## Why no LLM eval

`CLAUDE.md`'s latent/deterministic split, applied here: everything in this
service — path resolution, schema gap-fill, scoping precedence, verdict
computation — is same-input-same-output. There is no model call anywhere
in the request path, so there is nothing for an LLM-judge eval to score.
The gate test suite (`tests/run.sh`) *is* the proof: it's deterministic,
free, and the bash-parity test in particular is exactly the kind of
"prove it generalizes" check a periodic eval would otherwise exist for,
except it runs in under a second because the thing being checked is code,
not judgment. Contrast with [`services/eval`](../eval/README.md), which
exists precisely because *that* service scores latent model output — a
different kind of work, correctly living in a different service.
