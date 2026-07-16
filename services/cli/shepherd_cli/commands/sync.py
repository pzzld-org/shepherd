"""``shepherd sync`` — one-shot context-refresh pipeline (bash: ``cmd_sync.sh``).

Native port of ``skills/context/scripts/cmd_sync.sh`` (v5.0.4): a single,
idempotent pipeline that shells out to three sibling ``shctx`` subcommands
in a fixed order::

    refresh  ->  lint  ->  status

``cmd_sync.sh`` is a SUBCOMMAND-FREE, SUBPROCESS-ORCHESTRATION script — it
has no verbs of its own (unlike ``cmd_sprint.sh``'s ``open``/``wave``/
``close``), only flags: ``--scope=<symbols|github|artifacts|all>``,
``--all`` (the canonical alias for ``--scope=all``), and ``--verbose``/
``-v``. Every stage is a real bash sibling script this module SHELLS OUT
to (``cmd_refresh.sh``, ``cmd_lint.sh``, ``cmd_status.sh``) — none of them
are inlined here, exactly mirroring how ``cmd_sync.sh`` itself only ever
coordinates them via ``bash "$HERE/cmd_*.sh" ...`` subprocess calls. This
port locates the sibling scripts via
:func:`shepherd_cli.resolution.find_bash_shctx` (same directory as the
``shctx`` dispatcher) and runs them the same way bash's own ``run_stage``
helper does — output suppressed by default, or streamed/inherited when
``--verbose``/``-v`` is given.

**NO DATABASE.** ``cmd_sync.sh`` never touches ``sqlite3``/``shctx_sql``
at all — every one of its three stages is itself a separate subprocess
that may (or may not) touch the database on its own terms, but
``cmd_sync.sh`` itself just times them and aggregates their exit codes.
This module therefore imports neither :mod:`shepherd_cli.db` nor any
Tortoise model, opens no ``db.lifespan()``, and needs no
``models_sync.py`` mirror-model module (hard rule #7's "pure subprocess-
orchestration command with no DB access needs no lifespan" applies in
full — even more so than ``shepherd sprint``'s ``close``, which still
touches ``lane_closures`` directly; ``shepherd sync`` touches nothing).

Bash parity is the bar for every branch:

- Bare ``shepherd sync`` (no flags at all) runs the full pipeline with
  ``scope="all"``, ``verbose=0`` — bash's ``for arg in "$@"`` loop simply
  never executes when ``$@`` is empty, so there is NO "no-args shows
  usage" branch here (unlike ``cmd_sprint.sh``'s ``""|-h|--help|help)
  usage ;;`` case); a bare invocation always performs a real sync.
- ``--scope=<value>`` sets the scope forwarded to ``cmd_refresh.sh``
  verbatim, with no validation against the documented
  ``symbols|github|artifacts|all`` set (bash never validates it either —
  an unrecognized scope value is ``cmd_refresh.sh``'s problem, not
  ``cmd_sync.sh``'s).
- ``--all`` is a pure alias that sets ``scope="all"``, identical to
  ``--scope=all``.
- ``--verbose``/``-v`` forwards each stage's own stdout/stderr instead of
  discarding it, with a ``─── <stage> ───`` header per stage.
- ``-h``/``--help`` prints the verbatim bash usage text to stdout and
  exits 0, from ANY position in the argument list (bash's flag-scanning
  loop has no positional-consumption quirk the way ``cmd_export.sh``'s
  ``kind``-then-flags loop does — see :func:`_parse_args`).
- Any token that is none of the above (``--scope=*``, ``--all``,
  ``--verbose``/``-v``, ``-h``/``--help``) is an immediate hard error:
  ``"ERROR: unknown arg: <token>"`` on stderr, exit 1 — bash's ``case``
  statement's catch-all ``*)`` arm, unlike ``cmd_lint.sh``'s silent
  ignore-everything callback.
- Every one of the three stages always runs, regardless of an earlier
  stage's exit code (bash: ``run_stage refresh ... || rc_refresh=$?``,
  same pattern three times over — the ``||`` catches ``run_stage``'s own
  ``return $?`` and assigns it to the per-stage variable rather than
  letting the script's ``set -e`` abort the whole pipeline early).
- The final exit code is 0 only if all three stages succeeded, else 1 —
  bash: ``if (( rc_refresh != 0 || rc_lint != 0 || rc_status != 0 )); then
  exit 1; fi``.

Known parity note (shared with ``shepherd sprint``): this module reuses
``shepherd sprint``'s exact ``_scripts_dir()``/``_run_stage()`` shape
(:mod:`shepherd_cli.commands.sprint`) rather than importing them, since
hard rule #9 and the porting notes ask each command module to stay
self-contained (no cross-command-module imports beyond the shared
``shepherd_cli`` layer).
"""

from __future__ import annotations

import os
import subprocess
import time

import typer

from shepherd_cli.resolution import find_bash_shctx

app = typer.Typer(
    no_args_is_help=False,
    add_completion=False,
    # help_option_names=[] disables Click's own --help so -h/--help reach the
    # callback's token loop and print the verbatim bash usage (parity), matching
    # commands/search.py / models.py / query.py.
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True, "help_option_names": []},
    help="One-shot context-refresh pipeline: refresh -> lint -> status.",
)

#: Verbatim bash-parity usage text — the ``-h|--help`` heredoc in
#: ``cmd_sync.sh``. Printed to stdout (bash parity: plain ``cat``, not
#: stderr) on ``-h``/``--help``.
_HELP_TEXT = (
    "shctx sync [--scope=symbols|github|artifacts|all] [--all] [--verbose]\n"
    "\n"
    '  refresh → lint → status — one-shot context update pipeline.\n'
    '  --all is the canonical "all targets" alias (= --scope=all).'
)


# --------------------------------------------------------------------------
# Sibling-script location + stage runner (same shape as
# shepherd_cli.commands.sprint's own helpers, kept self-contained here per
# hard rule #9).
# --------------------------------------------------------------------------
def _scripts_dir() -> str:
    """Resolve the directory containing the sibling ``cmd_*.sh`` scripts.

    Mirrors ``cmd_sync.sh``'s own ``HERE="$(cd "$(dirname "$0")" && pwd)"``
    — the directory holding ``cmd_sync.sh`` itself is the same directory
    that holds ``cmd_refresh.sh``, ``cmd_lint.sh``, and ``cmd_status.sh``.
    This CLI locates it via
    :func:`shepherd_cli.resolution.find_bash_shctx` (the ``shctx``
    dispatcher lives in that same ``scripts/`` directory) rather than
    hard-coding a path, so it resolves the same way under
    ``CLAUDE_PLUGIN_ROOT`` or a plain repo checkout.

    Returns:
        The absolute path to ``skills/context/scripts``.

    Raises:
        typer.Exit: code 1, with a stderr message, if the bash ``shctx``
            tooling cannot be located at all — every stage of the sync
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
    unit ``cmd_sync.sh`` uses for its ``elapsed=$(( $(shctx_now) - t0 ))``
    timing, NOT the epoch-milliseconds unit
    ``deliverables``/``session_signals``/``teammates`` use.

    Returns:
        The current time as whole seconds since the Unix epoch.
    """
    return int(time.time())


def _run_stage(name: str, argv: list[str], verbose: bool) -> int:
    """Run one pipeline stage, mirroring ``cmd_sync.sh``'s ``run_stage()`` helper.

    Bash::

        run_stage() {
          local name="$1"; shift
          if (( verbose )); then
            echo "─── $name ───"
            "$@" || return $?
          else
            "$@" >/dev/null 2>&1 || return $?
          fi
        }

    Args:
        name: Human label for the stage header, printed only when
            ``verbose`` (bash: the ``echo "─── $name ───"`` line).
        argv: The full argv to execute, e.g.
            ``["bash", "<scripts>/cmd_refresh.sh", "--scope=all"]``.
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
# Argument parsing (bash-parity port of cmd_sync.sh's ``for arg in "$@"``
# loop).
# --------------------------------------------------------------------------
def _parse_args(argv: list[str]) -> tuple[str, bool]:
    """Parse ``shctx sync``'s arguments, mirroring ``cmd_sync.sh`` line for line.

    Bash::

        scope="all"
        verbose=0
        for arg in "$@"; do
          case "$arg" in
            --scope=*) scope="${arg#--scope=}" ;;
            --all)     scope="all" ;;
            --verbose|-v) verbose=1 ;;
            -h|--help)
              cat <<'EOF' ... EOF
              exit 0 ;;
            *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
          esac
        done

    Every token is visited in order; the LAST ``--scope=<value>``/
    ``--all`` given wins (plain variable reassignment, matching bash
    exactly — e.g. ``--scope=github --all`` resolves to ``scope="all"``,
    while ``--all --scope=github`` resolves to ``scope="github"``).
    ``-h``/``--help`` and an unrecognized token both short-circuit
    immediately, from ANY position in ``argv`` — there is no positional-
    consumption quirk here the way ``cmd_export.sh``'s ``kind``-then-
    flags loop has, since ``cmd_sync.sh`` has no leading positional
    argument at all, only flags.

    Args:
        argv: Every token given to ``shepherd sync`` after the command
            name itself, in order.

    Returns:
        ``(scope, verbose)`` when no ``-h``/``--help`` token was
        encountered and every token was recognized — ``scope`` defaults
        to ``"all"`` and ``verbose`` defaults to False when ``argv`` is
        empty (bash: the ``for`` loop simply never executes).

    Raises:
        typer.Exit: code 0, after printing :data:`_HELP_TEXT` to stdout,
            the instant an ``-h``/``--help`` token is reached. Code 1,
            after printing ``"ERROR: unknown arg: <token>"`` to stderr,
            the instant a token matching none of the recognized shapes is
            reached.
    """
    scope = "all"
    verbose = False
    for arg in argv:
        if arg.startswith("--scope="):
            scope = arg[len("--scope=") :]
        elif arg == "--all":
            scope = "all"
        elif arg in ("--verbose", "-v"):
            verbose = True
        elif arg in ("-h", "--help"):
            typer.echo(_HELP_TEXT)
            raise typer.Exit(code=0)
        else:
            typer.echo(f"ERROR: unknown arg: {arg}", err=True)
            raise typer.Exit(code=1)
    return scope, verbose


# --------------------------------------------------------------------------
# Pipeline driver.
# --------------------------------------------------------------------------
def _sync_impl(scope: str, verbose: bool) -> None:
    """Run the refresh -> lint -> status pipeline and print its bash-parity summary.

    Bash: refresh (``--scope=$scope``) -> lint -> status, each independent
    (a later stage always runs even if an earlier one failed — bash
    captures each ``rc_*`` separately via ``run_stage ... || rc_*=$?``
    rather than letting ``set -e`` abort the pipeline on the first
    failure).

    Args:
        scope: The resolved ``--scope`` value forwarded to
            ``cmd_refresh.sh`` verbatim (already resolved by
            :func:`_parse_args`; ``"all"`` by default or via ``--all``).
        verbose: Forward each stage's own stdout/stderr instead of
            discarding it, with a ``─── <stage> ───`` header per stage.

    Raises:
        typer.Exit: code 0 if every stage succeeded, else code 1 — bash
            parity with ``if (( rc_refresh != 0 || rc_lint != 0 ||
            rc_status != 0 )); then exit 1; fi`` (falling through to the
            script's own implicit ``exit 0`` otherwise).
    """
    scripts_dir = _scripts_dir()
    t0 = _now_s()

    rc_refresh = _run_stage(
        "refresh",
        ["bash", os.path.join(scripts_dir, "cmd_refresh.sh"), f"--scope={scope}"],
        verbose,
    )
    rc_lint = _run_stage("lint", ["bash", os.path.join(scripts_dir, "cmd_lint.sh")], verbose)
    rc_status = _run_stage("status", ["bash", os.path.join(scripts_dir, "cmd_status.sh")], verbose)

    elapsed = _now_s() - t0
    typer.echo(f"shctx sync: scope={scope}  elapsed={elapsed}s")
    typer.echo(f"  refresh: {'ok' if rc_refresh == 0 else f'fail (rc={rc_refresh})'}")
    typer.echo(f"  lint:    {'ok' if rc_lint == 0 else f'fail (rc={rc_lint})'}")
    typer.echo(f"  status:  {'ok' if rc_status == 0 else f'fail (rc={rc_status})'}")

    all_ok = rc_refresh == 0 and rc_lint == 0 and rc_status == 0
    raise typer.Exit(code=0 if all_ok else 1)


@app.callback(invoke_without_command=True)
def sync(
    args: list[str] = typer.Argument(
        None,
        metavar="[--scope=<symbols|github|artifacts|all>] [--all] [--verbose|-v] [-h|--help]",
        hidden=True,
        help=(
            "Flags only, no positional arguments — see cmd_sync.sh's usage "
            "text (-h/--help)."
        ),
    ),
) -> None:
    """One-shot context-refresh pipeline: refresh -> lint -> status.

    Native port of ``shctx sync`` (``cmd_sync.sh``). Takes no subcommands
    — only the flags documented in :data:`_HELP_TEXT` — captured together
    as one variadic argument (mirroring
    :mod:`shepherd_cli.commands.export`'s ``context_settings`` pattern) and
    parsed bash-verbatim by :func:`_parse_args`, since ``ignore_unknown_
    options``/``allow_extra_args`` are required for this module to own its
    own ``"ERROR: unknown arg: ..."`` message and exit code (1) instead of
    Click's own "No such option" error (exit code 2).

    Args:
        args: Every token given after ``sync`` on the command line, or
            None/empty for a bare ``shepherd sync`` (bash parity: runs the
            full pipeline with ``scope="all"``, not a usage screen).

    Raises:
        typer.Exit: code 0 with the pipeline summary if every stage
            succeeded; code 1 if any stage failed, if an argument was
            unrecognized, or if the bash ``shctx`` tooling could not be
            located; code 0 with the usage text if ``-h``/``--help`` was
            given.
    """
    argv = list(args) if args else []
    scope, verbose = _parse_args(argv)
    _sync_impl(scope, verbose)


__all__ = ["app"]
