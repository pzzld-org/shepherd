"""Tests for `shepherd prune` — native port of `cmd_prune.sh` (v6.2.5, #171).

`shepherd prune` is DESTRUCTIVE workdir + registry GC, so this suite's
center of gravity is the safety contract, not just bash-parity output
shape:

  - dry-run (the DEFAULT) removes NOTHING, on disk or in the DB.
  - `--confirm` MOVES only eligible on-disk items into the `/tmp` run dir
    (reversible — the move preserves the workdir-relative path, so
    `logs/hooks/foo.jsonl` lands at `<run_dir>/logs/hooks/foo.jsonl`, never
    flattened).
  - the CURRENT git branch's own `dispatch/<branch>/` dir is NEVER swept,
    regardless of age (the active-sprint fence).
  - every DB "sweep" in this bash version is PREVIEW-ONLY: `--confirm`
    never deletes a single registry row, and a table absent from
    `sqlite_master` (an older/partial schema) is skipped, never an error.
  - `--vacuum` is opt-in and itself gated on `--confirm`.

Every test isolates the CLI to a throwaway git repo (`repo` fixture, cwd —
drives git-branch resolution + `.claude/shepherd.toml` config lookup) and a
throwaway `SHEPHERD_WORKDIR` (`workdir` fixture — the swept namespace),
matching the pattern `test_worktree.py`/`test_lock.py` already established
for cwd-/workdir-sensitive ports.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest
from conftest import PY, REPO_ROOT, build_full_schema_db, build_partial_schema_db, clean_env_dict, insert_project

CMD_PRUNE_SH = REPO_ROOT / "skills" / "context" / "scripts" / "cmd_prune.sh"


# --------------------------------------------------------------------------
# git / workdir / CLI invocation helpers.
# --------------------------------------------------------------------------
def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a git command in `cwd`, raising on failure."""
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway git repo on branch 'main', one commit — drives branch resolution."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "a.txt").write_text("a\n")
    _git(root, "add", "a.txt")
    _git(root, "commit", "-q", "-m", "init")
    return root


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    """The throwaway `.shepherd`-equivalent namespace `SHEPHERD_WORKDIR` points at.

    Kept separate from `repo` deliberately — `resolve_workdir()` never
    assumes the namespace lives under `cwd`/the repo root.
    """
    d = tmp_path / "ns"
    d.mkdir()
    return d


def _env(workdir: Path, *, db_path: Path | None = None) -> dict[str, str]:
    """A stripped-then-rebuilt environment: SHEPHERD_WORKDIR (+ optional SHCTX_DB)."""
    env = clean_env_dict()
    env["SHEPHERD_WORKDIR"] = str(workdir)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    if db_path is not None:
        env["SHCTX_DB"] = str(db_path)
    return env


def _run(args: list[str], cwd: Path, env: dict[str, str], *, timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
    """Run `shepherd prune <args>` as a real subprocess, cwd pinned to `cwd`."""
    return subprocess.run(
        [PY, "-m", "shepherd_cli", "prune", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _run_bash(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the legacy `cmd_prune.sh` directly under `cwd` (bash-parity twin)."""
    return subprocess.run(
        ["bash", str(CMD_PRUNE_SH), *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )


def _touch(path: Path, *, mtime: float | None = None, is_dir: bool = False) -> None:
    """Create a file (or directory) at `path`, optionally backdated to `mtime`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if is_dir:
        path.mkdir(parents=True, exist_ok=True)
    else:
        path.touch()
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def _run_dir_from_stdout(stdout: str) -> str:
    """Extract the `run_dir` (parent of `plan.csv`) from the text report's last line."""
    for line in stdout.splitlines():
        if line.startswith("plan CSV: "):
            return line[len("plan CSV: ") :].rsplit("/plan.csv", 1)[0]
    raise AssertionError(f"no 'plan CSV:' line in stdout: {stdout!r}")


# --------------------------------------------------------------------------
# Fixture DB helpers (raw sqlite3, schema-tolerant — mirrors conftest.py's
# own `insert_teammate` PRAGMA table_info pattern).
# --------------------------------------------------------------------------
def _insert_row(db_path: Path, table: str, fields: dict[str, object]) -> None:
    """Insert one row into `table`, using only columns that actually exist there."""
    conn = sqlite3.connect(str(db_path))
    try:
        columns = {info[1] for info in conn.execute(f"PRAGMA table_info({table})")}  # noqa: S608 - test-only, fixed table names
        present = {k: v for k, v in fields.items() if k in columns}
        cols = ", ".join(present.keys())
        placeholders = ", ".join("?" for _ in present)
        conn.execute(
            f"INSERT INTO {table} ({cols}) VALUES ({placeholders})",  # noqa: S608 - test-only, fixed table/column names
            list(present.values()),
        )
        conn.commit()
    finally:
        conn.close()


def _count(db_path: Path, table: str) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608 - test-only, fixed table names
    finally:
        conn.close()


@pytest.fixture
def full_db(tmp_path: Path) -> tuple[Path, str]:
    """A full-schema fixture DB with one registered project."""
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    project_id = insert_project(db_path)
    return db_path, project_id


# --------------------------------------------------------------------------
# Bare invocation / dry-run-by-default / no-DB.
# --------------------------------------------------------------------------
def test_bare_invocation_is_dry_run_by_default(repo: Path, workdir: Path) -> None:
    proc = _run([], repo, _env(workdir))
    assert proc.returncode == 0, proc.stderr
    assert "shctx prune — dry-run" in proc.stdout
    assert "DRY-RUN: nothing removed" in proc.stdout
    assert "plan CSV:" in proc.stdout


def test_missing_db_is_tolerated_and_reported(repo: Path, workdir: Path) -> None:
    db_path = workdir / "shepherd.db"  # never created
    proc = _run([], repo, _env(workdir, db_path=db_path))
    assert proc.returncode == 0, proc.stderr
    assert f"registry DB: none at {db_path} (skipped)" in proc.stdout
    assert "registry rows (PREVIEW" not in proc.stdout


def test_missing_db_json_reports_db_present_false(repo: Path, workdir: Path) -> None:
    db_path = workdir / "shepherd.db"
    proc = _run(["--json"], repo, _env(workdir, db_path=db_path))
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["db_present"] is False
    assert payload["db_preview"] == []


def test_help_prints_verbatim_bash_usage_exit_0(repo: Path, workdir: Path) -> None:
    proc = _run(["-h"], repo, _env(workdir))
    bash_proc = _run_bash(["-h"], repo, _env(workdir))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == bash_proc.stdout.rstrip("\n")
    assert proc.stdout.rstrip("\n").startswith("# shctx prune [--confirm]")
    assert proc.stdout.rstrip("\n").endswith("DB-row sweeps are PREVIEW-ONLY in v6.2.5 (eligible counts printed, nothing")


def test_help_long_form_matches(repo: Path, workdir: Path) -> None:
    proc = _run(["--help"], repo, _env(workdir))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("# shctx prune")


def test_unknown_arg_exits_2(repo: Path, workdir: Path) -> None:
    proc = _run(["--bogus"], repo, _env(workdir))
    assert proc.returncode == 2
    assert proc.stdout == ""
    assert proc.stderr.rstrip("\n") == "ERROR: unknown arg: --bogus"


def test_invalid_retention_value_exits_2(repo: Path, workdir: Path) -> None:
    proc = _run(["--logs-days=abc"], repo, _env(workdir))
    assert proc.returncode == 2
    assert "ERROR: invalid --logs-days value: abc" in proc.stderr


def test_dry_run_flag_after_confirm_wins(repo: Path, workdir: Path) -> None:
    """Bash parity: plain sequential reassignment — the LAST confirm/dry-run flag wins."""
    proc = _run(["--confirm", "--dry-run"], repo, _env(workdir))
    assert proc.returncode == 0, proc.stderr
    assert "shctx prune — dry-run" in proc.stdout
    assert "DRY-RUN: nothing removed" in proc.stdout


# --------------------------------------------------------------------------
# On-disk sweep: dispatch dirs (current-branch fence + age boundary).
# --------------------------------------------------------------------------
def test_dry_run_moves_nothing_on_disk(repo: Path, workdir: Path) -> None:
    old_dispatch = workdir / "dispatch" / "oldsprint"
    now = time.time()
    _touch(old_dispatch / "a.json", mtime=now - 40 * 86400)
    os.utime(old_dispatch, (now - 40 * 86400, now - 40 * 86400))

    proc = _run(["--dispatch-days=30"], repo, _env(workdir))
    assert proc.returncode == 0, proc.stderr
    assert old_dispatch.is_dir(), "dry-run must never remove anything"
    assert (old_dispatch / "a.json").is_file()


def test_confirm_moves_noncurrent_dispatch_but_keeps_current_branch(repo: Path, workdir: Path) -> None:
    now = time.time()
    old_dir = workdir / "dispatch" / "oldsprint"
    cur_dir = workdir / "dispatch" / "main"  # 'main' == the repo fixture's branch
    _touch(old_dir / "a.json", mtime=now - 40 * 86400)
    os.utime(old_dir, (now - 40 * 86400, now - 40 * 86400))
    _touch(cur_dir / "b.json", mtime=now - 40 * 86400)
    os.utime(cur_dir, (now - 40 * 86400, now - 40 * 86400))  # aged too, but MUST survive (fence)

    proc = _run(["--confirm", "--dispatch-days=30"], repo, _env(workdir))
    assert proc.returncode == 0, proc.stderr
    assert not old_dir.exists(), "non-current, aged dispatch dir must be swept"
    assert cur_dir.is_dir(), "current-branch dispatch dir must NEVER be swept"
    assert (cur_dir / "b.json").is_file()

    run_dir = Path(_run_dir_from_stdout(proc.stdout))
    assert (run_dir / "dispatch" / "oldsprint" / "a.json").is_file(), "moved dir keeps its contents"


def test_dispatch_age_boundary_exactly_at_threshold_is_not_eligible(repo: Path, workdir: Path) -> None:
    """age_days == threshold is NOT eligible (find -mtime +N is a strict '>')."""
    now = time.time()
    at_boundary = workdir / "dispatch" / "at-boundary"
    _touch(at_boundary / "f.json", is_dir=False)
    os.utime(at_boundary / "f.json", (now - (5 * 86400 + 50), now - (5 * 86400 + 50)))
    os.utime(at_boundary, (now - (5 * 86400 + 50), now - (5 * 86400 + 50)))

    proc = _run(["--confirm", "--dispatch-days=5"], repo, _env(workdir))
    assert proc.returncode == 0, proc.stderr
    assert at_boundary.is_dir(), "age exactly at the N-day floor must NOT be eligible"


def test_dispatch_age_one_day_past_threshold_is_eligible(repo: Path, workdir: Path) -> None:
    now = time.time()
    past_boundary = workdir / "dispatch" / "past-boundary"
    _touch(past_boundary / "f.json", is_dir=False)
    os.utime(past_boundary / "f.json", (now - (6 * 86400 + 50), now - (6 * 86400 + 50)))
    os.utime(past_boundary, (now - (6 * 86400 + 50), now - (6 * 86400 + 50)))

    proc = _run(["--confirm", "--dispatch-days=5"], repo, _env(workdir))
    assert proc.returncode == 0, proc.stderr
    assert not past_boundary.exists(), "age one day past the N-day floor must be eligible"


# NOTE: a dedicated "move-failed" test (permission-denied on the parent dir)
# is deliberately NOT included here. This suite's subprocess runs as root in
# every environment this port has been validated against, and root bypasses
# directory-permission-based move failures entirely (verified empirically:
# chmod 0o555 on the parent dir does not stop root from unlinking/renaming
# entries inside it) — a permission-based trigger would be either a false
# negative (root: silently "moved", not "move-failed") or environment-
# dependent flake (non-root: works), neither of which is an acceptable test.
# _sweep_path's move-failed branch (shepherd_cli/commands/prune.py) is a
# plain `try/except (OSError, shutil.Error): ... "move-failed"` around
# `shutil.move` — the same well-established exception-to-status-string
# mapping every other move/write path in this port already uses (see
# lock.py's dual-write, mem.py's file writes), not bespoke logic this
# module invents, so the uncovered branch carries materially lower risk
# than an unreliable test asserting the wrong thing depending on who runs
# the suite.


# --------------------------------------------------------------------------
# On-disk sweep: logs (events-*.jsonl + hooks/*.jsonl), reversible subpath.
# --------------------------------------------------------------------------
def test_confirm_moves_aged_logs_preserving_hooks_subpath(repo: Path, workdir: Path) -> None:
    now = time.time()
    events = workdir / "logs" / "events-old.jsonl"
    hooks = workdir / "logs" / "hooks" / "2020-01-01.jsonl"
    _touch(events, mtime=now - 90 * 86400)
    _touch(hooks, mtime=now - 90 * 86400)

    proc = _run(["--confirm", "--logs-days=60", "--json"], repo, _env(workdir))
    assert proc.returncode == 0, proc.stderr
    assert not events.exists()
    assert not hooks.exists()

    payload = json.loads(proc.stdout)
    assert payload["on_disk"]["logs"] == 2
    run_dir = Path(payload["run_dir"])
    assert (run_dir / "logs" / "events-old.jsonl").is_file()
    assert (run_dir / "logs" / "hooks" / "2020-01-01.jsonl").is_file(), (
        "logs/hooks/ subpath must be preserved, not flattened — reversibility contract"
    )


def test_fresh_logs_are_not_swept(repo: Path, workdir: Path) -> None:
    fresh = workdir / "logs" / "events-fresh.jsonl"
    _touch(fresh)  # mtime == now
    proc = _run(["--confirm", "--logs-days=60"], repo, _env(workdir))
    assert proc.returncode == 0, proc.stderr
    assert fresh.is_file()


def test_non_matching_log_file_is_ignored(repo: Path, workdir: Path) -> None:
    """A log file matching neither `events-*.jsonl` nor `*/hooks/*.jsonl` is never swept."""
    now = time.time()
    other = workdir / "logs" / "other.jsonl"
    _touch(other, mtime=now - 90 * 86400)
    proc = _run(["--confirm", "--logs-days=60"], repo, _env(workdir))
    assert proc.returncode == 0, proc.stderr
    assert other.is_file()


# --------------------------------------------------------------------------
# On-disk sweep: precompact snapshots (newest-N kept).
# --------------------------------------------------------------------------
def test_snapshots_keeps_newest_n_sweeps_the_rest(repo: Path, workdir: Path) -> None:
    now = time.time()
    snapdir = workdir / "cache" / "snapshots"
    snapdir.mkdir(parents=True)
    # 5 snapshots, oldest to newest, 100s apart.
    paths = [snapdir / f"precompact-run-{i}.json" for i in range(5)]
    for i, p in enumerate(paths):
        _touch(p, mtime=now - (5 - i) * 100)  # paths[0] oldest .. paths[4] newest

    proc = _run(["--confirm", "--snapshots-keep=2", "--json"], repo, _env(workdir))
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["on_disk"]["snapshots"] == 3

    # The 2 newest survive; the 3 oldest are gone.
    assert paths[4].is_file() and paths[3].is_file()
    assert not paths[0].exists() and not paths[1].exists() and not paths[2].exists()


def test_snapshots_keep_zero_sweeps_all(repo: Path, workdir: Path) -> None:
    snapdir = workdir / "cache" / "snapshots"
    p = snapdir / "precompact-only.json"
    _touch(p)
    proc = _run(["--confirm", "--snapshots-keep=0"], repo, _env(workdir))
    assert proc.returncode == 0, proc.stderr
    assert not p.exists()


def test_snapshots_sweeps_retired_memory_and_toplevel_dirs(repo: Path, workdir: Path) -> None:
    """v6.4.4: retired snapshot dirs stay under retention, not un-pruned forever.

    `memory/snapshots/` (v6.1.3) and top-level `snapshots/` (pre-v6.1.3) are no
    longer written to, but an un-migrated project still has files there. If
    prune only looked at `cache/`, those would accumulate without bound.
    """
    legacy_mem = workdir / "memory" / "snapshots" / "precompact-old.json"
    legacy_top = workdir / "snapshots" / "precompact-older.json"
    _touch(legacy_mem)
    _touch(legacy_top)
    proc = _run(["--confirm", "--snapshots-keep=0"], repo, _env(workdir))
    assert proc.returncode == 0, proc.stderr
    assert not legacy_mem.exists()
    assert not legacy_top.exists()


def test_snapshots_retention_is_one_budget_across_all_dirs(repo: Path, workdir: Path) -> None:
    """`snapshots_keep` keeps N snapshots TOTAL, not N per directory.

    Applying retention per-directory during the v6.4.4 transition would retain
    up to 3N snapshots, which is not what the setting means.
    """
    now = time.time()
    canonical = workdir / "cache" / "snapshots" / "precompact-new.json"
    legacy = workdir / "memory" / "snapshots" / "precompact-old.json"
    _touch(canonical, mtime=now - 100)   # newest
    _touch(legacy, mtime=now - 500)      # oldest

    proc = _run(["--confirm", "--snapshots-keep=1", "--json"], repo, _env(workdir))
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    # One kept (the newest, wherever it lives), one swept — NOT one per dir.
    assert payload["on_disk"]["snapshots"] == 1
    assert canonical.is_file()
    assert not legacy.exists()


# --------------------------------------------------------------------------
# Retention window precedence: flag > [prune] config > built-in default.
# --------------------------------------------------------------------------
def test_default_retention_values_shown_when_unset(repo: Path, workdir: Path) -> None:
    proc = _run([], repo, _env(workdir))
    assert proc.returncode == 0, proc.stderr
    assert "dispatch dirs (non-current, >30d):" in proc.stdout
    assert "log files (>60d):" in proc.stdout
    assert "precompact snapshots (beyond 20):" in proc.stdout


def test_config_file_overrides_default(repo: Path, workdir: Path) -> None:
    claude_dir = repo / ".claude"
    claude_dir.mkdir()
    (claude_dir / "shepherd.toml").write_text('[prune]\nlogs_days = 5\ndispatch_days = 7\n')

    proc = _run([], repo, _env(workdir))
    assert proc.returncode == 0, proc.stderr
    assert "dispatch dirs (non-current, >7d):" in proc.stdout
    assert "log files (>5d):" in proc.stdout


def test_flag_overrides_config_file(repo: Path, workdir: Path) -> None:
    claude_dir = repo / ".claude"
    claude_dir.mkdir()
    (claude_dir / "shepherd.toml").write_text("[prune]\nlogs_days = 5\n")

    proc = _run(["--logs-days=9"], repo, _env(workdir))
    assert proc.returncode == 0, proc.stderr
    assert "log files (>9d):" in proc.stdout


# --------------------------------------------------------------------------
# DB preview — table-guarded, PREVIEW ONLY (never deletes), text/JSON asymmetry.
# --------------------------------------------------------------------------
def test_db_preview_all_zero_on_empty_full_schema(repo: Path, workdir: Path, full_db: tuple[Path, str]) -> None:
    db_path, _project_id = full_db
    proc = _run(["--json"], repo, _env(workdir, db_path=db_path))
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["db_present"] is True
    names = {row["name"]: row for row in payload["db_preview"]}
    assert set(names) == {
        "logs_events", "crashed_hb", "consumed_sig", "closed_disc", "closed_audit", "released_locks",
    }
    for row in names.values():
        assert row["action"] == "preview:0"


def test_db_preview_counts_reflect_eligible_rows(repo: Path, workdir: Path, full_db: tuple[Path, str]) -> None:
    db_path, project_id = full_db
    now = int(time.time())

    # logs_events: one old row (eligible at logs_days=1), one fresh row (not).
    _insert_row(db_path, "logs_events", {
        "project_id": project_id, "ts": now - 90 * 86400, "level": "info", "source": "x", "event": "y",
    })
    _insert_row(db_path, "logs_events", {
        "project_id": project_id, "ts": now, "level": "info", "source": "x", "event": "y",
    })

    # heartbeats: one for a crashed teammate (eligible), one for an active one (not).
    _insert_row(db_path, "teammates", {
        "id": "tm-crashed", "project_id": project_id, "team_name": "t", "teammate_name": "crashed-1",
        "agent_type": "shepherd:engineer", "status": "crashed", "spawned_at": now, "last_seen_at": now,
    })
    _insert_row(db_path, "teammates", {
        "id": "tm-active", "project_id": project_id, "team_name": "t", "teammate_name": "active-1",
        "agent_type": "shepherd:engineer", "status": "active", "spawned_at": now, "last_seen_at": now,
    })
    _insert_row(db_path, "heartbeats", {"teammate_id": "tm-crashed", "ts": now})
    _insert_row(db_path, "heartbeats", {"teammate_id": "tm-active", "ts": now})

    # session_signals: one consumed (eligible), one unconsumed (not).
    _insert_row(db_path, "session_signals", {
        "project_id": project_id, "sender": "a", "recipient": "b", "kind": "seed-ready",
        "payload": "{}", "sent_at": now, "consumed_at": now,
    })
    _insert_row(db_path, "session_signals", {
        "project_id": project_id, "sender": "a", "recipient": "b", "kind": "seed-ready",
        "payload": "{}", "sent_at": now, "consumed_at": None,
    })

    # discovery_findings / audit_findings: one non-current sprint (eligible), one current (not).
    _insert_row(db_path, "discovery_findings", {
        "project_id": project_id, "sprint_branch": "old-sprint", "discovery_run": "r1",
        "title": "t", "body": "b", "created_at": now,
    })
    _insert_row(db_path, "discovery_findings", {
        "project_id": project_id, "sprint_branch": "main", "discovery_run": "r2",
        "title": "t", "body": "b", "created_at": now,
    })
    _insert_row(db_path, "audit_findings", {
        "project_id": project_id, "sprint_branch": "old-sprint", "concern": "c", "severity": "low",
        "hypothesis": "h", "finding": "f", "created_at": now,
    })
    _insert_row(db_path, "audit_findings", {
        "project_id": project_id, "sprint_branch": "main", "concern": "c", "severity": "low",
        "hypothesis": "h", "finding": "f", "created_at": now,
    })

    # locks_history: one released (eligible), one still held (not).
    _insert_row(db_path, "locks_history", {
        "project_id": project_id, "session_id": "s1", "mode": "context",
        "acquired_at": now, "released_at": now,
    })
    _insert_row(db_path, "locks_history", {
        "project_id": project_id, "session_id": "s2", "mode": "context",
        "acquired_at": now, "released_at": None,
    })

    proc = _run(["--json", "--logs-days=1"], repo, _env(workdir, db_path=db_path))
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    counts = {row["name"]: row["action"] for row in payload["db_preview"]}
    assert counts["logs_events"] == "preview:1"
    assert counts["crashed_hb"] == "preview:1"
    assert counts["consumed_sig"] == "preview:1"
    assert counts["closed_disc"] == "preview:1"
    assert counts["closed_audit"] == "preview:1"
    assert counts["released_locks"] == "preview:1"


def test_confirm_never_deletes_a_single_db_row(repo: Path, workdir: Path, full_db: tuple[Path, str]) -> None:
    """DB sweeps are PREVIEW-ONLY in this bash version — --confirm must not touch the registry."""
    db_path, project_id = full_db
    now = int(time.time())
    _insert_row(db_path, "logs_events", {
        "project_id": project_id, "ts": now - 90 * 86400, "level": "info", "source": "x", "event": "y",
    })
    _insert_row(db_path, "locks_history", {
        "project_id": project_id, "session_id": "s1", "mode": "context",
        "acquired_at": now, "released_at": now,
    })
    before_logs = _count(db_path, "logs_events")
    before_locks = _count(db_path, "locks_history")

    proc = _run(["--confirm", "--logs-days=1", "--vacuum"], repo, _env(workdir, db_path=db_path))
    assert proc.returncode == 0, proc.stderr

    assert _count(db_path, "logs_events") == before_logs, "confirm must not delete any logs_events row"
    assert _count(db_path, "locks_history") == before_locks, "confirm must not delete any locks_history row"


def test_table_absent_is_skipped_not_errored(repo: Path, workdir: Path, tmp_path: Path) -> None:
    """A DB that predates a table's migration (session_signals, added in 0020) is table-guarded."""
    db_path = tmp_path / "partial.db"
    build_partial_schema_db(db_path)
    insert_project(db_path)

    proc = _run([], repo, _env(workdir, db_path=db_path))
    assert proc.returncode == 0, proc.stderr
    # Column padding is right-justified to the widest count cell ("n/a" here), so
    # assert on whitespace-normalized rows rather than exact inter-column spacing
    # (the port matches cmd_prune.sh byte-for-byte; only the pad width shifts).
    norm = {" ".join(line.split()) for line in proc.stdout.splitlines()}
    assert "consumed_sig n/a cross-session signals already consumed (table absent)" in norm
    # Every OTHER table from migration 0007 (heartbeats, discovery_findings,
    # audit_findings) is present in the partial schema and previews normally.
    assert "crashed_hb 0 heartbeats for crashed/retired teammates" in norm


def test_table_absent_json_action_and_bare_detail(repo: Path, workdir: Path, tmp_path: Path) -> None:
    """JSON action is 'skip:table-absent'; detail is the BARE desc (no '(table absent)' suffix) —
    the text/JSON asymmetry documented in cmd_prune.sh's own count_pre()."""
    db_path = tmp_path / "partial.db"
    build_partial_schema_db(db_path)
    insert_project(db_path)

    proc = _run(["--json"], repo, _env(workdir, db_path=db_path))
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    row = next(r for r in payload["db_preview"] if r["name"] == "consumed_sig")
    assert row["action"] == "skip:table-absent"
    assert row["table"] == "session_signals"
    assert row["detail"] == "cross-session signals already consumed"
    assert "table absent" not in row["detail"]


def test_table_absent_is_never_deleted_or_created(repo: Path, workdir: Path, tmp_path: Path) -> None:
    """--confirm on a partial-schema DB must not create the missing table (no self-heal)."""
    db_path = tmp_path / "partial.db"
    build_partial_schema_db(db_path)
    insert_project(db_path)

    proc = _run(["--confirm"], repo, _env(workdir, db_path=db_path))
    assert proc.returncode == 0, proc.stderr

    conn = sqlite3.connect(str(db_path))
    try:
        exists = conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='session_signals'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert exists == 0, "prune must never self-heal/apply migrations — that would defeat the table-guard"


# --------------------------------------------------------------------------
# --vacuum.
# --------------------------------------------------------------------------
def test_vacuum_without_confirm_is_a_documented_noop(repo: Path, workdir: Path, full_db: tuple[Path, str]) -> None:
    db_path, _project_id = full_db
    proc = _run(["--vacuum"], repo, _env(workdir, db_path=db_path))
    assert proc.returncode == 0, proc.stderr
    assert "vacuum: --vacuum requires --confirm (skipped in dry-run)" in proc.stdout


def test_vacuum_with_confirm_and_db_succeeds(repo: Path, workdir: Path, full_db: tuple[Path, str]) -> None:
    db_path, _project_id = full_db
    proc = _run(["--confirm", "--vacuum"], repo, _env(workdir, db_path=db_path))
    assert proc.returncode == 0, proc.stderr
    assert "vacuum: WAL checkpointed + VACUUM ok" in proc.stdout


def test_vacuum_without_db_prints_nothing_extra(repo: Path, workdir: Path) -> None:
    db_path = workdir / "shepherd.db"  # never created
    proc = _run(["--confirm", "--vacuum"], repo, _env(workdir, db_path=db_path))
    assert proc.returncode == 0, proc.stderr
    # Assert the specific vacuum-ran message is absent — not the bare word
    # "vacuum", which the echoed workdir path contains (the pytest tmpdir is
    # ".../test_vacuum_without_db_prints_0/ns").
    assert "vacuum: WAL checkpointed" not in proc.stdout


def test_vacuum_json_mode_still_appends_after_json_blob(repo: Path, workdir: Path, full_db: tuple[Path, str]) -> None:
    """Bash-parity quirk: the vacuum line prints AFTER the JSON blob even in --json mode."""
    db_path, _project_id = full_db
    proc = _run(["--confirm", "--vacuum", "--json"], repo, _env(workdir, db_path=db_path))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n").endswith("vacuum: WAL checkpointed + VACUUM ok")
    # The JSON blob itself must still be valid on its own as a PREFIX.
    json_text = proc.stdout.rsplit("\nvacuum:", 1)[0]
    json.loads(json_text)  # must not raise


# --------------------------------------------------------------------------
# CSV plan file.
# --------------------------------------------------------------------------
def test_plan_csv_header_and_rows(repo: Path, workdir: Path) -> None:
    now = time.time()
    old_dir = workdir / "dispatch" / "oldsprint"
    _touch(old_dir / "a.json", is_dir=False)
    os.utime(old_dir, (now - 40 * 86400, now - 40 * 86400))

    proc = _run(["--confirm", "--dispatch-days=30"], repo, _env(workdir))
    assert proc.returncode == 0, proc.stderr
    run_dir = Path(_run_dir_from_stdout(proc.stdout))
    csv_text = (run_dir / "plan.csv").read_text()
    lines = csv_text.splitlines()
    assert lines[0] == "category,path_or_table,detail,action"
    assert any(line.startswith("dispatch,") and line.endswith(",moved") for line in lines[1:])


# --------------------------------------------------------------------------
# JSON structural shape (schema sanity, no DB, no on-disk items).
# --------------------------------------------------------------------------
def test_json_shape_bare_dry_run(repo: Path, workdir: Path) -> None:
    proc = _run(["--json"], repo, _env(workdir))
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["mode"] == "dry-run"
    assert payload["workdir"] == str(workdir)
    assert payload["branch"] == "main"
    assert payload["db_present"] is False
    assert payload["on_disk"] == {"dispatch": 0, "logs": 0, "snapshots": 0, "items": []}
    assert payload["db_preview"] == []
    assert payload["run_dir"].startswith("/tmp/shepherd-prune-")
    assert payload["csv"] == f"{payload['run_dir']}/plan.csv"


def test_json_mode_confirm(repo: Path, workdir: Path) -> None:
    proc = _run(["--confirm", "--json"], repo, _env(workdir))
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["mode"] == "confirm"


# --------------------------------------------------------------------------
# Bash-parity byte-for-byte comparisons (identical env/state, both tools).
# --------------------------------------------------------------------------
def test_bash_parity_text_output_no_db(repo: Path, workdir: Path) -> None:
    env = _env(workdir, db_path=workdir / "shepherd.db")
    py_proc = _run([], repo, env)
    bash_proc = _run_bash([], repo, env)
    assert py_proc.returncode == bash_proc.returncode == 0
    # The run_dir/epoch differs between the two invocations (each mints its
    # own /tmp/shepherd-prune-<epoch>), so strip that one line before
    # comparing everything else byte-for-byte.
    py_lines = [ln for ln in py_proc.stdout.splitlines() if not ln.startswith("plan CSV:")]
    bash_lines = [ln for ln in bash_proc.stdout.splitlines() if not ln.startswith("plan CSV:")]
    assert py_lines == bash_lines


def test_bash_parity_unknown_arg(repo: Path, workdir: Path) -> None:
    env = _env(workdir)
    py_proc = _run(["--nope"], repo, env)
    bash_proc = _run_bash(["--nope"], repo, env)
    assert py_proc.returncode == bash_proc.returncode == 2
    assert py_proc.stderr.rstrip("\n") == bash_proc.stderr.rstrip("\n")
