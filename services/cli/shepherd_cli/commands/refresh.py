"""``shepherd refresh`` — cache-rebuild pipeline (bash: ``cmd_refresh.sh``).

Native port of ``skills/context/scripts/cmd_refresh.sh`` (v5.1.3+): a
``--scope=<zone>``/``--all`` dispatcher over five independent cache-rebuild
zones —

    symbols   -> :func:`shepherd_cli.refresh_impl.refresh_symbols`
                 (rust public-symbol index, via cargo — bash: ``refresh-symbols.sh``)
    shapes    -> the :mod:`shepherd_cli.commands.dups` module IN-PROCESS,
                 dispatched as ``scan --update --quiet`` (struct/enum field
                 shapes for ``shctx dups`` — bash: ``cmd_dups.sh scan --update --quiet``)
    github    -> :func:`shepherd_cli.refresh_impl.refresh_github`
                 (issues/PRs/releases/milestones via ``gh`` — bash: ``refresh-github.sh``)
    artifacts -> :func:`shepherd_cli.refresh_impl.refresh_artifacts`
                 (markdown specs/plans/handoffs/journal — bash: ``refresh-artifacts.sh``)
    telemetry -> cache-usage rollup, INLINE (see below)
    all       -> every zone above, each isolated (default)

``cmd_refresh.sh`` is a SUBCOMMAND-FREE, flags-only script exactly like
:mod:`shepherd_cli.commands.sync` — no ``--verbose`` flag (unlike
``cmd_sync.sh``), just ``--scope=<value>`` and its ``--all`` alias.

**CALL PATH (v6.4 native port — no bash subprocesses).** The three
``refresh-*.sh`` stage scripts were ported natively into
:mod:`shepherd_cli.refresh_impl`; this module calls those functions
directly, in-process, and maps each one's returned process-style exit code
onto its own ``typer.Exit`` — exactly the exit-code contract the former
``bash "$HERE/refresh-*.sh"`` subprocesses had, with the same
stdout/stderr lines (unredirected, matching bash's own unsuppressed
``symbols)``/``github)``/``artifacts)`` case arms). ``shapes`` similarly
invokes :func:`shepherd_cli.commands.dups._dispatch` with the exact argv
bash passed (``["scan", "--update", "--quiet"]``, whose own ``--quiet``
flag handles its internal output suppression) — a ``typer.Exit`` escaping
that in-process dispatch is converted to its ``exit_code``, mirroring a
child process's return code. Nothing in this module ever executes
``bash``; the only real subprocesses left in the pipeline are the genuine
external binaries the impl functions themselves drive (``cargo``, ``gh``,
and dups' own ``python3 dups-core.py``).

**``telemetry`` is reimplemented INLINE in this module** (it always was —
bash's own ``refresh_telemetry()`` helper does not shell out to a sibling
``cmd_*.sh`` script either; it pipes a raw ``python3 -`` heredoc into a
subshell that reads every ``<ns>/logs/events-*.jsonl`` file, filters for
``event_type == "cache_usage"``, and ``INSERT OR IGNORE``s into
``index_cache_usage`` (idempotent via its ``UNIQUE(session_id, agent_id,
ts)`` constraint — migration ``0006_cache_telemetry.sql``). Since bash's
own "external tool" here is already a bespoke Python script, the faithful,
non-reinventing port is to translate that embedded Python verbatim into a
first-class async function using this CLI's own Tortoise connection
(:func:`_insert_cache_usage_rows`). No mirror model is declared for
``index_cache_usage`` — the single ``INSERT OR IGNORE ... RETURNING id``
statement this module needs is a poor fit for a full Tortoise model (hard
rule #8), so it goes straight through ``Tortoise.get_connection("default")
.execute_query_dict(...)`` inside ``db.lifespan()``, exactly like
``commands/audit.py``'s ``insert`` subverb and ``commands/lock.py``'s
``locks_history`` writes.

**Timestamps.** ``index_cache_usage.ts`` is epoch-SECONDS (the column
comment in ``0006_cache_telemetry.sql`` says so explicitly: ``-- unix
seconds (epoch)``) — :func:`_coerce_ts` mirrors bash's own ISO-string ->
epoch-seconds coercion (``datetime.fromisoformat`` after stripping a
trailing ``Z`` and, on a second failure, any fractional-seconds suffix)
exactly, including its numeric-passthrough branch (``isinstance(ts, (int,
float))`` -> ``int(ts)``) and its everything-else-is-skipped branch.

**Fail-open semantics, reproduced exactly.** Bash's heredoc wraps almost
nothing in a top-level ``try`` — the per-FILE ``OSError`` guard, the
per-LINE JSON-parse guard, and the per-ROW ``sqlite3.Error`` guard are each
individually caught and skipped, but the python3 invocation AS A WHOLE is
captured via ``inserted=$(python3 - ... <<'PY' 2>/dev/null) || inserted="?"``
— any uncaught failure (e.g. the initial ``sqlite3.connect()`` call itself
raising) degrades the printed count to the literal string ``"?"`` rather
than aborting the command. :func:`_insert_cache_usage_rows` reproduces both
layers: fine-grained ``try/except`` around each file/line/row, wrapped in
one broad ``except Exception`` that returns the ``"?"`` sentinel instead of
propagating.

**Project-id resolution is ``shctx_project_id()``, NOT the ``projects``
table.** ``refresh_telemetry()`` calls
``project_id=$(shctx_project_id) || return 1`` — ``_lib.sh``'s
``shctx_project_id`` reads ``<workdir>/project.json`` (``jq -r '.id'``),
printing ``"ERROR: <path> missing — run 'shctx init' first"`` to stderr and
returning non-zero when the file is absent. :func:`_telemetry_project_id`
mirrors this (self-contained per hard rule #9, duplicated from the nearly
identical helpers in ``commands/query.py``/``commands/dups.py``/
``commands/search.py``/``commands/handoff.py``/``commands/sprint.py`` and
:mod:`shepherd_cli.refresh_impl`'s ``_project_id``): missing file -> the
exact bash stderr message, returns ``None``; malformed JSON -> an
equivalent (not byte-identical — jq's own parse-error text is not
reproduced) message, returns ``None``; present-but-JSON-``null`` ``"id"``
-> the literal string ``"null"`` (jq -r's raw-output rendering of JSON
``null``), matching every other such helper in this codebase.

**``--scope=all`` ALWAYS exits 0, regardless of any zone's failure.** Bash:

    all)
      bash "$HERE/refresh-symbols.sh"   || echo "shctx: symbols refresh failed (continuing)"   >&2
      refresh_shapes                    || echo "shctx: shapes refresh failed (continuing)"     >&2
      bash "$HERE/refresh-github.sh"    || echo "shctx: github refresh failed (continuing)"    >&2
      bash "$HERE/refresh-artifacts.sh" || echo "shctx: artifacts refresh failed (continuing)" >&2
      refresh_telemetry                 || echo "shctx: telemetry refresh failed (continuing)" >&2
      ;;

Every stage is guarded by its own ``|| echo ... >&2`` — under ``set -e``,
a failing LEFT side of ``||`` is caught by the RIGHT side (the ``echo``),
whose own exit status (0) becomes that line's status, so the script never
aborts early and its FINAL exit status (the last command run) is always 0.
:func:`_run_all_scopes` reproduces this: every one of the five stages
always runs, in the same fixed order, with a stderr
``"shctx: <name> refresh failed (continuing)"`` line on any non-zero
result, and the top-level dispatcher always raises ``typer.Exit(code=0)``
after it returns — no stage's exit code is ever allowed to become the
overall exit code for ``--scope=all``.

**A single-scope run (``symbols``/``shapes``/``github``/``artifacts``)
propagates that ONE stage's exit code verbatim.** Bash: e.g.
``symbols) bash "$HERE/refresh-symbols.sh" ;;`` is NOT guarded by
``|| echo ...`` — under ``set -e``, a non-zero exit from that one command
(the last command the script runs for that scope) IS the script's own
final exit code. :func:`_refresh_impl` mirrors this: each single-scope
branch calls ``raise typer.Exit(code=rc)`` with the stage function's own
returned code, unmodified. ``shapes``'s extra nuance: bash's
``refresh_shapes()`` helper only prints ``"shctx refresh shapes: ok"``
AFTER ``bash "$HERE/cmd_dups.sh" scan --update --quiet`` succeeds — a
failing scan aborts ``refresh_shapes()`` (and thus the whole script, via
``set -e``) BEFORE that echo ever runs, so :func:`_run_shapes` only echoes
``"ok"`` on a zero return code, matching exactly.

**Unknown ``--scope=<value>``** (bash: the case statement's catch-all
``*) echo "ERROR: unknown --scope: $scope" >&2; exit 1 ;;``) and unknown
argument tokens (bash: the arg-parsing loop's own catch-all,
``"ERROR: unknown arg: $arg"``, exit 1) are two textually DIFFERENT error
paths, exactly as in bash — ``--scope=bogus`` parses fine (any string is
accepted by the ``--scope=*`` case arm) and only fails later, at
dispatch, with the ``unknown --scope`` message; a genuinely unrecognized
TOKEN (e.g. ``--bogus``, a bare positional) fails immediately, at parse
time, with the ``unknown arg`` message.
"""

from __future__ import annotations

import asyncio
import datetime
import glob
import json
import os
from collections.abc import Callable

import typer
from tortoise import Tortoise

from shepherd_cli import db, refresh_impl
from shepherd_cli.commands import dups as dups_cmd
from shepherd_cli.resolution import resolve_db_path, resolve_workdir

app = typer.Typer(
    no_args_is_help=False,
    add_completion=False,
    # help_option_names=[] disables Click's own --help so -h/--help reach the
    # callback's own token loop and print the verbatim bash usage text
    # (parity) — matching commands/sync.py / audit.py / search.py / models.py.
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True, "help_option_names": []},
    help="Cache-rebuild pipeline: symbols/shapes/github/artifacts/telemetry, --scope=/--all.",
)

#: Verbatim bash-parity usage text — the ``-h|--help`` heredoc in
#: ``cmd_refresh.sh``. Printed to stdout (bash parity: plain ``cat``, not
#: stderr) on ``-h``/``--help``, exit 0.
_HELP_TEXT = (
    "shctx refresh [--scope=symbols|shapes|github|artifacts|telemetry|all] [--all]\n"
    "\n"
    "  --scope=NAME  refresh a single zone\n"
    "                  symbols   — index public symbols from the workspace\n"
    "                  shapes    — index public struct/enum FIELD SHAPES for `dups` (v6.1.8 #157)\n"
    "                  github    — issues / PRs / releases / milestones via gh\n"
    "                  artifacts — markdown specs / plans / handoffs / journal\n"
    "                  telemetry — cache-usage events from <ns>/logs/events-*.jsonl (v5.1.3+)\n"
    "                  all       — every zone above (default)\n"
    "  --all         alias for --scope=all (canonical universal flag, v5.0.4)"
)


# --------------------------------------------------------------------------
# Argument parsing (bash-parity port of cmd_refresh.sh's ``for arg in "$@"``
# loop).
# --------------------------------------------------------------------------
def _parse_args(argv: list[str]) -> str:
    """Parse ``shctx refresh``'s arguments, mirroring ``cmd_refresh.sh`` line for line.

    Bash::

        scope="all"
        for arg in "$@"; do
          case "$arg" in
            --scope=*) scope="${arg#--scope=}" ;;
            --all)     scope="all" ;;
            -h|--help)
              cat <<'EOF' ... EOF
              exit 0 ;;
            *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
          esac
        done

    Every token is visited in order; the LAST ``--scope=<value>``/
    ``--all`` given wins (plain variable reassignment, matching bash
    exactly). ``-h``/``--help`` and an unrecognized token both
    short-circuit immediately, from ANY position in ``argv``. Unlike
    ``cmd_sync.sh``, there is no ``--verbose``/``-v`` flag here at all —
    an unadorned ``-v`` falls straight through to the catch-all
    ``"ERROR: unknown arg: -v"`` branch.

    Args:
        argv: Every token given to ``shepherd refresh`` after the command
            name itself, in order.

    Returns:
        The resolved ``scope`` string — ``"all"`` by default (bash: the
        ``for`` loop simply never executes on empty ``argv``), NOT
        validated against the known zone set here (that happens at
        dispatch time in :func:`_refresh_impl`, matching bash's own
        case-statement catch-all being a SEPARATE arm from the arg-loop's
        catch-all).

    Raises:
        typer.Exit: code 0, after printing :data:`_HELP_TEXT` to stdout,
            the instant an ``-h``/``--help`` token is reached. Code 1,
            after printing ``"ERROR: unknown arg: <token>"`` to stderr,
            the instant a token matching none of the recognized shapes is
            reached.
    """
    scope = "all"
    for arg in argv:
        if arg.startswith("--scope="):
            scope = arg[len("--scope=") :]
        elif arg == "--all":
            scope = "all"
        elif arg in ("-h", "--help"):
            typer.echo(_HELP_TEXT)
            raise typer.Exit(code=0)
        else:
            typer.echo(f"ERROR: unknown arg: {arg}", err=True)
            raise typer.Exit(code=1)
    return scope


# --------------------------------------------------------------------------
# shapes — in-process dispatch into the dups module (bash: the
# refresh_shapes() helper shelling to ``cmd_dups.sh scan --update --quiet``).
# --------------------------------------------------------------------------
def _run_shapes() -> int:
    """Run the ``shapes`` zone, mirroring bash's ``refresh_shapes()`` helper.

    Bash::

        refresh_shapes() {
          bash "$HERE/cmd_dups.sh" scan --update --quiet
          echo "shctx refresh shapes: ok"
        }

    The scan itself is now the :mod:`shepherd_cli.commands.dups` module,
    invoked IN-PROCESS via its own bash-parity dispatcher with the exact
    argv bash passed (``scan --update --quiet``) — no ``bash`` subprocess.
    A ``typer.Exit`` escaping that dispatch (e.g. dups' own tooling-lookup
    failure) is converted to its ``exit_code``, exactly like a child
    process's return code was before.

    ``"shctx refresh shapes: ok"`` is printed ONLY on success — under
    ``set -e``, a non-zero scan aborted the (bash) function before its own
    ``echo`` ever ran, so this port checks the return code FIRST and only
    echoes ``"ok"`` on success, exactly matching that ordering.

    Returns:
        0 with ``"shctx refresh shapes: ok"`` printed to stdout, if the
        scan succeeded; otherwise the scan's own non-zero exit code, with
        nothing additional printed.
    """
    try:
        rc = dups_cmd._dispatch(["scan", "--update", "--quiet"])
    except typer.Exit as exc:
        rc = exc.exit_code
    if rc != 0:
        return rc
    typer.echo("shctx refresh shapes: ok")
    return 0


# --------------------------------------------------------------------------
# telemetry zone — reimplemented natively (see module docstring).
# --------------------------------------------------------------------------
def _telemetry_project_id() -> str | None:
    """Resolve the active project id, bash-parity with ``_lib.sh``'s ``shctx_project_id``.

    Duplicated (per hard rule #9's self-contained-module requirement) from
    the near-identical helpers in ``commands/query.py``/``commands/dups.py``/
    ``commands/search.py``/``commands/handoff.py``/``commands/sprint.py`` —
    all read the SAME ``<workdir>/project.json`` file via the same
    ``_lib.sh`` helper, but this call site additionally needs the
    "missing -> print bash's exact error, signal failure to the caller"
    shape ``shctx_project_id() ... || return 1`` has, rather than those
    other modules' "collapse every failure to `\"\"`/`\"null\"`" shape —
    so it is its own function, not a copy of theirs.

    Returns:
        The resolved project id string — the literal ``"null"`` when
        ``project.json``'s ``"id"`` key is present-but-JSON-``null`` (jq
        -r's raw-output rendering of JSON ``null``, not an error) — or
        None on any failure (``project.json`` missing or unparseable),
        after printing a bash-parity error message to stderr.
    """
    path = os.path.join(resolve_workdir(), "project.json")
    if not os.path.isfile(path):
        typer.echo(f"ERROR: {path} missing — run 'shctx init' first", err=True)
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        typer.echo(f"ERROR: failed to parse {path} as JSON", err=True)
        return None
    if not isinstance(data, dict) or data.get("id") is None:
        return "null"
    value = data["id"]
    return value if isinstance(value, str) else json.dumps(value)


def _coerce_ts(ts: object) -> int | None:
    """Coerce one event's ``ts`` field to epoch SECONDS, bash-parity with the python3 heredoc.

    Bash (the embedded python3 script)::

        ts = ev.get("ts")
        if isinstance(ts, str):
            s = ts.rstrip("Z")
            try:
                try:
                    dt = _dt.datetime.fromisoformat(s)
                except ValueError:
                    if "." in s:
                        s = s.split(".", 1)[0]
                    dt = _dt.datetime.fromisoformat(s)
                ts_int = int(dt.replace(tzinfo=_dt.timezone.utc).timestamp())
            except Exception:
                continue
        elif isinstance(ts, (int, float)):
            ts_int = int(ts)
        else:
            continue

    Args:
        ts: The raw ``ev.get("ts")`` value from one parsed JSONL event —
            any JSON type.

    Returns:
        The epoch-SECONDS integer, treating an ISO-8601 string (a
        trailing ``Z`` is stripped first; a fractional-seconds suffix is
        additionally stripped on a first ``fromisoformat`` failure) as
        UTC, or passing an already-numeric ``ts`` straight through via
        ``int()``. None if ``ts`` is neither a string nor a number, or if
        every parse attempt raises.
    """
    if isinstance(ts, str):
        s = ts.rstrip("Z")
        try:
            try:
                dt = datetime.datetime.fromisoformat(s)
            except ValueError:
                if "." in s:
                    s = s.split(".", 1)[0]
                dt = datetime.datetime.fromisoformat(s)
            return int(dt.replace(tzinfo=datetime.timezone.utc).timestamp())
        except Exception:
            return None
    if isinstance(ts, (int, float)):
        return int(ts)
    return None


#: Column list for the ``index_cache_usage`` INSERT — bash-parity order
#: with the python3 heredoc's own ``INSERT INTO index_cache_usage (...)``
#: statement (migration 0006_cache_telemetry.sql's column order).
_CACHE_USAGE_COLUMNS = (
    "project_id",
    "ts",
    "session_id",
    "role",
    "agent_id",
    "sprint",
    "turns",
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
    "ephemeral_5m_input_tokens",
    "ephemeral_1h_input_tokens",
    "hit_rate",
    "parse_error",
)

_CACHE_USAGE_INSERT_SQL = (
    f"INSERT OR IGNORE INTO index_cache_usage ({', '.join(_CACHE_USAGE_COLUMNS)}) "
    f"VALUES ({', '.join('?' for _ in _CACHE_USAGE_COLUMNS)}) RETURNING id"
)


def _event_values(project_id: str, ts_int: int, ev: dict[str, object]) -> list[object]:
    """Build the bind-parameter list for one ``index_cache_usage`` row.

    Bash-parity with the python3 heredoc's ``cur.execute(...)`` call:
    every column beyond ``project_id``/``ts`` is read straight off the
    parsed event dict via ``.get(...)`` (None when absent — sqlite stores
    that as SQL ``NULL``), EXCEPT ``role``, which falls back to the
    literal string ``"unknown"`` when absent/empty/``None``
    (``ev.get("role") or "unknown"``).

    Args:
        project_id: The resolved host project id.
        ts_int: The coerced epoch-seconds timestamp (:func:`_coerce_ts`).
        ev: The parsed JSON event dict for one JSONL line.

    Returns:
        Bind values in the exact column order of
        :data:`_CACHE_USAGE_COLUMNS`.
    """
    return [
        project_id,
        ts_int,
        ev.get("session_id"),
        ev.get("role") or "unknown",
        ev.get("agent_id"),
        ev.get("sprint"),
        ev.get("turns"),
        ev.get("input_tokens"),
        ev.get("output_tokens"),
        ev.get("cache_read_input_tokens"),
        ev.get("cache_creation_input_tokens"),
        ev.get("ephemeral_5m_input_tokens"),
        ev.get("ephemeral_1h_input_tokens"),
        ev.get("hit_rate"),
        ev.get("parse_error"),
    ]


async def _insert_cache_usage_rows(project_id: str, logs_dir: str, db_path: str) -> str:
    """Insert every ``cache_usage`` event found under ``logs_dir`` into ``index_cache_usage``.

    Bash-parity with the python3 heredoc's full body (see the module
    docstring's "fail-open semantics" section): every
    ``<logs_dir>/events-*.jsonl`` file is visited in SORTED order; per
    FILE, an ``OSError`` opening it skips that file and continues with
    the next; per LINE, a JSON-parse failure, a non-dict top level, or an
    ``event_type`` other than ``"cache_usage"`` skips that line; per ROW,
    any exception from the ``INSERT`` (constraint violation, type
    mismatch, etc.) skips that row. The ``INSERT OR IGNORE ... RETURNING
    id`` pattern replaces bash's ``cur.rowcount > 0`` check — sqlite's
    ``RETURNING`` clause simply produces no row when ``OR IGNORE``
    silently skipped an insert (a duplicate ``(session_id, agent_id,
    ts)``), so an empty result set is the "not counted" signal, exactly
    like ``cur.rowcount == 0`` was in bash.

    The ENTIRE body runs inside one broad ``try/except Exception`` — bash
    parity with ``inserted=$(python3 ... <<'PY' 2>/dev/null) || inserted="?"``:
    any failure NOT already caught by the finer-grained guards above
    (most notably ``Tortoise.init`` itself failing inside
    ``db.lifespan()``) degrades to the literal string ``"?"`` rather than
    propagating — :func:`_refresh_telemetry_async` always prints a
    row-count line either way, never raises past this function.

    Args:
        project_id: The resolved host project id (every inserted row's
            ``project_id`` column).
        logs_dir: The directory to glob ``events-*.jsonl`` files from
            (already confirmed to exist by the caller).
        db_path: The resolved sqlite database path.

    Returns:
        The decimal string count of rows actually inserted (never
        counting an ``OR IGNORE``-skipped duplicate), or the literal
        string ``"?"`` if the whole operation failed before that count
        could be determined.
    """
    try:
        inserted = 0
        async with db.lifespan(db_path):
            connection = Tortoise.get_connection("default")
            for path in sorted(glob.glob(os.path.join(logs_dir, "events-*.jsonl"))):
                try:
                    with open(path, encoding="utf-8", errors="replace") as fh:
                        lines = fh.readlines()
                except OSError:
                    continue
                for raw_line in lines:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(ev, dict):
                        continue
                    if ev.get("event_type") != "cache_usage":
                        continue
                    ts_int = _coerce_ts(ev.get("ts"))
                    if ts_int is None:
                        continue
                    try:
                        rows = await connection.execute_query_dict(
                            _CACHE_USAGE_INSERT_SQL, _event_values(project_id, ts_int, ev)
                        )
                    except Exception:
                        continue
                    if rows:
                        inserted += 1
        return str(inserted)
    except Exception:
        return "?"


async def _refresh_telemetry_async() -> int:
    """Run the ``telemetry`` zone end-to-end, mirroring bash's ``refresh_telemetry()``.

    Bash::

        refresh_telemetry() {
          project_id=$(shctx_project_id) || return 1
          ns=$(shctx_artifacts_root)
          logs_dir="$ns/logs"
          db=$(shctx_db_path)
          if [[ ! -d "$logs_dir" ]]; then
            echo "shctx refresh telemetry: no log dir at $logs_dir (skipping)"
            return 0
          fi
          inserted=$(python3 - ... <<'PY' 2>/dev/null) || inserted="?"
          echo "shctx refresh telemetry: $inserted new row(s)"
        }

    Returns:
        1 if :func:`_telemetry_project_id` failed (its own bash-parity
        error message already printed to stderr) — nothing further is
        printed, matching bash's ``|| return 1`` short-circuit. Otherwise
        0, having printed either the "no log dir" skip line or the final
        "N new row(s)" summary line (N possibly the literal ``"?"``).
    """
    project_id = _telemetry_project_id()
    if project_id is None:
        return 1

    logs_dir = f"{resolve_workdir()}/logs"
    if not os.path.isdir(logs_dir):
        typer.echo(f"shctx refresh telemetry: no log dir at {logs_dir} (skipping)")
        return 0

    db_path = resolve_db_path()
    inserted = await _insert_cache_usage_rows(project_id, logs_dir, db_path)
    typer.echo(f"shctx refresh telemetry: {inserted} new row(s)")
    return 0


def _run_telemetry() -> int:
    """Synchronous entry point for the ``telemetry`` zone (wraps :func:`_refresh_telemetry_async`)."""
    return asyncio.run(_refresh_telemetry_async())


# --------------------------------------------------------------------------
# --scope=all fan-out.
# --------------------------------------------------------------------------
def _run_all_scopes() -> None:
    """Run every zone in bash's fixed order, isolating each one's failure (see module docstring).

    Every one of the five zones always runs, regardless of any earlier
    zone's result — a non-zero result prints
    ``"shctx: <name> refresh failed (continuing)"`` to stderr and moves
    on. An exception escaping a zone (including a ``typer.Exit`` from the
    in-process ``shapes`` dispatch's own internals) is treated as that
    zone failing, exactly like a crashing child process was before the
    native port.
    """

    def run_or_warn(label: str, fn: Callable[[], int]) -> None:
        try:
            rc = fn()
        except typer.Exit as exc:
            rc = exc.exit_code
        except Exception:
            rc = 1
        if rc != 0:
            typer.echo(f"shctx: {label} refresh failed (continuing)", err=True)

    run_or_warn("symbols", refresh_impl.refresh_symbols)
    run_or_warn("shapes", _run_shapes)
    run_or_warn("github", refresh_impl.refresh_github)
    run_or_warn("artifacts", refresh_impl.refresh_artifacts)
    run_or_warn("telemetry", _run_telemetry)


# --------------------------------------------------------------------------
# Top-level dispatch (bash-parity port of cmd_refresh.sh's ``case "$scope"
# in ... esac``).
# --------------------------------------------------------------------------
def _refresh_impl(scope: str) -> None:
    """Dispatch on the resolved ``scope``, mirroring ``cmd_refresh.sh``'s ``case`` statement.

    Args:
        scope: The resolved ``--scope`` value from :func:`_parse_args`
            (``"all"`` by default).

    Raises:
        typer.Exit: code equal to the one dispatched stage's own exit
            code, for ``symbols``/``shapes``/``github``/``artifacts``/
            ``telemetry``; always code 0 for ``"all"``; code 1, with
            ``"ERROR: unknown --scope: <scope>"`` on stderr, for anything
            else.
    """
    if scope == "symbols":
        raise typer.Exit(code=refresh_impl.refresh_symbols())
    if scope == "shapes":
        raise typer.Exit(code=_run_shapes())
    if scope == "github":
        raise typer.Exit(code=refresh_impl.refresh_github())
    if scope == "artifacts":
        raise typer.Exit(code=refresh_impl.refresh_artifacts())
    if scope == "telemetry":
        raise typer.Exit(code=_run_telemetry())
    if scope == "all":
        _run_all_scopes()
        raise typer.Exit(code=0)
    typer.echo(f"ERROR: unknown --scope: {scope}", err=True)
    raise typer.Exit(code=1)


@app.callback(invoke_without_command=True)
def refresh(
    args: list[str] = typer.Argument(
        None,
        metavar="[--scope=<symbols|shapes|github|artifacts|telemetry|all>] [--all] [-h|--help]",
        hidden=True,
        help=(
            "Flags only, no positional arguments — see cmd_refresh.sh's usage "
            "text (-h/--help)."
        ),
    ),
) -> None:
    """Cache-rebuild pipeline: symbols/shapes/github/artifacts/telemetry, ``--scope=``/``--all``.

    Native port of ``shctx refresh`` (``cmd_refresh.sh``). Takes no
    subcommands — only the flags documented in :data:`_HELP_TEXT` —
    captured together as one variadic argument (mirroring
    :mod:`shepherd_cli.commands.sync`'s ``context_settings`` pattern) and
    parsed bash-verbatim by :func:`_parse_args`.

    Args:
        args: Every token given after ``refresh`` on the command line, or
            None/empty for a bare ``shepherd refresh`` (bash parity: runs
            the full ``--scope=all`` pipeline, not a usage screen).

    Raises:
        typer.Exit: See :func:`_refresh_impl` for the full matrix of exit
            codes; code 0 with the usage text if ``-h``/``--help`` was
            given (see :func:`_parse_args`); code 1 if an argument token
            was unrecognized (also :func:`_parse_args`).
    """
    argv = list(args) if args else []
    scope = _parse_args(argv)
    _refresh_impl(scope)


__all__ = ["app"]
