"""``shepherd lock`` — project lock file + ``locks_history`` audit Typer sub-app.

Native port of ``skills/context/scripts/cmd_lock.sh``: a single-holder lock
coordinated through a live JSON file (``<workdir>/shepherd.lock``, read/
written directly — the SAME file :mod:`shepherd_cli.commands.status`
reports on) plus an audit trail in the ``locks_history`` table (migration
``0009_locks_mode_sprint.sql``). ``show``/``acquire``/``release``/``reap``
mirror the bash script's four ``case`` arms exactly, including its
unusual no-subcommand default (``sub="${1:-show}"`` — running ``shctx
lock`` with no arguments is NOT a usage message, it silently means
``show``).

``show``/``acquire``/``release``/``reap`` are four separate
``@app.command()``s, exactly like
:mod:`shepherd_cli.commands.signal`/:mod:`shepherd_cli.commands.deliverable`
— NOT one callback manually dispatching on a positional subcommand
string. That single-callback shape was tried first and does not work:
Click's ``Group``/``MultiCommand`` machinery (which every Typer sub-app
with a callback compiles down to — see ``typer.main.get_command``, which
builds a Group whenever ``registered_callback`` is truthy, REGARDLESS of
whether any ``@app.command()`` is registered) disables interspersed
option parsing for the group itself (``allow_interspersed_args = False``
on ``TyperGroup``): the first bare token is always claimed as the
"subcommand name" slot, and anything after it is handed to subcommand
resolution verbatim, so ``lock acquire --mode=parallel`` would parse
``acquire`` into a callback-level positional argument and then choke
trying to resolve ``--mode=parallel`` itself as a (nonexistent)
subcommand name — there is no way to attach subcommand-specific options
to a bare callback positional under Click's Group model. Four real
subcommands is the only shape where each verb's own options parse
correctly.

The one bash behavior this shape cannot reproduce is bash's custom
``*)`` fallback for a genuinely UNRECOGNIZED subcommand name (e.g.
``shctx lock bogus`` -> the exact stderr text
``ERROR: usage: shctx lock <show|acquire|release|reap>``, exit 1):
Click resolves an unknown subcommand name to its own generic
"No such command 'bogus'." UsageError (exit 2) during
``Group.resolve_command``, entirely before any callback of ours —
including the top-level one below — ever runs; reproducing bash's exact
text/exit-code here would require subclassing Typer's internal vendored
``TyperGroup``/``_click`` machinery to override command resolution, a
disproportionate amount of fragile-to-a-dependency-bump surface for one
edge case that neither ``signal.py`` nor ``deliverable.py`` (this port's
own reference groups) attempts either. This is a documented, deliberate
scope decision, not an oversight: an unrecognized ``shepherd lock``
subcommand exits 2 with Typer's own message instead of bash's exit 1
with its own message. Every OTHER bash behavior below — including the
much more surprising no-subcommand-means-``show`` default — is matched
exactly via :func:`_default`.

**Project-id resolution deviation** (matches
:mod:`shepherd_cli.commands.mem`'s documented deviation #1 exactly):
``cmd_lock.sh`` computes ``project_id=$(shctx_project_id)``
UNCONDITIONALLY at the top of the script, before dispatching to ANY
subcommand, under ``set -eu -o pipefail`` — so even ``shctx lock show``
fails with exit 1 if ``.shepherd/project.json`` is missing, despite
``show`` never using ``project_id`` for anything. This module reproduces
that exact prerequisite-gate ordering (:func:`_require_project_id` runs
first in every subcommand handler, before any subcommand-specific work),
but — like ``mem.py`` — resolves the active project via ``SELECT id FROM
projects LIMIT 1`` against the ``projects`` table rather than reading the
``project.json`` sidecar file, because that table is what the shared test
harness (:func:`tests.conftest.insert_project`) and every other ported
command group scope through. In a healthy project the two always agree
(both written once, together, by ``shctx init``).

**Corrupt lock file — deliberate ROBUSTNESS deviation** (matches
:mod:`shepherd_cli.commands.status`'s already-documented precedent for
the SAME file, see ``status.py::_read_lock_state`` and
``tests/test_status.py::test_corrupt_lock_file_still_reports_held_without_crashing``):
``cmd_lock.sh`` pipes the lock file straight into ``jq -r`` in
``release``/``reap`` with no error tolerance, so a corrupt/unparseable
lock file crashes the whole command under ``set -e`` (exit 5, jq's own
parse-error status) WITHOUT removing the file or updating
``locks_history`` — i.e. a corrupt lock file wedges the project forever,
since ``release``/``reap`` are the only two ways to clear a lock and both
would crash on it. This module never lets a corrupt lock file wedge
anything: :func:`_load_lock_json_tolerant` returns ``{}`` (never raises)
for a missing/unreadable/non-JSON/non-object lock file, so ``release``
still removes the file and stamps history (with an empty/``"null"``
session_id, matching nothing but succeeding), and ``reap`` treats an
unparseable file as maximally stale (conservatively reaps it) rather than
refusing to run. ``show`` degrades identically to ``status.py``: still
reports ``lock: held`` (the file's existence is not in question) and
simply omits the unparseable JSON body instead of crashing.

For the common case of a WELL-FORMED lock JSON object that is merely
MISSING an expected key (e.g. hand-edited or written by a future bash
version with fewer fields), :func:`_jq_r` reproduces ``jq -r``'s exact
textual semantics — a missing/``null`` key renders as the four-character
string ``"null"`` (never Python's ``None`` or empty string) — used
verbatim both in the printed message AND as the ``session_id`` SQL bind
value, exactly like bash's own ``sess=$(jq -r .holder_session_id "$lock")``
interpolated straight into the ``UPDATE ... WHERE session_id='$sess'``
clause (this module binds it as a parameter instead of interpolating it,
which is strictly safer against the SQL-injection-shaped edge case bash's
own raw string interpolation has for a ``--session`` value containing a
quote, but observably identical for any normal value).

Timestamps are epoch SECONDS throughout (``locks_history.acquired_at`` /
``released_at``, and the lock file's own ``acquired_at``), matching
``_lib.sh``'s ``shctx_now`` (``date +%s``) — NOT the epoch-millisecond
unit ``deliverables``/``teammates`` use.

``locks_history`` already has a mirroring Tortoise model
(:class:`shepherd_cli.models_status.LockHistoryRow`), but it declares only
``id`` (status only ever needs ``COUNT(*)`` on it) — nowhere near enough
columns for this module's inserts/updates, and redeclaring the same table
with more fields would collide with that existing model in the same
Tortoise app. Per the port contract's rule 8, all ``locks_history`` reads/
writes here go through raw parameterized SQL
(``Tortoise.get_connection("default").execute_query(...)``, exactly
:mod:`shepherd_cli.commands.mem`'s ``_search_entries`` pattern) instead —
so this module needs no ``models_lock.py`` at all.
"""

from __future__ import annotations

import asyncio
import json
import os
import time

import typer
from pydantic import BaseModel, ConfigDict
from tortoise import Tortoise

from shepherd_cli import db
from shepherd_cli.models import Project
from shepherd_cli.resolution import resolve_workdir

app = typer.Typer(
    add_completion=False,
    help="Project lock file (shepherd.lock) + locks_history audit trail.",
)

#: Bash-parity default ``--mode`` value (``MODE="context"`` in ``parse_kv``).
_DEFAULT_MODE = "context"

#: Seconds before a live-but-old lock still gets reaped, matching
#: ``cmd_lock.sh``'s hardcoded ``age_min > 60`` (60 MINUTES, not seconds —
#: named in seconds here only because it multiplies the minute constant).
_REAP_AGE_MINUTES = 60

_LOCK_FILENAME = "shepherd.lock"


class LockShow(BaseModel):
    """The ``shepherd lock show --json`` payload.

    Unlike the plain-text renderer (which re-serializes whatever raw JSON
    object the lock file actually contains, preserving unknown keys and
    original key order exactly like ``jq .``), this typed view exposes
    only the fields ``acquire`` ever writes — a field that is absent, or
    present with the wrong JSON type, reads as None rather than raising.

    Attributes:
        held: True if the lock file exists.
        holder_session_id: The session holding the lock, if present and a
            string.
        mode: The lock's mode, if present and a string.
        acquired_at: Epoch seconds the lock was acquired, if present and
            an int.
        pid: The holding process's pid, if present and an int.
        children: The lock's ``children`` array, if present and a list.
    """

    model_config = ConfigDict(from_attributes=True)

    held: bool
    holder_session_id: str | None = None
    mode: str | None = None
    acquired_at: int | None = None
    pid: int | None = None
    children: list[object] | None = None


def _now_s() -> int:
    """Return the current wall-clock time in epoch seconds.

    Returns:
        The current time as whole seconds since the Unix epoch, matching
        ``_lib.sh``'s ``shctx_now`` (``date +%s``) — the unit
        ``locks_history.acquired_at``/``released_at`` and the lock file's
        own ``acquired_at`` field use.
    """
    return int(time.time())


def _lock_path() -> str:
    """Resolve the live lock file's path.

    Bash parity with ``_lib.sh``'s ``shctx_lock_path``:
    ``$(shctx_artifacts_root)/shepherd.lock``, where
    ``shctx_artifacts_root`` delegates straight to ``resolve_workdir``.
    Mirrors :func:`shepherd_cli.commands.status._lock_path` exactly (small
    intentional duplication — every ported command module is
    self-contained per the port contract, so this is not imported from a
    sibling command module).

    Returns:
        The absolute path to ``shepherd.lock`` in the resolved shepherd
        work directory (need not exist on disk).
    """
    return os.path.join(resolve_workdir(), _LOCK_FILENAME)


async def _require_project_id() -> str:
    """Resolve the active project id, or exit 1 (bash-parity prerequisite gate).

    See the module docstring's "Project-id resolution deviation" note:
    ``cmd_lock.sh`` computes ``project_id=$(shctx_project_id)``
    UNCONDITIONALLY before dispatching to any subcommand, under
    ``set -eu -o pipefail`` — so a missing project aborts EVERY
    subcommand, including ``show``, with exit 1, before any
    subcommand-specific work happens. Every async handler in this module
    calls this FIRST, inside ``db.lifespan()``, to preserve that exact
    ordering.

    Returns:
        The active project id.

    Raises:
        typer.Exit: With code 1 (and a stderr message) if no project is
            registered.
    """
    project = await Project.all().first()
    if project is None:
        typer.echo("ERROR: no project registered — run 'shctx init' first", err=True)
        raise typer.Exit(code=1)
    return project.id


def _load_lock_json_tolerant(path: str) -> tuple[bool, dict[str, object]]:
    """Parse the lock file as a JSON object, tolerantly.

    See the module docstring's "Corrupt lock file" deviation note: this
    NEVER raises. A missing file, an unreadable file, invalid JSON, or
    JSON whose top level is not an object all resolve to ``(False, {})``
    — the empty dict lets every field lookup downstream degrade through
    :func:`_jq_r`'s own missing-key-is-``"null"`` handling instead of
    crashing the command, while the boolean lets :func:`_show_async`
    distinguish "genuinely an empty object" from "failed to parse" the
    same way :func:`shepherd_cli.commands.status._read_lock_state` does
    (its ``raw_dict_or_None``).

    Args:
        path: The lock file path (already confirmed to exist by the
            caller via ``os.path.isfile`` — this function tolerates it
            vanishing between that check and the read too).

    Returns:
        ``(True, parsed_object)`` on success (even an empty ``{}``
        object); ``(False, {})`` on any failure to produce one.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return False, {}
    if not isinstance(raw, dict):
        return False, {}
    return True, raw


def _jq_r(data: dict[str, object], key: str) -> str:
    """Render ``data[key]`` exactly as ``jq -r .<key>`` would print it.

    Args:
        data: A parsed lock-file JSON object (or ``{}``).
        key: The field to render.

    Returns:
        The field's value as ``jq -r`` would print it to stdout: the
        four-character string ``"null"`` for a missing key or explicit
        JSON ``null`` (jq's own behavior — NOT Python's ``None`` or an
        empty string); the string itself, unquoted, for a string value;
        ``"true"``/``"false"`` for a boolean; and the plain JSON text for
        any other JSON value (numbers, arrays, objects).
    """
    value = data.get(key)
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _is_pid_alive(pid: object) -> bool:
    """Mimic ``kill -0 "$pid" 2>/dev/null`` — is a process with this pid alive?

    Args:
        pid: The candidate pid, in whatever type it came from JSON (an
            int for a well-formed lock file; anything else for a
            corrupt/missing ``pid`` field).

    Returns:
        True if ``pid`` is a positive int naming a process that exists
        (whether or not we have permission to signal it — ``kill -0`` on
        someone else's process still reports the process exists, just
        that the caller lacks permission, which is not "not alive").
        False for a non-positive or non-int pid (never signaled — pid 0
        or a negative pid means something else entirely to ``kill(2)``,
        not "check this one process"), or a pid that does not exist.
    """
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


async def _show_async(json_out: bool) -> None:
    """Print the current lock state (``lock: held``/``lock: free``).

    Args:
        json_out: When True, print a :class:`LockShow` JSON object
            instead of the bash-parity text.

    Raises:
        typer.Exit: With code 1 if no project is registered (bash-parity
            prerequisite gate — see :func:`_require_project_id`).
    """
    async with db.lifespan():
        await _require_project_id()

    lock_path = _lock_path()
    if not os.path.isfile(lock_path):
        if json_out:
            typer.echo(LockShow(held=False).model_dump_json(indent=2))
        else:
            typer.echo("lock: free")
        return

    parsed_ok, raw = _load_lock_json_tolerant(lock_path)
    if json_out:
        typer.echo(
            LockShow(
                held=True,
                holder_session_id=raw.get("holder_session_id") if isinstance(raw.get("holder_session_id"), str) else None,
                mode=raw.get("mode") if isinstance(raw.get("mode"), str) else None,
                acquired_at=raw.get("acquired_at") if isinstance(raw.get("acquired_at"), int) else None,
                pid=raw.get("pid") if isinstance(raw.get("pid"), int) else None,
                children=raw.get("children") if isinstance(raw.get("children"), list) else None,
            ).model_dump_json(indent=2)
        )
    else:
        typer.echo("lock: held")
        # Bash-parity-with-status.py deviation: a corrupt/unparseable lock
        # file still reports "lock: held" (the file's existence is not in
        # question) but the unparseable JSON body is simply omitted rather
        # than crashing (see the module docstring).
        if parsed_ok:
            typer.echo(json.dumps(raw, indent=2))


async def _acquire_async(mode: str, session: str | None) -> None:
    """Acquire the lock: write the lock file, THEN insert a history row.

    Bash parity with ``cmd_lock.sh``'s ``acquire`` arm, including the
    exact dual-write ORDER (lock file first, ``locks_history`` insert
    second — see the module docstring's "file+table dual-write ordering"
    contract): a failure in the history insert (e.g. an invalid ``mode``
    rejected by ``locks_history``'s ``CHECK`` constraint) leaves the lock
    file written but the history row missing, exactly like bash's own
    ``jq -nc ... > "$lock"`` followed by a separate ``shctx_sql`` call
    that can fail independently under ``set -e``.

    Args:
        mode: The ``--mode`` value (default ``"context"``), passed
            through UNVALIDATED — bash never checks it either, relying on
            the ``locks_history.mode`` ``CHECK`` constraint to reject an
            invalid value at INSERT time (after the lock file already
            exists).
        session: The ``--session`` value, or None/empty to generate one.

    Raises:
        typer.Exit: With code 1 (stderr message) if the lock is already
            held — bash's ``[[ -f "$lock" ]] && { echo "ERROR: lock
            already held" >&2; exit 1; }``.
    """
    async with db.lifespan():
        project_id = await _require_project_id()
        sess = session if session else _uuid7()
        lock_path = _lock_path()
        if os.path.isfile(lock_path):
            typer.echo("ERROR: lock already held", err=True)
            raise typer.Exit(code=1)

        now = _now_s()
        pid = os.getpid()
        payload = {
            "holder_session_id": sess,
            "mode": mode,
            "acquired_at": now,
            "pid": pid,
            "children": [],
        }
        # Bash parity: `jq -nc ... > "$lock"` — compact (no whitespace),
        # and does NOT create the parent directory if it is missing
        # (bash's redirection would fail with "No such file or
        # directory" under set -e, exactly like this open() raising).
        with open(lock_path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, separators=(",", ":")))

        connection = Tortoise.get_connection("default")
        await connection.execute_query(
            "INSERT INTO locks_history (project_id, session_id, mode, acquired_at) VALUES (?, ?, ?, ?)",
            [project_id, sess, mode, now],
        )
    typer.echo(f"lock: acquired ({sess}, {mode})")


def _uuid7() -> str:
    """Generate a UUIDv7 (RFC 9562) id for a new lock's ``holder_session_id``.

    Bash generates the default session id via ``_lib.sh``'s
    ``shctx_uuid7`` (a 48-bit millisecond-timestamp-prefixed,
    timestamp-sortable UUID built from ``date +%s%3N`` and
    ``/dev/urandom``). This is an independent, equally-valid UUIDv7
    generator over the stdlib ``time``/``os.urandom`` — NOT byte-for-byte
    identical to bash's construction, but every id it produces is a
    spec-compliant, monotonically-sortable-by-creation-time UUIDv7, which
    is the only property either tool depends on. Mirrors
    :func:`shepherd_cli.commands.mem._uuid7` exactly (small intentional
    duplication — self-contained modules per the port contract).

    Returns:
        A lowercase, hyphenated UUIDv7 string.
    """
    ts_ms = int(time.time() * 1000)
    raw = bytearray(16)
    raw[0:6] = ts_ms.to_bytes(6, "big")
    rand = os.urandom(10)
    raw[6] = 0x70 | (rand[0] & 0x0F)  # version nibble (0111) + 4 random bits
    raw[7] = rand[1]
    raw[8] = 0x80 | (rand[2] & 0x3F)  # variant bits (10) + 6 random bits
    raw[9:16] = rand[3:10]
    hex_str = raw.hex()
    return f"{hex_str[0:8]}-{hex_str[8:12]}-{hex_str[12:16]}-{hex_str[16:20]}-{hex_str[20:32]}"


async def _release_async(force: bool) -> None:
    """Release the lock: remove the lock file, THEN stamp the history row.

    Bash parity with ``cmd_lock.sh``'s ``release`` arm. Per v5.0.4,
    ``--force``/``--all`` are aliases that release unconditionally (no
    liveness check — that is what ``reap`` is for); this module's
    corrupt-lock-file tolerance (see the module docstring) means the
    force/non-force code paths differ only in the stamped
    ``released_by`` value and the printed suffix, unlike bash where they
    also differ in corrupt-JSON tolerance (bash's non-force path has NO
    ``2>/dev/null`` fallback and crashes on invalid JSON; this module
    tolerates it in both paths — a deliberate, documented deviation).

    Args:
        force: True for ``--force``/``--all``.

    Raises:
        typer.Exit: With code 1 if no project is registered (bash-parity
            prerequisite gate).
    """
    async with db.lifespan():
        await _require_project_id()
        lock_path = _lock_path()
        if not os.path.isfile(lock_path):
            typer.echo("lock: free")
            return

        now = _now_s()
        _, data = _load_lock_json_tolerant(lock_path)
        sess = _jq_r(data, "holder_session_id")
        os.remove(lock_path)

        released_by = "force" if force else "normal"
        connection = Tortoise.get_connection("default")
        await connection.execute_query(
            "UPDATE locks_history SET released_at=?, released_by=? WHERE session_id=? AND released_at IS NULL",
            [now, released_by, sess],
        )
    typer.echo(f"lock: released{' (force)' if force else ''}")


async def _reap_async() -> None:
    """Reap a stale lock: dead-pid OR age>60min clears it; a live+fresh lock stays.

    Bash parity with ``cmd_lock.sh``'s ``reap`` arm: ``!kill -0 "$pid" ||
    age_min > 60`` — a dead holder process clears the lock regardless of
    age; a live holder only survives if it is also 60 minutes old or
    younger.

    Raises:
        typer.Exit: With code 1 (stderr message, no removal) if the lock
            is held by a live process younger than 60 minutes — bash's
            ``else ... exit 1`` arm. Also with code 1 if no project is
            registered (bash-parity prerequisite gate).
    """
    async with db.lifespan():
        await _require_project_id()
        lock_path = _lock_path()
        if not os.path.isfile(lock_path):
            typer.echo("lock: free")
            return

        now = _now_s()
        _, data = _load_lock_json_tolerant(lock_path)
        pid_raw = data.get("pid")
        pid = pid_raw if isinstance(pid_raw, int) and not isinstance(pid_raw, bool) else None
        pid_display = _jq_r(data, "pid")
        acquired_at_raw = data.get("acquired_at")
        acquired_at = acquired_at_raw if isinstance(acquired_at_raw, (int, float)) and not isinstance(acquired_at_raw, bool) else 0
        sess = _jq_r(data, "holder_session_id")
        # Bash parity: `age_min=$(( (now - at) / 60 ))` truncates toward
        # zero (bash `$(( ))` integer division), matching Python's
        # int(x / 60) rather than `//` (floor division diverges for a
        # future-dated acquired_at) — same idiom status.py's staleness
        # section documents for the identical reason.
        age_min = int((now - acquired_at) / 60)

        if not _is_pid_alive(pid) or age_min > _REAP_AGE_MINUTES:
            os.remove(lock_path)
            connection = Tortoise.get_connection("default")
            await connection.execute_query(
                "UPDATE locks_history SET released_at=?, released_by='reap' WHERE session_id=? AND released_at IS NULL",
                [now, sess],
            )
            typer.echo(f"lock: reaped (pid={pid_display}, age={age_min}m)")
        else:
            typer.echo(f"lock: held by live pid {pid_display} (age {age_min}m); not reaping")
            raise typer.Exit(code=1)


@app.callback(invoke_without_command=True)
def _default(
    ctx: typer.Context,
    json_out: bool = typer.Option(
        False,
        "--json",
        help="Emit a JSON object instead of the text report (the implicit 'show' default only).",
    ),
) -> None:
    """No subcommand -> ``show`` (bash parity: ``sub="${1:-show}"``, NOT a usage message).

    ``cmd_lock.sh`` treats a bare ``shctx lock`` invocation as exactly
    equivalent to ``shctx lock show`` — unlike
    :mod:`shepherd_cli.commands.signal`/:mod:`shepherd_cli.commands.deliverable`,
    whose bare invocation prints a usage message instead. This callback
    reproduces that: when no subcommand was given, it runs ``show``
    directly (including ``show``'s own project-registered prerequisite
    gate — a bare ``shepherd lock`` with no project registered exits 1,
    exactly like a bare ``shctx lock``).

    ``--json`` is declared here (not only on the ``show`` subcommand)
    specifically so ``shepherd lock --json`` (no subcommand token at all)
    works — Click's Group parsing binds options before the first
    positional/subcommand token to the group's own callback, so this is
    the only option ``show``'s implicit invocation can see.

    Args:
        ctx: The Typer/Click context; ``invoked_subcommand`` is None only
            when ``shepherd lock`` is run with no subcommand.
        json_out: ``--json`` for the implicit ``show``.
    """
    if ctx.invoked_subcommand is None:
        asyncio.run(_show_async(json_out=json_out))


@app.command()
def show(
    json_out: bool = typer.Option(
        False,
        "--json",
        help="Emit a JSON object instead of the text report.",
    ),
) -> None:
    """Print the current lock state.

    Bash parity with ``cmd_lock.sh``'s ``show`` arm: ``lock: held``
    followed by the lock file's contents pretty-printed (``jq .``), or
    ``lock: free`` if no lock file exists.

    Args:
        json_out: Emit a :class:`LockShow` JSON object instead of text.
    """
    asyncio.run(_show_async(json_out=json_out))


@app.command()
def acquire(
    mode: str = typer.Option(
        _DEFAULT_MODE,
        "--mode",
        help="Lock mode to record (passed through unvalidated; rejected by the DB CHECK constraint if invalid).",
    ),
    session: str | None = typer.Option(
        None,
        "--session",
        help="Holder session id; generated (UUIDv7) if omitted.",
    ),
) -> None:
    """Acquire the lock: write the lock file, then insert a locks_history row.

    Bash parity with ``cmd_lock.sh``'s ``acquire`` arm.

    Args:
        mode: ``--mode`` (default ``"context"``).
        session: ``--session``; generated if omitted.
    """
    asyncio.run(_acquire_async(mode=mode, session=session))


@app.command()
def release(
    force: bool = typer.Option(
        False,
        "--force",
        "--all",
        help="Release unconditionally, no liveness check (v5.0.4 aliases for the same behavior).",
    ),
) -> None:
    """Release the lock: remove the lock file, then stamp the history row.

    Bash parity with ``cmd_lock.sh``'s ``release`` arm.

    Args:
        force: ``--force``/``--all``.
    """
    asyncio.run(_release_async(force=force))


@app.command()
def reap() -> None:
    """Reap a stale lock: a dead holder process or age over 60 minutes clears it.

    Bash parity with ``cmd_lock.sh``'s ``reap`` arm. A lock held by a
    live process younger than 60 minutes is left alone (exit 1).
    """
    asyncio.run(_reap_async())


__all__ = ["app", "LockShow"]
