"""shepherd_cli — Python-side CLI for shepherd (issue #198).

Tortoise ORM models mirror the canonical SQL schema at
``skills/context/schema/`` (the bash ``shctx`` tooling remains the schema
source of truth for now); Pydantic gives typed I/O; Typer is the command
surface. See ``services/cli/README.md`` for the full contract and the
coexistence/phasing plan.
"""

from __future__ import annotations

__version__ = "6.5.0"

__all__ = ["__version__"]
