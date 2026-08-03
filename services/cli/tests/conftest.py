"""Shared pytest fixtures/helpers for the shepherd CLI test suite (issue #198).

Every test drives the real CLI (or a bare resolution snippet) as a fresh
``${PY}`` subprocess — never by importing ``shepherd_cli`` into the pytest
process itself. That matches how the shipped ``shepherd`` entry point is
actually invoked and keeps every test's environment (``SHCTX_DB``,
``CLAUDE_PLUGIN_ROOT``, ``SHEPHERD_SESSION_ID``, cwd, ...) fully explicit
instead of leaking through whatever pytest happened to inherit.

The canonical schema lives at ``skills/context/schema/`` (0001_init.sql +
migrations/*.sql) and is owned by bash ``shctx`` — this module is the ONE
place the test suite builds SQLite fixture databases from that schema, by
applying the same files bash's ``cmd_migrate.sh`` / ``shctx_apply_pending_
migrations`` would, in the same sorted order, via stdlib ``sqlite3``.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import pytest

# --------------------------------------------------------------------------
# Fixed locations (issue #198 contract, v6.3.3), derived from this file's own
# position so the suite runs from any clone path, worktree, or CI checkout —
# never from a hardcoded developer-machine absolute path.
# --------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[3]
CLI_ROOT = REPO_ROOT / "services" / "cli"
PY = str(CLI_ROOT / ".venv" / "bin" / "python")

SCHEMA_DIR = REPO_ROOT / "skills" / "context" / "schema"
SCHEMA_BASE_SQL = SCHEMA_DIR / "0001_init.sql"
MIGRATIONS_DIR = SCHEMA_DIR / "migrations"
MIGRATION_0007_SQL = MIGRATIONS_DIR / "0007_canonical_state.sql"

BASH_SHCTX = REPO_ROOT / "skills" / "context" / "scripts" / "shctx"
CMD_TEAMMATE_SH = REPO_ROOT / "skills" / "context" / "scripts" / "cmd_teammate.sh"

assert Path(PY).is_file(), (
    f"test venv python not found at {PY} — see services/cli/.venv "
    "(deps must already be installed there per the #198 contract)"
)
assert SCHEMA_BASE_SQL.is_file(), f"missing base schema: {SCHEMA_BASE_SQL}"
assert MIGRATIONS_DIR.is_dir(), f"missing migrations dir: {MIGRATIONS_DIR}"
assert MIGRATION_0007_SQL.is_file(), f"missing fixture migration: {MIGRATION_0007_SQL}"

# Fixture team/session identifiers shared by seeded_db and its consumers.
GHOST_TEAM = "ghost-team"
GHOST_SESSION = "ghost-session-0001"
CURRENT_TEAM = "current-team"
CURRENT_SESSION = "current-session-0001"

# Every env var a test might need to control explicitly. Stripped from the
# inherited environment before each test rebuilds exactly what it needs.
_STRIP_ENV_KEYS = (
    "SHCTX_DB",
    "SHEPHERD_WORKDIR",
    "SHEPHERD_HOME",
    "SHCTX_ROOT_OVERRIDE",
    "SHEPHERD_SESSION_ID",
    "CLAUDE_SESSION_ID",
    "CLAUDE_PLUGIN_ROOT",
    "SHCTX_SKILL_ROOT",
    "SHCTX_QUIET",
)


# --------------------------------------------------------------------------
# Schema construction (stdlib sqlite3, applied BEFORE any test process runs).
# --------------------------------------------------------------------------
def _migration_files() -> list[Path]:
    """Every migrations/NNNN_*.sql file, sorted by filename (= by version)."""
    return sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def _record_schema_version(conn: sqlite3.Connection, migration_sql: Path) -> None:
    """Insert one schema_versions row, mirroring cmd_migrate.sh's apply loop.

    Migration files (unlike 0001_init.sql) never self-insert their
    schema_versions row — the runner does it after a successful apply. This
    is that runner, for test fixtures.
    """
    version = int(migration_sql.name[:4])
    checksum = hashlib.sha256(migration_sql.read_bytes()).hexdigest()
    conn.execute(
        "INSERT OR IGNORE INTO schema_versions (version, applied_at, checksum) VALUES (?, ?, ?)",
        (version, int(time.time()), checksum),
    )


def build_full_schema_db(db_path: Path) -> None:
    """Apply 0001_init.sql then every migrations/*.sql, in sorted order.

    Leaves schema_versions fully caught up (versions 1..N all recorded) —
    the "healthy, up to date" DB shape most tests want.

    Args:
        db_path: Where to create the sqlite file. Must not already exist
            with conflicting content; parent directory must exist.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(SCHEMA_BASE_SQL.read_text())
        conn.commit()
        for migration_sql in _migration_files():
            conn.executescript(migration_sql.read_text())
            _record_schema_version(conn, migration_sql)
            conn.commit()
    finally:
        conn.close()


def build_partial_schema_db(db_path: Path) -> None:
    """Apply ONLY 0001_init.sql + 0007_canonical_state.sql (issue #200 fixture).

    schema_versions ends up holding ONLY version=1 (0001_init.sql's own
    self-insert) even though the teammates table (created by 0007) already
    exists — 0007's row is deliberately left unrecorded. declared_state
    (added by migration 0019) is absent. This reproduces the exact "DB left
    behind by an older plugin install, schema genuinely behind HEAD" shape
    that #200's self-heal (``ensure_migrated``) exists to repair.

    Args:
        db_path: Where to create the sqlite file.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(SCHEMA_BASE_SQL.read_text())
        conn.commit()
        conn.executescript(MIGRATION_0007_SQL.read_text())
        conn.commit()
    finally:
        conn.close()


def insert_project(db_path: Path, project_id: str = "proj-test") -> str:
    """Insert one projects row (teammates.project_id FKs into this).

    Args:
        db_path: The fixture DB to write into.
        project_id: The id to insert; also what active_project_id() should
            resolve to when it is the only projects row.

    Returns:
        The inserted project_id, for convenience.
    """
    now = int(time.time())
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO projects (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (project_id, "shepherd-cli-tests", now, now),
        )
        conn.commit()
    finally:
        conn.close()
    return project_id


@dataclass(frozen=True, slots=True)
class TeammateRow:
    """One teammates row to seed into a fixture DB."""

    id: str
    team_name: str
    teammate_name: str
    agent_type: str
    session_id: str | None
    status: str
    declared_state: str | None
    spawned_at: int
    last_seen_at: int


def insert_teammate(db_path: Path, project_id: str, row: TeammateRow) -> None:
    """Insert one teammates row, adapting to whether declared_state exists yet.

    A pre-0019 (partial-schema) fixture DB has no declared_state column at
    all; inserting into a column that doesn't exist would raise
    OperationalError, so the column list is built from PRAGMA table_info
    rather than assumed.

    Args:
        db_path: The fixture DB to write into.
        project_id: FK target in projects.id.
        row: The teammate fields to insert.

    Raises:
        AssertionError: If row.declared_state is set but the fixture DB
            predates migration 0019 (declared_state column absent) — that
            combination is a fixture-authoring bug, not a real scenario.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        columns = {info[1] for info in conn.execute("PRAGMA table_info(teammates)")}
        fields: list[str] = [
            "id", "project_id", "team_name", "teammate_name", "agent_type",
            "session_id", "spawned_at", "last_seen_at", "status",
        ]
        values: list[object] = [
            row.id, project_id, row.team_name, row.teammate_name, row.agent_type,
            row.session_id, row.spawned_at, row.last_seen_at, row.status,
        ]
        if "declared_state" in columns:
            fields.append("declared_state")
            values.append(row.declared_state)
        else:
            assert row.declared_state is None, (
                "declared_state given but this fixture db predates migration 0019 "
                "(no declared_state column) — build_partial_schema_db() rows must "
                "leave declared_state unset"
            )
        placeholders = ", ".join("?" for _ in fields)
        conn.execute(
            f"INSERT INTO teammates ({', '.join(fields)}) VALUES ({placeholders})",  # noqa: S608 - fixed column allow-list above, no user input
            values,
        )
        conn.commit()
    finally:
        conn.close()


@dataclass(frozen=True, slots=True)
class SeededDb:
    """A full-schema fixture DB with a 'ghost' team and a 'current' team."""

    db_path: Path
    project_id: str
    ghost_team: str = GHOST_TEAM
    ghost_session: str = GHOST_SESSION
    current_team: str = CURRENT_TEAM
    current_session: str = CURRENT_SESSION


@pytest.fixture
def seeded_db(tmp_path: Path) -> SeededDb:
    """A full-schema DB with an old 'ghost' team and a fresh 'current' team.

    Ghost team (the #195 field-bug scenario — a prior-session teammate that
    should not leak into a fresh session's default liveness view): one row,
    spawned 30 days ago, undeclared, ancient last_seen_at (also verdict-
    relevant: undeclared + stale + active -> presumed-crashed).

    Current team: spawned "now"; six rows chosen to cover every verdict
    branch in Teammate.verdict() (#193/#200 parity):
      - engineer-inprogress:        declared in-progress, STALE last_seen_at
                                     -> must read 'ok' (never presumed-crashed,
                                     the #193 fix).
      - engineer-undeclared-stale:  undeclared, active, STALE
                                     -> 'presumed-crashed'.
      - engineer-undeclared-fresh:  undeclared, booting, fresh
                                     -> 'ok'.
      - engineer-error:             declared error   -> 'error'.
      - engineer-complete:          declared complete -> 'complete'.
      - engineer-idle:              declared idle     -> 'idle'.
    """
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    project_id = insert_project(db_path)

    now_ms = int(time.time() * 1000)
    long_ago_ms = now_ms - 30 * 24 * 60 * 60 * 1000  # 30 days: well past any stale window
    stale_ms = now_ms - 20 * 60 * 1000  # 20 minutes: past the 5-min default stale window
    fresh_ms = now_ms - 10 * 1000  # 10 seconds: well within it

    insert_teammate(db_path, project_id, TeammateRow(
        id="tm-ghost-1", team_name=GHOST_TEAM, teammate_name="ghost-alpha",
        agent_type="shepherd:engineer", session_id=GHOST_SESSION,
        status="active", declared_state=None,
        spawned_at=long_ago_ms, last_seen_at=long_ago_ms,
    ))

    current_rows = (
        TeammateRow(
            id="tm-cur-inprog", team_name=CURRENT_TEAM, teammate_name="engineer-inprogress",
            agent_type="shepherd:engineer", session_id=CURRENT_SESSION,
            status="active", declared_state="in-progress",
            spawned_at=now_ms, last_seen_at=stale_ms,
        ),
        TeammateRow(
            id="tm-cur-crash", team_name=CURRENT_TEAM, teammate_name="engineer-undeclared-stale",
            agent_type="shepherd:engineer", session_id=CURRENT_SESSION,
            status="active", declared_state=None,
            spawned_at=now_ms, last_seen_at=stale_ms,
        ),
        TeammateRow(
            id="tm-cur-fresh", team_name=CURRENT_TEAM, teammate_name="engineer-undeclared-fresh",
            agent_type="shepherd:engineer", session_id=CURRENT_SESSION,
            status="booting", declared_state=None,
            spawned_at=now_ms, last_seen_at=fresh_ms,
        ),
        TeammateRow(
            id="tm-cur-error", team_name=CURRENT_TEAM, teammate_name="engineer-error",
            agent_type="shepherd:engineer", session_id=CURRENT_SESSION,
            status="active", declared_state="error",
            spawned_at=now_ms, last_seen_at=fresh_ms,
        ),
        TeammateRow(
            id="tm-cur-complete", team_name=CURRENT_TEAM, teammate_name="engineer-complete",
            agent_type="shepherd:engineer", session_id=CURRENT_SESSION,
            status="idle", declared_state="complete",
            spawned_at=now_ms, last_seen_at=fresh_ms,
        ),
        TeammateRow(
            id="tm-cur-idle", team_name=CURRENT_TEAM, teammate_name="engineer-idle",
            agent_type="shepherd:engineer", session_id=CURRENT_SESSION,
            status="idle", declared_state="idle",
            spawned_at=now_ms, last_seen_at=fresh_ms,
        ),
    )
    for row in current_rows:
        insert_teammate(db_path, project_id, row)

    return SeededDb(db_path=db_path, project_id=project_id)


# --------------------------------------------------------------------------
# Subprocess environment + invocation helpers.
# --------------------------------------------------------------------------
def clean_env_dict() -> dict[str, str]:
    """A copy of the host environment with every shepherd override stripped.

    Returns:
        An environment dict safe to build a test-specific env from: no
        SHCTX_DB / SHEPHERD_WORKDIR / session / plugin-root bleed-through
        from whatever happens to be set in the actual host environment this
        suite runs in, plus PYTHONPATH pointed at the package so `-c`
        snippets and `-m shepherd_cli` resolve regardless of subprocess cwd.
    """
    env = dict(os.environ)
    for key in _STRIP_ENV_KEYS:
        env.pop(key, None)
    env["PYTHONPATH"] = str(CLI_ROOT)
    return env


@pytest.fixture
def clean_env() -> dict[str, str]:
    """Function-scoped stripped environment, for tests that build their own."""
    return clean_env_dict()


def cli_env(db_path: Path, *, session_id: str | None = None) -> dict[str, str]:
    """The environment for driving the shepherd CLI against one fixture DB.

    Args:
        db_path: The sqlite file the CLI should read/write. Sets SHCTX_DB,
            which resolve_db_path() honors above every workdir auto-detect
            — the test does not need a real .shepherd/ layout on disk.
        session_id: When given, sets SHEPHERD_SESSION_ID so
            resolve_session_id() resolves it (drives the #195
            session-scoping branch under test).

    Returns:
        A stripped-then-rebuilt environment: SHCTX_DB, CLAUDE_PLUGIN_ROOT
        (so find_migrations_dir()/find_bash_shctx() resolve against the
        real skills/context/ tree), PYTHONPATH, and optionally
        SHEPHERD_SESSION_ID.
    """
    env = clean_env_dict()
    env["SHCTX_DB"] = str(db_path)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    if session_id is not None:
        env["SHEPHERD_SESSION_ID"] = session_id
    return env


def run_cli(args: Sequence[str], env: dict[str, str], *, timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
    """Run the shepherd CLI as a real subprocess: ``${PY} -m shepherd_cli <args>``.

    Args:
        args: Arguments after the module name, e.g. ``["teammate", "liveness"]``.
        env: The full environment to run under — see cli_env().
        timeout: Seconds to wait before the test fails with a timeout error.

    Returns:
        The completed subprocess, stdout/stderr captured as text.
    """
    return subprocess.run(
        [PY, "-m", "shepherd_cli", *args],
        env=env,
        cwd=str(CLI_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def resolve_fields(fields: Sequence[str], env: dict[str, str], cwd: Path) -> dict[str, object]:
    """Call each named zero-arg shepherd_cli.resolution function in one subprocess.

    Runs `${PY} -c "..."` rather than importing shepherd_cli.resolution into
    the pytest process, so cwd and env are exactly what the function sees —
    no reliance on pytest's own inherited state.

    Args:
        fields: Names of zero-argument functions in shepherd_cli.resolution
            to call, e.g. ("resolve_workdir", "resolve_db_path").
        env: The environment to run the subprocess under.
        cwd: The working directory to run the subprocess from (drives
            resolve_repo_root()'s git-toplevel / getcwd() fallback).

    Returns:
        A dict mapping each field name to its JSON-decoded return value.
    """
    body = ", ".join(f'"{name}": resolution.{name}()' for name in fields)
    code = f"import json\nfrom shepherd_cli import resolution\nprint(json.dumps({{{body}}}))\n"
    proc = subprocess.run(
        [PY, "-c", code],
        env=env,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, (
        f"resolution snippet failed (exit {proc.returncode}): stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    return json.loads(proc.stdout)
