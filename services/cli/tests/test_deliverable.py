"""Subprocess parity tests for ``shepherd deliverable`` (promise/complete/stalled).

Bash parity target: ``skills/context/scripts/cmd_deliverable.sh``. Every
test drives the real CLI as a subprocess (``${PY} -m shepherd_cli
deliverable ...``), exactly like ``test_liveness_scoping.py`` — never by
importing ``shepherd_cli`` into the pytest process — and seeds/reads the
``deliverables`` table via raw ``sqlite3`` so these tests exercise the
same on-disk shape the bash tooling itself reads and writes.

Timestamps in this table are epoch-MILLISECONDS (``now_ms()`` in
``cmd_deliverable.sh``), not epoch-seconds — several assertions below
pin that down explicitly (``% 1000 == 0``, since bash's ``now_ms()`` is
second-precision multiplied by 1000).
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest
from conftest import build_full_schema_db, cli_env, insert_project, run_cli

# --------------------------------------------------------------------------
# Fixture DB + raw-sqlite3 seed/read helpers (schema-tolerant, mirroring
# conftest.insert_teammate's PRAGMA table_info approach).
# --------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """A fresh full-schema (0001_init.sql + every migrations/*.sql) fixture DB."""
    path = tmp_path / "shepherd.db"
    build_full_schema_db(path)
    return path


@pytest.fixture
def project_id(db_path: Path) -> str:
    """One seeded ``projects`` row; ``deliverables.project_id`` FKs into this."""
    return insert_project(db_path)


def insert_deliverable(
    db_path: Path,
    project_id: str,
    *,
    kind: str = "pr",
    target_ref: str = "https://example.invalid/pr/1",
    agent_session: str = "seed-session",
    agent_role: str = "engineer",
    promised_at: int,
    delivered_at: int | None = None,
    status: str = "pending",
) -> int:
    """Insert one ``deliverables`` row directly via sqlite3.

    Column-tolerant via ``PRAGMA table_info`` (mirroring
    ``conftest.insert_teammate``) even though, unlike ``teammates``, the
    ``deliverables`` table has never gained columns across migrations
    (created wholesale by ``0007_canonical_state.sql``) — kept consistent
    with the house style rather than assuming that never changes.

    Args:
        db_path: The fixture DB to write into.
        project_id: FK target in ``projects.id``.
        kind: The ``kind`` column value.
        target_ref: The ``target_ref`` column value.
        agent_session: The ``agent_session`` column value.
        agent_role: The ``agent_role`` column value.
        promised_at: Epoch-milliseconds for the ``promised_at`` column.
        delivered_at: Epoch-milliseconds for ``delivered_at``, or None to
            leave it NULL (a still-pending row).
        status: The ``status`` column value.

    Returns:
        The inserted row's autoincrement ``id``.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        columns = {info[1] for info in conn.execute("PRAGMA table_info(deliverables)")}
        fields: list[str] = [
            "project_id", "agent_session", "agent_role", "kind", "target_ref", "promised_at", "status",
        ]
        values: list[object] = [
            project_id, agent_session, agent_role, kind, target_ref, promised_at, status,
        ]
        if "delivered_at" in columns:
            fields.append("delivered_at")
            values.append(delivered_at)
        else:
            assert delivered_at is None, (
                "delivered_at given but this fixture db has no delivered_at column"
            )
        placeholders = ", ".join("?" for _ in fields)
        cursor = conn.execute(
            f"INSERT INTO deliverables ({', '.join(fields)}) VALUES ({placeholders})",  # noqa: S608 - fixed column allow-list above, no user input
            values,
        )
        conn.commit()
        assert cursor.lastrowid is not None
        return int(cursor.lastrowid)
    finally:
        conn.close()


def fetch_deliverable(db_path: Path, deliverable_id: int) -> dict[str, object]:
    """Read one ``deliverables`` row as a plain dict, or fail the test.

    Args:
        db_path: The fixture DB to read from.
        deliverable_id: The row's ``id`` to look up.

    Returns:
        The row's columns as a dict.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM deliverables WHERE id = ?", (deliverable_id,)).fetchone()
        assert row is not None, f"no deliverable row with id={deliverable_id}"
        return dict(row)
    finally:
        conn.close()


def _now_ms() -> int:
    """Test-side mirror of ``cmd_deliverable.sh``'s ``now_ms()`` (second-precision * 1000)."""
    return int(time.time()) * 1000


# --------------------------------------------------------------------------
# promise
# --------------------------------------------------------------------------


def test_promise_happy_path_inserts_pending_row_and_prints_id(db_path: Path, project_id: str) -> None:
    env = cli_env(db_path)
    before = _now_ms()
    proc = run_cli(
        ["deliverable", "promise", "--kind=pr", "--target=https://github.com/x/y/pull/1", "--role=engineer"],
        env,
    )
    after = _now_ms()

    assert proc.returncode == 0, proc.stderr
    deliverable_id = int(proc.stdout.strip())

    row = fetch_deliverable(db_path, deliverable_id)
    assert row["project_id"] == project_id
    assert row["agent_role"] == "engineer"
    assert row["kind"] == "pr"
    assert row["target_ref"] == "https://github.com/x/y/pull/1"
    assert row["status"] == "pending"
    assert row["delivered_at"] is None
    assert before <= row["promised_at"] <= after
    # Bash parity: now_ms() is second-precision * 1000 — always a whole
    # thousand, never true millisecond precision.
    assert row["promised_at"] % 1000 == 0


def test_promise_defaults_session_and_role_to_unknown(db_path: Path, project_id: str) -> None:
    # cli_env() with no session_id strips SHEPHERD_SESSION_ID/CLAUDE_SESSION_ID
    # from the subprocess environment entirely.
    env = cli_env(db_path)
    proc = run_cli(["deliverable", "promise", "--kind=doc", "--target=README.md"], env)

    assert proc.returncode == 0, proc.stderr
    deliverable_id = int(proc.stdout.strip())
    row = fetch_deliverable(db_path, deliverable_id)
    assert row["agent_session"] == "unknown"
    assert row["agent_role"] == "unknown"


def test_promise_role_falls_back_to_claude_agent_role_env(db_path: Path, project_id: str) -> None:
    env = cli_env(db_path)
    env["CLAUDE_AGENT_ROLE"] = "reviewer"
    proc = run_cli(["deliverable", "promise", "--kind=doc", "--target=README.md"], env)

    assert proc.returncode == 0, proc.stderr
    row = fetch_deliverable(db_path, int(proc.stdout.strip()))
    assert row["agent_role"] == "reviewer"


def test_promise_explicit_role_flag_wins_over_env(db_path: Path, project_id: str) -> None:
    env = cli_env(db_path)
    env["CLAUDE_AGENT_ROLE"] = "reviewer"
    proc = run_cli(["deliverable", "promise", "--kind=doc", "--target=README.md", "--role=architect"], env)

    assert proc.returncode == 0, proc.stderr
    row = fetch_deliverable(db_path, int(proc.stdout.strip()))
    assert row["agent_role"] == "architect"


def test_promise_uses_resolved_session_id(db_path: Path, project_id: str) -> None:
    env = cli_env(db_path, session_id="sess-abc-123")
    proc = run_cli(["deliverable", "promise", "--kind=pr", "--target=x"], env)

    assert proc.returncode == 0, proc.stderr
    row = fetch_deliverable(db_path, int(proc.stdout.strip()))
    assert row["agent_session"] == "sess-abc-123"


@pytest.mark.parametrize(
    "args",
    [
        ["deliverable", "promise", "--target=x"],
        ["deliverable", "promise", "--kind=pr"],
        ["deliverable", "promise", "--kind=", "--target=x"],
        ["deliverable", "promise", "--kind=pr", "--target="],
        ["deliverable", "promise"],
    ],
)
def test_promise_missing_or_empty_required_flag_exits_2_with_usage(
    db_path: Path, project_id: str, args: list[str]
) -> None:
    env = cli_env(db_path)
    proc = run_cli(args, env)

    assert proc.returncode == 2
    assert "shctx deliverable promise" in proc.stdout
    assert "shctx deliverable complete" in proc.stdout
    assert "shctx deliverable stalled" in proc.stdout


# --------------------------------------------------------------------------
# complete
# --------------------------------------------------------------------------


def test_complete_happy_path_marks_delivered(db_path: Path, project_id: str) -> None:
    promised_at = _now_ms() - 5 * 60_000
    deliverable_id = insert_deliverable(db_path, project_id, promised_at=promised_at)
    env = cli_env(db_path)

    before = _now_ms()
    proc = run_cli(["deliverable", "complete", str(deliverable_id)], env)
    after = _now_ms()

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""

    row = fetch_deliverable(db_path, deliverable_id)
    assert row["status"] == "delivered"
    assert row["delivered_at"] is not None
    assert before <= row["delivered_at"] <= after


def test_complete_nonnumeric_id_exits_2(db_path: Path, project_id: str) -> None:
    env = cli_env(db_path)
    proc = run_cli(["deliverable", "complete", "not-a-number"], env)

    assert proc.returncode == 2
    assert "ERR: id must be numeric" in proc.stderr


def test_complete_unknown_id_still_succeeds_noop(db_path: Path, project_id: str) -> None:
    """Bash parity: the UPDATE has no existence check — an id that matches
    nothing still exits 0 (0 rows affected, no error)."""
    env = cli_env(db_path)
    proc = run_cli(["deliverable", "complete", "999999"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""


# --------------------------------------------------------------------------
# stalled
# --------------------------------------------------------------------------


@pytest.fixture
def stalled_seed(db_path: Path, project_id: str) -> dict[str, int]:
    """Four deliverables spanning every branch ``stalled`` must discriminate on.

    - very_old:     pending, 40 minutes old -> stalled at every threshold tested.
    - stalled_mid:  pending, 20 minutes old -> stalled at the default (10min)
                    threshold, NOT at a 25min threshold.
    - fresh:        pending, 2 minutes old -> never stalled.
    - delivered_old: DELIVERED, 30 minutes old -> excluded by status alone,
                    regardless of age (proves the WHERE status='pending'
                    clause, not just the age clause).
    """
    now = _now_ms()
    ids = {
        "very_old": insert_deliverable(
            db_path, project_id, kind="pr", target_ref="ref-very-old", agent_role="engineer",
            promised_at=now - 40 * 60_000,
        ),
        "stalled_mid": insert_deliverable(
            db_path, project_id, kind="doc", target_ref="ref-stalled-mid", agent_role="writer",
            promised_at=now - 20 * 60_000,
        ),
        "fresh": insert_deliverable(
            db_path, project_id, kind="pr", target_ref="ref-fresh", agent_role="engineer",
            promised_at=now - 2 * 60_000,
        ),
        "delivered_old": insert_deliverable(
            db_path, project_id, kind="pr", target_ref="ref-delivered-old", agent_role="engineer",
            promised_at=now - 30 * 60_000, delivered_at=now - 25 * 60_000, status="delivered",
        ),
    }
    return ids


def test_stalled_default_threshold_filters_status_and_age_orders_ascending(
    db_path: Path, stalled_seed: dict[str, int]
) -> None:
    env = cli_env(db_path)
    proc = run_cli(["deliverable", "stalled", "--json"], env)

    assert proc.returncode == 0, proc.stderr
    rows = json.loads(proc.stdout)
    ids = [row["id"] for row in rows]

    # Ascending by promised_at: very_old (40min) is the OLDEST (smallest
    # timestamp) and sorts first.
    assert ids == [stalled_seed["very_old"], stalled_seed["stalled_mid"]]


def test_stalled_json_shape_matches_bash_column_projection(
    db_path: Path, stalled_seed: dict[str, int]
) -> None:
    env = cli_env(db_path)
    proc = run_cli(["deliverable", "stalled", "--json"], env)

    assert proc.returncode == 0, proc.stderr
    rows = json.loads(proc.stdout)
    assert len(rows) == 2
    for row in rows:
        # Bash SELECTs exactly these five columns — no project_id,
        # agent_session, status, or delivered_at.
        assert set(row.keys()) == {"id", "agent_role", "kind", "target_ref", "promised_at"}

    very_old_row = next(row for row in rows if row["id"] == stalled_seed["very_old"])
    assert very_old_row["kind"] == "pr"
    assert very_old_row["target_ref"] == "ref-very-old"
    assert very_old_row["agent_role"] == "engineer"


def test_stalled_custom_since_mins_narrows_the_window(db_path: Path, stalled_seed: dict[str, int]) -> None:
    env = cli_env(db_path)

    proc_25 = run_cli(["deliverable", "stalled", "--since-mins=25", "--json"], env)
    assert proc_25.returncode == 0, proc_25.stderr
    assert [row["id"] for row in json.loads(proc_25.stdout)] == [stalled_seed["very_old"]]

    proc_50 = run_cli(["deliverable", "stalled", "--since-mins=50", "--json"], env)
    assert proc_50.returncode == 0, proc_50.stderr
    assert json.loads(proc_50.stdout) == []


def test_stalled_delivered_row_never_appears_regardless_of_age(
    db_path: Path, stalled_seed: dict[str, int]
) -> None:
    env = cli_env(db_path)
    proc = run_cli(["deliverable", "stalled", "--since-mins=1", "--json"], env)

    assert proc.returncode == 0, proc.stderr
    ids = {row["id"] for row in json.loads(proc.stdout)}
    assert stalled_seed["delivered_old"] not in ids


def test_stalled_empty_result_json_is_empty_array(db_path: Path, project_id: str) -> None:
    env = cli_env(db_path)
    proc = run_cli(["deliverable", "stalled", "--json"], env)

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == []


def test_stalled_table_rendering_header_only_when_empty(db_path: Path, project_id: str) -> None:
    env = cli_env(db_path)
    proc = run_cli(["deliverable", "stalled"], env)

    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.rstrip("\n").splitlines()
    assert len(lines) == 1
    header = lines[0]
    assert "id" in header
    assert "agent_role" in header
    assert "kind" in header
    assert "target_ref" in header
    assert "promised_at" in header


def test_stalled_table_rendering_includes_row_values(db_path: Path, stalled_seed: dict[str, int]) -> None:
    env = cli_env(db_path)
    proc = run_cli(["deliverable", "stalled"], env)

    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.rstrip("\n").splitlines()
    assert len(lines) == 3  # header + very_old + stalled_mid
    assert "ref-very-old" in lines[1]
    assert "ref-stalled-mid" in lines[2]


# --------------------------------------------------------------------------
# Sub-app usage/exit-code parity.
# --------------------------------------------------------------------------


def test_unknown_subcommand_exits_2(db_path: Path, project_id: str) -> None:
    env = cli_env(db_path)
    proc = run_cli(["deliverable", "bogus"], env)

    assert proc.returncode == 2


def test_no_subcommand_shows_help_and_exits_0(db_path: Path, project_id: str) -> None:
    env = cli_env(db_path)
    proc = run_cli(["deliverable"], env)

    assert proc.returncode == 0, proc.stderr
    assert "promise" in proc.stdout
    assert "complete" in proc.stdout
    assert "stalled" in proc.stdout
