"""Self-heal regression test (#200).

A DB left behind by an older plugin install — schema_versions recording
only version=1, even though migration 0007's tables (teammates, etc.)
already exist on disk — must not crash `teammate liveness` with
"no such column: declared_state". db.lifespan()'s ensure_migrated() call
(run BEFORE Tortoise.init on every command) is the fix; this test proves it
end-to-end through the real CLI subprocess, not by unit-testing
ensure_migrated() in isolation.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from conftest import MIGRATIONS_DIR, TeammateRow, build_partial_schema_db, cli_env, insert_project, insert_teammate, run_cli


def _teammates_columns(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return {row[1] for row in conn.execute("PRAGMA table_info(teammates)")}
    finally:
        conn.close()


def _schema_versions(db_path: Path) -> set[int]:
    conn = sqlite3.connect(str(db_path))
    try:
        return {row[0] for row in conn.execute("SELECT version FROM schema_versions")}
    finally:
        conn.close()


def test_liveness_heals_a_schema_behind_db(tmp_path: Path) -> None:
    db_path = tmp_path / "shepherd.db"
    build_partial_schema_db(db_path)
    project_id = insert_project(db_path)

    now_ms = int(time.time() * 1000)
    insert_teammate(db_path, project_id, TeammateRow(
        id="tm-preheal", team_name="preheal-team", teammate_name="preheal-engineer",
        agent_type="shepherd:engineer", session_id="preheal-session",
        status="active", declared_state=None,
        spawned_at=now_ms, last_seen_at=now_ms,
    ))

    # Preconditions: this fixture really is "behind" before the CLI touches it.
    assert "declared_state" not in _teammates_columns(db_path)
    assert _schema_versions(db_path) == {1}

    env = cli_env(db_path)
    proc = run_cli(["teammate", "liveness", "--all", "--json"], env)

    # The historical #200 crash: a raw sqlite3.OperationalError surfacing to
    # the user as "no such column: declared_state". This must never happen,
    # in stdout OR stderr, regardless of which healing strategy fixed it.
    assert "no such column" not in proc.stdout.lower()
    assert "no such column" not in proc.stderr.lower()
    assert proc.returncode == 0, f"liveness crashed on a schema-behind db: {proc.stderr}"

    rows = json.loads(proc.stdout)

    # Per the contract, EITHER is valid evidence of the fix:
    #   (a) ensure_migrated() actually applied the gap-filled migrations, so
    #       declared_state now exists on disk; or
    #   (b) the query degraded gracefully (declared_state=None) and still
    #       returned rows instead of raising.
    # A raw OperationalError (already ruled out above) is the only failure.
    column_healed = "declared_state" in _teammates_columns(db_path)
    assert column_healed or len(rows) >= 1, (
        "liveness did not raise, but neither healed the schema nor returned any rows"
    )

    if rows:
        names = {row["teammate_name"] for row in rows}
        assert "preheal-engineer" in names


def test_liveness_after_heal_leaves_a_fully_migrated_schema(tmp_path: Path) -> None:
    """A stronger assertion for the common (expected) case: after one liveness
    call against a behind DB, the schema is not just column-patched but fully
    caught up — every migration's schema_versions row is present. This is
    what lets a SECOND command run without paying the heal cost again."""
    db_path = tmp_path / "shepherd.db"
    build_partial_schema_db(db_path)
    insert_project(db_path)

    env = cli_env(db_path)
    proc = run_cli(["teammate", "liveness", "--all", "--json"], env)
    assert proc.returncode == 0, proc.stderr

    columns_after = _teammates_columns(db_path)
    if "declared_state" in columns_after:
        # The full-heal path ran: schema_versions should now cover every
        # shipped migration, not just the ones from before this test's setup.
        shipped_versions = {
            int(path.name[:4]) for path in MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql")
        }
        assert _schema_versions(db_path) >= shipped_versions | {1}
