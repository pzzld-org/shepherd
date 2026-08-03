"""Tortoise ORM lifecycle + schema self-heal (#200).

ARCHITECTURE — COEXISTENCE: the SQL migrations under
``skills/context/schema/`` remain the single schema source of truth; this
module NEVER calls ``Tortoise.generate_schemas``. :func:`ensure_migrated`
is the CLI-side twin of ``_lib.sh``'s ``shctx_ensure_migrated`` /
``shctx_apply_pending_migrations`` (mirrored via
``skills/context/scripts/cmd_migrate.sh``'s gap-fill apply loop) — it runs
synchronously, with stdlib ``sqlite3``, BEFORE Tortoise ever opens a
connection, so Tortoise never observes a schema behind the shipped
migrations.

**READ-SAFETY (#250).** :func:`lifespan` calls :func:`ensure_migrated`
unconditionally by default, which is correct for every command that
intends to WRITE — but a command that only presents itself as an
inspection tool (``status``, ``audit``, ``style show``/``list``) has no
business mutating a live project's on-disk schema as a side effect of
being asked a question. Callers that want that guarantee pass
``lifespan(db_path, migrate=False)``, which skips :func:`ensure_migrated`
entirely and opens Tortoise against the DB exactly as it sits on disk.
Because a read-only open can then walk straight into a query against a
column a pending migration hasn't added yet, :func:`schema_is_current` is
the paired cheap pre-check: a caller opting out of self-heal is expected
to call it FIRST and refuse loudly (one stderr line, a nonzero exit) when
it returns False, rather than let a stale schema surface as a confusing
500 or a silently-empty result set.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from tortoise import Tortoise

from shepherd_cli.resolution import find_migrations_dir, resolve_db_path

#: Matches a shipped migration filename, capturing its 4-digit version,
#: e.g. ``0019_teammate_declared_state.sql`` -> ``"0019"``. Mirrors
#: _lib.sh's glob ``[0-9][0-9][0-9][0-9]_*.sql``.
_MIGRATION_NAME_RE = re.compile(r"^(\d{4})_.*\.sql$")

#: sqlite error substrings that mean "this migration was already applied
#: out-of-band" rather than a real failure — mirrors
#: ``shctx_apply_pending_migrations``'s tolerance for a sibling process
#: (or, in tests, a hand-built DB) having applied the same DDL already.
_TOLERATED_ERROR_MARKERS = ("duplicate column", "already exists")


def _shipped_migrations(migrations_dir: str) -> list[tuple[int, str]]:
    """List shipped migration files as ``(version, filename)`` pairs, sorted.

    Args:
        migrations_dir: Directory to scan for ``NNNN_*.sql`` files.

    Returns:
        Pairs sorted by filename (equivalently by version, since the
        4-digit zero-padded prefix sorts identically either way) —
        matching the order bash's nullglob loop visits them in. Returns
        an empty list if the directory cannot be listed.
    """
    try:
        names = os.listdir(migrations_dir)
    except OSError:
        return []
    shipped = [
        (int(match.group(1)), name)
        for name in names
        if (match := _MIGRATION_NAME_RE.match(name)) is not None
    ]
    shipped.sort(key=lambda pair: pair[1])
    return shipped


def _shipped_head(shipped: list[tuple[int, str]]) -> tuple[int, int]:
    """The ``(MAX(version), COUNT(*))`` a fully-caught-up DB would show for ``shipped``.

    Shared by :func:`ensure_migrated`'s fast path and :func:`schema_is_current`
    so the "what does current even mean" arithmetic lives in exactly one
    place.

    Args:
        shipped: A non-empty :func:`_shipped_migrations` result — callers
            must not pass an empty list (there is no shipped HEAD to
            compare against; both callers below short-circuit before
            reaching here in that case).

    Returns:
        ``(highest shipped version, count of shipped migration files)``.
    """
    return max(version for version, _ in shipped), len(shipped)


def _schema_versions_maxcount(conn: sqlite3.Connection) -> tuple[int, int] | None:
    """Read ``(COALESCE(MAX(version), 0), COUNT(*))`` from ``schema_versions`` via ``conn``.

    The one place ``ensure_migrated``'s fast path and :func:`schema_is_current`
    both go for the applied side of the currency comparison — factored out
    so the two callers can never drift on what "reading schema_versions"
    means.

    Args:
        conn: An already-open sqlite3 connection.

    Returns:
        ``(applied_max, applied_cnt)``, or None if ``schema_versions`` is
        missing/unreadable (mirrors ``ensure_migrated``'s own fail-soft
        contract: nothing safe to compare against).
    """
    try:
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0), COUNT(*) FROM schema_versions;"
        ).fetchone()
    except sqlite3.Error:
        return None
    return (row[0], row[1]) if row is not None else (0, 0)


def schema_is_current(db_path: str) -> bool:
    """Cheaply check whether ``db_path``'s schema is caught up to the shipped HEAD (#250).

    Read-only: opens its own short-lived sqlite3 connection (never
    Tortoise, never :func:`ensure_migrated`) purely to run the identical
    ``MAX(version)``/``COUNT(*)`` comparison :func:`ensure_migrated`'s fast
    path already does, via the SAME shared helpers
    (:func:`_shipped_head`/:func:`_schema_versions_maxcount`) — this
    function never re-derives that arithmetic itself. Intended as the
    pre-check a caller opting out of self-heal (``lifespan(migrate=False)``)
    runs BEFORE opening Tortoise, so a stale schema is refused loudly
    instead of surfacing as a missing-column crash or a silently-empty
    query result.

    Args:
        db_path: Path to the sqlite database file.

    Returns:
        True if the DB is already at (or ahead of — never possible in
        practice, but not penalized either) the shipped migration set, OR
        if there is nothing meaningful to compare (the migrations
        directory can't be located, no migration files are shipped, or
        the DB file doesn't exist yet — none of those is "behind", they
        are "nothing to be behind on", matching :func:`ensure_migrated`'s
        own fail-soft treatment of the same conditions). False if
        ``schema_versions`` is missing/unreadable (a schema at or before
        ``0001_init.sql`` that somehow lost its own bookkeeping table
        counts as behind, not "nothing to compare") or its
        ``MAX(version)``/``COUNT(*)`` falls short of the shipped HEAD.
    """
    migrations_dir = find_migrations_dir()
    if migrations_dir is None or not os.path.isfile(db_path):
        return True

    shipped = _shipped_migrations(migrations_dir)
    if not shipped:
        return True
    shipped_max, shipped_cnt = _shipped_head(shipped)

    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error:
        return False
    try:
        state = _schema_versions_maxcount(conn)
    finally:
        conn.close()
    if state is None:
        return False

    applied_max, applied_cnt = state
    return applied_max >= shipped_max and applied_cnt >= shipped_cnt


def ensure_migrated(db_path: str) -> int:
    """Self-heal a project DB to the shipped HEAD schema (#200).

    Synchronous, stdlib ``sqlite3``, run BEFORE ``Tortoise.init`` so
    Tortoise never issues a query against a column that migration files
    haven't added yet (root cause of #200: ``shctx init`` seeds only
    ``0001_init.sql``, and a DB left half-migrated — or simply never
    caught up — then 500s on ``SELECT declared_state``).

    Mirrors ``_lib.sh``'s ``shctx_ensure_migrated`` fast path (compares
    ``MAX(version)`` AND ``COUNT(*)`` of ``schema_versions`` against the
    shipped migration set — the count check catches a gap a middle
    migration left even when the max version looks current) followed by
    ``shctx_apply_pending_migrations``'s gap-fill loop when behind: every
    migration file whose 4-digit version is ABSENT from
    ``schema_versions`` gets applied, in filename order, regardless of
    whether its version is below or above the current
    ``MAX(version)`` — a true gap-fill, not merely "apply anything
    newer".

    Tolerant of ``duplicate column`` / ``already exists`` sqlite errors —
    a migration applied out-of-band (a sibling bash process, or a
    hand-built test DB seeded with a subset of migrations) is treated as
    already-applied and its version is still recorded
    (``INSERT OR IGNORE``), exactly like the bash gap-fill loop.

    Fails soft by contract: a missing migrations directory, a missing DB
    file, an unreadable ``schema_versions`` table, or any error while
    applying/recording a migration returns the count of migrations
    applied so far rather than raising. This runs on every CLI
    invocation via :func:`lifespan` and must never take a command down —
    a caller that still hits a missing column after this runs is
    expected to degrade gracefully itself (see
    :mod:`shepherd_cli.queries`) as the final backstop.

    Args:
        db_path: Path to the sqlite database file.

    Returns:
        The number of migrations applied during this call. Zero means
        either "already current" or "could not heal" — callers that need
        to distinguish those should check column presence directly; this
        function's contract is fail-soft, not fail-silent-but-honest.
    """
    applied = 0

    migrations_dir = find_migrations_dir()
    if migrations_dir is None or not os.path.isfile(db_path):
        return applied

    shipped = _shipped_migrations(migrations_dir)
    if not shipped:
        return applied

    try:
        conn = sqlite3.connect(db_path, isolation_level=None)
    except sqlite3.Error:
        return applied

    try:
        try:
            conn.execute("PRAGMA busy_timeout=5000;")
        except sqlite3.Error:
            return applied

        shipped_max, shipped_cnt = _shipped_head(shipped)
        state = _schema_versions_maxcount(conn)
        if state is None:
            # schema_versions missing/unreadable — nothing safe to heal;
            # the caller's own column-exists degradation is the backstop.
            return applied
        applied_max, applied_cnt = state

        if applied_max >= shipped_max and applied_cnt >= shipped_cnt:
            return applied  # already current — fast path, matches shctx_ensure_migrated

        try:
            known_versions = {r[0] for r in conn.execute("SELECT version FROM schema_versions;")}
        except sqlite3.Error:
            return applied

        for version, fname in shipped:
            if version in known_versions:
                continue

            sql_path = os.path.join(migrations_dir, fname)
            try:
                with open(sql_path, encoding="utf-8") as fh:
                    sql_text = fh.read()
            except OSError:
                return applied

            checksum = hashlib.sha256(sql_text.encode("utf-8")).hexdigest()
            try:
                conn.executescript(sql_text)
            except sqlite3.Error as exc:
                message = str(exc).lower()
                if not any(marker in message for marker in _TOLERATED_ERROR_MARKERS):
                    return applied  # hard failure — stop, keep what already succeeded

            try:
                conn.execute(
                    "INSERT OR IGNORE INTO schema_versions (version, applied_at, checksum) VALUES (?, ?, ?);",
                    (version, int(time.time()), checksum),
                )
            except sqlite3.Error:
                return applied

            applied += 1
            known_versions.add(version)
    finally:
        conn.close()

    return applied


@asynccontextmanager
async def lifespan(db_path: str | None = None, *, migrate: bool = True) -> AsyncIterator[None]:
    """Tortoise ORM lifecycle for one shepherd CLI command invocation.

    Runs :func:`ensure_migrated` first by default (self-heal the schema
    before any query can hit a missing column), then initializes Tortoise
    against the SAME sqlite file the bash ``shctx`` tooling reads/writes.
    ``Tortoise.generate_schemas`` is NEVER called — the SQL migrations
    remain the single schema source of truth; Tortoise only mirrors
    existing tables via :mod:`shepherd_cli.models`.

    Usage::

        async with lifespan():
            rows = await queries.teammates_live(session_id)

        # A read-only inspection command that must never mutate schema
        # as a side effect (#250) — pair with schema_is_current() first:
        async with lifespan(db_path, migrate=False):
            rows = await queries.teammates_live(session_id)

    Args:
        db_path: Path to the sqlite database file. Defaults to
            :func:`shepherd_cli.resolution.resolve_db_path` when omitted
            (the normal CLI path; tests pass an explicit path via
            ``SHCTX_DB`` instead, which ``resolve_db_path`` already
            honors, so most callers can omit this too).
        migrate: When True (the default — every existing caller keeps its
            current behavior unchanged), run :func:`ensure_migrated`
            before opening Tortoise. When False, skip it entirely and
            open Tortoise against the DB exactly as it sits on disk — for
            a command that presents itself as read-only and must not
            silently bump a live project's schema version (#250). A
            caller passing ``migrate=False`` is expected to have already
            checked :func:`schema_is_current` and refused loudly if it
            returned False; this function itself does not check it, so a
            behind schema opened this way can still surface as an
            ordinary Tortoise ``OperationalError`` on the first query that
            touches a missing column.

    Yields:
        None. The Tortoise connection is live for the duration of the
        ``async with`` block and is always closed on exit, including on
        an exception raised inside the block.
    """
    path = db_path if db_path is not None else resolve_db_path()
    if migrate:
        ensure_migrated(path)
    await Tortoise.init(
        db_url=f"sqlite://{path}",
        modules={
            "models": [
                "shepherd_cli.models",
                "shepherd_cli.models_deliverable",
                "shepherd_cli.models_mem",
                "shepherd_cli.models_status",
                "shepherd_cli.models_sprint",
                "shepherd_cli.models_style",
                "shepherd_cli.models_report",
                "shepherd_cli.models_dash",
                "shepherd_cli.models_eval",
            ]
        },
    )
    try:
        yield
    finally:
        await Tortoise.close_connections()


__all__ = ["ensure_migrated", "lifespan", "schema_is_current"]
