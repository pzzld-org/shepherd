"""Entrypoint for the shepherd CLI.

Ported subcommands (currently just ``teammate``) run through the Typer
root app in :mod:`shepherd_cli.app`. Everything else is a drop-in-superset
passthrough to the legacy bash ``shctx`` script, via ``os.execv`` so the
child process transparently inherits stdio and exit code.
"""

from __future__ import annotations

import os
import sys

from shepherd_cli.app import app, command_names
from shepherd_cli.resolution import find_bash_shctx


def _ported() -> frozenset[str]:
    """Every subcommand name the Typer app itself registers.

    DERIVED, never hand-maintained (v6.4.2). This set used to be a literal
    that had to mirror :mod:`shepherd_cli.app`'s ``add_typer``/``command``
    calls exactly; the two drifted the moment a command was added to one and
    not the other, and the failure was silent and confusing rather than
    loud -- an unlisted-but-registered command falls through to the
    ``os.execv`` branch below, so ``shepherd home`` answered
    ``ERROR: unknown subcommand: home`` from the RETIRED bash layer while
    being perfectly well registered in the Typer app three lines away.
    (That is exactly how it shipped broken: #254's ``home`` was added to
    ``app.py`` alone.) Reading the app object closes the class of bug --
    registering a command is now the single act that makes it dispatchable.

    Returns:
        Every name the Typer app serves (:func:`shepherd_cli.app.command_names`,
        which reads the lazy dispatch table) — i.e. every name that must NOT
        be shimmed to bash.
    """
    return command_names()


PORTED = _ported()


def main() -> None:
    """Dispatch to the Typer app, or shim un-ported subcommands to bash shctx.

    Raises:
        SystemExit: With code 2 if a passthrough subcommand is requested
            but no bash ``shctx`` script can be located.
    """
    argv = sys.argv[1:]
    if argv and not argv[0].startswith("-") and argv[0] not in PORTED:
        shctx = find_bash_shctx()
        if shctx is None:
            sys.stderr.write("ERR: bash shctx not found\n")
            raise SystemExit(2)
        os.execv("/bin/bash", ["bash", shctx, *argv])
    app()


if __name__ == "__main__":
    main()
