"""``shepherd sprint`` — sprint-cycle pipeline Typer sub-app.

Native port of ``skills/context/scripts/cmd_sprint.sh`` (v5.0.4): three
ORCHESTRATION pipelines that stage other ``shctx`` subcommands together,
not a CRUD surface of its own.

* ``open <branch>``  kickoff:   lock acquire -> refresh --all -> lint -> status
* ``wave <wave-id>``  wave-gate: refresh --scope=github,artifacts -> lint
  (``--all`` forwards ``--scope=all`` to refresh instead)
* ``close <branch>``  finale:    close-lane (each known lane) -> handoff ->
  worktree gc -> lock release

Every stage but the lane-closure loop in ``close`` is a bash sibling script
this module SHELLS OUT to (``cmd_lock.sh``, ``cmd_refresh.sh``,
``cmd_lint.sh``, ``cmd_status.sh``, ``cmd_handoff.sh``, ``cmd_worktree.sh``,
``cmd_close-lane.sh``) — none of those subcommands are ported to this
Python CLI yet, and ``cmd_sprint.sh`` itself only ever coordinates them via
``bash "$HERE/cmd_*.sh" ...`` subprocess calls, never by inlining their
logic. This port mirrors that architecture exactly: it locates the sibling
scripts via :func:`shepherd_cli.resolution.find_bash_shctx` (same
directory as the ``shctx`` dispatcher) and runs them the same way bash's
own ``run_stage`` helper does — output suppressed by default, or
inherited/streamed when ``--verbose``/``-v`` is given.

The ONE piece of this pipeline that touches the database directly is
``close``'s first stage: finding every ``lane_closures`` row tied to the
closing sprint branch that still needs ``cmd_close-lane.sh`` invoked on it
(see :mod:`shepherd_cli.models_sprint`). That query — and the
``sqlite_master`` introspection bash uses to defend against an unmigrated
DB — is the only part of this module that opens a Tortoise connection;
``open`` and ``wave`` never touch the database at all, so they need no
``db.lifespan()`` wrapper (hard rule #7: a command with no DB access needs
no lifespan).

Known parity gap (matches the existing ``deliverable``/``signal`` ports):
``cmd_sprint.sh``'s ``*) echo "ERROR: unknown subcommand: $sub" >&2; usage
>&2; exit 1 ;;`` branch is not reproduced verbatim — Typer/Click's own
"No such command" error fires instead, with its own message and exit code
2 (not bash's 1). Overriding this would require subclassing Typer's
internal (undocumented, unstable) Click fork; the rest of this porting
wave (``deliverable.py``, ``signal.py``) accepted the same gap rather than
depend on that private API, and this module follows the same precedent.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time

import typer
from tortoise import Tortoise

from shepherd_cli import db
from shepherd_cli.models_sprint import LaneClosure
from shepherd_cli.resolution import find_bash_shctx, resolve_workdir

app = typer.Typer(
    no_args_is_help=False,
    add_completion=False,
    help="Sprint-cycle pipelines: open (kickoff), wave (wave-gate), close (finale).",
)

#: Verbatim bash-parity usage text — ``usage()`` in ``cmd_sprint.sh``.
#: Printed to stdout on a bare ``shepherd sprint`` invocation or the
#: literal ``help`` subcommand (both exit 0, matching bash's
#: ``""|-h|--help|help) usage ;;`` case branch).
_USAGE = (
    "shctx sprint <open|wave|close> [args]\n"
    "\n"
    "  open <branch>           kickoff: lock acquire → refresh --all → lint → status\n"
    "  wave <wave-id> [--all]  wave-gate: refresh --scope=github,artifacts → lint\n"
    "                          --all forwards --scope=all to refresh\n"
    "  close <branch>          finale: close-lane (each) → handoff → worktree gc → lock release\n"
    "\n"
    "All pipelines emit a per-stage summary; --verbose forwards stage output."
)

_PROJECT_JSON_FILENAME = "project.json"


@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context) -> None:
    """Print usage and exit 0 when no subcommand is given (bash parity).

    ``cmd_sprint.sh``'s ``""|-h|--help|help) usage ;;`` branch prints the
    usage text to stdout and exits 0 (the case statement's implicit
    fallthrough — ``usage`` is a plain ``cat`` heredoc, always rc 0).
    Typer's ``no_args_is_help`` would exit 2 instead (Click treats a
    missing command as a usage error), so this callback restores the
    exact bash no-subcommand contract. The literal ``help`` subcommand is
    handled by the separate :func:`help_` command below, for the same
    bash branch reached a different way.

    Args:
        ctx: The Typer/Click context; ``invoked_subcommand`` is None only
            when ``shepherd sprint`` is run with no subcommand at all.

    Raises:
        typer.Exit: code 0, after printing usage, when no subcommand was
            given.
    """
    if ctx.invoked_subcommand is None:
        typer.echo(_USAGE)
        raise typer.Exit(code=0)


@app.command(name="help")
def help_() -> None:
    """Print usage and exit 0 (bash parity: the literal ``help`` subcommand).

    ``cmd_sprint.sh``'s ``""|-h|--help|help) usage ;;`` branch treats a
    bare invocation, ``-h``, ``--help``, and the literal word ``help`` as
    the same case. Typer/Click intercepts ``-h``/``--help`` itself before
    any command body runs (its own auto-generated help text, still exit
    0), so only the literal ``help`` subcommand needed an explicit command
    here to reach this exact bash-parity usage text.
    """
    typer.echo(_USAGE)


def _scripts_dir() -> str:
    """Resolve the directory containing the sibling ``cmd_*.sh`` scripts.

    Mirrors ``cmd_sprint.sh``'s own ``HERE="$(cd "$(dirname "$0")" && pwd)"``
    — the directory holding ``cmd_sprint.sh`` itself is the same directory
    that holds ``cmd_lock.sh``, ``cmd_refresh.sh``, ``cmd_lint.sh``,
    ``cmd_status.sh``, ``cmd_handoff.sh``, ``cmd_worktree.sh``, and
    ``cmd_close-lane.sh``. This CLI locates it via
    :func:`shepherd_cli.resolution.find_bash_shctx` (the ``shctx``
    dispatcher lives in that same ``scripts/`` directory) rather than
    hard-coding a path, so it resolves the same way under
    ``CLAUDE_PLUGIN_ROOT`` or a plain repo checkout.

    Returns:
        The absolute path to ``skills/context/scripts``.

    Raises:
        typer.Exit: code 1, with a stderr message, if the bash ``shctx``
            tooling cannot be located at all — every stage of every sprint
            pipeline shells out to it, so there is nothing useful this
            command can do without it.
    """
    shctx_path = find_bash_shctx()
    if shctx_path is None:
        typer.echo("ERROR: bash shctx tooling not found (skills/context/scripts/)", err=True)
        raise typer.Exit(code=1)
    return os.path.dirname(shctx_path)


def _now_s() -> int:
    """Return the current wall-clock time in epoch SECONDS.

    Bash parity with ``_lib.sh``'s ``shctx_now() { date +%s; }`` — the
    unit ``cmd_sprint.sh`` uses for its ``elapsed=$(( $(shctx_now) - t0
    ))`` timing, NOT the epoch-milliseconds unit
    ``deliverables``/``session_signals``/``teammates`` use.

    Returns:
        The current time as whole seconds since the Unix epoch.
    """
    return int(time.time())


def _run_stage(name: str, argv: list[str], verbose: bool) -> int:
    """Run one pipeline stage, mirroring ``cmd_sprint.sh``'s ``run_stage()`` helper.

    Bash::

        run_stage() {
          local name="$1"; shift
          if (( verbose )); then echo "─── $name ───"; "$@"
          else "$@" >/dev/null 2>&1 || return $?
          fi
        }

    Args:
        name: Human label for the stage header, printed only when
            ``verbose`` (bash: the ``echo "─── $name ───"`` line).
        argv: The full argv to execute, e.g.
            ``["bash", "<scripts>/cmd_lock.sh", "acquire", "--mode=sprint"]``.
        verbose: When True, print the stage header and let the child
            process inherit this process's stdout/stderr (bash: run
            ``"$@"`` directly, unredirected). When False, discard the
            child's stdout AND stderr entirely (bash: ``"$@" >/dev/null
            2>&1``) — only the exit code is observed either way.

    Returns:
        The child process's exit code (0 on success), exactly as bash's
        ``run_stage`` return value — the underlying command's exit status
        is preserved regardless of whether its output was captured or
        suppressed.
    """
    if verbose:
        typer.echo(f"─── {name} ───")
        result = subprocess.run(argv, check=False)
    else:
        result = subprocess.run(argv, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode


# --------------------------------------------------------------------------
# open
# --------------------------------------------------------------------------


def _open_impl(branch: str, verbose: bool) -> None:
    """Run the ``open`` pipeline and print its bash-parity summary.

    Bash: lock acquire (``--mode=sprint``) -> refresh ``--scope=all`` ->
    lint -> status, each independent (a later stage always runs even if an
    earlier one failed — bash captures each ``rc_*`` separately rather
    than short-circuiting on the first failure).

    Args:
        branch: The sprint branch being kicked off (``<branch>``
            positional; already validated non-empty by the caller).
        verbose: Forward each stage's own stdout/stderr instead of
            discarding it, with a ``─── <stage> ───`` header per stage.

    Raises:
        typer.Exit: code 0 if every stage succeeded, else code 1 — bash
            parity with ``(( rc_lock == 0 && rc_refresh == 0 && rc_lint ==
            0 && rc_status == 0 ))`` as the case branch's (and therefore
            the whole script's) final exit status.
    """
    scripts_dir = _scripts_dir()
    t0 = _now_s()

    rc_lock = _run_stage(
        "lock acquire",
        ["bash", os.path.join(scripts_dir, "cmd_lock.sh"), "acquire", "--mode=sprint"],
        verbose,
    )
    rc_refresh = _run_stage(
        "refresh --all",
        ["bash", os.path.join(scripts_dir, "cmd_refresh.sh"), "--scope=all"],
        verbose,
    )
    rc_lint = _run_stage("lint", ["bash", os.path.join(scripts_dir, "cmd_lint.sh")], verbose)
    rc_status = _run_stage("status", ["bash", os.path.join(scripts_dir, "cmd_status.sh")], verbose)

    elapsed = _now_s() - t0
    typer.echo(f"shctx sprint open {branch}: elapsed={elapsed}s")
    typer.echo(f"  lock:    {'acquired' if rc_lock == 0 else f'fail (rc={rc_lock})'}")
    typer.echo(f"  refresh: {'ok' if rc_refresh == 0 else f'fail (rc={rc_refresh})'}")
    typer.echo(f"  lint:    {'ok' if rc_lint == 0 else f'fail (rc={rc_lint})'}")
    typer.echo(f"  status:  {'ok' if rc_status == 0 else f'fail (rc={rc_status})'}")

    all_ok = rc_lock == 0 and rc_refresh == 0 and rc_lint == 0 and rc_status == 0
    raise typer.Exit(code=0 if all_ok else 1)


@app.command(name="open")
def open_(
    branch: str | None = typer.Argument(
        None,
        metavar="BRANCH",
        help="The sprint branch being kicked off.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Forward each stage's own stdout/stderr instead of discarding it.",
    ),
) -> None:
    """Sprint kickoff: lock acquire -> refresh --all -> lint -> status.

    Args:
        branch: The sprint branch (required; validated manually rather
            than via Typer's ``required=True`` so a missing/empty value
            reproduces bash's exact
            ``"ERROR: usage: shctx sprint open <branch>"`` message and
            exit code 1, instead of Click's own missing-argument error).
        verbose: Stream each stage's own output instead of discarding it.

    Raises:
        typer.Exit: code 1 (stderr message) if ``branch`` is missing or
            empty.
    """
    if not branch:
        typer.echo("ERROR: usage: shctx sprint open <branch>", err=True)
        raise typer.Exit(code=1)
    _open_impl(branch, verbose)


# --------------------------------------------------------------------------
# wave
# --------------------------------------------------------------------------


def _wave_impl(wave_id: str, all_scope: bool, verbose: bool) -> None:
    """Run the ``wave`` pipeline and print its bash-parity summary.

    Bash: with ``--all``, a single ``refresh --scope=all`` stage
    (``rc_a`` stays 0, untouched); otherwise two independent refresh
    stages, ``--scope=github`` then ``--scope=artifacts``, followed by
    lint either way.

    Args:
        wave_id: The wave identifier (``<wave-id>`` positional; already
            validated non-empty by the caller).
        all_scope: When True, forward ``--scope=all`` to refresh as one
            stage instead of the default ``github``/``artifacts`` pair.
        verbose: Forward each stage's own stdout/stderr instead of
            discarding it.

    Raises:
        typer.Exit: code 0 if every stage succeeded, else code 1 — bash
            parity with ``(( rc_g == 0 && rc_a == 0 && rc_lint == 0 ))``.
    """
    scripts_dir = _scripts_dir()
    refresh_script = os.path.join(scripts_dir, "cmd_refresh.sh")
    t0 = _now_s()

    rc_g = 0
    rc_a = 0
    if all_scope:
        scope = "all"
        rc_g = _run_stage("refresh --all", ["bash", refresh_script, "--scope=all"], verbose)
    else:
        scope = "github,artifacts"
        rc_g = _run_stage("refresh github", ["bash", refresh_script, "--scope=github"], verbose)
        rc_a = _run_stage("refresh artifacts", ["bash", refresh_script, "--scope=artifacts"], verbose)

    rc_lint = _run_stage("lint", ["bash", os.path.join(scripts_dir, "cmd_lint.sh")], verbose)

    elapsed = _now_s() - t0
    typer.echo(f"shctx sprint wave {wave_id}: scope={scope} elapsed={elapsed}s")
    if rc_g == 0 and rc_a == 0:
        typer.echo("  refresh: ok")
    else:
        typer.echo(f"  refresh: fail (g={rc_g} a={rc_a})")
    typer.echo(f"  lint:    {'ok' if rc_lint == 0 else f'fail (rc={rc_lint})'}")

    all_ok = rc_g == 0 and rc_a == 0 and rc_lint == 0
    raise typer.Exit(code=0 if all_ok else 1)


@app.command(name="wave")
def wave(
    wave_id: str | None = typer.Argument(
        None,
        metavar="WAVE_ID",
        help="The wave identifier this wave-gate is running for.",
    ),
    all_scope: bool = typer.Option(
        False,
        "--all",
        help="Forward --scope=all to refresh, instead of the default --scope=github,artifacts pair.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Forward each stage's own stdout/stderr instead of discarding it.",
    ),
) -> None:
    """Wave-gate: refresh --scope=github,artifacts -> lint (or --scope=all with --all).

    Args:
        wave_id: The wave identifier (required; validated manually — see
            :func:`open_` for why — reproducing bash's exact
            ``"ERROR: usage: shctx sprint wave <wave-id>"`` message and
            exit code 1).
        all_scope: Forward ``--scope=all`` to refresh as a single stage
            instead of the default ``github``/``artifacts`` pair.
        verbose: Stream each stage's own output instead of discarding it.

    Raises:
        typer.Exit: code 1 (stderr message) if ``wave_id`` is missing or
            empty.
    """
    if not wave_id:
        typer.echo("ERROR: usage: shctx sprint wave <wave-id>", err=True)
        raise typer.Exit(code=1)
    _wave_impl(wave_id, all_scope, verbose)


# --------------------------------------------------------------------------
# close
# --------------------------------------------------------------------------


def _read_project_id() -> str:
    """Read the host project id from ``<workdir>/project.json``.

    Bash parity with ``_lib.sh``'s ``shctx_project_id`` as called in
    ``cmd_sprint.sh``'s ``close`` branch:
    ``project_id=$(shctx_project_id 2>/dev/null || echo "")`` — every
    failure mode (missing file, unreadable, invalid JSON, a non-object top
    level) is swallowed to ``""`` by that wrapper, so this function never
    raises; it mirrors ``jq -r '.id'``'s exact stringification instead:

    * Missing file, OS error, or invalid JSON -> ``""`` (mirrors
      ``shctx_project_id``'s own ``echo "ERROR: ... missing"; return 1``
      being caught by the ``2>/dev/null || echo ""`` wrapper).
    * Top level is not a JSON object -> ``""`` (``jq``'s ``.id`` on a
      non-object raises "Cannot index ... with string", a nonzero exit
      the same wrapper catches).
    * ``.id`` absent or JSON ``null`` -> the literal string ``"null"``
      (``jq -r '.id'`` prints the word ``null`` for a JSON null — NOT an
      error, so the ``2>/dev/null || echo ""`` fallback never fires here;
      this is the one non-obvious branch worth calling out explicitly).
    * ``.id`` is a JSON string -> that string, verbatim.
    * ``.id`` is a JSON bool/number -> its ``jq -r`` text form
      (``"true"``/``"false"``, or the number's compact JSON form).
    * ``.id`` is a JSON object/array (never happens in a real
      ``project.json``, but ``jq -r`` does not error on this shape) ->
      ``jq``'s 2-space-indented pretty-print form.

    Returns:
        The resolved project id string (bash parity — including the
        literal ``"null"`` case above), or ``""`` on any failure.
    """
    path = os.path.join(resolve_workdir(), _PROJECT_JSON_FILENAME)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    if "id" not in data or data["id"] is None:
        return "null"
    value = data["id"]
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    return json.dumps(value, indent=2)


async def _lane_closures_table_exists() -> bool:
    """Check whether the ``lane_closures`` table exists in the live DB.

    Bash parity with ``cmd_sprint.sh``'s defensive ``sqlite_master``
    introspection: ``shctx_sql "SELECT 1 FROM sqlite_master WHERE
    type='table' AND name='lane_closures';" | grep -q 1`` — guards the
    lane-closing step against a DB that has not been migrated past
    ``0003_canonical_types_filter.sql``. Uses a raw connection (per the
    port contract's raw-SQL guidance for ``sqlite_master`` introspection)
    rather than the ORM, since a missing table would make any ORM query
    against :class:`shepherd_cli.models_sprint.LaneClosure` raise instead
    of degrading gracefully.

    Returns:
        True if ``lane_closures`` exists as a table in the current
        connection's database.
    """
    conn = Tortoise.get_connection("default")
    rows = await conn.execute_query_dict(
        "SELECT 1 AS present FROM sqlite_master WHERE type='table' AND name='lane_closures';"
    )
    return len(rows) > 0


async def _pending_lane_ids(project_id: str, branch: str) -> list[str]:
    """Fetch lane ids tied to this sprint branch that still need closing.

    Bash parity with ``cmd_sprint.sh``'s
    ``SELECT lane_id FROM lane_closures WHERE project_id='$project_id' AND
    sprint_branch='$branch' AND closed_at IS NULL ORDER BY lane_id;`` —
    same filter, same ``ORDER BY lane_id`` (ascending, bash's default).
    Unlike bash's raw string-interpolated SQL, this uses Tortoise's
    parameterized filter — functionally identical for any project_id/
    branch value that doesn't itself contain a stray single quote (where
    bash's version would break), a strictly safer divergence.

    Args:
        project_id: The host project id (``_read_project_id()``'s
            result); bash never even reaches this query when it's empty
            (short-circuited by the caller's ``[[ -n "$project_id" ]]``
            check), and neither does this function's caller.
        branch: The sprint branch being closed.

    Returns:
        The matching ``lane_id`` values, in ascending order. Empty when
        nothing matches — note ``closed_at`` is a ``NOT NULL`` column that
        ``cmd_close-lane.sh`` always populates on write (see
        :class:`shepherd_cli.models_sprint.LaneClosure`), so in practice
        this is always empty; the query is still issued, bash-verbatim.
    """
    rows = await (
        LaneClosure.filter(project_id=project_id, sprint_branch=branch, closed_at__isnull=True)
        .order_by("lane_id")
        .all()
    )
    return [row.lane_id for row in rows]


async def _close_lanes_async(branch: str, scripts_dir: str) -> tuple[int, int]:
    """Close every known lane tied to this sprint branch (``close`` stage 1).

    Bash parity with ``cmd_sprint.sh``'s ``close`` branch, step 1: gated on
    a non-empty project id AND the ``lane_closures`` table existing; for
    each matching lane id, shells out to ``cmd_close-lane.sh <lane-id>
    --sprint=<branch> --status=clean`` with its output always discarded
    (bash: ``>/dev/null 2>&1``, unconditionally — NOT gated on
    ``--verbose`` the way the other stages' ``run_stage`` calls are).

    Args:
        branch: The sprint branch being closed.
        scripts_dir: Directory containing ``cmd_close-lane.sh``.

    Returns:
        ``(closed, lane_failed)`` — counts of lanes whose
        ``cmd_close-lane.sh`` invocation exited 0 vs. nonzero,
        respectively. ``(0, 0)`` when there is no project id yet, the
        ``lane_closures`` table doesn't exist, or no lane matches.
    """
    project_id = _read_project_id()
    closed = 0
    lane_failed = 0
    if project_id and await _lane_closures_table_exists():
        close_lane_script = os.path.join(scripts_dir, "cmd_close-lane.sh")
        for lane_id in await _pending_lane_ids(project_id, branch):
            if not lane_id:
                continue
            result = subprocess.run(
                ["bash", close_lane_script, lane_id, f"--sprint={branch}", "--status=clean"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if result.returncode == 0:
                closed += 1
            else:
                lane_failed += 1
    return closed, lane_failed


async def _close_async(branch: str, verbose: bool) -> None:
    """Run the ``close`` pipeline and print its bash-parity summary.

    Bash: close each known lane (DB-driven loop) -> handoff create ->
    worktree gc -> lock release, each stage independent (bash captures
    each ``rc_*``/count separately rather than short-circuiting).

    Args:
        branch: The sprint branch being closed (already validated
            non-empty by the caller).
        verbose: Forward each of the handoff/gc/lock stages' own
            stdout/stderr instead of discarding it (the lane-closing loop
            itself is never affected by this flag — see
            :func:`_close_lanes_async`).

    Raises:
        typer.Exit: code 0 if handoff, gc, and lock release all succeeded
            AND no lane failed to close, else code 1 — bash parity with
            ``(( rc_h == 0 && rc_gc == 0 && rc_l == 0 && lane_failed == 0
            ))``.
    """
    scripts_dir = _scripts_dir()
    t0 = _now_s()

    async with db.lifespan():
        closed, lane_failed = await _close_lanes_async(branch, scripts_dir)

    rc_h = _run_stage(
        "handoff",
        ["bash", os.path.join(scripts_dir, "cmd_handoff.sh"), "create", f"--branch={branch}"],
        verbose,
    )
    rc_gc = _run_stage("worktree gc", ["bash", os.path.join(scripts_dir, "cmd_worktree.sh"), "gc"], verbose)
    rc_l = _run_stage("lock release", ["bash", os.path.join(scripts_dir, "cmd_lock.sh"), "release"], verbose)

    elapsed = _now_s() - t0
    typer.echo(f"shctx sprint close {branch}: elapsed={elapsed}s")
    typer.echo(f"  lanes:   closed={closed} failed={lane_failed}")
    typer.echo(f"  handoff: {'ok' if rc_h == 0 else f'fail (rc={rc_h})'}")
    typer.echo(f"  gc:      {'ok' if rc_gc == 0 else f'fail (rc={rc_gc})'}")
    typer.echo(f"  lock:    {'released' if rc_l == 0 else f'fail (rc={rc_l})'}")

    all_ok = rc_h == 0 and rc_gc == 0 and rc_l == 0 and lane_failed == 0
    raise typer.Exit(code=0 if all_ok else 1)


@app.command(name="close")
def close(
    branch: str | None = typer.Argument(
        None,
        metavar="BRANCH",
        help="The sprint branch being closed.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Forward each stage's own stdout/stderr instead of discarding it.",
    ),
) -> None:
    """Sprint finale: close-lane (each known lane) -> handoff -> worktree gc -> lock release.

    Args:
        branch: The sprint branch (required; validated manually — see
            :func:`open_` for why — reproducing bash's exact
            ``"ERROR: usage: shctx sprint close <branch>"`` message and
            exit code 1).
        verbose: Stream the handoff/gc/lock stages' own output instead of
            discarding it.

    Raises:
        typer.Exit: code 1 (stderr message) if ``branch`` is missing or
            empty.
    """
    if not branch:
        typer.echo("ERROR: usage: shctx sprint close <branch>", err=True)
        raise typer.Exit(code=1)
    asyncio.run(_close_async(branch, verbose))


__all__ = ["app"]
