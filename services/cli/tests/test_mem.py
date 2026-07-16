"""Subprocess parity tests for ``shepherd mem`` (add/list/search/show/pin/unpin/rm).

Bash parity target: ``skills/context/scripts/cmd_mem.sh``. Every test
drives the real CLI as a subprocess (``${PY} -m shepherd_cli mem ...``),
exactly like ``test_liveness_scoping.py``/``test_deliverable.py`` — never
by importing ``shepherd_cli`` into the pytest process — and seeds/reads
the ``mem_entries`` table via raw ``sqlite3`` so these tests exercise the
same on-disk shape the bash tooling itself reads and writes.

Timestamps in this table are epoch-SECONDS (``shctx_now`` = ``date
+%s``), NOT epoch-milliseconds — the opposite unit from ``teammates``/
``deliverables``. Several assertions below pin that down explicitly.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path

import pytest
from conftest import build_full_schema_db, cli_env, insert_project, run_cli

# UUIDv7 shape: 8-4-4-4-12 hex, version nibble '7', variant nibble in [8-b].
_UUID7_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


# --------------------------------------------------------------------------
# Fixture DB + raw-sqlite3 seed/read helpers (schema-tolerant, mirroring
# conftest.insert_teammate's / test_deliverable.insert_deliverable's PRAGMA
# table_info approach).
# --------------------------------------------------------------------------
@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """A fresh full-schema (0001_init.sql + every migrations/*.sql) fixture DB."""
    path = tmp_path / "shepherd.db"
    build_full_schema_db(path)
    return path


@pytest.fixture
def project_id(db_path: Path) -> str:
    """One seeded ``projects`` row; ``mem_entries.project_id`` FKs into this."""
    return insert_project(db_path)


def insert_mem_entry(
    db_path: Path,
    project_id: str,
    *,
    entry_id: str,
    kind: str = "note",
    title: str = "Untitled",
    body: str = "",
    tags: str = "[]",
    pinned: int = 0,
    created_at: int,
    updated_at: int | None = None,
) -> None:
    """Insert one ``mem_entries`` row directly via sqlite3.

    Column-tolerant via ``PRAGMA table_info`` (house style, mirroring
    ``conftest.insert_teammate`` / ``test_deliverable.insert_deliverable``).

    Args:
        db_path: The fixture DB to write into.
        project_id: FK target in ``projects.id``.
        entry_id: The primary key to insert.
        kind: The ``kind`` column value.
        title: The ``title`` column value.
        body: The ``body`` column value.
        tags: JSON-array text for the ``tags`` column.
        pinned: ``0`` or ``1``.
        created_at: Epoch SECONDS for ``created_at``.
        updated_at: Epoch SECONDS for ``updated_at``; defaults to
            ``created_at`` when omitted.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        columns = {info[1] for info in conn.execute("PRAGMA table_info(mem_entries)")}
        fields = ["id", "project_id", "kind", "title", "body", "tags", "pinned", "created_at", "updated_at"]
        assert columns.issuperset(fields), f"mem_entries missing expected columns: {fields} not subset of {columns}"
        values: list[object] = [
            entry_id, project_id, kind, title, body, tags, pinned,
            created_at, updated_at if updated_at is not None else created_at,
        ]
        placeholders = ", ".join("?" for _ in fields)
        conn.execute(
            f"INSERT INTO mem_entries ({', '.join(fields)}) VALUES ({placeholders})",  # noqa: S608 - fixed column allow-list above, no user input
            values,
        )
        conn.commit()
    finally:
        conn.close()


def fetch_mem_entry(db_path: Path, entry_id: str) -> dict[str, object]:
    """Read one ``mem_entries`` row as a plain dict, or fail the test.

    Args:
        db_path: The fixture DB to read from.
        entry_id: The row's ``id`` to look up.

    Returns:
        The row's columns as a dict.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM mem_entries WHERE id = ?", (entry_id,)).fetchone()
        assert row is not None, f"no mem_entries row with id={entry_id}"
        return dict(row)
    finally:
        conn.close()


def count_mem_entries(db_path: Path) -> int:
    """Total row count in ``mem_entries``, across all projects."""
    conn = sqlite3.connect(str(db_path))
    try:
        return int(conn.execute("SELECT COUNT(*) FROM mem_entries").fetchone()[0])
    finally:
        conn.close()


def _now() -> int:
    """Test-side mirror of ``_lib.sh``'s ``shctx_now`` (epoch seconds)."""
    return int(time.time())


# --------------------------------------------------------------------------
# add
# --------------------------------------------------------------------------


def test_add_happy_path_inserts_row_and_prints_id(db_path: Path, project_id: str) -> None:
    env = cli_env(db_path)
    before = _now()
    proc = run_cli(["mem", "add", "--title=My First Note"], env)
    after = _now()

    assert proc.returncode == 0, proc.stderr
    entry_id = proc.stdout.strip()
    assert _UUID7_RE.match(entry_id), f"not a UUIDv7: {entry_id!r}"

    row = fetch_mem_entry(db_path, entry_id)
    assert row["project_id"] == project_id
    assert row["kind"] == "note"  # bash default
    assert row["title"] == "My First Note"
    assert row["body"] == ""  # bash default
    assert row["tags"] == "[]"  # bash default
    assert row["pinned"] == 0
    assert before <= row["created_at"] <= after
    assert row["created_at"] == row["updated_at"]


def test_add_all_flags_set_every_column(db_path: Path, project_id: str) -> None:
    env = cli_env(db_path)
    proc = run_cli(
        [
            "mem", "add",
            "--title=Decision about X",
            "--kind=decision",
            "--body=We chose X because Y.",
            '--tags=["arch","decision"]',
        ],
        env,
    )

    assert proc.returncode == 0, proc.stderr
    row = fetch_mem_entry(db_path, proc.stdout.strip())
    assert row["kind"] == "decision"
    assert row["title"] == "Decision about X"
    assert row["body"] == "We chose X because Y."
    assert row["tags"] == '["arch","decision"]'


def test_add_prior_kind_accepted(db_path: Path, project_id: str) -> None:
    """Migration 0011 widened the CHECK to add 'prior' — must be accepted."""
    env = cli_env(db_path)
    proc = run_cli(["mem", "add", "--title=Harvested lesson", "--kind=prior"], env)

    assert proc.returncode == 0, proc.stderr
    row = fetch_mem_entry(db_path, proc.stdout.strip())
    assert row["kind"] == "prior"


def test_add_missing_title_exits_1(db_path: Path, project_id: str) -> None:
    env = cli_env(db_path)
    before = count_mem_entries(db_path)
    proc = run_cli(["mem", "add"], env)

    assert proc.returncode == 1
    assert "ERROR: --title required" in proc.stderr
    assert count_mem_entries(db_path) == before  # nothing written


def test_add_empty_title_flag_exits_1(db_path: Path, project_id: str) -> None:
    env = cli_env(db_path)
    proc = run_cli(["mem", "add", "--title="], env)

    assert proc.returncode == 1
    assert "ERROR: --title required" in proc.stderr


def test_add_no_project_registered_exits_1_before_title_check(db_path: Path) -> None:
    """No ``projects`` row at all: the project-resolution gate fires FIRST,
    even when --title is also missing (bash-parity ordering — project_id
    resolves unconditionally at the top of cmd_mem.sh, before dispatch)."""
    env = cli_env(db_path)  # no project_id fixture used -> no projects row
    proc = run_cli(["mem", "add"], env)

    assert proc.returncode == 1
    assert "no project registered" in proc.stderr
    assert "--title required" not in proc.stderr


def test_add_invalid_kind_rejected_by_check_constraint(db_path: Path, project_id: str) -> None:
    env = cli_env(db_path)
    before = count_mem_entries(db_path)
    proc = run_cli(["mem", "add", "--title=X", "--kind=not-a-real-kind"], env)

    assert proc.returncode != 0
    assert count_mem_entries(db_path) == before  # nothing written


def test_add_invalid_tags_json_rejected_by_check_constraint(db_path: Path, project_id: str) -> None:
    env = cli_env(db_path)
    before = count_mem_entries(db_path)
    proc = run_cli(["mem", "add", "--title=X", "--tags=not-json"], env)

    assert proc.returncode != 0
    assert count_mem_entries(db_path) == before


# --------------------------------------------------------------------------
# list
# --------------------------------------------------------------------------


def test_list_empty_project_prints_nothing_and_exits_0(db_path: Path, project_id: str) -> None:
    env = cli_env(db_path)
    proc = run_cli(["mem", "list"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""  # bash: sqlite3 -header -column prints ZERO bytes for zero rows


def test_list_empty_project_json_is_empty_array(db_path: Path, project_id: str) -> None:
    env = cli_env(db_path)
    proc = run_cli(["mem", "list", "--json"], env)

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == []


def test_list_orders_pinned_first_then_newest_first(db_path: Path, project_id: str) -> None:
    now = _now()
    insert_mem_entry(db_path, project_id, entry_id="e-old-unpinned", title="Old unpinned", created_at=now - 300)
    insert_mem_entry(db_path, project_id, entry_id="e-new-unpinned", title="New unpinned", created_at=now - 10)
    insert_mem_entry(
        db_path, project_id, entry_id="e-old-pinned", title="Old pinned", pinned=1, created_at=now - 600,
    )
    env = cli_env(db_path)
    proc = run_cli(["mem", "list", "--json"], env)

    assert proc.returncode == 0, proc.stderr
    ids = [row["id"] for row in json.loads(proc.stdout)]
    # pinned DESC first (e-old-pinned, despite being oldest), then created_at DESC.
    assert ids == ["e-old-pinned", "e-new-unpinned", "e-old-unpinned"]


def test_list_json_shape_matches_bash_column_projection(db_path: Path, project_id: str) -> None:
    now = _now()
    insert_mem_entry(db_path, project_id, entry_id="e1", kind="incident", title="Outage", created_at=now)
    env = cli_env(db_path)
    proc = run_cli(["mem", "list", "--json"], env)

    assert proc.returncode == 0, proc.stderr
    rows = json.loads(proc.stdout)
    assert len(rows) == 1
    # Bash SELECTs exactly these five columns — no body, tags, updated_at, project_id.
    assert set(rows[0].keys()) == {"id", "kind", "title", "pinned", "created_at"}
    assert rows[0]["kind"] == "incident"
    assert rows[0]["title"] == "Outage"
    assert rows[0]["created_at"] == now


def test_list_table_rendering_matches_sqlite3_column_mode(db_path: Path, project_id: str) -> None:
    now = _now()
    insert_mem_entry(db_path, project_id, entry_id="e1", kind="note", title="Short", created_at=now)
    env = cli_env(db_path)
    proc = run_cli(["mem", "list"], env)

    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.rstrip("\n").split("\n")  # ignore the single conventional trailing newline
    assert len(lines) == 3  # header, separator, one data row
    assert lines[0].split() == ["id", "kind", "title", "pinned", "created_at"]
    assert set(lines[1].replace(" ", "")) == {"-"}  # dash separator row
    assert "e1" in lines[2]
    assert "Short" in lines[2]


def test_list_scoped_to_active_project_only(db_path: Path, project_id: str) -> None:
    """A row belonging to a DIFFERENT project must never appear."""
    other_project = insert_project(db_path, project_id="proj-other")
    now = _now()
    insert_mem_entry(db_path, project_id, entry_id="e-mine", title="Mine", created_at=now)
    insert_mem_entry(db_path, other_project, entry_id="e-other", title="Other", created_at=now)
    env = cli_env(db_path)
    proc = run_cli(["mem", "list", "--json"], env)

    assert proc.returncode == 0, proc.stderr
    ids = {row["id"] for row in json.loads(proc.stdout)}
    assert ids == {"e-mine"}


# --------------------------------------------------------------------------
# search
# --------------------------------------------------------------------------


def test_search_missing_q_exits_1(db_path: Path, project_id: str) -> None:
    env = cli_env(db_path)
    proc = run_cli(["mem", "search"], env)

    assert proc.returncode == 1
    assert "ERROR: --q=<text> required for mem search" in proc.stderr


def test_search_empty_q_flag_exits_1(db_path: Path, project_id: str) -> None:
    env = cli_env(db_path)
    proc = run_cli(["mem", "search", "--q="], env)

    assert proc.returncode == 1
    assert "ERROR: --q=<text> required for mem search" in proc.stderr


def test_search_matches_title_or_body_case_insensitive(db_path: Path, project_id: str) -> None:
    now = _now()
    insert_mem_entry(db_path, project_id, entry_id="e-title-hit", title="Contains ROCKET word", created_at=now)
    insert_mem_entry(
        db_path, project_id, entry_id="e-body-hit", title="Unrelated", body="mentions rocket in body",
        created_at=now - 5,
    )
    insert_mem_entry(db_path, project_id, entry_id="e-miss", title="Nothing here", body="nope", created_at=now - 10)
    env = cli_env(db_path)
    proc = run_cli(["mem", "search", "--q=rocket", "--json"], env)

    assert proc.returncode == 0, proc.stderr
    ids = {row["id"] for row in json.loads(proc.stdout)}
    assert ids == {"e-title-hit", "e-body-hit"}


def test_search_json_shape_matches_bash_column_projection(db_path: Path, project_id: str) -> None:
    now = _now()
    insert_mem_entry(db_path, project_id, entry_id="e1", kind="doctrine", title="Widget policy", created_at=now)
    env = cli_env(db_path)
    proc = run_cli(["mem", "search", "--q=widget", "--json"], env)

    assert proc.returncode == 0, proc.stderr
    rows = json.loads(proc.stdout)
    assert len(rows) == 1
    # Bash SELECTs exactly these four columns — no created_at, body, tags, updated_at.
    assert set(rows[0].keys()) == {"id", "kind", "title", "pinned"}


def test_search_orders_pinned_first_then_newest_first(db_path: Path, project_id: str) -> None:
    now = _now()
    insert_mem_entry(db_path, project_id, entry_id="e-new", title="match new", created_at=now - 5)
    insert_mem_entry(db_path, project_id, entry_id="e-pinned", title="match pinned", pinned=1, created_at=now - 100)
    env = cli_env(db_path)
    proc = run_cli(["mem", "search", "--q=match", "--json"], env)

    assert proc.returncode == 0, proc.stderr
    ids = [row["id"] for row in json.loads(proc.stdout)]
    assert ids == ["e-pinned", "e-new"]


def test_search_no_matches_prints_nothing_and_exits_0(db_path: Path, project_id: str) -> None:
    now = _now()
    insert_mem_entry(db_path, project_id, entry_id="e1", title="Something else entirely", created_at=now)
    env = cli_env(db_path)
    proc = run_cli(["mem", "search", "--q=zzz-nomatch-zzz"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""


def test_search_no_matches_json_is_empty_array(db_path: Path, project_id: str) -> None:
    env = cli_env(db_path)
    proc = run_cli(["mem", "search", "--q=zzz-nomatch-zzz", "--json"], env)

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == []


def test_search_scoped_to_active_project_only(db_path: Path, project_id: str) -> None:
    other_project = insert_project(db_path, project_id="proj-other")
    now = _now()
    insert_mem_entry(db_path, project_id, entry_id="e-mine", title="shared-term here", created_at=now)
    insert_mem_entry(db_path, other_project, entry_id="e-other", title="shared-term there", created_at=now)
    env = cli_env(db_path)
    proc = run_cli(["mem", "search", "--q=shared-term", "--json"], env)

    assert proc.returncode == 0, proc.stderr
    ids = {row["id"] for row in json.loads(proc.stdout)}
    assert ids == {"e-mine"}


# --------------------------------------------------------------------------
# show
# --------------------------------------------------------------------------


def test_show_happy_path_prints_full_row(db_path: Path, project_id: str) -> None:
    now = _now()
    insert_mem_entry(
        db_path, project_id, entry_id="e-full", kind="incident", title="Prod down",
        body="Detailed body text.", tags='["p1"]', pinned=1, created_at=now - 20, updated_at=now,
    )
    env = cli_env(db_path)
    proc = run_cli(["mem", "show", "e-full", "--json"], env)

    assert proc.returncode == 0, proc.stderr
    row = json.loads(proc.stdout)
    assert row == {
        "id": "e-full",
        "kind": "incident",
        "title": "Prod down",
        "body": "Detailed body text.",
        "tags": '["p1"]',
        "pinned": 1,
        "created_at": now - 20,
        "updated_at": now,
    }


def test_show_table_rendering_includes_all_eight_columns(db_path: Path, project_id: str) -> None:
    now = _now()
    insert_mem_entry(db_path, project_id, entry_id="e-full", title="Prod down", body="details", created_at=now)
    env = cli_env(db_path)
    proc = run_cli(["mem", "show", "e-full"], env)

    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.rstrip("\n").split("\n")  # ignore the single conventional trailing newline
    assert len(lines) == 3
    assert lines[0].split() == ["id", "kind", "title", "body", "tags", "pinned", "created_at", "updated_at"]


def test_show_missing_id_exits_1(db_path: Path, project_id: str) -> None:
    env = cli_env(db_path)
    proc = run_cli(["mem", "show"], env)

    assert proc.returncode == 1
    assert "ERROR: usage: shctx mem show <id>" in proc.stderr


def test_show_nonexistent_id_prints_nothing_and_exits_0(db_path: Path, project_id: str) -> None:
    env = cli_env(db_path)
    proc = run_cli(["mem", "show", "does-not-exist"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""


def test_show_nonexistent_id_json_is_null(db_path: Path, project_id: str) -> None:
    env = cli_env(db_path)
    proc = run_cli(["mem", "show", "does-not-exist", "--json"], env)

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) is None


def test_show_scoped_to_active_project_only(db_path: Path, project_id: str) -> None:
    other_project = insert_project(db_path, project_id="proj-other")
    now = _now()
    insert_mem_entry(db_path, other_project, entry_id="e-other", title="Not mine", created_at=now)
    env = cli_env(db_path)
    proc = run_cli(["mem", "show", "e-other", "--json"], env)

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) is None


# --------------------------------------------------------------------------
# pin / unpin
# --------------------------------------------------------------------------


def test_pin_sets_pinned_and_bumps_updated_at_with_no_stdout(db_path: Path, project_id: str) -> None:
    now = _now()
    insert_mem_entry(db_path, project_id, entry_id="e1", title="X", pinned=0, created_at=now - 1000)
    env = cli_env(db_path)
    before = _now()
    proc = run_cli(["mem", "pin", "e1"], env)
    after = _now()

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""  # bash: no echo on success

    row = fetch_mem_entry(db_path, "e1")
    assert row["pinned"] == 1
    assert before <= row["updated_at"] <= after
    assert row["created_at"] == now - 1000  # unchanged


def test_unpin_clears_pinned_with_no_stdout(db_path: Path, project_id: str) -> None:
    now = _now()
    insert_mem_entry(db_path, project_id, entry_id="e1", title="X", pinned=1, created_at=now)
    env = cli_env(db_path)
    proc = run_cli(["mem", "unpin", "e1"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""
    assert fetch_mem_entry(db_path, "e1")["pinned"] == 0


def test_pin_missing_id_exits_1(db_path: Path, project_id: str) -> None:
    env = cli_env(db_path)
    proc = run_cli(["mem", "pin"], env)

    assert proc.returncode == 1
    assert "ERROR: usage: shctx mem pin <id>" in proc.stderr


def test_unpin_missing_id_exits_1(db_path: Path, project_id: str) -> None:
    env = cli_env(db_path)
    proc = run_cli(["mem", "unpin"], env)

    assert proc.returncode == 1
    assert "ERROR: usage: shctx mem unpin <id>" in proc.stderr


def test_pin_unknown_id_still_succeeds_noop(db_path: Path, project_id: str) -> None:
    """Bash parity: the UPDATE has no existence check — an id that matches
    nothing still exits 0 with empty stdout (0 rows affected, no error)."""
    env = cli_env(db_path)
    proc = run_cli(["mem", "pin", "does-not-exist"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""


def test_pin_scoped_to_active_project_only(db_path: Path, project_id: str) -> None:
    """Pinning an id that only exists in a DIFFERENT project must not touch it."""
    other_project = insert_project(db_path, project_id="proj-other")
    now = _now()
    insert_mem_entry(db_path, other_project, entry_id="e-other", title="Not mine", pinned=0, created_at=now)
    env = cli_env(db_path)
    proc = run_cli(["mem", "pin", "e-other"], env)

    assert proc.returncode == 0, proc.stderr
    assert fetch_mem_entry(db_path, "e-other")["pinned"] == 0  # untouched


# --------------------------------------------------------------------------
# rm / delete
# --------------------------------------------------------------------------


def test_rm_deletes_row_and_prints_confirmation(db_path: Path, project_id: str) -> None:
    now = _now()
    insert_mem_entry(db_path, project_id, entry_id="e1", title="X", created_at=now)
    env = cli_env(db_path)
    proc = run_cli(["mem", "rm", "e1"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "shctx mem rm: removed e1"
    assert count_mem_entries(db_path) == 0


def test_delete_alias_deletes_row_and_hardcodes_rm_in_confirmation(db_path: Path, project_id: str) -> None:
    now = _now()
    insert_mem_entry(db_path, project_id, entry_id="e1", title="X", created_at=now)
    env = cli_env(db_path)
    proc = run_cli(["mem", "delete", "e1"], env)

    assert proc.returncode == 0, proc.stderr
    # Bash hard-codes "rm" in this message even via the "delete" alias.
    assert proc.stdout.strip() == "shctx mem rm: removed e1"
    assert count_mem_entries(db_path) == 0


def test_rm_missing_id_exits_1(db_path: Path, project_id: str) -> None:
    env = cli_env(db_path)
    proc = run_cli(["mem", "rm"], env)

    assert proc.returncode == 1
    assert "ERROR: usage: shctx mem rm <id>" in proc.stderr


def test_delete_alias_missing_id_hardcodes_rm_in_usage(db_path: Path, project_id: str) -> None:
    env = cli_env(db_path)
    proc = run_cli(["mem", "delete"], env)

    assert proc.returncode == 1
    # Bash hard-codes "rm" in this message even via the "delete" alias.
    assert "ERROR: usage: shctx mem rm <id>" in proc.stderr


def test_rm_unknown_id_still_succeeds_and_prints_confirmation(db_path: Path, project_id: str) -> None:
    """Bash parity: the DELETE has no existence check — an id that matches
    nothing still exits 0 and prints the same confirmation message."""
    env = cli_env(db_path)
    proc = run_cli(["mem", "rm", "does-not-exist"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "shctx mem rm: removed does-not-exist"


def test_rm_scoped_to_active_project_only(db_path: Path, project_id: str) -> None:
    """Deleting an id that only exists in a DIFFERENT project must not remove it."""
    other_project = insert_project(db_path, project_id="proj-other")
    now = _now()
    insert_mem_entry(db_path, other_project, entry_id="e-other", title="Not mine", created_at=now)
    env = cli_env(db_path)
    proc = run_cli(["mem", "rm", "e-other"], env)

    assert proc.returncode == 0, proc.stderr
    assert count_mem_entries(db_path) == 1  # e-other survives, untouched


# --------------------------------------------------------------------------
# Sub-app usage/exit-code parity.
# --------------------------------------------------------------------------


def test_unknown_subcommand_exits_2(db_path: Path, project_id: str) -> None:
    env = cli_env(db_path)
    proc = run_cli(["mem", "bogus"], env)

    assert proc.returncode == 2


def test_no_subcommand_shows_usage_and_exits_1(db_path: Path, project_id: str) -> None:
    # Bash parity: `shctx mem` (no subcommand) hits the `*)` default → stderr
    # usage error, exit 1 (mem has no `""|help)` 0-exit branch, unlike
    # deliverable/signal).
    env = cli_env(db_path)
    proc = run_cli(["mem"], env)

    assert proc.returncode == 1, proc.stdout
    for name in ("add", "list", "search", "show", "pin", "unpin", "rm"):
        assert name in proc.stderr
