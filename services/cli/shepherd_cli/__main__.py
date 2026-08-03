"""Entrypoint for the shepherd CLI.

Ported subcommands (currently just ``teammate``) run through the Typer
root app in :mod:`shepherd_cli.app`. Everything else is a drop-in-superset
passthrough to the legacy bash ``shctx`` script, via ``os.execv`` so the
child process transparently inherits stdio and exit code.
"""

from __future__ import annotations

import os
import sys

from shepherd_cli.app import app
from shepherd_cli.resolution import find_bash_shctx

PORTED = {
    "teammate", "signal", "deliverable", "mem", "status",
    "lock", "sprint", "models", "query", "style", "report",
    "search", "export", "lint", "seed", "config", "sync",
    "dash", "insights", "dups", "handoff", "ready",
    "discovery", "audit", "eval", "doctor",
    "migrate", "init", "close-lane", "issues", "worktree", "refresh", "prune",
    "render", "run",
}


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
