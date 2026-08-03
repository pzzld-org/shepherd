"""Tests for the #250 read-safety fix: ``shepherd_cli.db``'s ``migrate=False``
opt-out, ``schema_is_current``, and the read commands that now use both.

Issue #250: ``status``, ``audit``, and ``style show``/``list`` present as
read-only inspection commands but historically opened the DB through
``db.lifespan()``'s DEFAULT (``migrate=True``), which silently bumped a
live project's on-disk schema as a side effect of being asked a question.
This suite covers two layers:

1. **``shepherd_cli.db`` itself** (no CLI process, just the library) —
   ``lifespan(migrate=False)`` must leave a behind DB byte-identical;
   ``lifespan()``'s default must still self-heal exactly as before this
   fix (pinning that the opt-out did not change the opt-in path);
   ``schema_is_current`` must read False on a behind DB and True once
   healed. Every test in this section drives ``${PY} -c "..."`` snippets
   against a REAL fixture DB, never by importing ``shepherd_cli`` into the
   pytest process itself — see ``conftest.py``'s own module docstring for
   why (matches ``conftest.resolve_fields``'s established pattern for
   testing a library function without a full CLI invocation).
2. **The read commands** (``status``, ``audit``, ``style show``,
   ``style list``) — each invoked as a real CLI subprocess against a
   deliberately-behind fixture DB (only ``0001_init.sql`` seeded, mirroring
   the exact "``shctx init`` seeds only the base schema" shape #200/#250
   are both about), asserting the DB file's sha256 is untouched AND the
   operator gets the documented refusal message + exit code — not a
   traceback, not a silently-empty table, and not a silent migration.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path

from conftest import CLI_ROOT, MIGRATIONS_DIR, PY, SCHEMA_BASE_SQL, cli_env, run_cli

#: The bash-parity refusal message every #250 read command emits verbatim
#: to stderr when ``db.schema_is_current`` reads False. Duplicated here
#: (not imported) rather than importing a private module constant from
#: three separate command modules — the CLI's own observable contract is
#: the string itself, not which module owns it.
_SCHEMA_BEHIND_MSG = "schema is behind the shipped migrations; run: shepherd migrate"


# --------------------------------------------------------------------------
# Fixture-DB construction + inspection helpers.
# --------------------------------------------------------------------------
def _build_behind_db(db_path: Path) -> None:
    """Seed ONLY ``0001_init.sql`` — the #200/#250 "never caught up" shape.

    ``0001_init.sql`` self-inserts its own ``schema_versions`` row
    (``version=1``); no ``migrations/*.sql`` file is applied, so
    ``schema_versions`` ends up holding exactly one row while the shipped
    migration SET (``MIGRATIONS_DIR``'s files, disjoint from
    ``0001_init.sql`` itself — see ``shepherd_cli.resolution``) is
    whatever this checkout currently ships. As long as at least one
    migration file exists (asserted by ``conftest.py`` at import time),
    this DB is unconditionally behind.

    Args:
        db_path: Where to create the sqlite file. Must not already exist.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(SCHEMA_BASE_SQL.read_text())
        conn.commit()
    finally:
        conn.close()


def _max_migration_version() -> int:
    """The highest version among ``migrations/NNNN_*.sql`` files in this checkout."""
    files = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    assert files, "no migration files found — fixture setup is broken"
    return max(int(f.name[:4]) for f in files)


def _migration_file_count() -> int:
    """The number of ``migrations/NNNN_*.sql`` files in this checkout."""
    return len(list(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql")))


def _file_sha256(path: Path) -> str:
    """The sha256 of a file's raw bytes — the byte-identical proof #250 asks for."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _schema_versions_state(db_path: Path) -> tuple[int, int]:
    """``(MAX(version), COUNT(*))`` read directly from ``schema_versions``, bypassing the CLI."""
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("SELECT COALESCE(MAX(version), 0), COUNT(*) FROM schema_versions;").fetchone()
    finally:
        conn.close()
    return (row[0], row[1])


# --------------------------------------------------------------------------
# ``shepherd_cli.db`` library-level snippet runner (no full CLI invocation
# needed — these three functions take an explicit db_path and touch no
# other CLI state).
# --------------------------------------------------------------------------
_DB_SNIPPET = """\
import asyncio
import json
import sys

from shepherd_cli import db

mode = sys.argv[1]
db_path = sys.argv[2]

if mode == "schema_is_current":
    print(json.dumps(db.schema_is_current(db_path)))
elif mode == "ensure_migrated":
    print(json.dumps(db.ensure_migrated(db_path)))
elif mode in ("lifespan_default", "lifespan_migrate_true", "lifespan_migrate_false"):
    async def main() -> None:
        if mode == "lifespan_default":
            async with db.lifespan(db_path):
                pass
        else:
            async with db.lifespan(db_path, migrate=(mode == "lifespan_migrate_true")):
                pass

    asyncio.run(main())
    print(json.dumps(True))
else:
    raise SystemExit(f"unknown mode: {mode}")
"""


def _run_db_snippet(mode: str, db_path: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run one ``_DB_SNIPPET`` mode as a fresh subprocess against ``db_path``."""
    return subprocess.run(
        [PY, "-c", _DB_SNIPPET, mode, str(db_path)],
        env=env,
        cwd=str(CLI_ROOT),
        capture_output=True,
        text=True,
        timeout=15,
    )


# ==========================================================================
# 1. shepherd_cli.db — lifespan(migrate=False) / schema_is_current().
# ==========================================================================


def test_schema_is_current_false_on_behind_db_true_after_heal(tmp_path: Path) -> None:
    db_path = tmp_path / "shepherd.db"
    _build_behind_db(db_path)
    env = cli_env(db_path)

    before = _run_db_snippet("schema_is_current", db_path, env)
    assert before.returncode == 0, before.stderr
    assert json.loads(before.stdout) is False

    healed = _run_db_snippet("ensure_migrated", db_path, env)
    assert healed.returncode == 0, healed.stderr
    assert json.loads(healed.stdout) == _migration_file_count()

    after = _run_db_snippet("schema_is_current", db_path, env)
    assert after.returncode == 0, after.stderr
    assert json.loads(after.stdout) is True


def test_schema_is_current_true_on_already_current_db(tmp_path: Path) -> None:
    """The common case: a fresh, fully-migrated DB is never mistaken for behind."""
    db_path = tmp_path / "shepherd.db"
    _build_behind_db(db_path)
    env = cli_env(db_path)
    heal = _run_db_snippet("ensure_migrated", db_path, env)
    assert heal.returncode == 0, heal.stderr

    current = _run_db_snippet("schema_is_current", db_path, env)
    assert current.returncode == 0, current.stderr
    assert json.loads(current.stdout) is True


def test_schema_is_current_true_when_db_file_does_not_exist(tmp_path: Path) -> None:
    """Nothing to be behind on: a never-created DB is not treated as a refusal case
    (the caller's own missing-DB check is expected to run first — see status.py)."""
    db_path = tmp_path / "does-not-exist.db"
    env = cli_env(db_path)

    result = _run_db_snippet("schema_is_current", db_path, env)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) is True


def test_lifespan_migrate_false_leaves_behind_db_byte_identical(tmp_path: Path) -> None:
    """The core #250 fix: opting out of self-heal must not touch the file at all —
    not the schema_versions bookkeeping, not any other byte."""
    db_path = tmp_path / "shepherd.db"
    _build_behind_db(db_path)
    env = cli_env(db_path)

    before_state = _schema_versions_state(db_path)
    before_hash = _file_sha256(db_path)

    result = _run_db_snippet("lifespan_migrate_false", db_path, env)
    assert result.returncode == 0, result.stderr

    after_state = _schema_versions_state(db_path)
    after_hash = _file_sha256(db_path)

    assert after_state == before_state == (1, 1)  # only 0001_init.sql's own self-insert
    assert after_hash == before_hash, "lifespan(migrate=False) must not write to the DB file"


def test_lifespan_default_still_self_heals_exactly_as_today(tmp_path: Path) -> None:
    """Pins that the #250 opt-out did not change lifespan()'s existing opt-in
    (default) behavior: a bare ``lifespan(db_path)`` — no ``migrate=`` at
    all — still self-heals a behind DB, exactly like every other caller in
    this package still relies on."""
    db_path = tmp_path / "shepherd.db"
    _build_behind_db(db_path)
    env = cli_env(db_path)

    result = _run_db_snippet("lifespan_default", db_path, env)
    assert result.returncode == 0, result.stderr

    applied_max, applied_cnt = _schema_versions_state(db_path)
    assert applied_max == _max_migration_version()
    assert applied_cnt == 1 + _migration_file_count()  # 0001_init.sql's row + every migration's


def test_lifespan_migrate_true_explicit_matches_default(tmp_path: Path) -> None:
    """``migrate=True`` given explicitly behaves identically to the omitted default."""
    db_path = tmp_path / "shepherd.db"
    _build_behind_db(db_path)
    env = cli_env(db_path)

    result = _run_db_snippet("lifespan_migrate_true", db_path, env)
    assert result.returncode == 0, result.stderr

    applied_max, applied_cnt = _schema_versions_state(db_path)
    assert applied_max == _max_migration_version()
    assert applied_cnt == 1 + _migration_file_count()


# ==========================================================================
# 2. The read commands: status, audit, style show, style list — each
#    refuses on a behind DB instead of silently migrating it.
# ==========================================================================


def test_status_refuses_on_behind_schema_and_leaves_db_untouched(tmp_path: Path) -> None:
    db_path = tmp_path / "shepherd.db"
    _build_behind_db(db_path)
    env = cli_env(db_path)
    env["SHEPHERD_WORKDIR"] = str(tmp_path / "work")
    before_hash = _file_sha256(db_path)

    proc = run_cli(["status"], env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.strip() == _SCHEMA_BEHIND_MSG
    assert _file_sha256(db_path) == before_hash


def test_status_json_also_refuses_on_behind_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "shepherd.db"
    _build_behind_db(db_path)
    env = cli_env(db_path)
    env["SHEPHERD_WORKDIR"] = str(tmp_path / "work")
    before_hash = _file_sha256(db_path)

    proc = run_cli(["status", "--json"], env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.strip() == _SCHEMA_BEHIND_MSG
    assert _file_sha256(db_path) == before_hash


def test_audit_bare_invocation_refuses_on_behind_schema_before_any_stage_runs(
    tmp_path: Path,
) -> None:
    """Bare ``shepherd audit`` (no ``--verbose``) must still surface the
    refusal — the pipeline's non-verbose mode ordinarily suppresses every
    stage's own stderr, so this pre-check must run BEFORE any stage, not
    rely on a stage's own (suppressed) refusal."""
    db_path = tmp_path / "shepherd.db"
    _build_behind_db(db_path)
    env = cli_env(db_path)
    env["SHEPHERD_WORKDIR"] = str(tmp_path / "work")
    before_hash = _file_sha256(db_path)

    proc = run_cli(["audit"], env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.strip() == _SCHEMA_BEHIND_MSG
    assert _file_sha256(db_path) == before_hash


def test_audit_verbose_also_refuses_on_behind_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "shepherd.db"
    _build_behind_db(db_path)
    env = cli_env(db_path)
    env["SHEPHERD_WORKDIR"] = str(tmp_path / "work")
    before_hash = _file_sha256(db_path)

    proc = run_cli(["audit", "--verbose"], env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.strip() == _SCHEMA_BEHIND_MSG
    assert "─── lint ───" not in proc.stdout  # no stage ever started
    assert _file_sha256(db_path) == before_hash


def test_style_show_refuses_on_behind_schema_and_leaves_db_untouched(tmp_path: Path) -> None:
    db_path = tmp_path / "shepherd.db"
    _build_behind_db(db_path)
    env = cli_env(db_path)
    env["SHEPHERD_WORKDIR"] = str(tmp_path / "work")
    before_hash = _file_sha256(db_path)

    proc = run_cli(["style", "show", "python"], env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.strip() == _SCHEMA_BEHIND_MSG
    assert _file_sha256(db_path) == before_hash


def test_style_list_refuses_on_behind_schema_and_leaves_db_untouched(tmp_path: Path) -> None:
    db_path = tmp_path / "shepherd.db"
    _build_behind_db(db_path)
    env = cli_env(db_path)
    env["SHEPHERD_WORKDIR"] = str(tmp_path / "work")
    before_hash = _file_sha256(db_path)

    proc = run_cli(["style", "list"], env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.strip() == _SCHEMA_BEHIND_MSG
    assert _file_sha256(db_path) == before_hash


def test_style_bare_invocation_defaults_to_list_and_also_refuses(tmp_path: Path) -> None:
    """Bash parity (see style.py's module docstring): a bare ``shepherd
    style`` dispatches as ``list``, so it must refuse identically."""
    db_path = tmp_path / "shepherd.db"
    _build_behind_db(db_path)
    env = cli_env(db_path)
    env["SHEPHERD_WORKDIR"] = str(tmp_path / "work")
    before_hash = _file_sha256(db_path)

    proc = run_cli(["style"], env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.strip() == _SCHEMA_BEHIND_MSG
    assert _file_sha256(db_path) == before_hash


def test_style_init_still_self_heals_on_behind_schema_unlike_show_list(tmp_path: Path) -> None:
    """The write subcommands are DELIBERATELY exempt from the #250 refusal
    (see style.py's module docstring WRITE-SAFETY note): ``init`` still
    self-heals a behind DB via ``db.lifespan()``'s default, exactly as
    before this fix — a project's first ``style init`` must keep working
    on a freshly-``shctx init``'d (base-schema-only) project."""
    db_path = tmp_path / "shepherd.db"
    _build_behind_db(db_path)
    env = cli_env(db_path)
    env["SHEPHERD_WORKDIR"] = str(tmp_path / "work")

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO projects (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("proj-test", "test", 0, 0),
        )
        conn.commit()
    finally:
        conn.close()

    proc = run_cli(["style", "init", "python"], env)

    assert proc.returncode == 0, proc.stderr
    applied_max, _ = _schema_versions_state(db_path)
    assert applied_max == _max_migration_version()
