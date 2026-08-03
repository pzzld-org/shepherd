"""``shepherd sync`` — one-shot context-refresh pipeline (bash: ``cmd_sync.sh``).

Native port of ``skills/context/scripts/cmd_sync.sh`` (v5.0.4): a single,
idempotent pipeline that runs three sibling ``shepherd`` subcommands in a
fixed order::

    refresh  ->  lint  ->  status

``cmd_sync.sh`` was a SUBCOMMAND-FREE, SUBPROCESS-ORCHESTRATION script — it
has no verbs of its own (unlike ``cmd_sprint.sh``'s ``open``/``wave``/
``close``), only flags: ``--scope=<symbols|github|artifacts|all>``,
``--all`` (the canonical alias for ``--scope=all``), and ``--verbose``/
``-v``. Where bash shelled out to three sibling scripts (``cmd_refresh.sh``,
``cmd_lint.sh``, ``cmd_status.sh``) via ``bash "$HERE/cmd_*.sh" ...``, every
one of those scripts now has a native port in this package
(:mod:`shepherd_cli.commands.refresh`, :mod:`shepherd_cli.commands.lint`,
:mod:`shepherd_cli.commands.status`), so this module re-invokes THIS
interpreter's own CLI per stage — ``[sys.executable, "-m", "shepherd_cli",
"<stage>", ...]``, see :func:`_stage_argv` — and never execs bash or the
retired ``skills/context/scripts/`` tree. The sibling modules expose only
Typer apps (no public functions), and each stage deliberately stays a
separate OS process rather than an in-process
:class:`typer.testing.CliRunner` call (the :mod:`shepherd_cli.commands.inject`
idiom) because bash's ``run_stage`` semantics are FD-level: suppressing or
streaming a stage's output must apply transitively to everything the stage
itself spawns (``refresh``'s zone helpers, ``gh``, ``git``), a stage's crash
must not take down the pipeline, and each stage opens/closes its own DB
lifespan exactly as each bash child process did. ``CliRunner`` swaps only
the Python-level ``sys.stdout``/``sys.stderr`` objects, so grandchild
subprocess output would leak past it — a subprocess of this interpreter is
the only faithful swap.

**NO DATABASE.** ``cmd_sync.sh`` never touches ``sqlite3``/``shctx_sql``
at all — every one of its three stages is itself a separate subprocess
that may (or may not) touch the database on its own terms, but
the pipeline itself just times them and aggregates their exit codes.
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
- ``--scope=<value>`` sets the scope forwarded to the ``refresh`` stage
  verbatim, with no validation against the documented
  ``symbols|github|artifacts|all`` set (bash never validates it either —
  an unrecognized scope value is the refresh stage's problem, not
  ``shepherd sync``'s).
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
- A stage that cannot be launched at all (an :class:`OSError` from process
  creation — the moral equivalent of bash's missing/unexecutable
  ``cmd_*.sh``) counts as rc 127, the shell's own command-not-found code,
  captured per stage like any other failure instead of crashing the
  pipeline.

Known parity note (shared with ``shepherd ready``/``shepherd audit``):
this module keeps its own ``_stage_argv()``/``_run_stage()`` copies rather
than importing them from a sibling command module, since hard rule #9 and
the porting notes ask each command module to stay self-contained (no
cross-command-module imports beyond the shared ``shepherd_cli`` layer).
"""

from __future__ import annotations

import subprocess
import sys
import time

import typer

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
# Stage argv construction + stage runner (same shape as
# shepherd_cli.commands.ready's/audit's own helpers, kept self-contained
# here per hard rule #9).
# --------------------------------------------------------------------------
def _stage_argv(*stage_args: str) -> list[str]:
    """Build the argv for one pipeline stage: this interpreter's own CLI.

    Replaces bash's ``bash "$HERE/cmd_<stage>.sh" ...`` — every stage of
    this pipeline is a ported sibling subcommand of this same package, so
    the stage runs as ``[sys.executable, "-m", "shepherd_cli", <stage>,
    ...]``: a child process of THIS interpreter, deterministic, with no
    bash and no dependency on the retired ``skills/context/scripts/``
    tree. The child inherits this process's environment (``SHCTX_DB``,
    ``SHEPHERD_WORKDIR``, ...) exactly as bash's child scripts did.

    Args:
        stage_args: The subcommand name followed by its arguments, e.g.
            ``("refresh", "--scope=all")``.

    Returns:
        The full argv ready for :func:`_run_stage`/``subprocess.run``.
    """
    return [sys.executable, "-m", "shepherd_cli", *stage_args]


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
            ``[sys.executable, "-m", "shepherd_cli", "refresh",
            "--scope=all"]`` (see :func:`_stage_argv`).
        verbose: When True, print the stage header and let the child
            process inherit this process's stdout/stderr (bash: run
            ``"$@"`` directly, unredirected). When False, discard the
            child's stdout AND stderr entirely (bash: ``"$@" >/dev/null
            2>&1``) — only the exit code is observed either way.

    Returns:
        The child process's exit code (0 on success), exactly as bash's
        ``run_stage`` return value — the underlying command's exit status
        is preserved regardless of whether its output was captured or
        suppressed. A stage that cannot be launched at all (``OSError``
        from process creation) returns 127, the shell's own
        command-not-found code for a missing ``cmd_*.sh``.
    """
    try:
        if verbose:
            typer.echo(f"─── {name} ───")
            result = subprocess.run(argv, check=False)
        else:
            result = subprocess.run(argv, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return 127
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
    failure). Each stage is the ported sibling subcommand, run as a child
    process of this interpreter (see :func:`_stage_argv`).

    Args:
        scope: The resolved ``--scope`` value forwarded to the ``refresh``
            stage verbatim (already resolved by :func:`_parse_args`;
            ``"all"`` by default or via ``--all``).
        verbose: Forward each stage's own stdout/stderr instead of
            discarding it, with a ``─── <stage> ───`` header per stage.

    Raises:
        typer.Exit: code 0 if every stage succeeded, else code 1 — bash
            parity with ``if (( rc_refresh != 0 || rc_lint != 0 ||
            rc_status != 0 )); then exit 1; fi`` (falling through to the
            script's own implicit ``exit 0`` otherwise).
    """
    t0 = _now_s()

    rc_refresh = _run_stage("refresh", _stage_argv("refresh", f"--scope={scope}"), verbose)
    rc_lint = _run_stage("lint", _stage_argv("lint"), verbose)
    rc_status = _run_stage("status", _stage_argv("status"), verbose)

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
            succeeded; code 1 if any stage failed or if an argument was
            unrecognized; code 0 with the usage text if ``-h``/``--help``
            was given.
    """
    argv = list(args) if args else []
    scope, verbose = _parse_args(argv)
    _sync_impl(scope, verbose)


__all__ = ["app"]
