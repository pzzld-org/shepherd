"""Tests for `shepherd lock` — native port of `cmd_lock.sh` (bash-parity #198-successor).

Covers: `show` (free/held, --json, no-subcommand-defaults-to-show), `acquire`
(happy path, already-held, generated session, dual-write ordering on an
invalid mode), `release` (normal, --force/--all alias, free, corrupt lock
file), `reap` (free, dead pid, live+fresh, live+stale, corrupt lock file),
the shared "no project registered" prerequisite gate (exit 1, every
subcommand including `show`), and the documented unrecognized-subcommand
deviation (Typer's own exit 2, not bash's custom exit 1).

Where the underlying behavior is deterministic and unaffected by this port's
documented deviations (project-id resolution via the `projects` table
instead of `project.json`; graceful tolerance of a corrupt lock file), tests
assert BYTE-FOR-BYTE stdout parity against the legacy `cmd_lock.sh` on the
IDENTICAL sqlite file and lock-file state, mirroring the bash-parity pattern
`test_status.py` established. Every test isolates the lock file to a
throwaway `SHEPHERD_WORKDIR` (a `tmp_path` subdirectory) so it never reads or
writes this real repo's own `.artifacts/`/`.shepherd/` lock file.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest
from conftest import PY, REPO_ROOT, build_full_schema_db, clean_env_dict, insert_project, run_cli

CMD_LOCK_SH = REPO_ROOT / "skills" / "context" / "scripts" / "cmd_lock.sh"


# --------------------------------------------------------------------------
# Environment helpers.
# --------------------------------------------------------------------------
def _lock_env(db_path: Path, workdir: Path) -> dict[str, str]:
    """Environment for `shepherd lock` (and `cmd_lock.sh`), isolated to `workdir`.

    Sets `SHCTX_DB` (both tools read/write the exact fixture DB) AND
    `SHEPHERD_WORKDIR` (both tools' lock-file lookup — independent of
    `SHCTX_DB` — resolves inside `workdir`, never the real repo's own
    `.shepherd`/`.artifacts`).

    Args:
        db_path: The fixture sqlite file.
        workdir: The throwaway directory `shepherd.lock` (and, for bash
            parity runs, `project.json`) is read from/written to; need not
            exist yet.

    Returns:
        A stripped-then-rebuilt environment safe for `run_cli` or a raw
        `subprocess.run` against `cmd_lock.sh` directly.
    """
    env = clean_env_dict()
    env["SHCTX_DB"] = str(db_path)
    env["SHEPHERD_WORKDIR"] = str(workdir)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    return env


def _write_project_json(workdir: Path, project_id: str) -> None:
    """Write `<workdir>/project.json`, the file bash's `shctx_project_id` reads.

    Only needed for BASH-PARITY comparison tests: this Python port resolves
    the active project via the `projects` DB table instead (see
    `shepherd_cli/commands/lock.py`'s module docstring, "Project-id
    resolution deviation"), so Python-only tests never need this file — but
    a true side-by-side parity assertion needs both tools to resolve the
    SAME project_id, which requires this file to agree with the DB row.

    Args:
        workdir: The directory to write `project.json` into (created if
            missing).
        project_id: The id both tools must resolve to.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "project.json").write_text(json.dumps({"id": project_id}))


def _run_bash_lock(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the legacy `cmd_lock.sh` directly (bash-parity twin of `run_cli`)."""
    return subprocess.run(
        ["bash", str(CMD_LOCK_SH), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )


@pytest.fixture
def lock_db(tmp_path: Path) -> tuple[Path, str]:
    """A full-schema fixture DB with one registered project (FK target).

    Returns:
        `(db_path, project_id)`.
    """
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    project_id = insert_project(db_path)
    return db_path, project_id


def _history_rows(db_path: Path) -> list[tuple[object, ...]]:
    """Every `locks_history` row, ordered by `id` (insertion order)."""
    conn = sqlite3.connect(str(db_path))
    try:
        cols = [info[1] for info in conn.execute("PRAGMA table_info(locks_history)")]
        assert cols, "locks_history has no columns — fixture schema is broken"
        rows = conn.execute(
            f"SELECT {', '.join(cols)} FROM locks_history ORDER BY id"  # noqa: S608 - columns from PRAGMA, not user input
        ).fetchall()
        return [dict(zip(cols, row, strict=True)) for row in rows]  # type: ignore[return-value]
    finally:
        conn.close()


def _insert_history_row(
    db_path: Path,
    *,
    project_id: str,
    session_id: str,
    mode: str = "context",
    acquired_at: int,
    released_at: int | None = None,
    released_by: str | None = None,
) -> None:
    """Seed one `locks_history` row via raw sqlite3, schema-tolerant.

    Args:
        db_path: The fixture DB to write into.
        project_id: FK target in `projects.id`.
        session_id: The holder session id.
        mode: One of `locks_history.mode`'s CHECK values.
        acquired_at: Epoch seconds.
        released_at: Epoch seconds, or None for an still-open row.
        released_by: One of `locks_history.released_by`'s CHECK values, or
            None.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        columns = {info[1] for info in conn.execute("PRAGMA table_info(locks_history)")}
        fields = ["project_id", "session_id", "mode", "acquired_at"]
        values: list[object] = [project_id, session_id, mode, acquired_at]
        if "released_at" in columns:
            fields.append("released_at")
            values.append(released_at)
        if "released_by" in columns:
            fields.append("released_by")
            values.append(released_by)
        placeholders = ", ".join("?" for _ in fields)
        conn.execute(
            f"INSERT INTO locks_history ({', '.join(fields)}) VALUES ({placeholders})",  # noqa: S608 - fixed column allow-list above
            values,
        )
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------
# show — free / held / --json / no-subcommand default.
# --------------------------------------------------------------------------
def test_show_free_bash_parity(lock_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = lock_db
    workdir = tmp_path / "work"  # never created -> no lock file -> free
    _write_project_json(workdir, project_id)
    env = _lock_env(db_path, workdir)

    python_proc = run_cli(["lock", "show"], env)
    bash_proc = _run_bash_lock(["show"], env)

    assert python_proc.returncode == 0, python_proc.stderr
    assert bash_proc.returncode == 0, bash_proc.stderr
    assert python_proc.stdout == bash_proc.stdout == "lock: free\n"


def test_no_subcommand_defaults_to_show_bash_parity(lock_db: tuple[Path, str], tmp_path: Path) -> None:
    """Bash parity: `shctx lock` with NO subcommand means `show`, not usage."""
    db_path, project_id = lock_db
    workdir = tmp_path / "work"
    _write_project_json(workdir, project_id)
    env = _lock_env(db_path, workdir)

    python_proc = run_cli(["lock"], env)
    bash_proc = _run_bash_lock([], env)

    assert python_proc.returncode == 0, python_proc.stderr
    assert bash_proc.returncode == 0, bash_proc.stderr
    assert python_proc.stdout == bash_proc.stdout == "lock: free\n"


def _write_lock_file(workdir: Path, *, holder: str, mode: str, acquired_at: int, pid: int) -> dict[str, object]:
    """Write `shepherd.lock` shaped exactly like `cmd_lock.sh acquire` writes it.

    Key order matters for the bash-parity assertion: `jq .` (and this
    module's Python renderer) both preserve source key order, so this must
    match `cmd_lock.sh`'s `jq -nc` object literal order exactly:
    `holder_session_id, mode, acquired_at, pid, children`.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    data = {"holder_session_id": holder, "mode": mode, "acquired_at": acquired_at, "pid": pid, "children": []}
    (workdir / "shepherd.lock").write_text(json.dumps(data, separators=(",", ":")))
    return data


def test_show_held_bash_parity_pretty_prints_like_jq(lock_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = lock_db
    workdir = tmp_path / "work"
    _write_project_json(workdir, project_id)
    lock_data = _write_lock_file(workdir, holder="sess-xyz", mode="autorun", acquired_at=1234567890, pid=4242)
    env = _lock_env(db_path, workdir)

    python_proc = run_cli(["lock", "show"], env)
    bash_proc = _run_bash_lock(["show"], env)

    assert python_proc.returncode == 0, python_proc.stderr
    assert bash_proc.returncode == 0, bash_proc.stderr
    assert python_proc.stdout == bash_proc.stdout
    assert python_proc.stdout == f"lock: held\n{json.dumps(lock_data, indent=2)}\n"


def test_show_json_free(lock_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = lock_db
    workdir = tmp_path / "work"
    _write_project_json(workdir, project_id)
    env = _lock_env(db_path, workdir)

    proc = run_cli(["lock", "show", "--json"], env)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload == {
        "held": False,
        "holder_session_id": None,
        "mode": None,
        "acquired_at": None,
        "pid": None,
        "children": None,
    }


def test_show_json_held(lock_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = lock_db
    workdir = tmp_path / "work"
    _write_project_json(workdir, project_id)
    _write_lock_file(workdir, holder="sess-abc", mode="parallel", acquired_at=1700000000, pid=555)
    env = _lock_env(db_path, workdir)

    proc = run_cli(["lock", "show", "--json"], env)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload == {
        "held": True,
        "holder_session_id": "sess-abc",
        "mode": "parallel",
        "acquired_at": 1700000000,
        "pid": 555,
        "children": [],
    }


def test_no_subcommand_json_flag_works(lock_db: tuple[Path, str], tmp_path: Path) -> None:
    """`shepherd lock --json` (no subcommand token) still reaches the implicit show."""
    db_path, project_id = lock_db
    workdir = tmp_path / "work"
    _write_project_json(workdir, project_id)
    env = _lock_env(db_path, workdir)

    proc = run_cli(["lock", "--json"], env)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["held"] is False


def test_show_corrupt_lock_file_still_reports_held_without_crashing(lock_db: tuple[Path, str], tmp_path: Path) -> None:
    """Deliberate ROBUSTNESS deviation from bash (see lock.py's module
    docstring): `cmd_lock.sh` pipes a corrupt lock file straight into
    `jq .`, which fails and (under `set -eu -o pipefail`) aborts the whole
    script non-zero. `shepherd lock show` degrades instead: still reports
    `lock: held` and simply omits the unparseable JSON body."""
    db_path, project_id = lock_db
    workdir = tmp_path / "work"
    _write_project_json(workdir, project_id)
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "shepherd.lock").write_text("{not valid json")
    env = _lock_env(db_path, workdir)

    proc = run_cli(["lock", "show"], env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "lock: held\n"


# --------------------------------------------------------------------------
# acquire — happy path, dual-write ordering, already-held, generated session.
# --------------------------------------------------------------------------
def test_acquire_bash_parity_writes_file_and_history_row(lock_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = lock_db
    workdir = tmp_path / "work"
    workdir.mkdir(parents=True)
    _write_project_json(workdir, project_id)
    env = _lock_env(db_path, workdir)

    proc = run_cli(["lock", "acquire", "--mode", "parallel", "--session", "sess-fixed"], env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "lock: acquired (sess-fixed, parallel)\n"

    lock_path = workdir / "shepherd.lock"
    assert lock_path.is_file()
    data = json.loads(lock_path.read_text())
    assert data["holder_session_id"] == "sess-fixed"
    assert data["mode"] == "parallel"
    assert data["children"] == []
    assert isinstance(data["pid"], int)
    assert isinstance(data["acquired_at"], int)
    assert list(data.keys()) == ["holder_session_id", "mode", "acquired_at", "pid", "children"]

    rows = _history_rows(db_path)
    assert len(rows) == 1
    assert rows[0]["project_id"] == project_id
    assert rows[0]["session_id"] == "sess-fixed"
    assert rows[0]["mode"] == "parallel"
    assert rows[0]["acquired_at"] == data["acquired_at"]
    assert rows[0]["released_at"] is None
    assert rows[0]["released_by"] is None


def test_acquire_bash_parity_stdout(lock_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = lock_db
    workdir = tmp_path / "work"
    workdir.mkdir(parents=True)
    _write_project_json(workdir, project_id)
    env = _lock_env(db_path, workdir)

    python_proc = run_cli(["lock", "acquire", "--mode", "spawn", "--session", "sess-parity"], env)
    assert python_proc.returncode == 0, python_proc.stderr
    assert python_proc.stdout == "lock: acquired (sess-parity, spawn)\n"

    # Reset for the bash run against a fresh copy of the same starting state.
    (workdir / "shepherd.lock").unlink()
    conn = sqlite3.connect(str(db_path))
    conn.execute("DELETE FROM locks_history")
    conn.commit()
    conn.close()

    bash_proc = _run_bash_lock(["acquire", "--mode=spawn", "--session=sess-parity"], env)
    assert bash_proc.returncode == 0, bash_proc.stderr
    assert bash_proc.stdout == python_proc.stdout


def test_acquire_default_mode_is_context(lock_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = lock_db
    workdir = tmp_path / "work"
    workdir.mkdir(parents=True)
    _write_project_json(workdir, project_id)
    env = _lock_env(db_path, workdir)

    proc = run_cli(["lock", "acquire", "--session", "sess-default-mode"], env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "lock: acquired (sess-default-mode, context)\n"


def test_acquire_generates_session_when_omitted(lock_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = lock_db
    workdir = tmp_path / "work"
    workdir.mkdir(parents=True)
    _write_project_json(workdir, project_id)
    env = _lock_env(db_path, workdir)

    proc = run_cli(["lock", "acquire"], env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("lock: acquired (")
    generated = proc.stdout.split("(", 1)[1].split(",", 1)[0]
    # A UUIDv7 string: 8-4-4-4-12 hex groups.
    parts = generated.split("-")
    assert [len(p) for p in parts] == [8, 4, 4, 4, 12], f"not UUID-shaped: {generated!r}"


def test_acquire_already_held_exits_1(lock_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = lock_db
    workdir = tmp_path / "work"
    workdir.mkdir(parents=True)
    _write_project_json(workdir, project_id)
    env = _lock_env(db_path, workdir)

    first = run_cli(["lock", "acquire", "--session", "sess-1"], env)
    assert first.returncode == 0, first.stderr

    second = run_cli(["lock", "acquire", "--session", "sess-2"], env)
    assert second.returncode == 1
    assert second.stdout == ""
    assert second.stderr.strip() == "ERROR: lock already held"

    # The original holder is untouched, and no second history row appeared.
    data = json.loads((workdir / "shepherd.lock").read_text())
    assert data["holder_session_id"] == "sess-1"
    assert len(_history_rows(db_path)) == 1


def test_acquire_already_held_bash_parity(lock_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = lock_db
    workdir = tmp_path / "work"
    _write_project_json(workdir, project_id)
    _write_lock_file(workdir, holder="sess-existing", mode="context", acquired_at=1700000000, pid=1)
    env = _lock_env(db_path, workdir)

    python_proc = run_cli(["lock", "acquire"], env)
    bash_proc = _run_bash_lock(["acquire"], env)

    assert python_proc.returncode == bash_proc.returncode == 1
    assert python_proc.stdout == bash_proc.stdout == ""
    assert python_proc.stderr.strip() == bash_proc.stderr.strip() == "ERROR: lock already held"


def test_acquire_invalid_mode_dual_write_ordering(lock_db: tuple[Path, str], tmp_path: Path) -> None:
    """Bash-parity dual-write ORDER: the lock file is written BEFORE the
    locks_history INSERT, so an invalid --mode (rejected by the CHECK
    constraint at INSERT time) still leaves the lock file on disk even
    though the command itself fails non-zero and no history row exists."""
    db_path, project_id = lock_db
    workdir = tmp_path / "work"
    workdir.mkdir(parents=True)
    _write_project_json(workdir, project_id)
    env = _lock_env(db_path, workdir)

    proc = run_cli(["lock", "acquire", "--mode", "not-a-real-mode", "--session", "sess-bad"], env)
    assert proc.returncode != 0

    lock_path = workdir / "shepherd.lock"
    assert lock_path.is_file(), "lock file must exist even though the history insert failed (dual-write ordering)"
    data = json.loads(lock_path.read_text())
    assert data["holder_session_id"] == "sess-bad"
    assert data["mode"] == "not-a-real-mode"
    assert _history_rows(db_path) == []


# --------------------------------------------------------------------------
# release — normal, --force/--all, free, corrupt lock file.
# --------------------------------------------------------------------------
def test_release_normal_stamps_history_and_removes_file(lock_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = lock_db
    workdir = tmp_path / "work"
    workdir.mkdir(parents=True)
    _write_project_json(workdir, project_id)
    env = _lock_env(db_path, workdir)

    acquire = run_cli(["lock", "acquire", "--session", "sess-rel"], env)
    assert acquire.returncode == 0, acquire.stderr

    proc = run_cli(["lock", "release"], env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "lock: released\n"
    assert not (workdir / "shepherd.lock").exists()

    rows = _history_rows(db_path)
    assert len(rows) == 1
    assert rows[0]["session_id"] == "sess-rel"
    assert rows[0]["released_by"] == "normal"
    assert rows[0]["released_at"] is not None


def test_release_bash_parity(lock_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = lock_db
    workdir = tmp_path / "work"
    _write_project_json(workdir, project_id)
    _write_lock_file(workdir, holder="sess-rel-parity", mode="context", acquired_at=1700000000, pid=1)
    now = int(time.time())
    _insert_history_row(db_path, project_id=project_id, session_id="sess-rel-parity", acquired_at=now)
    env = _lock_env(db_path, workdir)

    python_proc = run_cli(["lock", "release"], env)
    assert python_proc.returncode == 0, python_proc.stderr
    assert python_proc.stdout == "lock: released\n"

    # Reset lock file + history for a bash comparison run against identical starting state.
    _write_lock_file(workdir, holder="sess-rel-parity", mode="context", acquired_at=1700000000, pid=1)
    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE locks_history SET released_at=NULL, released_by=NULL WHERE session_id='sess-rel-parity'")
    conn.commit()
    conn.close()

    bash_proc = _run_bash_lock(["release"], env)
    assert bash_proc.returncode == 0, bash_proc.stderr
    assert bash_proc.stdout == python_proc.stdout


def test_release_force_and_all_are_aliases(lock_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = lock_db
    for flag in ("--force", "--all"):
        workdir = tmp_path / f"work-{flag.strip('-')}"
        workdir.mkdir(parents=True)
        _write_project_json(workdir, project_id)
        env = _lock_env(db_path, workdir)

        acquire = run_cli(["lock", "acquire", "--session", f"sess-{flag}"], env)
        assert acquire.returncode == 0, acquire.stderr

        proc = run_cli(["lock", "release", flag], env)
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout == "lock: released (force)\n"
        assert not (workdir / "shepherd.lock").exists()

        rows = [r for r in _history_rows(db_path) if r["session_id"] == f"sess-{flag}"]
        assert len(rows) == 1
        assert rows[0]["released_by"] == "force"


def test_release_only_stamps_the_open_row_for_that_session(lock_db: tuple[Path, str], tmp_path: Path) -> None:
    """WHERE session_id=? AND released_at IS NULL — a prior, already-closed
    row for the SAME session_id must not be touched again."""
    db_path, project_id = lock_db
    workdir = tmp_path / "work"
    _write_project_json(workdir, project_id)
    now = int(time.time())
    _insert_history_row(
        db_path, project_id=project_id, session_id="sess-repeat",
        acquired_at=now - 1000, released_at=now - 900, released_by="normal",
    )
    _write_lock_file(workdir, holder="sess-repeat", mode="context", acquired_at=now, pid=1)
    _insert_history_row(db_path, project_id=project_id, session_id="sess-repeat", acquired_at=now)
    env = _lock_env(db_path, workdir)

    proc = run_cli(["lock", "release"], env)
    assert proc.returncode == 0, proc.stderr

    rows = [r for r in _history_rows(db_path) if r["session_id"] == "sess-repeat"]
    assert len(rows) == 2
    assert rows[0]["released_at"] == now - 900  # untouched
    assert rows[0]["released_by"] == "normal"
    assert rows[1]["released_at"] is not None  # newly stamped
    assert rows[1]["acquired_at"] == now


def test_release_when_free_prints_free_exits_0(lock_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = lock_db
    workdir = tmp_path / "work"
    _write_project_json(workdir, project_id)
    env = _lock_env(db_path, workdir)

    python_proc = run_cli(["lock", "release"], env)
    bash_proc = _run_bash_lock(["release"], env)

    assert python_proc.returncode == 0, python_proc.stderr
    assert bash_proc.returncode == 0, bash_proc.stderr
    assert python_proc.stdout == bash_proc.stdout == "lock: free\n"


def test_release_corrupt_lock_file_still_releases(lock_db: tuple[Path, str], tmp_path: Path) -> None:
    """Deliberate ROBUSTNESS deviation from bash (see lock.py's module
    docstring): bash's non-force `release` has NO jq error tolerance and
    crashes (exit 5) on a corrupt lock file, WITHOUT removing it — wedging
    the project forever, since release/reap are the only ways to clear a
    lock. This module tolerates it in both the --force and normal paths."""
    db_path, project_id = lock_db
    workdir = tmp_path / "work"
    workdir.mkdir(parents=True)
    _write_project_json(workdir, project_id)
    (workdir / "shepherd.lock").write_text("{not valid json")
    env = _lock_env(db_path, workdir)

    proc = run_cli(["lock", "release"], env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "lock: released\n"
    assert not (workdir / "shepherd.lock").exists()


# --------------------------------------------------------------------------
# reap — free, dead pid, live+fresh (refuses), live+stale, corrupt file.
# --------------------------------------------------------------------------
def test_reap_when_free_bash_parity(lock_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = lock_db
    workdir = tmp_path / "work"
    _write_project_json(workdir, project_id)
    env = _lock_env(db_path, workdir)

    python_proc = run_cli(["lock", "reap"], env)
    bash_proc = _run_bash_lock(["reap"], env)

    assert python_proc.returncode == 0, python_proc.stderr
    assert bash_proc.returncode == 0, bash_proc.stderr
    assert python_proc.stdout == bash_proc.stdout == "lock: free\n"


def test_reap_dead_pid_reaps_regardless_of_age(lock_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = lock_db
    workdir = tmp_path / "work"
    _write_project_json(workdir, project_id)
    now = int(time.time())
    # A pid essentially guaranteed not to exist, acquired 1 minute ago (well
    # under the 60-minute age threshold — dead-pid alone must trigger reap).
    dead_pid = 9_999_999
    _write_lock_file(workdir, holder="sess-dead", mode="context", acquired_at=now - 60, pid=dead_pid)
    _insert_history_row(db_path, project_id=project_id, session_id="sess-dead", acquired_at=now - 60)
    env = _lock_env(db_path, workdir)

    proc = run_cli(["lock", "reap"], env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == f"lock: reaped (pid={dead_pid}, age=1m)\n"
    assert not (workdir / "shepherd.lock").exists()

    rows = _history_rows(db_path)
    assert rows[0]["released_by"] == "reap"
    assert rows[0]["released_at"] is not None


def test_reap_live_and_fresh_refuses_exits_1(lock_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = lock_db
    workdir = tmp_path / "work"
    _write_project_json(workdir, project_id)
    now = int(time.time())
    live_pid = os.getpid()  # this pytest process — definitely alive.
    _write_lock_file(workdir, holder="sess-live", mode="context", acquired_at=now, pid=live_pid)
    _insert_history_row(db_path, project_id=project_id, session_id="sess-live", acquired_at=now)
    env = _lock_env(db_path, workdir)

    proc = run_cli(["lock", "reap"], env)
    assert proc.returncode == 1
    assert proc.stdout == f"lock: held by live pid {live_pid} (age 0m); not reaping\n"
    assert (workdir / "shepherd.lock").exists(), "a live, fresh lock must not be removed"
    assert _history_rows(db_path)[0]["released_at"] is None


def test_reap_live_but_over_60_minutes_still_reaps(lock_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = lock_db
    workdir = tmp_path / "work"
    _write_project_json(workdir, project_id)
    now = int(time.time())
    live_pid = os.getpid()
    old_acquired_at = now - 61 * 60  # 61 minutes ago — over the threshold.
    _write_lock_file(workdir, holder="sess-old", mode="context", acquired_at=old_acquired_at, pid=live_pid)
    _insert_history_row(db_path, project_id=project_id, session_id="sess-old", acquired_at=old_acquired_at)
    env = _lock_env(db_path, workdir)

    proc = run_cli(["lock", "reap"], env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == f"lock: reaped (pid={live_pid}, age=61m)\n"
    assert not (workdir / "shepherd.lock").exists()


def test_reap_bash_parity_dead_pid(lock_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = lock_db
    workdir = tmp_path / "work"
    _write_project_json(workdir, project_id)
    now = int(time.time())
    dead_pid = 9_999_998
    _write_lock_file(workdir, holder="sess-dead-parity", mode="context", acquired_at=now - 120, pid=dead_pid)
    _insert_history_row(db_path, project_id=project_id, session_id="sess-dead-parity", acquired_at=now - 120)
    env = _lock_env(db_path, workdir)

    python_proc = run_cli(["lock", "reap"], env)
    assert python_proc.returncode == 0, python_proc.stderr

    # Reset for the bash run against identical starting state.
    _write_lock_file(workdir, holder="sess-dead-parity", mode="context", acquired_at=now - 120, pid=dead_pid)
    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE locks_history SET released_at=NULL, released_by=NULL WHERE session_id='sess-dead-parity'")
    conn.commit()
    conn.close()

    bash_proc = _run_bash_lock(["reap"], env)
    assert bash_proc.returncode == 0, bash_proc.stderr
    assert bash_proc.stdout == python_proc.stdout


def test_reap_corrupt_lock_file_conservatively_reaps(lock_db: tuple[Path, str], tmp_path: Path) -> None:
    """Deliberate ROBUSTNESS deviation from bash (see lock.py's module
    docstring): bash's `reap` has NO jq error tolerance and crashes on a
    corrupt lock file, refusing to run at all (wedging the project, since
    reap/release are the only two ways to clear a lock). This module treats
    an unparseable lock file as maximally stale and conservatively reaps
    it rather than refusing to run."""
    db_path, project_id = lock_db
    workdir = tmp_path / "work"
    workdir.mkdir(parents=True)
    _write_project_json(workdir, project_id)
    (workdir / "shepherd.lock").write_text("{not valid json")
    env = _lock_env(db_path, workdir)

    proc = run_cli(["lock", "reap"], env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("lock: reaped (pid=null, age=")
    assert not (workdir / "shepherd.lock").exists()


# --------------------------------------------------------------------------
# Shared "no project registered" prerequisite gate — every subcommand,
# including `show` (bash parity: project_id is resolved BEFORE dispatch).
# --------------------------------------------------------------------------
@pytest.mark.parametrize("args", [["lock"], ["lock", "show"], ["lock", "acquire"], ["lock", "release"], ["lock", "reap"]])
def test_no_project_registered_exits_1_every_subcommand(tmp_path: Path, args: list[str]) -> None:
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)  # no projects row inserted
    workdir = tmp_path / "work"  # also no project.json
    env = _lock_env(db_path, workdir)

    proc = run_cli(args, env)
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.strip() == "ERROR: no project registered — run 'shctx init' first"


# --------------------------------------------------------------------------
# Unrecognized subcommand — documented deviation from bash's custom exit 1.
# --------------------------------------------------------------------------
def test_unrecognized_subcommand_exits_2_documented_deviation(lock_db: tuple[Path, str], tmp_path: Path) -> None:
    """`cmd_lock.sh`'s `*)` arm prints a custom usage error to stderr and
    exits 1. This port cannot reproduce that exactly (see lock.py's module
    docstring): Typer/Click's Group resolves an unrecognized subcommand
    name to its own generic error BEFORE any callback of ours runs, so
    `shepherd lock bogus` exits 2 with Typer's own "No such command"
    message instead. This is a documented, deliberate scope decision."""
    db_path, project_id = lock_db
    workdir = tmp_path / "work"
    _write_project_json(workdir, project_id)
    env = _lock_env(db_path, workdir)

    proc = run_cli(["lock", "bogus"], env)
    assert proc.returncode == 2
    assert "No such command" in proc.stderr


def test_python_venv_exists() -> None:
    """Sanity check the shared test harness contract this module depends on."""
    assert Path(PY).is_file()
