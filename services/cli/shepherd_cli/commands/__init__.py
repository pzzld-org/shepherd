"""Command sub-apps for the shepherd CLI.

Re-exports the ``teammate`` Typer sub-app (issue #198's only ported surface);
see :mod:`shepherd_cli.commands.teammate` for the ``liveness``/``status``/
``state`` command implementations.
"""

from __future__ import annotations

from shepherd_cli.commands import teammate

__all__ = ["teammate"]
