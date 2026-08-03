"""Tests for `shepherd status` — native port of `cmd_status.sh` (bash-parity #198-successor).

Covers: happy path with seeded rows across every table, `--json` shape and
key ordering, the "never refreshed" branch, the missing-DB validation
branch (exit 1), and — the real regression gate — byte-for-byte STDOUT
parity against the legacy `skills/context/scripts/cmd_status.sh` on the
IDENTICAL sqlite file and lock-file state, mirroring the bash-parity
pattern `test_liveness_verdict_parity.py` established for `teammate
liveness`.

Every test isolates the lock file to a throwaway `SHEPHERD_WORKDIR` (a
`tmp_path` subdirectory) — `shepherd status` (and `cmd_status.sh`) resolve
the lock path independently of `SHCTX_DB`, so without this a test would
silently read/depend on this REAL repo's `.artifacts/`/`.shepherd/`
directory instead of a hermetic fixture.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import time
from pathlib import Path

from conftest import (
    MIGRATIONS_DIR,
    REPO_ROOT,
    SCHEMA_BASE_SQL,
    build_full_schema_db,
    clean_env_dict,
    insert_project,
    run_cli,
)

CMD_STATUS_SH = REPO_ROOT / "skills" / "context" / "scripts" / "cmd_status.sh"

#: `cmd_status.sh`'s exact `for t in ...` loop order (the "Tables (rows):" section).
EXPECTED_TABLE_ORDER = (
    "projects",
    "sessions",
    "profiles_defs",
    "mem_entries",
    "index_symbols",
    "index_concepts",
    "index_issues",
    "index_prs",
    "index_releases",
    "index_milestones",
    "logs_events",
    "artifacts",
    "locks_history",
)

#: `cmd_status.sh`'s exact "Refresh staleness:" loop order.
EXPECTED_STALENESS_ORDER = (
    "index_symbols",
    "index_issues",
    "index_prs",
    "index_releases",
    "index_milestones",
)


def _max_migration_version() -> int:
    """The highest migration version `build_full_schema_db` applies.

    Mirrors what `MAX(version) FROM schema_versions` resolves to on a
    freshly built full-schema fixture DB (every migration file's version
    gets its own recorded row, in addition to `0001_init.sql`'s own
    self-inserted `version=1`).
    """
    files = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    assert files, "no migration files found — fixture setup is broken"
    return max(int(f.name[:4]) for f in files)


def _status_env(db_path: Path, workdir: Path) -> dict[str, str]:
    """Environment for `shepherd status` (and `cmd_status.sh`), isolated to `workdir`.

    Sets `SHCTX_DB` (so both tools read/write the exact fixture DB) AND
    `SHEPHERD_WORKDIR` (so both tools' lock-file lookup — independent of
    `SHCTX_DB` — resolves inside `workdir`, never the real repo's
    `.shepherd`/`.artifacts`).

    Args:
        db_path: The fixture sqlite file.
        workdir: The throwaway directory `shepherd.lock` is read from/
            written to; need not exist yet.

    Returns:
        A stripped-then-rebuilt environment safe for `run_cli` or a raw
        `subprocess.run` against `cmd_status.sh` directly.
    """
    env = clean_env_dict()
    env["SHCTX_DB"] = str(db_path)
    env["SHEPHERD_WORKDIR"] = str(workdir)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    return env


def _run_bash_status(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the legacy `cmd_status.sh` directly (bash-parity twin of `run_cli`)."""
    return subprocess.run(
        ["bash", str(CMD_STATUS_SH)],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )


def _write_lock_file(workdir: Path, *, holder: str = "sess-xyz", mode: str = "autorun") -> dict[str, object]:
    """Write a `shepherd.lock` file shaped exactly like `cmd_lock.sh` writes it.

    Key order matters for the bash-parity assertion: `jq .` (and this
    suite's Python renderer) both preserve source key order, so this
    must match `cmd_lock.sh`'s `jq -nc` object literal order exactly:
    `holder_session_id, mode, acquired_at, pid, children`.

    Args:
        workdir: The directory to write `shepherd.lock` into (created if
            missing).
        holder: The `holder_session_id` value.
        mode: The `mode` value (one of the `locks_history.mode` CHECK
            values; not itself validated here).

    Returns:
        The dict that was written, for the caller to assert against.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    data = {
        "holder_session_id": holder,
        "mode": mode,
        "acquired_at": 1234567890,
        "pid": 4242,
        "children": [],
    }
    (workdir / "shepherd.lock").write_text(json.dumps(data))
    return data


def _insert_row(db_path: Path, table: str, **columns: object) -> None:
    """Insert one row into `table` via a fixed, hardcoded column list.

    Unlike `conftest.insert_teammate` this does NOT need to be
    schema-tolerant (every column here is part of `0001_init.sql`'s
    baseline schema, present on every fixture DB `build_full_schema_db`
    produces) — callers below pass exactly the NOT NULL / CHECK-satisfying
    columns each table requires.

    Args:
        db_path: The fixture DB to write into.
        table: The table name (from a fixed set of call sites below —
            never user input).
        **columns: Column name -> value pairs for one row.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        keys = list(columns.keys())
        placeholders = ", ".join("?" for _ in keys)
        conn.execute(
            f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({placeholders})",  # noqa: S608 - fixed table/column names from hardcoded call sites, no user input
            [columns[k] for k in keys],
        )
        conn.commit()
    finally:
        conn.close()


def _seed_all_tables(db_path: Path, project_id: str, now_s: int) -> None:
    """Seed every table `shepherd status` counts, with varied row counts and staleness.

    Row counts chosen to be distinguishable per table (no two tables end
    up with the same count by accident, so an ordering/label bug in the
    renderer can't hide behind coincidentally-equal numbers). `index_prs`
    is deliberately left EMPTY — it is the fixture's "never refreshed"
    case (`COALESCE(MAX(refreshed_at),0)` -> `age="never"`). The other
    four staleness tables get `refreshed_at` set 10, 20, 30, and 40
    minutes in the past respectively (well clear of a minute-boundary
    flip between the bash and Python subprocess runs in the parity
    tests).

    Args:
        db_path: The fixture DB to seed.
        project_id: FK target in `projects.id` (already inserted by the
            caller via `insert_project`).
        now_s: The current time in epoch SECONDS, used to derive
            `refreshed_at`/`acquired_at`/`started_at` values relative to
            "now".
    """
    _insert_row(db_path, "sessions", id="sess-1", project_id=project_id, started_at=now_s)
    _insert_row(db_path, "sessions", id="sess-2", project_id=project_id, started_at=now_s)

    _insert_row(
        db_path,
        "profiles_defs",
        id="prof-1",
        project_id=project_id,
        name="strict",
        kind="modifier",
        config="{}",
        created_at=now_s,
        updated_at=now_s,
    )

    for i in range(3):
        _insert_row(
            db_path,
            "mem_entries",
            id=f"mem-{i}",
            project_id=project_id,
            kind="note",
            title=f"note {i}",
            body="body",
            created_at=now_s,
            updated_at=now_s,
        )

    _insert_row(
        db_path,
        "index_symbols",
        id="sym-1",
        project_id=project_id,
        name="Foo",
        kind="fn",
        package="pkg",
        file_path="f.rs",
        language="rust",
        hash="h1",
        refreshed_at=now_s - 10 * 60 - 5,
    )
    _insert_row(
        db_path,
        "index_symbols",
        id="sym-2",
        project_id=project_id,
        name="Bar",
        kind="fn",
        package="pkg",
        file_path="g.rs",
        language="rust",
        hash="h2",
        refreshed_at=now_s - 5 * 60,  # freshest row → MAX(refreshed_at) picks it → staleness reads 5 min, not 10
    )

    _insert_row(
        db_path,
        "index_concepts",
        id="concept-1",
        project_id=project_id,
        concept="widget",
        canonical_symbol_id="sym-1",
    )

    _insert_row(
        db_path,
        "index_issues",
        id="issue-1",
        project_id=project_id,
        source="github",
        number=1,
        title="bug",
        state="open",
        url="https://example.test/issues/1",
        created_at=now_s,
        updated_at=now_s,
        refreshed_at=now_s - 20 * 60 - 5,
    )

    # index_prs: deliberately left empty (the "never" staleness case).

    _insert_row(
        db_path,
        "index_releases",
        id="rel-1",
        project_id=project_id,
        source="github",
        tag="v1.0.0",
        url="https://example.test/releases/v1.0.0",
        refreshed_at=now_s - 30 * 60 - 5,
    )

    _insert_row(
        db_path,
        "index_milestones",
        id="mile-1",
        project_id=project_id,
        source="github",
        number=1,
        title="v1.0",
        state="open",
        url="https://example.test/milestones/1",
        refreshed_at=now_s - 40 * 60 - 5,
    )

    for i in range(4):
        _insert_row(
            db_path,
            "logs_events",
            project_id=project_id,
            ts=now_s,
            level="info",
            source="test",
            event=f"event-{i}",
        )

    for i in range(2):
        _insert_row(
            db_path,
            "artifacts",
            id=f"art-{i}",
            project_id=project_id,
            kind="doc",
            path=f"/tmp/art-{i}.md",
            hash=f"hash-{i}",
            created_at=now_s,
            updated_at=now_s,
        )

    _insert_row(
        db_path,
        "locks_history",
        project_id=project_id,
        session_id="sess-1",
        mode="autorun",
        acquired_at=now_s,
    )


# --------------------------------------------------------------------------
# Missing-DB validation branch (exit 1, bash-parity error message).
# --------------------------------------------------------------------------
def test_missing_db_exits_1_with_bash_parity_message(tmp_path: Path) -> None:
    db_path = tmp_path / "shepherd.db"  # never created
    workdir = tmp_path / "work"
    env = _status_env(db_path, workdir)

    proc = run_cli(["status"], env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.strip() == f"ERROR: no DB at {db_path} — run 'shctx init'"


def test_missing_db_bash_parity(tmp_path: Path) -> None:
    """Python and bash must fail identically — same exit code, same stderr."""
    db_path = tmp_path / "shepherd.db"
    workdir = tmp_path / "work"
    env = _status_env(db_path, workdir)

    python_proc = run_cli(["status"], env)
    bash_proc = _run_bash_status(env)

    assert python_proc.returncode == bash_proc.returncode == 1
    assert python_proc.stdout == bash_proc.stdout == ""
    assert python_proc.stderr == bash_proc.stderr


# --------------------------------------------------------------------------
# Behind-schema validation branch (#250) — distinct from the missing-DB
# branch above: the DB file exists but its schema predates the shipped
# migration set. See tests/test_db_readonly.py for the full #250 suite
# (library-level lifespan(migrate=False)/schema_is_current() coverage plus
# the sha256-unchanged assertion shared by status/audit/style); this test
# pins that `shepherd status` specifically still refuses correctly and
# keeps this file's own missing-DB-vs-behind-schema branches distinguished
# in one place.
# --------------------------------------------------------------------------
def test_behind_schema_refuses_distinctly_from_missing_db(tmp_path: Path) -> None:
    db_path = tmp_path / "shepherd.db"
    workdir = tmp_path / "work"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(SCHEMA_BASE_SQL.read_text())  # ONLY 0001_init.sql — no migrations applied
        conn.commit()
    finally:
        conn.close()
    env = _status_env(db_path, workdir)

    proc = run_cli(["status"], env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.strip() == "schema is behind the shipped migrations; run: shepherd migrate"
    # Distinct message from the missing-DB branch above — never confusable.
    assert "ERROR: no DB at" not in proc.stderr


# --------------------------------------------------------------------------
# Empty DB / free lock — the all-zeros, all-"never" baseline.
# --------------------------------------------------------------------------
def test_empty_schema_db_bash_parity_free_lock(tmp_path: Path) -> None:
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    workdir = tmp_path / "work"  # never created -> no lock file -> free
    env = _status_env(db_path, workdir)

    python_proc = run_cli(["status"], env)
    bash_proc = _run_bash_status(env)

    assert python_proc.returncode == 0, python_proc.stderr
    assert bash_proc.returncode == 0, bash_proc.stderr
    assert python_proc.stdout == bash_proc.stdout

    expected_version = _max_migration_version()
    assert f"Schema version: {expected_version}" in python_proc.stdout
    assert "Lock: free" in python_proc.stdout
    for table in EXPECTED_TABLE_ORDER:
        assert f"  {table:<20} 0" in python_proc.stdout
    assert "  index_symbols        never" in python_proc.stdout


# --------------------------------------------------------------------------
# Seeded rows across every table + one "never" staleness table.
# --------------------------------------------------------------------------
def test_seeded_tables_and_staleness_bash_parity(tmp_path: Path) -> None:
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    project_id = insert_project(db_path)
    now_s = int(time.time())
    _seed_all_tables(db_path, project_id, now_s)
    workdir = tmp_path / "work"
    env = _status_env(db_path, workdir)

    python_proc = run_cli(["status"], env)
    bash_proc = _run_bash_status(env)

    assert python_proc.returncode == 0, python_proc.stderr
    assert bash_proc.returncode == 0, bash_proc.stderr
    assert python_proc.stdout == bash_proc.stdout, (
        f"python:\n{python_proc.stdout}\n---\nbash:\n{bash_proc.stdout}"
    )

    expected_counts = {
        "projects": 1,
        "sessions": 2,
        "profiles_defs": 1,
        "mem_entries": 3,
        "index_symbols": 2,
        "index_concepts": 1,
        "index_issues": 1,
        "index_prs": 0,
        "index_releases": 1,
        "index_milestones": 1,
        "logs_events": 4,
        "artifacts": 2,
        "locks_history": 1,
    }
    for table, count in expected_counts.items():
        assert f"  {table:<20} {count}" in python_proc.stdout, python_proc.stdout

    assert "  index_symbols        5 min ago" in python_proc.stdout
    assert "  index_issues         20 min ago" in python_proc.stdout
    assert "  index_prs            never" in python_proc.stdout
    assert "  index_releases       30 min ago" in python_proc.stdout
    assert "  index_milestones     40 min ago" in python_proc.stdout


def test_table_row_order_matches_bash_loop_order(tmp_path: Path) -> None:
    """The "Tables (rows):" lines appear in `cmd_status.sh`'s exact loop order."""
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    workdir = tmp_path / "work"
    env = _status_env(db_path, workdir)

    proc = run_cli(["status"], env)
    assert proc.returncode == 0, proc.stderr

    lines = proc.stdout.splitlines()
    start = lines.index("Tables (rows):") + 1
    table_names_in_output = [line.strip().split()[0] for line in lines[start : start + len(EXPECTED_TABLE_ORDER)]]
    assert table_names_in_output == list(EXPECTED_TABLE_ORDER)


def test_staleness_row_order_matches_bash_loop_order(tmp_path: Path) -> None:
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    workdir = tmp_path / "work"
    env = _status_env(db_path, workdir)

    proc = run_cli(["status"], env)
    assert proc.returncode == 0, proc.stderr

    lines = proc.stdout.splitlines()
    start = lines.index("Refresh staleness:") + 1
    names_in_output = [line.strip().split()[0] for line in lines[start : start + len(EXPECTED_STALENESS_ORDER)]]
    assert names_in_output == list(EXPECTED_STALENESS_ORDER)


# --------------------------------------------------------------------------
# Lock state — held (with pretty-printed JSON) vs free.
# --------------------------------------------------------------------------
def test_lock_held_bash_parity_pretty_prints_like_jq(tmp_path: Path) -> None:
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    workdir = tmp_path / "work"
    lock_data = _write_lock_file(workdir)
    env = _status_env(db_path, workdir)

    python_proc = run_cli(["status"], env)
    bash_proc = _run_bash_status(env)

    assert python_proc.returncode == 0, python_proc.stderr
    assert bash_proc.returncode == 0, bash_proc.stderr
    assert python_proc.stdout == bash_proc.stdout

    assert "Lock: held" in python_proc.stdout
    # jq's default pretty-print == json.dumps(..., indent=2) for this shape
    # (verified: both use 2-space indent, ", "-free item separators, and
    # preserve the source object's key insertion order).
    assert json.dumps(lock_data, indent=2) in python_proc.stdout


def test_lock_free_when_no_lock_file(tmp_path: Path) -> None:
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    workdir = tmp_path / "work"
    env = _status_env(db_path, workdir)

    proc = run_cli(["status"], env)

    assert proc.returncode == 0, proc.stderr
    assert "Lock: free" in proc.stdout
    assert "Lock: held" not in proc.stdout


def test_corrupt_lock_file_still_reports_held_without_crashing(tmp_path: Path) -> None:
    """Deliberate ROBUSTNESS deviation from bash: `cmd_status.sh` pipes a
    corrupt lock file straight into `jq .`, which fails and (under
    `set -eu -o pipefail`) aborts the whole script non-zero. `shepherd
    status` degrades instead: still reports `Lock: held` (the file
    exists — that fact is not in question) and simply omits the
    unparseable JSON body, rather than crashing a read-only status
    command over one corrupt debug file."""
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    workdir = tmp_path / "work"
    workdir.mkdir(parents=True)
    (workdir / "shepherd.lock").write_text("{not valid json")
    env = _status_env(db_path, workdir)

    proc = run_cli(["status"], env)

    assert proc.returncode == 0, proc.stderr
    assert "Lock: held" in proc.stdout


# --------------------------------------------------------------------------
# --json shape.
# --------------------------------------------------------------------------
def test_json_shape_empty_db(tmp_path: Path) -> None:
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    workdir = tmp_path / "work"
    env = _status_env(db_path, workdir)

    proc = run_cli(["status", "--json"], env)
    assert proc.returncode == 0, proc.stderr

    payload = json.loads(proc.stdout)
    assert payload["schema_version"] == _max_migration_version()
    assert payload["tables"] == {table: 0 for table in EXPECTED_TABLE_ORDER}
    assert list(payload["tables"].keys()) == list(EXPECTED_TABLE_ORDER)
    assert payload["staleness"] == {table: None for table in EXPECTED_STALENESS_ORDER}
    assert payload["lock"] == {"held": False, "holder": None}


def test_json_shape_with_seeded_rows_and_held_lock(tmp_path: Path) -> None:
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    project_id = insert_project(db_path)
    now_s = int(time.time())
    _seed_all_tables(db_path, project_id, now_s)
    workdir = tmp_path / "work"
    _write_lock_file(workdir, holder="sess-abc", mode="parallel")
    env = _status_env(db_path, workdir)

    proc = run_cli(["status", "--json"], env)
    assert proc.returncode == 0, proc.stderr

    payload = json.loads(proc.stdout)
    assert payload["tables"] == {
        "projects": 1,
        "sessions": 2,
        "profiles_defs": 1,
        "mem_entries": 3,
        "index_symbols": 2,
        "index_concepts": 1,
        "index_issues": 1,
        "index_prs": 0,
        "index_releases": 1,
        "index_milestones": 1,
        "logs_events": 4,
        "artifacts": 2,
        "locks_history": 1,
    }
    assert payload["staleness"]["index_prs"] is None
    assert payload["staleness"]["index_symbols"] == 5  # MAX(refreshed_at) picks the freshest of the two seeded rows
    assert payload["staleness"]["index_issues"] == 20
    assert payload["staleness"]["index_releases"] == 30
    assert payload["staleness"]["index_milestones"] == 40
    assert payload["lock"] == {"held": True, "holder": "sess-abc"}


def test_json_missing_db_still_exits_1_not_a_json_error_blob(tmp_path: Path) -> None:
    """`--json` does not change the missing-DB validation branch: still a
    plain stderr message and exit 1, never a JSON error payload on stdout
    (there is nothing valid to serialize)."""
    db_path = tmp_path / "shepherd.db"
    workdir = tmp_path / "work"
    env = _status_env(db_path, workdir)

    proc = run_cli(["status", "--json"], env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "ERROR: no DB at" in proc.stderr
