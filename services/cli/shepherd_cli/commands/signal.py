"""``shepherd signal`` — dedicated CROSS-SESSION handoff Typer sub-app (#206).

The native port of the bash ``shctx signal`` command (``cmd_signal.sh``): a
durable send/poll channel between two INDEPENDENT sessions that share a repo but
no team graph (today: the ``--staged`` plant→spawn ``seed-ready`` handoff). It is
NOT a teammate inbox — intra-session teammate↔lead messaging is the harness-native
``SendMessage``. Both this Python surface and the bash one read/write the SAME
``session_signals`` table (migration 0020), so a signal sent by either is polled
by either.

Parity with ``cmd_signal.sh`` is the bar: ``send`` requires ``--to`` and
``--kind`` (else exit 2), validates the stdin payload is JSON (else exit 1),
requires a registered project (else exit 1), and prints the new row id; ``poll``
requires ``--as``, optionally filters by ``--kind``, prints ``id kind payload``
lines (or a JSON array with ``--json``) ordered by ``sent_at``, and with
``--consume`` stamps ``consumed_at`` on the matched rows (a one-shot).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time

import typer
from pydantic import BaseModel, ConfigDict

from shepherd_cli import db
from shepherd_cli.models import Project, SessionSignal

app = typer.Typer(
    add_completion=False,
    help="Dedicated cross-session signal channel (NOT a teammate inbox; intra-session is SendMessage).",
)

_USAGE = (
    "shctx signal send --to=<recipient> --kind=<kind>   (payload JSON on stdin; prints new id)\n"
    "shctx signal poll --as=<recipient> [--kind=<kind>] [--consume] [--json]\n\n"
    "CROSS-SESSION ONLY. Intra-session teammate<->lead messaging uses native SendMessage."
)


@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context) -> None:
    """Print usage and exit 0 when no subcommand is given (bash parity).

    ``cmd_signal.sh``'s ``""|help|--help|-h) usage;;`` branch prints usage to
    stdout and exits 0; Typer's ``no_args_is_help`` would exit 2 instead, so this
    restores the exact bash no-subcommand contract.

    Args:
        ctx: The Typer/Click context; ``invoked_subcommand`` is None only when
            ``shepherd signal`` is run with no subcommand.

    Raises:
        typer.Exit: code 0, after printing usage, when no subcommand was given.
    """
    if ctx.invoked_subcommand is None:
        typer.echo(_USAGE)
        raise typer.Exit(code=0)


class SignalRow(BaseModel):
    """One ``session_signals`` row as emitted by ``signal poll --json``.

    Mirrors the columns bash's ``sqlite3 -json "SELECT * FROM session_signals"``
    returns, in the same shape, so a ``--json`` consumer sees identical fields
    from either tool.

    Attributes:
        id: The autoincrement row id (also what ``send`` prints).
        project_id: The owning project's id (FK into ``projects``).
        sender: The session/role that emitted the signal (advisory).
        recipient: The target session slug, e.g. ``spawn-<slug>``.
        kind: The signal type, e.g. ``seed-ready``.
        payload: The raw JSON payload text (unparsed, as stored).
        sent_at: Epoch milliseconds the signal was sent.
        consumed_at: Epoch milliseconds it was consumed, or None if pending.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: str
    sender: str
    recipient: str
    kind: str
    payload: str
    sent_at: int
    consumed_at: int | None


def _now_ms() -> int:
    """Return the current wall-clock time in epoch milliseconds.

    Returns:
        Milliseconds since the Unix epoch, matching ``session_signals.sent_at``
        / ``consumed_at`` and the bash ``now_ms()`` in ``cmd_signal.sh``.
    """
    return int(time.time() * 1000)


def _sender() -> str:
    """Resolve the signal sender label, bash-parity with ``cmd_signal.sh``.

    Returns:
        ``CLAUDE_TEAMMATE_NAME``, else ``SHEPHERD_SESSION_ID``, else ``"root"`` —
        the exact precedence the bash command uses. Advisory only (the recipient
        never routes on it).
    """
    return os.environ.get("CLAUDE_TEAMMATE_NAME") or os.environ.get("SHEPHERD_SESSION_ID") or "root"


async def _send_async(recipient: str, kind: str) -> None:
    """Validate the stdin payload and insert one signal row.

    Args:
        recipient: The target session slug (``--to``).
        kind: The signal type (``--kind``).

    Raises:
        typer.Exit: code 1 if the stdin payload is not valid JSON, or if no
            project is registered yet (bash-parity: both are runtime errors,
            not usage errors).
    """
    payload = sys.stdin.read()
    try:
        json.loads(payload)
    except (json.JSONDecodeError, ValueError) as exc:
        typer.echo("ERR: payload not valid JSON", err=True)
        raise typer.Exit(code=1) from exc

    async with db.lifespan():
        project = await Project.all().first()
        if project is None:
            typer.echo("ERR: no project registered (run 'shctx init')", err=True)
            raise typer.Exit(code=1)
        row = await SessionSignal.create(
            project_id=project.id,
            sender=_sender(),
            recipient=recipient,
            kind=kind,
            payload=payload,
            sent_at=_now_ms(),
        )
    typer.echo(str(row.id))


@app.command()
def send(
    to: str = typer.Option(..., "--to", help="Recipient session slug, e.g. spawn-<slug> (NOT a teammate)."),
    kind: str = typer.Option(..., "--kind", help="Signal kind, e.g. seed-ready."),
) -> None:
    """Send a cross-session signal; the JSON payload is read from stdin.

    Args:
        to: Recipient session slug (required; missing exits 2).
        kind: Signal kind (required; missing exits 2).
    """
    asyncio.run(_send_async(recipient=to, kind=kind))


async def _poll_async(recipient: str, kind: str | None, consume: bool, json_out: bool) -> None:
    """Fetch (and optionally consume) pending signals for one recipient.

    Args:
        recipient: The recipient session slug to poll (``--as``).
        kind: When set, restrict to this ``kind`` only (``--kind``).
        consume: When True, stamp ``consumed_at`` on the matched rows after
            reading them (one-shot; a re-poll then returns nothing).
        json_out: When True, print a JSON array of :class:`SignalRow`; else
            print ``id kind payload`` lines.
    """
    async with db.lifespan():
        query = SessionSignal.filter(recipient=recipient, consumed_at__isnull=True)
        if kind is not None:
            query = query.filter(kind=kind)
        rows = list(await query.order_by("sent_at"))
        if consume and rows:
            await SessionSignal.filter(id__in=[row.id for row in rows]).update(consumed_at=_now_ms())

    if json_out:
        typer.echo(json.dumps([SignalRow.model_validate(row).model_dump(mode="json") for row in rows], indent=2))
    else:
        for row in rows:
            typer.echo(f"{row.id} {row.kind} {row.payload}")


@app.command()
def poll(
    as_: str = typer.Option(..., "--as", help="Recipient session slug to poll for (NOT a teammate)."),
    kind: str | None = typer.Option(None, "--kind", help="Restrict to this signal kind only."),
    consume: bool = typer.Option(False, "--consume", help="Stamp consumed_at on matched rows (one-shot)."),
    json_out: bool = typer.Option(False, "--json", help="Emit a JSON array of SignalRow instead of text lines."),
) -> None:
    """Poll pending (unconsumed) cross-session signals for one recipient.

    Args:
        as_: Recipient session slug to poll (required; missing exits 2).
        kind: Restrict to a single kind, else all pending kinds.
        consume: One-shot consume of the matched rows after reading them.
        json_out: Emit JSON instead of text lines.
    """
    asyncio.run(_poll_async(recipient=as_, kind=kind, consume=consume, json_out=json_out))


__all__ = ["app"]
