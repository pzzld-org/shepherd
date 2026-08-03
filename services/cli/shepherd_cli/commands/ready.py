"""``shepherd ready`` — first-time consumer-project bootstrap (bash: ``cmd_ready.sh``).

Native port of ``skills/context/scripts/cmd_ready.sh`` (v5.0.4): a single,
idempotent pipeline::

    init (idempotent)  ->  migrate  ->  refresh --all  ->  lint  ->  doctor

Safe to run on already-initialized projects: ``init`` only runs the first
time (gated on ``<workdir>/project.json`` not existing yet); every other
stage is itself idempotent by construction of the sibling subcommand it
invokes.

``cmd_ready.sh`` was a SUBCOMMAND-FREE, mostly SUBPROCESS-ORCHESTRATION
script — like ``cmd_sync.sh``, it has no verbs of its own, only flags:
``--shepherd``/``--artifacts`` (forwarded to the ``init`` stage verbatim,
only when that stage actually runs) and ``--verbose``/``-v``. Where bash
shelled out to five sibling scripts (``cmd_init.sh``, ``cmd_migrate.sh``,
``cmd_refresh.sh``, ``cmd_lint.sh``, ``cmd_doctor.sh``) via ``bash
"$HERE/cmd_*.sh" ...``, every one of those scripts now has a native port in
this package (:mod:`shepherd_cli.commands.init`,
:mod:`shepherd_cli.commands.migrate`, :mod:`shepherd_cli.commands.refresh`,
:mod:`shepherd_cli.commands.lint`, :mod:`shepherd_cli.commands.doctor`), so
this module re-invokes THIS interpreter's own CLI per stage —
``[sys.executable, "-m", "shepherd_cli", "<stage>", ...]``, see
:func:`_stage_argv` — and never execs bash or the retired
``skills/context/scripts/`` tree. The sibling modules expose only Typer
apps (no public functions), and each stage deliberately stays a separate
OS process rather than an in-process :class:`typer.testing.CliRunner` call
(the :mod:`shepherd_cli.commands.inject` idiom) because the per-stage
output contracts here are FD-level: suppressing or streaming a stage must
apply transitively to everything the stage itself spawns (``refresh``'s
zone helpers, ``init``'s auto-refresh, ``gh``, ``git``), a stage's crash
must not take down the pipeline, and each stage opens/closes its own DB
lifespan exactly as each bash child process did. ``CliRunner`` swaps only
the Python-level ``sys.stdout``/``sys.stderr`` objects, so grandchild
subprocess output would leak past it — a subprocess of this interpreter is
the only faithful swap.

**NO DATABASE ACCESS OF ITS OWN.** ``cmd_ready.sh`` never issues a single
``sqlite3``/``shctx_sql`` query directly — the ONE piece of local state it
reads is a plain file existence check, ``[[ ! -f
"$(shctx_project_id_path)" ]]`` (i.e. ``<workdir>/project.json``), used
solely to decide whether the ``init`` stage needs to run at all. Every
actual database write (schema creation, project row insert, migrations,
refresh indexing) happens inside the sibling subcommands it invokes, on
their own terms. This module therefore imports neither
:mod:`shepherd_cli.db` nor any Tortoise model, opens no ``db.lifespan()``,
and needs no ``models_ready.py`` mirror-model module (hard rule #7's "pure
subprocess-orchestration command with no DB access needs no lifespan"
applies in full — the same as ``shepherd sync``).

Bash parity is the bar for every branch:

- Bare ``shepherd ready`` (no flags at all) runs the full pipeline —
  bash's ``for arg in "$@"`` loop simply never executes when ``$@`` is
  empty, so there is NO "no-args shows usage" branch (unlike
  ``cmd_sprint.sh``'s ``""|-h|--help|help) usage ;;`` case); a bare
  invocation always performs a real bootstrap.
- ``--shepherd``/``--artifacts`` are collected, in order, into a list
  forwarded to the ``init`` stage verbatim — but ONLY when the ``init``
  stage actually runs (project.json absent). When the project is already
  initialized, these flags are silently accepted and then ignored, exactly
  like bash (``init_flags`` is built regardless of whether it will ever be
  used).
- ``--verbose``/``-v`` forwards the ``migrate``/``refresh``/``lint``
  stages' own stdout/stderr instead of discarding them, with a ``───
  <stage> ───`` header per stage (``_run_stage``, shared shape with
  ``sync``/``audit``). The ``init`` stage is handled separately (see
  :func:`_run_init_stage`) since bash's own ``init`` block does NOT use
  ``run_stage`` — it always redirects stdout to ``/dev/null`` (verbose or
  not) while always leaving stderr connected, and its header is printed
  only when the stage actually runs (unlike ``run_stage``, which never
  prints a header for a stage that doesn't execute — moot here since
  ``init`` only "doesn't run" when skipped entirely, which also means no
  header). The ``doctor`` stage is ALSO handled separately (see
  :func:`_run_doctor_stage`): bash invokes it directly with NO redirection
  at all, regardless of ``--verbose`` — it is "the user-visible summary"
  per bash's own comment, always streamed.
- ``-h``/``--help`` prints the verbatim bash usage text to stdout and
  exits 0, from ANY position in the argument list.
- Any token that is none of the above is an immediate hard error:
  ``"ERROR: unknown arg: <token>"`` on stderr, exit 1 — bash's ``case``
  statement's catch-all ``*)`` arm.
- The ``init`` stage is NOT wrapped the way ``migrate``/``refresh``/
  ``lint`` are: bash's ``init`` block runs ``bash "$HERE/cmd_init.sh" ...
  >/dev/null`` with no ``|| rc=$?`` capture, under the script's own ``set
  -eu -o pipefail``. A nonzero exit from the ``init`` stage therefore
  aborts ``shepherd ready`` IMMEDIATELY, at that exact point — no later
  stage runs, and NONE of the final summary lines print. This port
  reproduces that exact short-circuit (see :func:`_run_init_stage`'s
  ``typer.Exit`` behavior), unlike ``migrate``/``refresh``/``lint``, which
  always run regardless of an earlier stage's exit code.
- ``migrate``/``refresh``/``lint`` are each independent (bash captures
  each ``rc_*`` separately via ``run_stage ... || rc_*=$?`` rather than
  short-circuiting on the first failure) — a later stage always runs even
  if an earlier one failed.
- ``doctor`` always runs last, unconditionally, printing its own full
  report to stdout (with a blank line before it, mirroring bash's bare
  ``echo``) — its exit code (0 ok / 1 fail / 2 warn-only, per
  ``shepherd doctor``'s own contract) feeds the ``doctor:`` summary line
  (``ok``/``warn``/``fail (rc=N)``) but does NOT factor into
  ``shepherd ready``'s own final exit code.
- The final exit code is 0 only if ``migrate``, ``refresh``, AND ``lint``
  all succeeded, else 1 — bash: ``if (( rc_migrate != 0 || rc_refresh != 0
  || rc_lint != 0 )); then exit 1; fi``. Note ``doctor``'s exit code is
  deliberately excluded from this check (see above).
- A stage that cannot be launched at all (an :class:`OSError` from process
  creation — the moral equivalent of bash's missing/unexecutable
  ``cmd_*.sh``) counts as rc 127, the shell's own command-not-found code:
  captured per stage for ``migrate``/``refresh``/``lint``/``doctor``, and
  — matching the ``set -e`` short-circuit above — an immediate exit 127
  for the ``init`` stage.

Known parity note (documented, not fixed — matches ``cmd_ready.sh``'s own
lightly redundant bash): the bash script computes ``root="$(shctx_artifacts_root)"``
on its own line, immediately before the ``project.json`` existence check
(which resolves the SAME workdir a second time, internally, via
``shctx_project_id_path`` -> ``shctx_artifacts_root``). Since
``resolve_workdir``/``shctx_artifacts_root`` has a side effect (a
dual-namespace ``.shepherd/``+``.artifacts/`` warning printed to stderr,
unless ``SHCTX_QUIET`` is set), bash prints that warning TWICE per
invocation whenever both namespaces exist; the ``root`` variable itself is
otherwise never referenced again in the script. This port calls
:func:`shepherd_cli.resolution.resolve_workdir` exactly ONCE for the same
purpose (computing the ``project.json`` path), so the warning — when
triggered — prints once here instead of twice. This is a strict
improvement (less redundant stderr noise) with no effect on exit codes,
stdout content, or any stage's behavior, and is not worth reproducing the
double stderr write for.

Known parity note (shared with ``shepherd sync``/``shepherd audit``):
this module keeps its own ``_stage_argv()``/``_now_s()``/``_run_stage()``
copies rather than importing them from a sibling command module, since
hard rule #9 and the porting notes ask each command module to stay
self-contained (no cross-command-module imports beyond the shared
``shepherd_cli`` layer).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import typer

from shepherd_cli.resolution import resolve_workdir

app = typer.Typer(
    no_args_is_help=False,
    add_completion=False,
    # help_option_names=[] disables Click's own --help so -h/--help reach the
    # callback's token loop and print the verbatim bash usage (parity), matching
    # commands/search.py / commands/sync.py / commands/models.py.
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True, "help_option_names": []},
    help="First-time bootstrap: init -> migrate -> refresh --all -> lint -> doctor.",
)

#: Verbatim bash-parity usage text — the ``-h|--help`` heredoc in
#: ``cmd_ready.sh``. Printed to stdout (bash parity: plain ``cat``, not
#: stderr) on ``-h``/``--help``.
_HELP_TEXT = (
    "shctx ready [--shepherd|--artifacts] [--verbose]\n"
    "\n"
    "  init → migrate → refresh --all → lint → doctor\n"
    "\n"
    "First-time bootstrap. Pass --artifacts for legacy `.artifacts/` namespace\n"
    "(default is `.shepherd/`). Idempotent."
)

_PROJECT_JSON_FILENAME = "project.json"


# --------------------------------------------------------------------------
# Stage argv construction + stage runner (same shape as
# shepherd_cli.commands.sync's/audit's own helpers, kept self-contained
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
            ``("refresh", "--scope=all")`` or ``("init", "--shepherd")``.

    Returns:
        The full argv ready for ``subprocess.run``.
    """
    return [sys.executable, "-m", "shepherd_cli", *stage_args]


def _now_s() -> int:
    """Return the current wall-clock time in epoch SECONDS.

    Bash parity with ``_lib.sh``'s ``shctx_now() { date +%s; }`` — the
    unit ``cmd_ready.sh`` uses for its ``elapsed=$(( $(shctx_now) - t0 ))``
    timing, NOT the epoch-milliseconds unit
    ``deliverables``/``session_signals``/``teammates`` use.

    Returns:
        The current time as whole seconds since the Unix epoch.
    """
    return int(time.time())


def _run_stage(name: str, argv: list[str], verbose: bool) -> int:
    """Run one ``run_stage``-shaped pipeline stage (migrate/refresh/lint).

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
            ``[sys.executable, "-m", "shepherd_cli", "lint"]`` (see
            :func:`_stage_argv`).
        verbose: When True, print the stage header and let the child
            process inherit this process's stdout/stderr (bash: run
            ``"$@"`` directly, unredirected). When False, discard the
            child's stdout AND stderr entirely (bash: ``"$@" >/dev/null
            2>&1``) — only the exit code is observed either way.

    Returns:
        The child process's exit code (0 on success), exactly as bash's
        ``run_stage`` return value. A stage that cannot be launched at all
        (``OSError`` from process creation) returns 127, the shell's own
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


def _run_init_stage(init_flags: list[str], verbose: bool) -> bool:
    """Run the ``init`` stage exactly once, ONLY if ``project.json`` is absent.

    Bash::

        root="$(shctx_artifacts_root)"
        if [[ ! -f "$(shctx_project_id_path)" ]]; then
          if (( verbose )); then echo "─── init ───"; fi
          bash "$HERE/cmd_init.sh" "${init_flags[@]+"${init_flags[@]}"}" >/dev/null
          did_init=1
        else
          did_init=0
        fi

    Unlike :func:`_run_stage`, this does NOT use the ``run_stage`` shape:
    stdout is always discarded (verbose or not — bash's ``>/dev/null`` is
    unconditional here) while stderr always inherits the parent process's
    stderr (verbose or not — bash never redirects it at all in this
    block). And critically, there is no ``|| rc=$?`` capture: under
    ``cmd_ready.sh``'s own ``set -eu -o pipefail``, a nonzero exit from
    the ``init`` stage aborts the ENTIRE script immediately, with that
    exact exit code — no later stage runs, and no summary prints. This
    function reproduces that short-circuit via ``typer.Exit``. The stage
    itself is the ported :mod:`shepherd_cli.commands.init`, run as a child
    process of this interpreter (see :func:`_stage_argv`).

    Args:
        init_flags: The ``--shepherd``/``--artifacts`` tokens collected by
            :func:`_parse_args`, in order, forwarded to the ``init`` stage
            verbatim.
        verbose: When True, print the ``─── init ───`` header before
            running (bash: only inside the "stage actually runs" branch —
            an already-initialized project prints no header, since the
            stage doesn't run at all).

    Returns:
        True if ``init`` was actually run (``project.json`` was absent —
        bash's ``did_init=1``); False if it was skipped because the
        project is already initialized (``did_init=0``).

    Raises:
        typer.Exit: with the ``init`` stage's own exit code, the instant
            it returns nonzero — bash parity with the unguarded ``set -e``
            abort described above. Code 127 if the stage cannot be
            launched at all (``OSError`` from process creation — bash's
            command-not-found code, aborting the same way).
    """
    pidfile = os.path.join(resolve_workdir(), _PROJECT_JSON_FILENAME)
    if os.path.isfile(pidfile):
        return False

    if verbose:
        typer.echo("─── init ───")
    try:
        result = subprocess.run(_stage_argv("init", *init_flags), check=False, stdout=subprocess.DEVNULL)
    except OSError:
        raise typer.Exit(code=127) from None
    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)
    return True


def _run_doctor_stage() -> int:
    """Run the ``doctor`` stage, always streaming its output (bash parity).

    Bash::

        echo
        bash "$HERE/cmd_doctor.sh"
        rc_doctor=$?

    Bash invoked ``cmd_doctor.sh`` with NO redirection at all, regardless
    of ``--verbose`` — the code comment above this block calls it out
    explicitly: "emit at end as the user-visible summary". Unlike
    :func:`_run_stage`, there is no suppressed-output branch for this
    stage. The stage itself is the ported
    :mod:`shepherd_cli.commands.doctor`, run as a child process of this
    interpreter (see :func:`_stage_argv`).

    Returns:
        The ``doctor`` stage's exit code: 0 (all checks ok), 1 (at least
        one FAIL), or 2 (warnings only, no FAIL) — per its own contract;
        127 if the stage cannot be launched at all (``OSError`` from
        process creation). This value feeds ONLY the ``doctor:`` summary
        line; it never affects ``shepherd ready``'s own final exit code
        (see module docstring).
    """
    typer.echo("")
    try:
        result = subprocess.run(_stage_argv("doctor"), check=False)
    except OSError:
        return 127
    return result.returncode


# --------------------------------------------------------------------------
# Argument parsing (bash-parity port of cmd_ready.sh's ``for arg in "$@"``
# loop).
# --------------------------------------------------------------------------
def _parse_args(argv: list[str]) -> tuple[list[str], bool]:
    """Parse ``shctx ready``'s arguments, mirroring ``cmd_ready.sh`` line for line.

    Bash::

        verbose=0
        init_flags=()
        for arg in "$@"; do
          case "$arg" in
            --verbose|-v) verbose=1 ;;
            --shepherd|--artifacts) init_flags+=("$arg") ;;
            -h|--help)
              cat <<'EOF' ... EOF
              exit 0 ;;
            *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
          esac
        done

    Every token is visited in order; ``--shepherd``/``--artifacts`` tokens
    accumulate into ``init_flags`` (bash: ``init_flags+=("$arg")`` — an
    append, not a reassignment, so BOTH flags can appear together if given
    together, in the order given; the ``init`` stage's own arg loop
    resolves which one wins if both are present, not this one).
    ``--verbose``/``-v`` is a plain boolean flag (last-wins is moot since
    it only ever sets True). ``-h``/``--help`` and an unrecognized token
    both short-circuit immediately, from ANY position in ``argv``.

    Args:
        argv: Every token given to ``shepherd ready`` after the command
            name itself, in order.

    Returns:
        ``(init_flags, verbose)`` when no ``-h``/``--help`` token was
        encountered and every token was recognized — ``init_flags``
        defaults to ``[]`` and ``verbose`` defaults to False when ``argv``
        is empty (bash: the ``for`` loop simply never executes).

    Raises:
        typer.Exit: code 0, after printing :data:`_HELP_TEXT` to stdout,
            the instant an ``-h``/``--help`` token is reached. Code 1,
            after printing ``"ERROR: unknown arg: <token>"`` to stderr,
            the instant a token matching none of the recognized shapes is
            reached.
    """
    init_flags: list[str] = []
    verbose = False
    for arg in argv:
        if arg in ("--verbose", "-v"):
            verbose = True
        elif arg in ("--shepherd", "--artifacts"):
            init_flags.append(arg)
        elif arg in ("-h", "--help"):
            typer.echo(_HELP_TEXT)
            raise typer.Exit(code=0)
        else:
            typer.echo(f"ERROR: unknown arg: {arg}", err=True)
            raise typer.Exit(code=1)
    return init_flags, verbose


# --------------------------------------------------------------------------
# Pipeline driver.
# --------------------------------------------------------------------------
def _ready_impl(init_flags: list[str], verbose: bool) -> None:
    """Run the init -> migrate -> refresh --all -> lint -> doctor pipeline.

    Bash: ``init`` (idempotent, short-circuits the whole script on
    failure — see :func:`_run_init_stage`) -> ``migrate`` -> ``refresh
    --scope=all`` -> ``lint`` (each of these three independent, a later
    stage always runs even if an earlier one failed) -> ``doctor``
    (always streamed, its exit code excluded from the final verdict).
    Every stage is the ported sibling subcommand, run as a child process
    of this interpreter (see :func:`_stage_argv`).

    Args:
        init_flags: The ``--shepherd``/``--artifacts`` tokens to forward
            to the ``init`` stage, in order (already resolved by
            :func:`_parse_args`; only actually used if the ``init`` stage
            runs at all).
        verbose: Forward the ``migrate``/``refresh``/``lint`` stages' own
            stdout/stderr instead of discarding them, with a ``───
            <stage> ───`` header per stage. Also gates the ``init``
            stage's own header (see :func:`_run_init_stage`). Never
            affects the ``doctor`` stage, which always streams (see
            :func:`_run_doctor_stage`).

    Raises:
        typer.Exit: with the ``init`` stage's own exit code if it fails
            (bash parity: unguarded ``set -e`` abort, no summary printed).
            Code 0 if ``migrate``, ``refresh``, and ``lint`` all succeeded
            (regardless of ``doctor``'s exit code); code 1 otherwise —
            bash parity with ``if (( rc_migrate != 0 || rc_refresh != 0 ||
            rc_lint != 0 )); then exit 1; fi``.
    """
    t0 = _now_s()

    did_init = _run_init_stage(init_flags, verbose)

    rc_migrate = _run_stage("migrate", _stage_argv("migrate"), verbose)
    rc_refresh = _run_stage("refresh", _stage_argv("refresh", "--scope=all"), verbose)
    rc_lint = _run_stage("lint", _stage_argv("lint"), verbose)

    rc_doctor = _run_doctor_stage()

    elapsed = _now_s() - t0
    typer.echo("")
    typer.echo(f"shctx ready: bootstrap done (elapsed={elapsed}s)")
    typer.echo(f"  init:    {'performed' if did_init else 'skipped (already initialized)'}")
    typer.echo(f"  migrate: {'ok' if rc_migrate == 0 else f'fail (rc={rc_migrate})'}")
    typer.echo(f"  refresh: {'ok' if rc_refresh == 0 else f'fail (rc={rc_refresh})'}")
    typer.echo(f"  lint:    {'ok' if rc_lint == 0 else f'fail (rc={rc_lint})'}")
    if rc_doctor == 0:
        doctor_status = "ok"
    elif rc_doctor == 2:
        doctor_status = "warn"
    else:
        doctor_status = f"fail (rc={rc_doctor})"
    typer.echo(f"  doctor:  {doctor_status}")

    all_ok = rc_migrate == 0 and rc_refresh == 0 and rc_lint == 0
    raise typer.Exit(code=0 if all_ok else 1)


@app.callback(invoke_without_command=True)
def ready(
    args: list[str] = typer.Argument(
        None,
        metavar="[--shepherd|--artifacts] [--verbose|-v] [-h|--help]",
        hidden=True,
        help=(
            "Flags only, no positional arguments — see cmd_ready.sh's usage "
            "text (-h/--help)."
        ),
    ),
) -> None:
    """First-time bootstrap: init -> migrate -> refresh --all -> lint -> doctor.

    Native port of ``shctx ready`` (``cmd_ready.sh``). Takes no
    subcommands — only the flags documented in :data:`_HELP_TEXT` —
    captured together as one variadic argument (mirroring
    :mod:`shepherd_cli.commands.sync`'s ``context_settings`` pattern) and
    parsed bash-verbatim by :func:`_parse_args`, since ``ignore_unknown_
    options``/``allow_extra_args`` are required for this module to own its
    own ``"ERROR: unknown arg: ..."`` message and exit code (1) instead of
    Click's own "No such option" error (exit code 2).

    Args:
        args: Every token given after ``ready`` on the command line, or
            None/empty for a bare ``shepherd ready`` (bash parity: runs
            the full bootstrap pipeline, not a usage screen).

    Raises:
        typer.Exit: code 0 with the pipeline summary if ``migrate``,
            ``refresh``, and ``lint`` all succeeded; code 1 if any of
            those three failed or if an argument was unrecognized; the
            ``init`` stage's own exit code if that stage runs and fails;
            code 0 with the usage text if ``-h``/``--help`` was given.
    """
    argv = list(args) if args else []
    init_flags, verbose = _parse_args(argv)
    _ready_impl(init_flags, verbose)


__all__ = ["app"]
