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

        shipped_max = max(version for version, _ in shipped)
        shipped_cnt = len(shipped)
        try:
            row = conn.execute(
                "SELECT COALESCE(MAX(version), 0), COUNT(*) FROM schema_versions;"
            ).fetchone()
        except sqlite3.Error:
            # schema_versions missing/unreadable — nothing safe to heal;
            # the caller's own column-exists degradation is the backstop.
            return applied
        applied_max, applied_cnt = (row[0], row[1]) if row is not None else (0, 0)

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
async def lifespan(db_path: str | None = None) -> AsyncIterator[None]:
    """Tortoise ORM lifecycle for one shepherd CLI command invocation.

    Runs :func:`ensure_migrated` first (self-heal the schema before any
    query can hit a missing column), then initializes Tortoise against
    the SAME sqlite file the bash ``shctx`` tooling reads/writes.
    ``Tortoise.generate_schemas`` is NEVER called — the SQL migrations
    remain the single schema source of truth; Tortoise only mirrors
    existing tables via :mod:`shepherd_cli.models`.

    Usage::

        async with lifespan():
            rows = await queries.teammates_live(session_id)

    Args:
        db_path: Path to the sqlite database file. Defaults to
            :func:`shepherd_cli.resolution.resolve_db_path` when omitted
            (the normal CLI path; tests pass an explicit path via
            ``SHCTX_DB`` instead, which ``resolve_db_path`` already
            honors, so most callers can omit this too).

    Yields:
        None. The Tortoise connection is live for the duration of the
        ``async with`` block and is always closed on exit, including on
        an exception raised inside the block.
    """
    path = db_path if db_path is not None else resolve_db_path()
    ensure_migrated(path)
    await Tortoise.init(
        db_url=f"sqlite://{path}",
        modules={
            "models": [
                "shepherd_cli.models",
                "shepherd_cli.models_deliverable",
                "shepherd_cli.models_mem",
                "shepherd_cli.models_status",
            ]
        },
    )
    try:
        yield
    finally:
        await Tortoise.close_connections()


__all__ = ["ensure_migrated", "lifespan"]
