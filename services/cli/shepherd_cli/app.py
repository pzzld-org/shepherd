"""Typer root app for the shepherd CLI.

Owns the root app object, the ``--version``/``-V`` flag, and the LAZY
subcommand table below. It does NOT own the passthrough decision — that is
:mod:`shepherd_cli.__main__`, which derives its ported-command set from this
module's registrations.

LAZY SUBCOMMAND DISPATCH (v6.4.2)
=============================================================================
This module used to eagerly ``from shepherd_cli.commands import (adapt,
audit, ..., worktree)`` — all 42 command modules — at import time. Because
nearly every command module pulls in :mod:`shepherd_cli.db` and its Tortoise
models, that made ``import shepherd_cli.app`` cost ~540 ms, and EVERY
invocation paid for all 42 modules to run one of them.

That cost is not academic. The test suite is subprocess-per-test by the #198
contract (1492 tests, one interpreter start each), and more importantly the
hooks shell out constantly: ``dups_write_guard.sh`` and
``conductor_write_guard.sh`` fire on every Write/Edit and make 4-5 CLI calls
apiece, so the eager import was pure added latency on every file the flock
touched.

Commands are now resolved on demand by :class:`_LazyGroup`: the root app
imports :mod:`typer` alone (~75 ms), and dispatching ``shepherd teammate
liveness`` imports exactly ``shepherd_cli.commands.teammate``. Measured
``import shepherd_cli.app``: ~540 ms -> ~75 ms; a full DB-touching command
invocation: ~540 ms -> ~350 ms (the residue is that command's own module
chain, which it genuinely needs).

Deliberately NOT done: deferring ``from tortoise import Tortoise`` inside
:mod:`shepherd_cli.db`. It looks like another ~150 ms, but command modules
import :mod:`shepherd_cli.models` directly at module scope (e.g.
``commands/teammate.py`` imports ``Teammate``), so Tortoise arrives through
the models chain regardless and the change would buy nothing while adding an
import-order trap.

The one accepted cost: ``shepherd --help`` renders a short help line per
command, which Click can only obtain by resolving each one — so the root
help listing imports every module and stays at roughly the old cost. That is
the rare interactive path, not the hot one.
"""

from __future__ import annotations

import importlib

import typer
import typer.main
from typer.core import TyperGroup

from shepherd_cli import __version__

#: Sub-app command name -> module under ``shepherd_cli.commands``.
#: The name is what the operator types; the module is what gets imported to
#: serve it. Keys differ from module names only where the CLI spelling uses a
#: hyphen (``close-lane`` -> ``close_lane``). Adding a command here is the
#: single act that registers it — :mod:`shepherd_cli.__main__` derives its
#: passthrough set from this table, so there is no second list to update.
LAZY_GROUPS: dict[str, str] = {
    "adapt": "adapt",
    "audit": "audit",
    "close-lane": "close_lane",
    "config": "config",
    "dash": "dash",
    "deliverable": "deliverable",
    "discovery": "discovery",
    "doctor": "doctor",
    "dups": "dups",
    "eval": "eval",
    "export": "export",
    "graph": "graph",
    "guard": "guard",
    "handoff": "handoff",
    "home": "home",
    "init": "init",
    "inject": "inject",
    "insights": "insights",
    "issues": "issues",
    "lint": "lint",
    "lock": "lock",
    "loop": "loop",
    "mem": "mem",
    "migrate": "migrate",
    "models": "models",
    "panes": "panes",
    "plan": "plan",
    "prune": "prune",
    "query": "query",
    "ready": "ready",
    "refresh": "refresh",
    "release": "release",
    "report": "report",
    "run": "run",
    "search": "search",
    "seed": "seed",
    "signal": "signal",
    "sprint": "sprint",
    "status": "status",
    "style": "style",
    "sync": "sync",
    "teammate": "teammate",
    "worktree": "worktree",
}

#: Root-level single commands (not sub-apps): name -> (module, attribute, help).
#: ``render`` is a bare command rather than a group, so it is built from its
#: callback instead of an ``app`` attribute.
LAZY_COMMANDS: dict[str, tuple[str, str, str]] = {
    "render": (
        "render",
        "render_command",
        "Render a shepherd template deterministically (project -> user -> bundled).",
    ),
}


def command_names() -> frozenset[str]:
    """Every top-level command name this app serves.

    Returns:
        The union of the lazy sub-app names and the lazy root-command names.
        Callers use this instead of introspecting Typer's ``registered_*``
        lists, which are empty under lazy dispatch.
    """
    return frozenset(LAZY_GROUPS) | frozenset(LAZY_COMMANDS)


class _LazyGroup(TyperGroup):
    """Root group that imports a command module only when it is invoked.

    Click resolves a subcommand through :meth:`get_command`, so deferring the
    import to that call is transparent to the rest of Typer/Click: parsing,
    ``--help``, error messages, and exit codes are unchanged. Anything
    registered eagerly on the app still takes precedence, which keeps this
    additive.
    """

    def list_commands(self, ctx: object) -> list[str]:
        """All command names, eager and lazy, sorted.

        Args:
            ctx: The Click context (unused beyond the base call).

        Returns:
            Sorted command names — what ``shepherd --help`` enumerates.
        """
        eager = set(super().list_commands(ctx))  # type: ignore[arg-type]
        return sorted(eager | command_names())

    def get_command(self, ctx: object, name: str) -> object | None:
        """Resolve one command, importing its module on first use.

        Args:
            ctx: The Click context.
            name: The command name the operator typed.

        Returns:
            The Click command, or None when the name is unknown (Click then
            renders its own "No such command" error, unchanged).
        """
        eager = super().get_command(ctx, name)  # type: ignore[arg-type]
        if eager is not None:
            return eager

        if name in LAZY_GROUPS:
            module = importlib.import_module(f"shepherd_cli.commands.{LAZY_GROUPS[name]}")
            command = typer.main.get_command(module.app)
            command.name = name
            return command

        if name in LAZY_COMMANDS:
            module_name, attribute, help_text = LAZY_COMMANDS[name]
            module = importlib.import_module(f"shepherd_cli.commands.{module_name}")
            holder = typer.Typer()
            holder.command(name, help=help_text)(getattr(module, attribute))
            command = typer.main.get_command(holder)
            command.name = name
            return command

        return None


# ``-h`` as a first-class alias for ``--help``, set ONCE on the root context
# (v6.4.2, GH #249 follow-on). Click's default ``help_option_names`` is
# ``["--help"]`` alone, so before this the CLI had two classes of command:
# the bash-parity modules that hand-roll their own ``-h``/``--help`` branch
# accepted both, while every Click-managed group rejected ``-h`` outright
# ("No such option: -h", exit 2) and the catch-all-argv modules swallowed it
# as positional data and tried to run -- ``shepherd lint -h`` silently ran
# the real lint check to completion, the same class of bug #249 filed against
# ``dash``/``migrate``. ``help_option_names`` is inherited down the Context
# chain, so setting it here reaches every sub-app that does not deliberately
# override it; the modules that set ``help_option_names=[]`` for byte-exact
# bash parity keep their own handling and are unaffected. Pinned for all 43
# commands by ``tests/test_help_parity.py``.
app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    cls=_LazyGroup,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _version_callback(value: bool) -> None:
    """Print the shepherd CLI version and exit, if requested.

    Args:
        value: True when ``--version``/``-V`` was passed on the command line.

    Raises:
        typer.Exit: Always, when ``value`` is True, after printing the
            version. This is the standard Typer eager-option pattern and
            short-circuits the rest of argument parsing.
    """
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show the shepherd CLI version and exit.",
    ),
) -> None:
    """shepherd — teammate liveness and coordination CLI.

    Args:
        version: Eager ``--version``/``-V`` flag; handled by
            :func:`_version_callback` before any subcommand runs.
    """
    return None
