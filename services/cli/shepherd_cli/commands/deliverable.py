"""``shepherd deliverable`` — promise/complete/stalled Typer sub-app.

Bash parity target: ``skills/context/scripts/cmd_deliverable.sh``. Thin
synchronous Typer commands over an async data layer, exactly like
:mod:`shepherd_cli.commands.teammate` — Typer/Click commands are called
synchronously, but Tortoise ORM's query API is async, so every command
wraps exactly one ``asyncio.run`` around ``async with db.lifespan(): ...``.

Unlike ``teammate``, this module is deliberately self-contained: its
Pydantic output schema and its async query helpers live INLINE here
rather than in :mod:`shepherd_cli.schemas` / :mod:`shepherd_cli.queries`,
per the #198-wave port contract (disjoint file ownership keeps parallel
ports from colliding on shared modules). The one thing it does still
import from the shared layer is :mod:`shepherd_cli.db` (Tortoise
lifecycle + schema self-heal) and
:func:`shepherd_cli.resolution.resolve_session_id` — those are
intentionally NOT reinvented here.

Timestamps are epoch-MILLISECONDS throughout (``deliverables.promised_at``
/ ``delivered_at``), matching bash's ``now_ms()`` helper in
``cmd_deliverable.sh`` — NOT epoch-seconds like ``_lib.sh``'s
``shctx_now()``, which other tables use.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time

import typer
from pydantic import BaseModel, ConfigDict

from shepherd_cli import db
from shepherd_cli.models import Project
from shepherd_cli.models_deliverable import Deliverable
from shepherd_cli.resolution import resolve_session_id

app = typer.Typer(
    add_completion=False,
    help="Deliverable promise/complete/stalled commands.",
)


@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context) -> None:
    """Print usage and exit 0 when no subcommand is given (bash parity).

    ``cmd_deliverable.sh``'s ``""|help|--help|-h) usage;;`` branch prints the
    usage text to stdout and exits 0. Typer's ``no_args_is_help`` would exit 2
    instead (Click treats a missing command as a usage error), so this callback
    restores the exact bash no-subcommand contract.

    Args:
        ctx: The Typer/Click context; ``invoked_subcommand`` is None only when
            ``shepherd deliverable`` is run with no subcommand.

    Raises:
        typer.Exit: code 0, after printing usage, when no subcommand was given.
    """
    if ctx.invoked_subcommand is None:
        typer.echo(_USAGE)
        raise typer.Exit(code=0)

#: Verbatim bash-parity usage text — ``usage()`` in ``cmd_deliverable.sh``.
#: Printed to stdout (not stderr, matching bash's plain ``cat``) both on
#: ``promise`` with a missing required flag (exit 2) and by Typer's own
#: ``no_args_is_help``/``--help`` machinery for this sub-app.
_USAGE = (
    "shctx deliverable promise --kind=<k> --target=<ref> [--role=<r>]\n"
    "shctx deliverable complete <id>\n"
    "shctx deliverable stalled [--since-mins=<n>]"
)

#: Matches bash's ``[[ "$id" =~ ^[0-9]+$ ]]`` numeric-id guard in the
#: ``complete`` branch of ``cmd_deliverable.sh`` exactly — digits only, no
#: sign, no decimal point.
_ID_RE = re.compile(r"^[0-9]+$")

#: Column order for ``stalled``'s table rendering, matching bash's
#: ``SELECT id, agent_role, kind, target_ref, promised_at FROM
#: deliverables ...`` column list and order exactly (bash deliberately
#: omits ``project_id``, ``agent_session``, ``status``, and
#: ``delivered_at`` from this projection).
_STALLED_COLUMNS = ("id", "agent_role", "kind", "target_ref", "promised_at")

#: Column separator for the plain-text table renderer, mirroring
#: :mod:`shepherd_cli.commands.teammate`'s ``_COLUMN_GUTTER`` convention.
_COLUMN_GUTTER = "  "


class DeliverableStalled(BaseModel):
    """One row of ``shepherd deliverable stalled`` output.

    Mirrors the exact column projection bash's ``stalled`` branch
    selects: ``id, agent_role, kind, target_ref, promised_at`` — in that
    order, and nothing else (no ``project_id``, ``agent_session``,
    ``status``, or ``delivered_at``, even though the underlying
    ``deliverables`` row has all of those).

    Attributes:
        id: The deliverable's primary key.
        agent_role: The role that made the promise.
        kind: The caller-supplied deliverable kind.
        target_ref: The caller-supplied target reference.
        promised_at: Epoch-milliseconds when the promise was made.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    agent_role: str
    kind: str
    target_ref: str
    promised_at: int


def _now_ms() -> int:
    """Return the current wall-clock time in epoch milliseconds.

    Bash parity with ``cmd_deliverable.sh``'s ``now_ms() { echo $(($(date
    +%s) * 1000)); }`` — second-precision multiplied by 1000, not true
    millisecond precision, but that distinction is invisible at the
    values this CLI ever compares (whole seconds either way).

    Returns:
        The current time as milliseconds since the Unix epoch.
    """
    return int(time.time()) * 1000


async def _active_project_id() -> str:
    """Return the active project's id, bash-parity with ``project_id()``.

    Bash: ``sqlite3 "$DB" "SELECT id FROM projects LIMIT 1;"`` — no
    ``ORDER BY``, and when the ``projects`` table is empty, sqlite3 prints
    nothing, which bash's command substitution turns into an empty
    string. This mirrors that empty-string fallback exactly (rather than
    ``None``) so a ``promise`` on a not-yet-``init``'d project inserts the
    same ``project_id=''`` bash would, instead of silently behaving
    differently.

    Returns:
        The first ``projects.id``, or ``""`` if no project is registered.
    """
    project = await Project.all().first()
    return project.id if project is not None else ""


def _render_stalled_table(rows: list[DeliverableStalled]) -> str:
    """Render stalled-deliverable rows as an aligned, fixed-width text table.

    Approximates ``sqlite3 -header -column``'s output shape (a header row
    then one row per record, columns padded to their widest value) using
    the same two-space-gutter, left-justified convention as
    :func:`shepherd_cli.commands.teammate._render_liveness_table`. With
    zero rows, only the header line is printed — matching
    ``sqlite3 -header`` on an empty result set.

    Args:
        rows: Typed stalled-deliverable rows, already in display order.

    Returns:
        A multi-line string: a header row followed by one row per
        deliverable.
    """
    records = [
        (str(row.id), row.agent_role, row.kind, row.target_ref, str(row.promised_at))
        for row in rows
    ]
    widths = [len(column) for column in _STALLED_COLUMNS]
    for record in records:
        for index, value in enumerate(record):
            widths[index] = max(widths[index], len(value))
    lines = [_COLUMN_GUTTER.join(column.ljust(width) for column, width in zip(_STALLED_COLUMNS, widths, strict=True))]
    lines.extend(
        _COLUMN_GUTTER.join(value.ljust(width) for value, width in zip(record, widths, strict=True)).rstrip()
        for record in records
    )
    return "\n".join(lines)


async def _promise_async(kind: str | None, target: str | None, role: str | None) -> None:
    """Validate, then insert, one deliverable promise.

    Args:
        kind: The ``--kind`` value, or None if the flag was not given.
        target: The ``--target`` value, or None if the flag was not
            given.
        role: The ``--role`` value, or None if the flag was not given —
            falls back to ``CLAUDE_AGENT_ROLE``, then ``"unknown"``.

    Raises:
        typer.Exit: With code 2 (usage text on stdout, bash parity) if
            ``kind`` or ``target`` is missing or empty — bash's
            ``[[ -n "$kind" && -n "$target" ]] || { usage; exit 2; }``.
    """
    if not kind or not target:
        typer.echo(_USAGE)
        raise typer.Exit(code=2)

    async with db.lifespan():
        project_id = await _active_project_id()
        # Bash parity: `session="${CLAUDE_SESSION_ID:-unknown}"`. We route
        # through resolve_session_id() per the shared resolution contract
        # (hard rule: never reinvent session resolution) rather than
        # reading CLAUDE_SESSION_ID directly — resolve_session_id() checks
        # CLAUDE_SESSION_ID too, plus SHEPHERD_SESSION_ID as a first-class
        # override, so this is a strict superset of the bash behavior with
        # the same "unknown" fallback.
        session = resolve_session_id() or "unknown"
        resolved_role = role or os.environ.get("CLAUDE_AGENT_ROLE") or "unknown"
        promised_at = _now_ms()
        deliverable = await Deliverable.create(
            project_id=project_id,
            agent_session=session,
            agent_role=resolved_role,
            kind=kind,
            target_ref=target,
            promised_at=promised_at,
            status="pending",
        )
    typer.echo(str(deliverable.id))


@app.command()
def promise(
    kind: str | None = typer.Option(
        None,
        "--kind",
        help="The kind of deliverable being promised (free text, e.g. 'pr', 'doc').",
    ),
    target: str | None = typer.Option(
        None,
        "--target",
        help="What was promised (free text — a PR URL, file path, etc.).",
    ),
    role: str | None = typer.Option(
        None,
        "--role",
        help="The promising agent's role. Defaults to CLAUDE_AGENT_ROLE, then 'unknown'.",
    ),
) -> None:
    """Record a new pending deliverable promise and print its id.

    Args:
        kind: Required (validated after parsing, not via Typer's
            ``required=True``, so an empty string is rejected the same
            way a missing flag is — bash parity).
        target: Required, same validation as ``kind``.
        role: Optional; falls back to ``CLAUDE_AGENT_ROLE``, then
            ``"unknown"``.
    """
    asyncio.run(_promise_async(kind=kind, target=target, role=role))


async def _complete_async(id_str: str) -> None:
    """Validate an id, then mark that deliverable delivered.

    Args:
        id_str: The raw ``<id>`` positional argument, validated as
            all-digits before use.

    Raises:
        typer.Exit: With code 2 (stderr message) if ``id_str`` does not
            match ``^[0-9]+$`` — bash's
            ``[[ "$id" =~ ^[0-9]+$ ]] || { echo "ERR: id must be numeric" >&2; exit 2; }``.
    """
    if not _ID_RE.match(id_str):
        typer.echo("ERR: id must be numeric", err=True)
        raise typer.Exit(code=2)

    deliverable_id = int(id_str)
    async with db.lifespan():
        # Bash parity: `UPDATE deliverables SET status='delivered',
        # delivered_at=$(now_ms) WHERE id=$id;` — unconditional, no
        # existence check, no error and no output either way (an id that
        # doesn't exist just updates zero rows and still exits 0).
        await Deliverable.filter(id=deliverable_id).update(status="delivered", delivered_at=_now_ms())


@app.command()
def complete(
    id_: str = typer.Argument(..., metavar="ID", help="The deliverable id to mark delivered."),
) -> None:
    """Mark a deliverable as delivered.

    Args:
        id_: The deliverable id (must be all-digits; validated before any
            write — bash parity exits 2 on a non-numeric id without
            touching the database).
    """
    asyncio.run(_complete_async(id_str=id_))


async def _stalled_async(since_mins: int, json_out: bool) -> None:
    """Fetch and print pending deliverables older than ``since_mins``.

    Args:
        since_mins: Minutes of age before a still-``pending`` deliverable
            counts as stalled. Bash default: 10.
        json_out: When True, print a JSON array of
            :class:`DeliverableStalled` objects instead of a table.
    """
    cutoff = _now_ms() - since_mins * 60_000
    async with db.lifespan():
        # Bash parity: `SELECT id, agent_role, kind, target_ref,
        # promised_at FROM deliverables WHERE status='pending' AND
        # promised_at < $cutoff ORDER BY promised_at;` — ascending
        # (stalest/oldest promise first), exactly this column projection.
        rows = await Deliverable.filter(status="pending", promised_at__lt=cutoff).order_by("promised_at")
    views = [DeliverableStalled.model_validate(row) for row in rows]
    if json_out:
        typer.echo(json.dumps([view.model_dump(mode="json") for view in views], indent=2))
    else:
        typer.echo(_render_stalled_table(views))


@app.command()
def stalled(
    since_mins: int = typer.Option(
        10,
        "--since-mins",
        help="Minutes of age before a pending deliverable counts as stalled.",
    ),
    json_out: bool = typer.Option(
        False,
        "--json",
        help="Emit a JSON array of DeliverableStalled objects instead of a table.",
    ),
) -> None:
    """List pending deliverables promised more than ``--since-mins`` ago.

    Args:
        since_mins: Minutes of age before a pending deliverable counts as
            stalled. Bash default: 10.
        json_out: Emit JSON instead of a table.
    """
    asyncio.run(_stalled_async(since_mins=since_mins, json_out=json_out))


__all__ = ["app", "DeliverableStalled"]
